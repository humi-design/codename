"""Classification: category, difficulty, proper-noun and frequency scoring.

Classification is heuristic and intentionally never invents precise data.
Where a source provides a category or frequency we keep it; otherwise we make
a conservative best-effort guess and fall back to ``OTHER`` / ``NORMAL``.

The one thing the classifier *does* assert confidently is ``is_proper_noun``,
which is cheap to detect from capitalisation and is useful for filtering.
"""

from __future__ import annotations

import re

from models.constants import Category, WordMode

# Keyword hints for English vocabulary.  Kept deliberately small and precise;
# an entry that matches nothing stays ``OTHER`` rather than being mislabelled.
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    Category.SCIENCE: (
        "atom", "quantum", "physics", "chemical", "molecule", "cell", "gene",
        "protein", "enzyme", "photon", "electron", "neutron", "galaxy",
        "nebula", "orbit", "gravity", "entropy", "energy", "enzyme", "isotope",
        "photosynthesis", "chromosome", "bacteria", "virus", "fossil",
    ),
    Category.MEDICAL: (
        "artery", "vein", "neuron", "cortex", "vaccine", "antibiotic",
        "diagnosis", "symptom", "surgery", "anatomy", "cardiac", "renal",
        "hepatic", "plasma", "platelet", "immunity", "pathogen", "tumour",
        "tumor", "syndrome", "disease",
    ),
    Category.COMPUTER: (
        "algorithm", "compiler", "kernel", "database", "protocol", "server",
        "boolean", "binary", "cache", "runtime", "byte", "pixel", "network",
        "software", "hardware", "encryption", "firewall", "variable",
    ),
    Category.TECHNOLOGY: (
        "turbine", "laser", "radar", "sonar", "circuit", "transistor",
        "battery", "engine", "sensor", "robot", "satellite", "antenna",
        "reactor", "turbine", "semiconductor",
    ),
    Category.ENGINEERING: (
        "bridge", "dam", "tunnel", "beam", "torque", "friction", "hydraulic",
        "pneumatic", "blueprint", "weld", "rivet", "gear", "piston",
    ),
    Category.GEOGRAPHY: (
        "river", "mountain", "valley", "desert", "island", "peninsula",
        "glacier", "plateau", "delta", "estuary", "canyon", "tundra",
        "savanna", "reef", "strait", "fjord", "volcano",
    ),
    Category.ANIMAL: (
        "tiger", "eagle", "shark", "whale", "dolphin", "penguin", "falcon",
        "otter", "badger", "salmon", "beetle", "spider", "lizard", "serpent",
        "panther", "buffalo", "antelope",
    ),
    Category.FOOD: (
        "bread", "cheese", "pepper", "vanilla", "cinnamon", "walnut", "pasta",
        "coffee", "honey", "mango", "banana", "tomato", "potato", "garlic",
        "ginger", "pistachio", "marmalade",
    ),
    Category.SPORT: (
        "football", "cricket", "tennis", "hockey", "rugby", "marathon",
        "sprint", "javelin", "hurdle", "goalkeeper", "referee", "stadium",
        "olympic", "boxing", "cycling",
    ),
    Category.PROFESSION: (
        "doctor", "lawyer", "engineer", "teacher", "pilot", "surgeon",
        "architect", "journalist", "pharmacist", "carpenter", "plumber",
        "electrician", "astronomer", "geologist",
    ),
    Category.BUSINESS: (
        "invoice", "ledger", "revenue", "startup", "shareholder", "dividend",
        "payroll", "audit", "equity", "merger", "acquisition", "logistics",
    ),
    Category.CONCEPT: (
        "freedom", "justice", "paradox", "logic", "ethics", "memory",
        "consciousness", "infinity", "causality", "identity", "metaphor",
        "hypothesis", "theory", "theorem",
    ),
    Category.HISTORY: (
        "empire", "dynasty", "revolution", "treaty", "century", "medieval",
        "colonial", "ancient", "civilisation", "civilization", "kingdom",
        "pharaoh", "gladiator", "crusade",
    ),
}

