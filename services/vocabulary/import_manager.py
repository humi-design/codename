"""Import orchestration: history rows, progress, cancellation and resume.

The Super Admin starts an import from the vocabulary page.  Processing runs in
a background thread so the request returns immediately and the status page can
poll for progress - no Celery/Redis required, which keeps the app deployable on
shared hosting.  The same code path powers the CLI import script, where the
caller can simply wait for completion.

Only one import may run at a time.  A lock plus a DB check prevent two
concurrent imports from fighting over the ``words`` table.
"""

from __future__ import annotations

import logging
import threading

from extensions import db
from models.constants import ImportStatus, VocabularyStatus, utcnow
from models.vocabulary_import import VocabularyImport
from models.word import Word
from services.settings_service import SettingsService
from services.vocabulary.datasets import dataset_dir, download_dataset, find_dataset
from services.vocabulary.importer import (
    ImportOptions,
    VocabularyImporter,
    build_provider,
)
from services.vocabulary.sources import update_source_stats

logger = logging.getLogger(__name__)

# Process-wide guard.  The DB check is the source of truth across processes;
# this lock additionally serialises threads within one worker.
_run_lock = threading.Lock()
_cancel_flags: dict[int, bool] = {}
_active_import_id: int | None = None


class ImportError_(Exception):
    """User-facing import error."""


