# Large-scale vocabulary datasets

Place downloadable dataset files here, then import them from the Super Admin
**Vocabulary** page or with `scripts/import_words.py`. The game only ever reads
the MySQL `words` table; this directory is the staging area for the one-time
(and periodic) ingestion step.

Files are auto-detected by name:

| Source      | Preferred file names                                  | Format |
|-------------|-------------------------------------------------------|--------|
| `kaikki`    | `kaikki*.jsonl`, `wiktionary*.jsonl`, `wiktextract*`  | JSONL (one JSON object per line) |
| `wikidata`  | `wikidata*.jsonl` / `wikidata*.json`                  | JSONL or a JSON array |
| `frequency` | `*frequency*`, `*freq*`, `*count*`, `*rank*`          | `word<TAB>count` or `word<TAB>rank` |
| `custom`    | `custom*.csv`, `custom*.txt`                          | one word per line, or CSV |

`<source>.jsonl` (for example `kaikki.jsonl`) is always preferred when present.

## Where to get datasets

Only official, downloadable datasets are supported. This project never scrapes
a service and never calls an external API during gameplay.

- **Wiktionary / Wiktextract (Kaikki)** — machine-readable dictionary dumps.
  License: CC BY-SA 4.0. <https://kaikki.org/dictionary/English/>
- **Wikidata** — entity dumps. License: CC0 1.0.
  <https://dumps.wikimedia.org/wikidatawiki/entities/>
- **Frequency lists** — e.g. Google Books Ngram derived lists, SUBTLEX,
  `wordfreq` exports. Check each dataset's license before redistributing.

## Import commands

```bash
# Wiktionary / Kaikki (large; the primary vocabulary source)
python scripts/import_words.py --source kaikki

# Wikidata entities
python scripts/import_words.py --source wikidata

# A frequency list (adds a real frequency_score used for difficulty buckets)
python scripts/import_words.py --source frequency

# Your own list
python scripts/import_words.py data/sample_words.csv --source custom

# Rebuild one source from scratch
python scripts/import_words.py --source custom --file words.csv --mode replace
```

Imports are resumable. If a large import is interrupted, resume it from the
recorded offset:

```bash
python scripts/import_words.py --source kaikki --resume-offset 12345678
```

Large files are processed one line at a time, so memory use stays flat no
matter how big the dataset is. Nothing is loaded into the browser and gameplay
never touches these files.
