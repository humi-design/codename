"""Word cleaning and normalisation for the vocabulary ingestion engine.

The cleaner is deliberately conservative: it rejects obvious noise (markup,
URLs, sentences, metadata fragments) but never removes legitimate unusual
vocabulary such as scientific, technical, medical, historical or proper-noun
entries.  Judging suitability is the job of the classifier and the board
filters, not of this module.
"""

from __future__ import annotations

import html
import re
import unicodedata

# Characters allowed in a vocabulary entry.  Letters (any script), digits,
# spaces, and the joiners/punctuation that appear inside real names and terms.
_ALLOWED_RE = re.compile(r"^[^\W_][\w'’.\- ]*$", re.UNICODE)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]{0,200}\}\}")
_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]|]{0,200})(?:\|([^\[\]]{0,200}))?\]\]")
_WIKI_BOLD_RE = re.compile(r"'{2,5}")
_REF_RE = re.compile(r"&lt;ref[^&]{0,300}?/ref&gt;|&#x?[0-9A-Fa-f]{1,6};")
_WHITESPACE_RE = re.compile(r"\s+")

# Metadata / grammatical noise that leaks out of dictionary dumps.
_NOISE_WORDS = frozenset(
    {
        "category", "categories", "plural", "plurals", "alternative",
        "synonym", "synonyms", "antonym", "antonyms", "unknown", "see also",
        "translation", "translations", "derived", "related", "pronunciation",
        "etymology", "inflection", "comparative", "superlative", "diminutive",
        "obsolete", "archaic", "misspelling", "abbreviation", "initialism",
        "acronym", "alternative form", "inflected form", "nonstandard",
        "non-standard", "definition", "definitions", "example", "examples",
        "quotations", "usage notes", "references", "external links",
    }
)

# Suffixes that indicate a sentence/metadata fragment rather than a word.
_SENTENCE_HINTS = ("http", "://", "<", ">", "{", "}", "|", "=")


class CleanResult:
    """Outcome of cleaning one raw entry."""

    __slots__ = ("ok", "word", "normalized", "reason")

    def __init__(self, ok: bool, word: str = "", normalized: str = "",
                 reason: str = "") -> None:
        self.ok = ok
        self.word = word
        self.normalized = normalized
        self.reason = reason


def strip_markup(value: str) -> str:
    """Remove URLs, HTML, wiki templates and leftover entities."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = html.unescape(value)
    value = _URL_RE.sub(" ", value)
    value = _HTML_TAG_RE.sub(" ", value)
    value = _TEMPLATE_RE.sub(" ", value)
    # [[target]] -> target; [[target|label]] -> label (the readable form).
    value = _WIKI_LINK_RE.sub(lambda m: m.group(2) or m.group(1), value)
    value = _WIKI_BOLD_RE.sub("", value)
    value = _REF_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_word(value: str) -> str:
    """Produce the canonical dedup key for a display word.

    Case-folding, Unicode normalisation and whitespace collapsing so that
    ``Quasar``, ``QUASAR`` and ``quasar`` share one key.  The display form is
    preserved separately on the row.
    """
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value.casefold()


def clean_word(raw, *, max_chars: int = 24, max_words: int = 3) -> CleanResult:
    """Clean a single raw vocabulary entry.

    Returns a :class:`CleanResult`; ``ok`` is ``False`` for anything that
    should be rejected, with a short machine-readable ``reason``.
    """
    if raw is None:
        return CleanResult(False, reason="empty")
    # Reject entries that are actually markup, a URL or a template rather than
    # a word.  Cleaning those silently would risk importing fragments.
    raw_str = str(raw)
    if (_URL_RE.search(raw_str) or _HTML_TAG_RE.search(raw_str)
            or _TEMPLATE_RE.search(raw_str)):
        return CleanResult(False, reason="markup")

    value = strip_markup(raw)
    if not value:
        return CleanResult(False, reason="empty")

    # Reject anything still carrying sentence / markup noise.
    if any(hint in value for hint in _SENTENCE_HINTS):
        return CleanResult(False, reason="markup")
    if value.endswith((".", "!", "?", ";", ":")):
        # Trailing sentence punctuation is a strong sentence signal.
        value = value.rstrip(" .,;:!?")
        if not value:
            return CleanResult(False, reason="empty")

    # Strip surrounding quotes / brackets that survive markup removal.
    value = value.strip(" \t\"'`()[]{}")

    if not value:
        return CleanResult(False, reason="empty")

    lowered = value.casefold()
    if lowered in _NOISE_WORDS:
        return CleanResult(False, reason="metadata")

    words = value.split(" ")
    if len(words) > max_words:
        return CleanResult(False, reason="too_many_words")
    if len(value) > max_chars:
        return CleanResult(False, reason="too_long")
    if len(value) < 1:
        return CleanResult(False, reason="empty")

    # Must start with a letter and contain no control / symbol soup.
    if not value[0].isalpha():
        return CleanResult(False, reason="not_word")
    if not _ALLOWED_RE.match(value):
        return CleanResult(False, reason="invalid_chars")
    # Require at least one letter overall (rejects pure punctuation/number).
    if not any(ch.isalpha() for ch in value):
        return CleanResult(False, reason="not_word")
    # A single "word" that is really a long digit string (years, ids).
    if value.replace(" ", "").isdigit():
        return CleanResult(False, reason="numeric")

    normalized = normalize_word(value)
    if not normalized:
        return CleanResult(False, reason="empty")

    return CleanResult(True, word=value, normalized=normalized)


def clean_definition(raw, *, max_chars: int = 400) -> str | None:
    """Clean a dictionary gloss for storage (never used for gameplay)."""
    if not raw:
        return None
    value = strip_markup(raw)
    if not value:
        return None
    return value[:max_chars]
