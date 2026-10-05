"""Import vocabulary into the ``words`` table from the command line.

Runs the same ingestion engine as the Super Admin vocabulary page, but
synchronously and with full control over the source and mode.

Usage
-----
    # Bundled sample list (first run / development)
    python scripts/import_words.py --source seed

    # A downloaded dataset (auto-detected in the dataset directory)
    python scripts/import_words.py --source kaikki
    python scripts/import_words.py --source wikidata
    python scripts/import_words.py --source frequency

    # An explicit file
    python scripts/import_words.py data/sample_words.csv
    python scripts/import_words.py /path/to/kaikki.jsonl --source kaikki

    # Rebuild one source from scratch
    python scripts/import_words.py --source custom --file words.csv --mode replace

    # Resume an interrupted import from its recorded byte offset
    python scripts/import_words.py --source kaikki --resume-offset 12345678

Dataset files live in ``data/datasets/`` (configurable with ``--dir`` or the
``vocab_dataset_dir`` setting).  No network access happens during gameplay;
downloads only occur when you explicitly pass ``--download``.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models.constants import utcnow  # noqa: E402
from models.vocabulary_import import VocabularyImport  # noqa: E402
from models.word import Word  # noqa: E402
from services.settings_service import SettingsService  # noqa: E402
from services.vocabulary.datasets import (  # noqa: E402
    dataset_dir,
    download_dataset,
    find_dataset,
)
from services.vocabulary.importer import (  # noqa: E402
    ImportOptions,
    VocabularyImporter,
    build_provider,
)
from services.vocabulary.sources import (  # noqa: E402
    ensure_source_rows,
    update_source_stats,
)

BUNDLED_SAMPLE = os.path.join("data", "sample_words.csv")


def _resolve_path(args) -> str | None:
    if args.file:
        return args.file if os.path.isabs(args.file) else os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            args.file,
        )
    if args.source == "seed":
        return os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            BUNDLED_SAMPLE,
        )
    return find_dataset(args.source, directory=args.dir)


def _download(args, path: str) -> str:
    url = args.url
    if not url:
        from services.vocabulary.sources import source_info

        url = source_info(args.source).dataset_url
    if not url:
        raise SystemExit(
            f"No dataset URL configured for source '{args.source}'. "
            "Pass --url explicitly."
        )
    print(f"Downloading {url}\n  -> {path}", flush=True)
    download_dataset(url, path)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import vocabulary into the words table."
    )
    parser.add_argument("file", nargs="?", default=None,
                        help="Explicit dataset file (.csv/.txt/.jsonl/.json)")
    parser.add_argument("--source", default="custom",
                        help="Source name: seed, kaikki, wikidata, frequency, custom")
    parser.add_argument("--file", dest="file_opt", default=None,
                        help="Explicit dataset file (alternative to positional)")
    parser.add_argument("--dir", default=None, help="Dataset directory")
    parser.add_argument("--mode", choices=["initial", "update", "replace"],
                        default="update")
    parser.add_argument("--language", default="en")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--resume-offset", type=int, default=0)
    parser.add_argument("--download", action="store_true",
                        help="Download the dataset URL before importing")
    parser.add_argument("--url", default=None,
                        help="Dataset URL to download (with --download)")
    parser.add_argument("--no-history", action="store_true",
                        help="Do not write a vocabulary_imports history row")
    args = parser.parse_args(argv)
    if args.file_opt and not args.file:
        args.file = args.file_opt

    app = create_app(os.environ.get("FLASK_CONFIG", "development"))
    with app.app_context():
        ensure_source_rows()
        directory = dataset_dir(args.dir or SettingsService.get("vocab_dataset_dir"))
        args.dir = directory

        path = _resolve_path(args)
        if args.download and args.source != "seed":
            destination = path or os.path.join(directory, f"{args.source}.dataset")
            path = _download(args, destination)
        if not path or not os.path.exists(path):
            print(f"No dataset found for source '{args.source}'.")
            print(f"Place a file in {directory} or pass a path explicitly.")
            return 1

        print(f"Importing from: {path}")
        print(f"Source: {args.source}  Mode: {args.mode}  Language: {args.language}")

        record = None
        if not args.no_history:
            record = VocabularyImport(
                source=args.source,
                label=os.path.basename(path),
                status="RUNNING",
                mode=args.mode,
                path=path,
                started_at=utcnow(),
                resume_offset=args.resume_offset,
            )
            db.session.add(record)
            db.session.commit()

        if args.mode == "replace":
            deleted = Word.query.filter(Word.source == args.source).delete()
            db.session.commit()
            print(f"Cleared {deleted} existing '{args.source}' rows.")

        provider = build_provider(path, source=args.source, language=args.language)
        filters = SettingsService.word_filters()
        options = ImportOptions(
            language=args.language,
            max_chars=filters["max_chars"],
            max_words=filters["max_words"],
            update_existing=(args.mode != "replace"),
            limit=args.limit,
        )
        importer = VocabularyImporter(provider, options, batch_size=args.batch_size)

        last = {"n": 0}

        def progress(stats):
            # Progress lines every ~50k entries keep the log readable.
            if stats.processed - last["n"] >= 50000:
                last["n"] = stats.processed
                print(
                    f"  processed={stats.processed:,} imported={stats.imported:,} "
                    f"updated={stats.updated:,} rejected={stats.rejected:,}",
                    flush=True,
                )
            if record is not None:
                record.total_processed = stats.processed
                record.total_imported = stats.imported
                record.total_updated = stats.updated
                record.total_duplicates = stats.duplicates
                record.total_rejected = stats.rejected
                record.total_errors = stats.errors
                record.resume_offset = stats.resume_offset
                db.session.commit()

        try:
            stats = importer.run(start_offset=args.resume_offset, progress=progress)
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            if record is not None:
                record.status = "FAILED"
                record.completed_at = utcnow()
                record.error_message = str(exc)[:2000]
                db.session.commit()
            print(f"Import failed: {exc}")
            return 1

        if record is not None:
            record.status = "COMPLETED"
            record.completed_at = utcnow()
            record.total_processed = stats.processed
            record.total_imported = stats.imported
            record.total_updated = stats.updated
            record.total_duplicates = stats.duplicates
            record.total_rejected = stats.rejected
            record.total_errors = stats.errors
            db.session.commit()

        update_source_stats(
            args.source, Word.query.filter_by(source=args.source).count()
        )

        print("\nImport complete:")
        print(f"  processed : {stats.processed:,}")
        print(f"  imported  : {stats.imported:,}")
        print(f"  updated   : {stats.updated:,}")
        print(f"  duplicates: {stats.duplicates:,}")
        print(f"  rejected  : {stats.rejected:,}")
        if stats.reject_reasons:
            for reason, count in sorted(stats.reject_reasons.items()):
                print(f"      - {reason}: {count:,}")
        print(f"  errors    : {stats.errors:,}")
        print(f"  total now : {Word.query.count():,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
