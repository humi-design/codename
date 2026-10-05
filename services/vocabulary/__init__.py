"""Vocabulary ingestion engine.

External datasets flow through here into MySQL:

    providers -> cleaner -> classifier -> importer -> words table

Gameplay never touches this package; it reads the ``words`` table directly
through :mod:`services.word_engine`.
"""

from services.vocabulary.base_provider import BaseProvider, RawEntry, SourceInfo
from services.vocabulary.cleaner import clean_definition, clean_word, normalize_word
from services.vocabulary.importer import (
    ImportOptions,
    ImportStats,
    VocabularyImporter,
    build_provider,
    import_file,
)

__all__ = [
    "BaseProvider",
    "RawEntry",
    "SourceInfo",
    "ImportOptions",
    "ImportStats",
    "VocabularyImporter",
    "build_provider",
    "import_file",
    "clean_definition",
    "clean_word",
    "normalize_word",
]
