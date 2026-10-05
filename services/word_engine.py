"""Word engine.

Selects words for a board from the local ``words`` table.  It never makes
external network calls at game time - vocabulary is imported once via
``scripts/import_words.py``.

A small built-in fallback pool guarantees the game is playable even when the
``words`` table has not been populated yet (e.g. fresh development install).
"""

from __future__ import annotations

import random

from sqlalchemy import func

from extensions import db
from models.constants import WordMode
from models.word import Word

# Difficulty buckets.  CHAOS intentionally draws from *every* bucket so the
# board can contain rare / technical / proper-noun words.
_MODE_DIFFICULTIES = {
    WordMode.EASY: (WordMode.EASY,),
    WordMode.NORMAL: (WordMode.EASY, WordMode.NORMAL),
    WordMode.HARD: (WordMode.HARD, WordMode.NORMAL),
    WordMode.CHAOS: (WordMode.EASY, WordMode.NORMAL, WordMode.HARD, WordMode.CHAOS),
}

# Fallback pool (development / first run).  Kept compact; the CSV holds more.
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


class WordEngine:
    """Query helper around the ``words`` table."""

    @staticmethod
    def _difficulties_for_mode(mode: str) -> tuple[str, ...]:
        return _MODE_DIFFICULTIES.get(mode, _MODE_DIFFICULTIES[WordMode.NORMAL])

    @staticmethod
    def count_available(mode: str = WordMode.NORMAL, language: str = "en") -> int:
        difficulties = WordEngine._difficulties_for_mode(mode)
        return (
            db.session.query(func.count(Word.id))
            .filter(
                Word.language == language,
                Word.is_active.is_(True),
                Word.difficulty.in_(difficulties),
            )
            .scalar()
            or 0
        )

    @staticmethod
    def pick_words(count: int, mode: str = WordMode.NORMAL, language: str = "en",
                   exclude: set[str] | None = None) -> list[str]:
        """Return ``count`` unique words for the requested mode.

        Words are drawn from the database when enough are available, otherwise
        the built-in fallback pool tops the selection up so a board can always
        be generated.
        """
        exclude = {w.upper() for w in (exclude or set())}
        difficulties = WordEngine._difficulties_for_mode(mode)

        rows = (
            db.session.query(Word.word)
            .filter(
                Word.language == language,
                Word.is_active.is_(True),
                Word.difficulty.in_(difficulties),
            )
            .all()
        )
        pool: list[str] = []
        seen: set[str] = set()
        for (word,) in rows:
            norm = (word or "").strip().upper()
            if not norm or norm in seen or norm in exclude:
                continue
            seen.add(norm)
            pool.append(norm)

        random.shuffle(pool)

        if len(pool) < count:
            fallback = [w for w in FALLBACK_WORDS if w not in seen and w not in exclude]
            random.shuffle(fallback)
            pool.extend(fallback)

        if len(pool) < count:
            raise ValueError(
                f"Not enough words available (need {count}, have {len(pool)}). "
                "Import a larger vocabulary with scripts/import_words.py."
            )

        return pool[:count]
