"""Dataset location and (optional) download helpers.

The importer needs a local file.  This module resolves a configured dataset
directory, finds a suitable local file for a source, and can stream-download a
remote dataset once.  Downloading is always an explicit administrative action -
never triggered by gameplay.
"""

from __future__ import annotations

import os
import shutil
import urllib.request

from config import basedir

# Recognised file extensions per source, in preference order.
_EXTENSIONS = {
    "kaikki": (".jsonl", ".json"),
    "wikidata": (".jsonl", ".json"),
    "frequency": (".txt", ".csv", ".tsv"),
    "custom": (".csv", ".txt"),
}

# Filename fragments that hint at the intended source.
_HINTS = {
    "kaikki": ("kaikki", "wiktionary", "wiktextract"),
    "wikidata": ("wikidata", "wikidatawiki", "latest-all"),
    "frequency": ("frequency", "freq", "count", "rank", "ngram"),
}


def dataset_dir(configured: str | None = None) -> str:
    """Resolve (and create) the dataset directory."""
    if not configured:
        configured = os.environ.get("VOCAB_DATASET_DIR") or "data/datasets"
    if not os.path.isabs(configured):
        configured = os.path.join(basedir, configured)
    os.makedirs(configured, exist_ok=True)
    return configured


def find_dataset(source: str, directory: str | None = None,
                 explicit: str | None = None) -> str | None:
    """Find a local dataset file for ``source``.

    Order of preference: an explicit path, an exact ``<source>.<ext>`` file,
    then the largest file whose name hints at the source.
    """
    if explicit:
        path = explicit if os.path.isabs(explicit) else os.path.join(
            basedir, explicit
        )
        return path if os.path.exists(path) else None

    directory = dataset_dir(directory)
    extensions = _EXTENSIONS.get(source, (".jsonl", ".json", ".csv", ".txt"))

    for ext in extensions:
        candidate = os.path.join(directory, f"{source}{ext}")
        if os.path.exists(candidate):
            return candidate

    hints = _HINTS.get(source, (source,))
    best = None
    best_size = -1
    for name in os.listdir(directory):
        lowered = name.lower()
        if not lowered.endswith(extensions):
            continue
        if not any(hint in lowered for hint in hints):
            continue
        path = os.path.join(directory, name)
        size = os.path.getsize(path)
        if size > best_size:
            best, best_size = path, size
    return best


def download_dataset(url: str, destination: str, *, progress=None,
                     should_stop=None) -> str:
    """Stream a dataset to ``destination`` without loading it into memory.

    Returns the destination path.  The caller is responsible for having the
    right to download and redistribute the dataset.
    """
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "CodenamesLive/1.0 (vocabulary import)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response, \
            open(destination, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            if should_stop is not None and should_stop():
                break
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(downloaded, total)
    return destination


def disk_free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:  # pragma: no cover
        return -1
