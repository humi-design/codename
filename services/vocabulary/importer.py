"""Core vocabulary importer.

Consumes a provider's stream, cleans and classifies each entry, deduplicates
against both the current run and the existing database rows, and upserts in
efficient batches.  It never loads a whole dataset into memory: entries are
processed one line at a time.

Persistence strategy
--------------------
* A batch of cleaned rows is inserted with a single multi-row INSERT.
* Duplicates within the run are dropped before they reach the database.
* Existing rows are updated (metadata merged, ``is_active`` re-enabled) rather
  than duplicated, using the ``(normalized_word, language)`` unique key.

The importer is deliberately free of Flask request context: it can be driven
from a CLI script, a background thread or a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from extensions import db
from models.constants import Category, WordMode, utcnow
from models.word import Word
from services.vocabulary.base_provider import BaseProvider, RawEntry
from services.vocabulary.classifier import (
    guess_category,
    guess_difficulty,
    guess_frequency_score,
    normalize_category,
    normalize_difficulty,
)
from services.vocabulary.cleaner import clean_definition, clean_word

# MySQL's max placeholders is ~65535; 1000 rows x 17 cols stays well clear and
# keeps transactions short on shared hosting.
BATCH_SIZE = 1000


@dataclass
class ImportStats:
    """Counters for one import run."""

    processed: int = 0
    imported: int = 0
    updated: int = 0
    duplicates: int = 0
    rejected: int = 0
    errors: int = 0
    resume_offset: int = 0
    reject_reasons: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "imported": self.imported,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "errors": self.errors,
            "resume_offset": self.resume_offset,
        }


@dataclass
class ImportOptions:
    language: str = "en"
    max_chars: int = 24
    max_words: int = 3
    default_category: str = Category.OTHER
    default_difficulty: str = WordMode.NORMAL
    update_existing: bool = True
    limit: int | None = None


class VocabularyImporter:
    """Runs a provider stream into the ``words`` table."""

    def __init__(self, provider: BaseProvider, options: ImportOptions | None = None,
                 *, batch_size: int = BATCH_SIZE) -> None:
        self.provider = provider
        self.options = options or ImportOptions()
        self.batch_size = batch_size
        # Populated lazily so tests can call ``run`` without a prior DB read.
        self._seen: set[tuple[str, str]] = set()

    # ----------------------------------------------------------------- run
    def run(self, *, start_offset: int = 0,
            progress=None, should_stop=None) -> ImportStats:
        """Import the provider stream.

        ``progress(stats)`` is called after each batch.  ``should_stop()`` may
        return ``True`` to cancel cooperatively; the run then returns with the
        offset it reached so it can be resumed later.
        """
        stats = ImportStats()
        batch: list[dict] = []
        offset = start_offset

        for entry, offset in self.provider.stream(start_offset):
            if should_stop is not None and should_stop():
                break
            stats.processed += 1
            if entry is None:
                stats.rejected += 1
                self._count_reason(stats, "unparsable")
                continue

            row = self._prepare_row(entry, stats)
            if row is None:
                continue

            batch.append(row)
            if len(batch) >= self.batch_size:
                self._flush(batch, stats)
                batch = []
                stats.resume_offset = offset
                if progress is not None:
                    progress(stats)
                if self.options.limit and stats.imported >= self.options.limit:
                    break

        if batch:
            self._flush(batch, stats)
        stats.resume_offset = offset
        if progress is not None:
            progress(stats)
        return stats

    # ------------------------------------------------------------- helpers
    def _prepare_row(self, entry: RawEntry, stats: ImportStats) -> dict | None:
        language = (entry.language or self.options.language or "en").lower()[:8]
        # Only English feeds the default board; other languages are stored but
        # clearly tagged so they can never flood an English game.
        result = clean_word(entry.word, max_chars=self.options.max_chars,
                            max_words=self.options.max_words)
        if not result.ok:
            stats.rejected += 1
            self._count_reason(stats, result.reason)
            return None

        key = (result.normalized, language)
        if key in self._seen:
            stats.duplicates += 1
            return None
        self._seen.add(key)

        proper = self._resolve_proper(entry, result.word)
        category = normalize_category(
            entry.category or self.options.default_category, Category.OTHER
        )
        if category == Category.OTHER:
            category = guess_category(
                result.word, part_of_speech=entry.part_of_speech,
                is_proper_noun=proper,
            )
        frequency = entry.frequency_score
        if frequency is None:
            frequency = guess_frequency_score(result.word, is_proper_noun=proper)
        difficulty = normalize_difficulty(entry.difficulty, "")
        if not difficulty:
            difficulty = guess_difficulty(
                result.word, is_proper_noun=proper,
                frequency_score=frequency, rare_hint=entry.rare,
            )

        return {
            "word": result.word,
            "normalized_word": result.normalized,
            "language": language,
            "part_of_speech": (entry.part_of_speech or None),
            "definition": clean_definition(entry.definition),
            "category": category,
            "difficulty": difficulty,
            "frequency_score": float(frequency),
            "is_proper_noun": proper,
            "is_multiword": " " in result.word,
            "character_count": len(result.word),
            "source": self.provider.name,
            "source_id": (entry.source_id or None),
            "is_active": True,
            # Core INSERT bypasses ORM defaults, so timestamps are set here.
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }

    @staticmethod
    def _resolve_proper(entry: RawEntry, word: str) -> bool:
        if entry.is_proper_noun is not None:
            return bool(entry.is_proper_noun)
        # Multi-word entries that are fully capitalised (e.g. "NEW YORK") are
        # treated as names; everything else is left as not-a-proper-noun.
        parts = word.split(" ")
        if len(parts) > 1:
            return all(p[:1].isupper() for p in parts if p)
        return False

    @staticmethod
    def _count_reason(stats: ImportStats, reason: str) -> None:
        stats.reject_reasons[reason] = stats.reject_reasons.get(reason, 0) + 1

    # ------------------------------------------------------------ database
    def _flush(self, rows: list[dict], stats: ImportStats) -> None:
        """Upsert a batch in a single statement.

        A single ``INSERT ... ON DUPLICATE KEY UPDATE`` is far cheaper than
        one INSERT/UPDATE per row, which matters on shared hosting.  New vs
        updated counts are derived from the pre-computed key set.
        """
        try:
            existing = self._existing_keys(rows)
            updates = sum(
                1 for r in rows
                if (r["normalized_word"], r["language"]) in existing
            )
            inserts = len(rows) - updates
            self._upsert(rows)
            db.session.commit()
            stats.imported += inserts
            stats.updated += updates
        except Exception:  # pragma: no cover - depends on DB state
            db.session.rollback()
            stats.errors += len(rows)
            raise

    @staticmethod
    def _existing_keys(rows: list[dict]) -> set[tuple[str, str]]:
        keys = {(r["normalized_word"], r["language"]) for r in rows}
        if not keys:
            return set()
        norms = {k[0] for k in keys}
        found = db.session.execute(
            select(Word.normalized_word, Word.language).where(
                Word.normalized_word.in_(norms)
            )
        ).all()
        return {(n, lang) for n, lang in found}

    def _upsert(self, rows: list[dict]) -> None:
        from sqlalchemy import func

        table = Word.__table__
        stmt = mysql_insert(table).values(rows)
        inserted = stmt.inserted
        if not self.options.update_existing:
            stmt = stmt.prefix_with("IGNORE")
            db.session.execute(stmt)
            return

        # Merge metadata intelligently: never wipe good existing values with a
        # null or a placeholder "OTHER" category.
        stmt = stmt.on_duplicate_key_update(
            part_of_speech=func.coalesce(inserted.part_of_speech,
                                         table.c.part_of_speech),
            definition=func.coalesce(inserted.definition, table.c.definition),
            category=func.coalesce(func.nullif(inserted.category, Category.OTHER),
                                   table.c.category),
            difficulty=inserted.difficulty,
            frequency_score=inserted.frequency_score,
            is_proper_noun=inserted.is_proper_noun,
            is_multiword=inserted.is_multiword,
            character_count=inserted.character_count,
            source=inserted.source,
            source_id=func.coalesce(inserted.source_id, table.c.source_id),
            is_active=True,
        )
        db.session.execute(stmt)


def import_file(path: str, *, source: str = "custom", language: str = "en",
                update_existing: bool = True, limit: int | None = None,
                start_offset: int = 0, provider: BaseProvider | None = None,
                options: ImportOptions | None = None):
    """Convenience wrapper used by the CLI and tests.

    Returns ``(stats, provider)`` so the caller can persist history.
    """
    if provider is None:
        provider = build_provider(path, source=source, language=language)
    opts = options or ImportOptions(language=language, update_existing=update_existing,
                                    limit=limit)
    importer = VocabularyImporter(provider, opts)
    stats = importer.run(start_offset=start_offset)
    return stats, provider


def build_provider(path: str, *, source: str = "custom", language: str = "en",
                   dataset_url: str | None = None) -> BaseProvider:
    """Pick a provider based on the requested source / file extension."""
    from services.vocabulary.custom_file_provider import CustomFileProvider
    from services.vocabulary.frequency_provider import FrequencyProvider
    from services.vocabulary.kaikki_provider import KaikkiProvider
    from services.vocabulary.wikidata_provider import WikidataProvider

    lowered = (source or "").lower()
    if lowered in ("kaikki", "wiktionary", "wiktextract"):
        return KaikkiProvider(path, language=language, dataset_url=dataset_url)
    if lowered in ("wikidata", "wd"):
        return WikidataProvider(path, language=language, dataset_url=dataset_url)
    if lowered in ("frequency", "freq"):
        return FrequencyProvider(path, language=language, dataset_url=dataset_url,
                                 source_name="frequency")
    return CustomFileProvider(path, language=language, dataset_url=dataset_url,
                              source_name=(source or "custom"))
