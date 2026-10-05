"""Custom file provider: CSV and TXT uploads.

Supported shapes (auto-detected):

* One word per line (``.txt``)
* CSV with only a ``word`` column, or a headerless single-column CSV
* Rich CSV with any of: word, category, difficulty, part_of_speech,
  definition, frequency_score, is_proper_noun, source_id

Missing metadata is simply left blank and filled in by the classifier.
"""

from __future__ import annotations

import csv
import io
import os
from typing import Iterator

from services.vocabulary.base_provider import (
    BaseProvider,
    RawEntry,
    SourceInfo,
)

_RICH_COLUMNS = {
    "word", "category", "difficulty", "part_of_speech", "pos", "definition",
    "frequency_score", "frequency", "is_proper_noun", "proper_noun",
    "source_id", "language", "lang",
}


class CustomFileProvider(BaseProvider):
    source = SourceInfo(
        name="custom",
        kind="file",
        description="Operator-provided CSV or TXT word list.",
        license_name="Operator-provided",
        license_url="",
        homepage_url="",
        dataset_url="",
        attribution="Uploaded by the site operator; license is the operator's responsibility.",
    )

    def __init__(self, path=None, *, language="en", dataset_url=None,
                 source_name: str = "custom") -> None:
        super().__init__(path, language=language, dataset_url=dataset_url)
        self.source = SourceInfo(
            name=source_name,
            kind="file",
            description="Operator-provided CSV or TXT word list.",
            license_name="Operator-provided",
            attribution="Uploaded by the site operator.",
        )

    def stream(self, start_offset: int = 0) -> Iterator[tuple[RawEntry, int]]:
        ext = os.path.splitext(self.path or "")[1].lower()
        if ext == ".txt":
            yield from self._stream_txt(start_offset)
        else:
            yield from self._stream_csv(start_offset)

    # ----------------------------------------------------------------- txt
    def _stream_txt(self, start_offset: int) -> Iterator[tuple[RawEntry, int]]:
        for line, offset in self._line_stream(start_offset):
            word = line.strip().lstrip("\ufeff")
            if not word:
                yield None, offset
                continue
            yield RawEntry(word=word, language=self.language), offset

    # ----------------------------------------------------------------- csv
    def _stream_csv(self, start_offset: int) -> Iterator[tuple[RawEntry, int]]:
        # Read a small header prefix to decide the shape, then stream the rest
        # so very large CSVs are processed incrementally.
        with open(self.path, "r", encoding="utf-8-sig", errors="replace",
                  newline="") as fh:
            if start_offset:
                fh.seek(start_offset)
            sample = fh.read(8192)
            fh.seek(start_offset)

            first_line = sample.splitlines()[0] if sample else ""
            header = next(csv.reader(io.StringIO(first_line)), [])
            header_lower = [h.strip().lower() for h in header]
            has_header = any(h in _RICH_COLUMNS for h in header_lower)
            word_index = (
                header_lower.index("word") if "word" in header_lower else 0
            )

            if has_header:
                # Consume the header line before streaming data rows.
                header_line = fh.readline()
                offset = start_offset + len(header_line.encode("utf-8"))
            else:
                offset = start_offset

            for line in fh:
                offset += len(line.encode("utf-8"))
                row = next(csv.reader(io.StringIO(line)), [])
                if not row:
                    yield None, offset
                    continue
                if has_header:
                    record = {
                        (header_lower[i] if i < len(header_lower) else str(i)): value
                        for i, value in enumerate(row)
                    }
                    yield self._entry_from_row(record), offset
                else:
                    word = row[word_index] if word_index < len(row) else row[0]
                    yield RawEntry(word=word, language=self.language), offset

    def _entry_from_row(self, record: dict) -> RawEntry | None:
        word = record.get("word")
        if word is None:
            return None
        pos = record.get("part_of_speech") or record.get("pos")
        freq_raw = record.get("frequency_score") or record.get("frequency")
        frequency = None
        if freq_raw not in (None, ""):
            try:
                frequency = float(freq_raw)
            except (TypeError, ValueError):
                frequency = None
        proper_raw = record.get("is_proper_noun") or record.get("proper_noun")
        proper = None
        if proper_raw not in (None, ""):
            proper = str(proper_raw).strip().lower() in {"1", "true", "yes", "y"}
        return RawEntry(
            word=word,
            source_id=(record.get("source_id") or None),
            language=(record.get("language") or record.get("lang")
                      or self.language),
            part_of_speech=(pos or None),
            definition=(record.get("definition") or None),
            category=(record.get("category") or None),
            difficulty=(record.get("difficulty") or None),
            frequency_score=frequency,
            is_proper_noun=proper,
        )
