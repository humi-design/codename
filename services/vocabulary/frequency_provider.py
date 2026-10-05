"""Frequency provider.

Reads a frequency list (word + count/rank) and yields entries carrying an
explicit ``frequency_score``.  Two common shapes are supported:

* ``word<TAB>count`` or ``word,count`` (Google Books / COCA style)
* ``word<TAB>rank`` (1 = most frequent)

The raw count/rank is converted to a normalised 0-100 score.  No frequency
data is invented: if a source does not provide it, the classifier's heuristic
is used instead.

Typical sources: Google Books Ngram derived lists, SUBTLEX, wordfreq exports.
Check each dataset's license before redistribution.
"""

from __future__ import annotations

import math
import os
from typing import Iterator

from services.vocabulary.base_provider import (
    BaseProvider,
    RawEntry,
    SourceInfo,
)


class FrequencyProvider(BaseProvider):
    source = SourceInfo(
        name="frequency",
        kind="frequency",
        description="Word frequency list (word + count or rank).",
        license_name="Dataset-specific",
        license_url="",
        homepage_url="",
        dataset_url="",
        attribution="Frequency data provided by the operator; check the dataset license.",
    )

    def __init__(self, path=None, *, language="en", dataset_url=None,
                 rank_based: bool | None = None, source_name: str = "frequency"):
        super().__init__(path, language=language, dataset_url=dataset_url)
        self.rank_based = rank_based
        self.source = SourceInfo(
            name=source_name,
            kind="frequency",
            description="Word frequency list (word + count or rank).",
            license_name="Dataset-specific",
            attribution="Frequency data provided by the operator.",
        )

    def stream(self, start_offset: int = 0) -> Iterator[tuple[RawEntry, int]]:
        rank_based = self.rank_based
        if rank_based is None:
            rank_based = "rank" in os.path.basename(self.path or "").lower()

        for line, offset in self._line_stream(start_offset):
            line = line.strip()
            if not line:
                yield None, offset
                continue
            parts = line.replace(",", "\t").split("\t")
            word = parts[0].strip()
            if not word:
                yield None, offset
                continue
            value = None
            if len(parts) > 1:
                try:
                    value = float(parts[1].strip())
                except (TypeError, ValueError):
                    value = None
            score = self._to_score(value, rank_based)
            yield RawEntry(
                word=word,
                language=self.language,
                frequency_score=score,
            ), offset

    @staticmethod
    def _to_score(value: float | None, rank_based: bool) -> float | None:
        if value is None:
            return None
        if rank_based:
            # Rank 1 -> ~100, rank 100k -> ~0.  Logarithmic so the long tail
            # keeps a non-zero score.
            if value < 1:
                value = 1
            score = 100.0 - (math.log10(value) / 6.0) * 100.0
        else:
            # Count based: normalise with a log scale so a handful of very
            # common words do not flatten everything else to zero.
            if value <= 0:
                return 0.0
            score = (math.log10(value + 1) / 7.0) * 100.0
        return max(0.0, min(100.0, score))
