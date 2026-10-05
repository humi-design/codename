"""Word engine - selects board words from the local ``words`` table.

This is the only place gameplay reads vocabulary.  It never makes external
network calls: the table is populated once by the ingestion engine
(``scripts/import_words.py`` or the Super Admin vocabulary page).

Large-table safety
------------------
A vocabulary table may hold millions of rows.  We never load it into Python and
we never use ``ORDER BY RAND()``.  Instead we pick random ids in the primary
key range and fetch a bounded oversample, which stays fast regardless of table
size.  Only the handful of words needed for a board ever leaves the database.
"""

from __future__ import annotations

import random

from sqlalchemy import func, select

from extensions import db
from models.constants import Category, WordMode
from models.word import Word
from services.settings_service import SettingsService

# Difficulty buckets per mode.  CHAOS deliberately spans every bucket so boards
# can mix common words with rare, technical and proper-noun entries.
_MODE_DIFFICULTIES = {
    WordMode.EASY: (WordMode.EASY,),
    WordMode.NORMAL: (WordMode.EASY, WordMode.NORMAL),
    WordMode.HARD: (WordMode.HARD, WordMode.NORMAL),
    WordMode.CHAOS: (
        WordMode.EASY, WordMode.NORMAL, WordMode.HARD, WordMode.CHAOS,
    ),
}

# Compact fallback so a fresh install is playable before any import.
FALLBACK_WORDS = [
    "SYNAPSE", "AXOLOTL", "QUASAR", "MITOSIS", "PARADOX", "PLATYPUS",
    "EINSTEIN", "MUMBAI", "LINUX", "MESSI", "NAPOLEON", "ORBIT", "NEURON",
    "VOLCANO", "PYTHON", "AMAZON", "TITANIUM", "MERCURY", "SATELLITE",
    "ALGORITHM", "COMPASS", "LANTERN", "GLACIER", "HARBOUR", "MEADOW",
    "CIRCUIT", "FOSSIL", "PHOTON", "TUNDRA", "REACTOR", "GRAVITY",
    "CANYON", "PENGUIN", "MAGNET", "ECLIPSE", "PIRATE", "CATHEDRAL",
    "VELOCITY", "MARMALADE", "OBSIDIAN", "NEBULA", "PENDULUM", "CORAL",
    "AZTEC", "SAMURAI", "VIKING", "PYRAMID", "GALAXY", "MOLECULE",
    "CHEETAH", "AVALANCHE", "LIGHTHOUSE", "SANDSTORM", "KILIMANJARO",
    "TOKYO", "SAHARA", "SHERLOCK", "GANDHI", "TESLA", "CURIOSITY",
    "BAMBOO", "CINNAMON", "PEPPER", "VANILLA", "WALNUT", "PISTACHIO",
]


class WordEngineError(ValueError):
    """Raised when not enough eligible vocabulary exists for a board."""


