"""Wikidata provider.

Reads a Wikidata entity dump (JSON array or newline-delimited JSON) and
extracts the English label of each item, its description as a gloss, and the
``instance of`` (P31) value to infer a coarse category.

Data license: Wikidata is released under CC0 1.0 (public domain dedication).
See ``services/vocabulary/sources.py``.  The operator downloads the dump; this
provider never queries a live API during gameplay.
"""

from __future__ import annotations

import json
from typing import Iterator

from services.vocabulary.base_provider import (
    BaseProvider,
    RawEntry,
    SourceInfo,
)

# A few common "instance of" (P31) QIDs mapped to game categories.
_P31_CATEGORY = {
    "Q5": "PERSON",            # human
    "Q6256": "PLACE",          # country
    "Q515": "PLACE",           # city
    "Q486972": "PLACE",        # human settlement
    "Q43229": "ORGANIZATION",  # organization
    "Q4830453": "BUSINESS",    # business
    "Q431289": "BRAND",        # brand
    "Q1656682": "HISTORY",     # event
    "Q11424": "CONCEPT",       # film
    "Q571": "CONCEPT",         # book
    "Q729": "ANIMAL",          # animal
    "Q756": "ANIMAL",          # plant
    "Q11173": "SCIENCE",       # chemical compound
    "Q8054": "SCIENCE",        # protein
    "Q523": "SCIENCE",         # star
    "Q634": "SCIENCE",         # planet
    "Q11563": "SPORT",         # number? keep as sport-ish fallback below
}

# P31 values that clearly indicate a proper noun / named entity.
_NAMED_ENTITY_P31 = {
    "Q5", "Q6256", "Q515", "Q486972", "Q43229", "Q4830453", "Q431289",
    "Q11424", "Q571", "Q523", "Q634",
}


class WikidataProvider(BaseProvider):
    source = SourceInfo(
        name="wikidata",
        kind="json",
        description="Wikidata entity dump (JSON array or JSONL).",
        license_name="CC0 1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        homepage_url="https://www.wikidata.org/",
        dataset_url="https://dumps.wikimedia.org/wikidatawiki/entities/",
        attribution="Data from Wikidata (CC0 1.0).",
    )

    def stream(self, start_offset: int = 0) -> Iterator[tuple[RawEntry, int]]:
        if (self.path or "").lower().endswith(".jsonl"):
            yield from self._stream_jsonl(start_offset)
        else:
            yield from self._stream_json_array(start_offset)

    # ---------------------------------------------------------------- jsonl
    def _stream_jsonl(self, start_offset: int) -> Iterator[tuple[RawEntry, int]]:
        for line, offset in self._line_stream(start_offset):
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                yield None, offset
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                yield None, offset
                continue
            entry = self._entry_from_entity(obj)
            yield entry, offset

    # ------------------------------------------------------------- array
    def _stream_json_array(self, start_offset: int) -> Iterator[tuple[RawEntry, int]]:
        """Stream a JSON array without loading the whole file into memory.

        Uses the incremental JSON decoder so multi-gigabyte dumps are handled
        one entity at a time.
        """
        decoder = json.JSONDecoder()
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            if start_offset:
                fh.seek(start_offset)
            buffer = ""
            offset = start_offset
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                buffer += chunk
                offset += len(chunk.encode("utf-8"))
                while True:
                    stripped = buffer.lstrip(" \t\r\n,")
                    if not stripped:
                        buffer = ""
                        break
                    if stripped[0] == "]":
                        buffer = ""
                        break
                    if stripped[0] == "[":
                        buffer = stripped[1:]
                        continue
                    try:
                        obj, end = decoder.raw_decode(stripped)
                    except ValueError:
                        break  # need more data
                    consumed = len(stripped) - len(buffer) + end
                    buffer = stripped[end:]
                    entry = self._entry_from_entity(obj)
                    yield entry, offset
            return

    # ------------------------------------------------------------ mapping
    def _entry_from_entity(self, obj) -> RawEntry | None:
        if not isinstance(obj, dict):
            return None
        qid = obj.get("id")
        labels = obj.get("labels") or {}
        label = None
        if isinstance(labels, dict):
            en = labels.get("en") or {}
            if isinstance(en, dict):
                label = en.get("value")
        if not label:
            return None

        descriptions = obj.get("descriptions") or {}
        definition = None
        if isinstance(descriptions, dict):
            en = descriptions.get("en") or {}
            if isinstance(en, dict):
                definition = en.get("value")

        p31 = self._claim_values(obj, "P31")
        category = None
        for value in p31:
            mapped = _P31_CATEGORY.get(value)
            if mapped:
                category = mapped
                break
        proper = bool(set(p31) & _NAMED_ENTITY_P31)

        return RawEntry(
            word=label,
            source_id=qid,
            language="en",
            definition=definition,
            category=category,
            is_proper_noun=proper,
            rare=False,
        )

    @staticmethod
    def _claim_values(obj: dict, prop: str) -> list[str]:
        claims = obj.get("claims") or {}
        values: list[str] = []
        for claim in claims.get(prop) or []:
            try:
                mainsnak = claim.get("mainsnak") or {}
                datavalue = mainsnak.get("datavalue") or {}
                value = datavalue.get("value")
                if isinstance(value, dict) and "id" in value:
                    values.append(value["id"])
                elif isinstance(value, str):
                    values.append(value)
            except AttributeError:
                continue
        return values
