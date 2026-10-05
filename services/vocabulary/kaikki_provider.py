"""Kaikki / Wiktextract provider.

Reads the machine-readable JSONL dumps published by Kaikki (derived from
Wiktionary / Wiktextract).  Each line is a JSON object describing one word
sense; the provider extracts the word, part of speech, a gloss and any category
tags it can find.

Data license: Wiktionary content is available under CC BY-SA 4.0 (and GFDL for
older revisions).  See ``services/vocabulary/sources.py`` for the attribution
recorded against the source.  This provider only reads datasets the operator
has downloaded; it does not scrape any service.
"""

from __future__ import annotations

import json
from typing import Iterator

from services.vocabulary.base_provider import (
    BaseProvider,
    RawEntry,
    SourceInfo,
)

# Wiktionary "topics" categories we can map onto game categories.
_TOPIC_MAP = {
    "science": "SCIENCE",
    "physics": "SCIENCE",
    "chemistry": "SCIENCE",
    "biology": "SCIENCE",
    "medicine": "MEDICAL",
    "computing": "COMPUTER",
    "computer": "COMPUTER",
    "engineering": "ENGINEERING",
    "technology": "TECHNOLOGY",
    "geography": "GEOGRAPHY",
    "history": "HISTORY",
    "sports": "SPORT",
    "food": "FOOD",
    "business": "BUSINESS",
    "animals": "ANIMAL",
    "people": "PERSON",
    "organizations": "ORGANIZATION",
    "military": "HISTORY",
    "music": "CONCEPT",
    "mathematics": "SCIENCE",
}


class KaikkiProvider(BaseProvider):
    source = SourceInfo(
        name="kaikki",
        kind="jsonl",
        description="Kaikki.org / Wiktextract English dictionary dump (JSONL).",
        license_name="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        homepage_url="https://kaikki.org/dictionary/English/",
        dataset_url="https://kaikki.org/dictionary/English/"
        "kaikki.org-dictionary-English.jsonl",
        attribution="Data derived from Wiktionary (CC BY-SA 4.0).",
    )

    def stream(self, start_offset: int = 0) -> Iterator[tuple[RawEntry, int]]:
        for line, offset in self._line_stream(start_offset):
            line = line.strip()
            if not line:
                yield None, offset
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                yield None, offset
                continue

            word = obj.get("word")
            if not word:
                yield None, offset
                continue

            pos = obj.get("pos")
            language = obj.get("lang_code") or obj.get("lang") or self.language
            senses = obj.get("senses") or []
            definition = None
            topics: list[str] = []
            tags: list[str] = []
            if isinstance(senses, list) and senses:
                first = senses[0] if isinstance(senses[0], dict) else {}
                glosses = first.get("glosses") or []
                if glosses:
                    definition = glosses[0]
                topics = first.get("topics") or []
                tags = first.get("tags") or []

            category = None
            for topic in topics:
                mapped = _TOPIC_MAP.get(str(topic).casefold())
                if mapped:
                    category = mapped
                    break

            rare = any(
                str(tag).casefold() in {"rare", "obsolete", "archaic"}
                for tag in tags
            )
            proper = pos == "name" or pos == "propn"

            yield (
                RawEntry(
                    word=word,
                    source_id=None,
                    language=language,
                    part_of_speech=pos,
                    definition=definition,
                    category=category,
                    is_proper_noun=proper,
                    rare=rare,
                ),
                offset,
            )