class WordEngine:
    """Query helper around the ``words`` table."""

    # ------------------------------------------------------------ filters
    @staticmethod
    def _difficulties_for_mode(mode: str) -> tuple[str, ...]:
        return _MODE_DIFFICULTIES.get(mode, _MODE_DIFFICULTIES[WordMode.NORMAL])

    @staticmethod
    def _base_conditions(mode: str, filters: dict, categories=None) -> list:
        conditions = [
            Word.language == filters["language"],
            Word.is_active.is_(True),
            Word.difficulty.in_(WordEngine._difficulties_for_mode(mode)),
        ]
        if not filters.get("allow_proper_nouns", True):
            conditions.append(Word.is_proper_noun.is_(False))
        if not filters.get("allow_multiword", True):
            conditions.append(Word.is_multiword.is_(False))
        max_chars = filters.get("max_chars") or 0
        if max_chars:
            conditions.append(Word.character_count <= int(max_chars))
        min_freq = filters.get("min_frequency") or 0
        if min_freq:
            conditions.append(Word.frequency_score >= float(min_freq))
        if categories:
            conditions.append(Word.category.in_(list(categories)))
        return conditions

    # -------------------------------------------------------------- counts
    @staticmethod
    def count_available(mode: str = WordMode.NORMAL, language: str | None = None,
                        categories=None, filters: dict | None = None) -> int:
        filters = filters or SettingsService.word_filters()
        if language:
            filters = {**filters, "language": language}
        conditions = WordEngine._base_conditions(mode, filters, categories)
        return (
            db.session.query(func.count(Word.id)).filter(*conditions).scalar()
            or 0
        )

    # ------------------------------------------------------------ selection
    @staticmethod
    def pick_words(count: int, mode: str = WordMode.NORMAL,
                   language: str | None = None, exclude: set[str] | None = None,
                   categories=None, filters: dict | None = None,
                   allow_fallback: bool = True) -> list[str]:
        """Return ``count`` unique display words for the requested mode.

        Uses random-key sampling for large tables and a plain random fetch for
        small ones.  Falls back to the bundled pool only when the database
        cannot supply enough words (fresh install).
        """
        exclude = {w.upper() for w in (exclude or set())}
        filters = filters or SettingsService.word_filters()
        if language:
            filters = {**filters, "language": language}
        conditions = WordEngine._base_conditions(mode, filters, categories)

        total = (
            db.session.query(func.count(Word.id)).filter(*conditions).scalar()
            or 0
        )

        pool: list[str] = []
        seen: set[str] = set()

        # Random id sampling can occasionally come up short on a large table
        # with gaps or many excluded rows; retry a couple of times before
        # concluding the vocabulary really is too small.
        attempts = 0
        while len(pool) < count and attempts < 3:
            attempts += 1
            for word in WordEngine._sample_rows(conditions, count, total):
                norm = (word or "").strip().upper()
                if not norm or norm in seen or norm in exclude:
                    continue
                seen.add(norm)
                pool.append(norm)
                if len(pool) >= count:
                    break

        if len(pool) < count:
            # Only a completely empty table falls back to the bundled list, so
            # a fresh install is playable.  A populated-but-insufficient table
            # is a real configuration problem and must surface as an error.
            if allow_fallback and total == 0:
                fallback = [
                    w for w in FALLBACK_WORDS if w not in seen and w not in exclude
                ]
                random.shuffle(fallback)
                pool.extend(fallback[: count - len(pool)])
            else:
                raise WordEngineError(
                    f"Not enough words available (need {count}, have {len(pool)} "
                    f"eligible, {total} in database). Import a larger vocabulary "
                    "from the Super Admin vocabulary page or run "
                    "scripts/import_words.py."
                )

        if len(pool) < count:
            raise WordEngineError(
                f"Not enough words available (need {count}, have {len(pool)}). "
                "Import a larger vocabulary from the Super Admin vocabulary page "
                "or run scripts/import_words.py."
            )
        return pool[:count]

    @staticmethod
    def _sample_rows(conditions, count: int, total: int):
        """Yield candidate words, sampled efficiently for large tables."""
        if total == 0:
            return

        # Oversample so post-filtering (dedupe / exclude) still leaves enough.
        want = min(total, max(count * 4, count + 20))

        if total <= 2000:
            # Small pool: a single ORDER BY RAND() over <=2000 rows is fine.
            rows = db.session.execute(
                select(Word.word).where(*conditions).order_by(func.rand()).limit(want)
            ).all()
            for (word,) in rows:
                yield word
            return

        # Large pool: pick random ids in the PK range and fetch a bounded set.
        min_id, max_id = db.session.query(
            func.min(Word.id), func.max(Word.id)
        ).filter(*conditions).one()
        if not min_id:
            return
        span = max_id - min_id
        picks = set()
        attempts = 0
        while len(picks) < want and attempts < want * 3:
            picks.add(random.randint(min_id, max_id))
            attempts += 1
        if not picks:
            return
        rows = db.session.execute(
            select(Word.word).where(*conditions, Word.id.in_(picks)).limit(want)
        ).all()
        for (word,) in rows:
            yield word

    # --------------------------------------------------------- statistics
    @staticmethod
    def statistics() -> dict:
        """Aggregate counts for the admin vocabulary page (cheap queries)."""
        total = Word.query.count()
        active = Word.query.filter(Word.is_active.is_(True)).count()
        stats = {
            "total": total,
            "active": active,
            "inactive": max(0, total - active),
            "proper_nouns": Word.query.filter(
                Word.is_proper_noun.is_(True)).count(),
            "multiword": Word.query.filter(Word.is_multiword.is_(True)).count(),
            "languages": dict(
                db.session.query(Word.language, func.count(Word.id))
                .group_by(Word.language)
                .order_by(func.count(Word.id).desc())
                .limit(20)
                .all()
            ),
            "categories": dict(
                db.session.query(Word.category, func.count(Word.id))
                .group_by(Word.category)
                .order_by(func.count(Word.id).desc())
                .all()
            ),
            "difficulties": dict(
                db.session.query(Word.difficulty, func.count(Word.id))
                .group_by(Word.difficulty)
                .all()
            ),
            "sources": dict(
                db.session.query(Word.source, func.count(Word.id))
                .group_by(Word.source)
                .order_by(func.count(Word.id).desc())
                .all()
            ),
        }
        stats["categories"] = {
            c: stats["categories"].get(c, 0) for c in Category.ALL
            if stats["categories"].get(c, 0) or c == Category.OTHER
        }
        return stats
