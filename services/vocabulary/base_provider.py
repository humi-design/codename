"""Base classes for vocabulary providers.

A provider knows how to read one kind of external dataset and yield *raw*
entry dicts.  Cleaning, classification and persistence are handled centrally by
the importer, so a new source only has to implement ``stream`` and the source
metadata.  This keeps the board generator and game engine completely decoupled
from where vocabulary came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class SourceInfo:
    """License / attribution metadata for a source."""

    name: str
    kind: str = "file"
    description: str = ""
    license_name: str = ""
    license_url: str = ""
    homepage_url: str = ""
    dataset_url: str = ""
    attribution: str = ""


@dataclass
class RawEntry:
    """A single raw vocabulary entry yielded by a provider."""

    word: str
    source_id: str | None = None
    language: str = "en"
    part_of_speech: str | None = None
    definition: str | None = None
    category: str | None = None
    difficulty: str | None = None
    frequency_score: float | None = None
    is_proper_noun: bool | None = None
    rare: bool = False
    extra: dict = field(default_factory=dict)


class BaseProvider:
    """Interface every vocabulary provider implements.

    Subclasses must set :attr:`source` and implement :meth:`stream`.
    """

    #: :class:`SourceInfo` describing the source (license, attribution).
    source: SourceInfo = SourceInfo(name="base")

    def __init__(self, path: str | None = None, *, language: str = "en",
                 dataset_url: str | None = None) -> None:
        self.path = path
        self.language = language
        self.dataset_url = dataset_url

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.source.name

    def available(self) -> bool:
        """Whether the underlying data is present and readable."""
        import os

        return bool(self.path) and os.path.exists(self.path)

    def stream(self, start_offset: int = 0) -> Iterator[tuple[RawEntry, int]]:
        """Yield ``(RawEntry, byte_offset_after_this_line)`` pairs.

        ``start_offset`` allows a resumed import to skip already-processed
        bytes.  Providers that cannot seek may ignore it.
        """
        raise NotImplementedError

    # ---------------------------------------------------------------- util
    def _line_stream(self, start_offset: int = 0):
        """Yield ``(line, byte_offset)`` for a UTF-8 text file, seeking safely.

        When resuming, the partial line at ``start_offset`` is discarded so we
        never emit a half-read record.
        """
        with open(self.path, "rb") as fh:
            if start_offset:
                fh.seek(start_offset)
                fh.readline()  # discard the partial line
            offset = fh.tell()
            for raw_line in fh:
                offset += len(raw_line)
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                yield line, offset