# Suffixes / patterns suggesting a proper noun (place, person, organisation).
_PLACE_SUFFIXES = (
    "stan", "land", "burg", "borough", "shire", "ton", "ville", "polis",
    "abad", "pur", "port", "field", "ford", "haven",
)
_ORG_SUFFIXES = (
    " inc", " corp", " corporation", " ltd", " llc", " university",
    " institute", " foundation", " association", " committee",
)

# Part-of-speech -> category hint (used when the source gives a POS but no
# category).  Deliberately sparse so we do not mislabel.
_POS_CATEGORY = {
    "name": Category.PLACE,
    "propn": Category.PLACE,
    "proper noun": Category.PLACE,
}


def detect_proper_noun(word: str, source_flag: bool | None = None) -> bool:
    """Detect proper nouns from capitalisation or an explicit source flag."""
    if source_flag is not None:
        return bool(source_flag)
    if not word or " " in word:
        # Multi-word names are usually capitalised; single lowercase words
        # are not proper nouns.
        return bool(word) and word[:1].isupper() and word[1:2].islower()
    # Single token: proper noun if it is not an all-caps dictionary form.
    return False


def guess_category(word: str, *, part_of_speech: str | None = None,
                   is_proper_noun: bool = False) -> str:
    """Best-effort category.  Returns ``OTHER`` when nothing matches."""
    lowered = word.casefold()

    if is_proper_noun:
        if any(lowered.endswith(sfx) for sfx in _ORG_SUFFIXES):
            return Category.ORGANIZATION
        if any(lowered.endswith(sfx) for sfx in _PLACE_SUFFIXES):
            return Category.PLACE
        return Category.PERSON

    pos = (part_of_speech or "").casefold()
    if pos in _POS_CATEGORY:
        return _POS_CATEGORY[pos]

    # Exact-ish keyword match on the whole word first, then substring.
    for category, hints in _CATEGORY_HINTS.items():
        if lowered in hints:
            return category
    for category, hints in _CATEGORY_HINTS.items():
        for hint in hints:
            if hint in lowered:
                return category
    return Category.OTHER


# Frequency buckets -> a 0-100 score used only when the source gives no
# explicit frequency.  This keeps common words distinguishable from rare ones
# without fabricating precise counts.
def guess_frequency_score(word: str, *, is_proper_noun: bool = False,
                          frequency_hint: float | None = None) -> float:
    if frequency_hint is not None:
        return max(0.0, min(100.0, float(frequency_hint)))
    length = len(word)
    if is_proper_noun:
        base = 45.0
    elif length <= 4:
        base = 85.0
    elif length <= 6:
        base = 70.0
    elif length <= 9:
        base = 55.0
    elif length <= 12:
        base = 40.0
    else:
        base = 25.0
    if " " in word:
        base -= 10.0
    return max(0.0, min(100.0, base))


def score_to_difficulty(frequency_score: float, *, is_proper_noun: bool = False,
                        rare_hint: bool = False) -> str:
    """Map a 0-100 frequency score to a difficulty bucket."""
    if rare_hint:
        return WordMode.CHAOS
    if frequency_score >= 75:
        return WordMode.EASY
    if frequency_score >= 45:
        return WordMode.NORMAL
    if frequency_score >= 20:
        return WordMode.HARD
    return WordMode.CHAOS


def guess_difficulty(word: str, *, is_proper_noun: bool = False,
                     frequency_score: float | None = None,
                     rare_hint: bool = False) -> str:
    score = (
        frequency_score
        if frequency_score is not None
        else guess_frequency_score(word, is_proper_noun=is_proper_noun)
    )
    return score_to_difficulty(score, is_proper_noun=is_proper_noun,
                               rare_hint=rare_hint)


def normalize_category(value, fallback: str = Category.OTHER) -> str:
    if not value:
        return fallback
    candidate = str(value).strip().upper()
    return candidate if candidate in Category.ALL else fallback


def normalize_difficulty(value, fallback: str = WordMode.NORMAL) -> str:
    if not value:
        return fallback
    candidate = str(value).strip().upper()
    return candidate if candidate in WordMode.ALL else fallback
