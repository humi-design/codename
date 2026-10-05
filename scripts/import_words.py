"""Import vocabulary into the ``words`` table.

Supports:
  * Simple line lists      (.txt) - one word per line
  * Simple CSV             (.csv) - one word per line (first column)
  * Rich CSV               (.csv) - header with word,category,difficulty,
                                    part_of_speech,is_proper_noun,definition
  * Kaikki / Wiktextract   (.jsonl) - one JSON object per line

Usage:
    python scripts/import_words.py data/sample_words.csv
    python scripts/import_words.py data/sample_words.csv --mode replace
    python scripts/import_words.py kaikki.jsonl --source kaikki --limit 20000
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models.constants import WordMode  # noqa: E402
from models.word import Word  # noqa: E402

VALID_DIFFICULTIES = set(WordMode.ALL)

CATEGORIES = {
    "COMMON", "SCIENCE", "TECHNOLOGY", "HISTORY", "GEOGRAPHY", "PERSON",
    "PLACE", "ANIMAL", "OBJECT", "FOOD", "BRAND", "SPORT", "PROFESSION",
    "ORGANIZATION", "CONCEPT", "MEDICAL", "ENGINEERING", "COMPUTER",
    "BUSINESS", "RARE", "OTHER",
}

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
HTML_RE = re.compile(r"<[^>]+>")
MARKUP_RE = re.compile(r"\{\{[^}]*\}\}|\[\[[^\]]*\]\]")
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\- ]*$")
MAX_WORD_LENGTH = 24
MAX_DEFINITION_LENGTH = 400


def clean_word(raw: str) -> str | None:
    """Normalise and validate a single word. Returns ``None`` to skip."""
    if raw is None:
        return None
    value = unicodedata.normalize("NFKC", str(raw))
    value = html.unescape(value)
    value = URL_RE.sub(" ", value)
    value = HTML_RE.sub(" ", value)
    value = MARKUP_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    # Strip trailing punctuation that leaks from definitions.
    value = value.strip(" .,;:!?\"'()[]{}")
    if not value:
        return None
    # Drop sentences / metadata fragments.
    if len(value) > MAX_WORD_LENGTH or value.count(" ") > 2:
        return None
    if not WORD_RE.match(value):
        return None
    # Reject obvious metadata words.
    lowered = value.lower()
    if lowered in {"category", "plural", "alternative", "synonym", "unknown"}:
        return None
    return value


def clean_definition(raw) -> str | None:
    if not raw:
        return None
    value = html.unescape(str(raw))
    value = URL_RE.sub(" ", value)
    value = HTML_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    return value[:MAX_DEFINITION_LENGTH]


def normalize_category(value) -> str:
    if not value:
        return "OTHER"
    cat = str(value).strip().upper()
    return cat if cat in CATEGORIES else "OTHER"


def normalize_difficulty(value) -> str:
    if not value:
        return WordMode.NORMAL
    diff = str(value).strip().upper()
    return diff if diff in VALID_DIFFICULTIES else WordMode.NORMAL


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


# ------------------------------------------------------------------ readers
def read_rich_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames and "word" in [f.strip().lower() for f in reader.fieldnames]:
            for row in reader:
                row = {(k or "").strip().lower(): v for k, v in row.items()}
                yield {
                    "word": row.get("word"),
                    "category": row.get("category"),
                    "difficulty": row.get("difficulty"),
                    "part_of_speech": row.get("part_of_speech"),
                    "is_proper_noun": to_bool(row.get("is_proper_noun")),
                    "definition": row.get("definition"),
                }
        else:
            # Header-less CSV: treat first column as the word.
            fh.seek(0)
            for row in csv.reader(fh):
                if row:
                    yield {"word": row[0]}


def read_txt(path: str):
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            yield {"word": line}


def read_kaikki(path: str):
    """Read a Wiktextract/Kaikki JSONL dump."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            word = obj.get("word")
            pos = obj.get("pos")
            senses = obj.get("senses") or []
            definition = None
            if senses and isinstance(senses, list):
                glosses = senses[0].get("glosses") or []
                if glosses:
                    definition = glosses[0]
            yield {
                "word": word,
                "part_of_speech": pos,
                "definition": definition,
                "is_proper_noun": pos == "name",
            }


def choose_reader(path: str, source: str | None):
    ext = os.path.splitext(path)[1].lower()
    if source == "kaikki" or ext == ".jsonl":
        return read_kaikki
    if ext == ".txt":
        return read_txt
    return read_rich_csv


# ------------------------------------------------------------------- import
def import_words(path: str, source: str | None, mode: str, limit: int | None,
                 default_category: str, default_difficulty: str) -> dict:
    reader_fn = choose_reader(path, source)
    reader = reader_fn(path)
    seen: set[str] = set()
    stats = {"read": 0, "imported": 0, "skipped": 0, "duplicates": 0}

    if mode == "replace":
        deleted = Word.query.filter(Word.source == (source or "import")).delete()
        db.session.commit()
        stats["deleted"] = deleted

    # Preload existing normalized words to avoid duplicates.
    existing = {
        row[0] for row in db.session.query(Word.normalized_word).all()
    }

    batch = []
    for entry in reader:
        stats["read"] += 1
        if limit and stats["imported"] >= limit:
            break
        word = clean_word(entry.get("word"))
        if not word:
            stats["skipped"] += 1
            continue
        normalized = word.upper()
        if normalized in seen or normalized in existing:
            stats["duplicates"] += 1
            continue
        seen.add(normalized)

        category = normalize_category(entry.get("category") or default_category)
        difficulty = normalize_difficulty(
            entry.get("difficulty") or default_difficulty
        )
        batch.append(
            Word(
                word=word,
                normalized_word=normalized,
                part_of_speech=(entry.get("part_of_speech") or None),
                definition=clean_definition(entry.get("definition")),
                category=category,
                difficulty=difficulty,
                is_proper_noun=bool(entry.get("is_proper_noun")),
                source=source or "import",
                is_active=True,
            )
        )
        stats["imported"] += 1

        if len(batch) >= 500:
            db.session.add_all(batch)
            db.session.commit()
            batch = []

    if batch:
        db.session.add_all(batch)
        db.session.commit()

    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import words into the database.")
    parser.add_argument("path", help="Path to .csv, .txt or .jsonl file")
    parser.add_argument("--source", default=None, help="Source label, e.g. kaikki, seed")
    parser.add_argument("--mode", choices=["append", "replace"], default="append")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", default="OTHER")
    parser.add_argument("--difficulty", default="NORMAL")
    args = parser.parse_args(argv)

    if not os.path.exists(args.path):
        print(f"File not found: {args.path}")
        return 1

    app = create_app(os.environ.get("FLASK_CONFIG", "development"))
    with app.app_context():
        stats = import_words(args.path, args.source, args.mode, args.limit,
                             args.category, args.difficulty)
        total = Word.query.count()
        print("Import complete:")
        print(f"  read      : {stats['read']}")
        print(f"  imported  : {stats['imported']}")
        print(f"  duplicates: {stats['duplicates']}")
        print(f"  skipped   : {stats['skipped']}")
        if "deleted" in stats:
            print(f"  deleted   : {stats['deleted']}")
        print(f"  total now : {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