class ImportManager:
    # ------------------------------------------------------------ queries
    @staticmethod
    def active_import() -> VocabularyImport | None:
        return (
            VocabularyImport.query.filter(
                VocabularyImport.status.in_(
                    (ImportStatus.QUEUED, ImportStatus.RUNNING)
                )
            )
            .order_by(VocabularyImport.id.desc())
            .first()
        )

    @staticmethod
    def latest_import() -> VocabularyImport | None:
        return VocabularyImport.query.order_by(
            VocabularyImport.id.desc()
        ).first()

    @staticmethod
    def history(limit: int = 50) -> list[VocabularyImport]:
        return (
            VocabularyImport.query.order_by(VocabularyImport.id.desc())
            .limit(limit)
            .all()
        )

    # ------------------------------------------------------------- status
    @staticmethod
    def status() -> dict:
        total = Word.query.count()
        active = Word.query.filter(Word.is_active.is_(True)).count()
        running = ImportManager.active_import()
        last = ImportManager.latest_import()

        if running is not None:
            vocabulary_status = VocabularyStatus.IMPORTING
        elif total == 0:
            vocabulary_status = VocabularyStatus.NOT_INITIALIZED
        elif last is not None and last.status == ImportStatus.FAILED:
            vocabulary_status = VocabularyStatus.ERROR
        else:
            vocabulary_status = VocabularyStatus.READY

        return {
            "status": vocabulary_status,
            "total": total,
            "active": active,
            "inactive": max(0, total - active),
            "running_import": running,
            "last_import": last,
        }

    # ------------------------------------------------------------ starting
    @staticmethod
    def start(source: str, *, mode: str = "initial", path: str | None = None,
              dataset_url: str | None = None, language: str = "en",
              label: str | None = None, background: bool = True) -> VocabularyImport:
        """Create a history row and begin importing.

        Raises :class:`ImportError_` if another import is already running.
        """
        if ImportManager.active_import() is not None:
            raise ImportError_("An import is already running. Please wait for it to finish.")

        resolved = path or find_dataset(source)
        if not resolved:
            raise ImportError_(
                f"No dataset found for source '{source}'. Upload a file or place it "
                f"in {dataset_dir()}."
            )

        record = VocabularyImport(
            source=source,
            label=label or source,
            status=ImportStatus.RUNNING,
            mode=mode,
            path=resolved,
            dataset_url=dataset_url,
            started_at=utcnow(),
        )
        db.session.add(record)
        db.session.commit()

        if background:
            from flask import current_app

            # Capture the real app object now, while a context is active; the
            # worker thread has no request/app context of its own.
            app = current_app._get_current_object()
            thread = threading.Thread(
                target=ImportManager._run_in_thread,
                args=(app, record.id, language),
                daemon=True,
                name=f"vocab-import-{record.id}",
            )
            thread.start()
        else:
            ImportManager.run(record.id, language=language)
        return record

    @staticmethod
    def cancel(import_id: int) -> bool:
        record = db.session.get(VocabularyImport, import_id)
        if record is None or not record.is_running:
            return False
        _cancel_flags[import_id] = True
        return True

    # ------------------------------------------------------------- runner
    @staticmethod
    def _run_in_thread(app, import_id: int, language: str) -> None:
        """Thread entry point - runs inside the app context it was given."""
        with app.app_context():
            try:
                ImportManager.run(import_id, language=language)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Vocabulary import %s crashed", import_id)

    @staticmethod
    def run(import_id: int, *, language: str = "en") -> VocabularyImport:
        """Execute an import synchronously (used by the thread and the CLI)."""
        record = db.session.get(VocabularyImport, import_id)
        if record is None:
            raise ImportError_("Import record not found.")

        with _run_lock:
            global _active_import_id
            _active_import_id = import_id
            _cancel_flags[import_id] = False
            try:
                ImportManager._execute(record, language)
            finally:
                _active_import_id = None
                _cancel_flags.pop(import_id, None)
        return record

    @staticmethod
    def _execute(record: VocabularyImport, language: str) -> None:
        try:
            record.status = ImportStatus.RUNNING
            record.started_at = record.started_at or utcnow()
            db.session.commit()

            path = record.path
            if not path and record.dataset_url:
                destination = f"{dataset_dir()}/{record.source}.dataset"
                download_dataset(record.dataset_url, destination)
                path = destination
                record.path = path
                db.session.commit()

            provider = build_provider(
                path, source=record.source, language=language,
                dataset_url=record.dataset_url,
            )

            # "replace" rebuilds a source from scratch (CLI only).  Failure
            # after this point is still safe: only that source's rows are
            # removed, and the import is retryable.
            if record.mode == "replace":
                Word.query.filter(Word.source == record.source).delete()
                db.session.commit()

            filters = SettingsService.word_filters()
            options = ImportOptions(
                language=language,
                max_chars=filters["max_chars"],
                max_words=filters["max_words"],
                update_existing=(record.mode != "replace"),
            )
            importer = VocabularyImporter(provider, options)

            def progress(stats) -> None:
                record.total_processed = stats.processed
                record.total_imported = stats.imported
                record.total_updated = stats.updated
                record.total_duplicates = stats.duplicates
                record.total_rejected = stats.rejected
                record.total_errors = stats.errors
                record.resume_offset = stats.resume_offset
                db.session.commit()

            stats = importer.run(
                start_offset=int(record.resume_offset or 0),
                progress=progress,
                should_stop=lambda: _cancel_flags.get(record.id, False),
            )

            if _cancel_flags.get(record.id, False):
                record.status = ImportStatus.CANCELLED
            else:
                record.status = ImportStatus.COMPLETED
            record.completed_at = utcnow()
            record.total_processed = stats.processed
            record.total_imported = stats.imported
            record.total_updated = stats.updated
            record.total_duplicates = stats.duplicates
            record.total_rejected = stats.rejected
            record.total_errors = stats.errors
            db.session.commit()

            update_source_stats(record.source, Word.query.filter_by(
                source=record.source).count())
            logger.info(
                "Vocabulary import %s finished (%s): +%s new, %s updated, %s rejected",
                record.id, record.status, stats.imported, stats.updated,
                stats.rejected,
            )
        except Exception as exc:  # noqa: BLE001 - record and preserve data
            db.session.rollback()
            # Existing vocabulary is never deleted on failure; we only mark
            # the run as failed so the operator can retry.
            record = db.session.get(VocabularyImport, record.id) or record
            record.status = ImportStatus.FAILED
            record.completed_at = utcnow()
            record.error_message = str(exc)[:2000]
            db.session.commit()
            logger.exception("Vocabulary import %s failed", record.id)
