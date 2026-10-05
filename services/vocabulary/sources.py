"""Known vocabulary sources and their license / attribution metadata.

The Super Admin vocabulary page shows this information so the operator can see
where data came from and what its redistribution terms are.  Nothing here
downloads or scrapes anything; sources are official downloadable datasets or
operator-provided files.
"""

from __future__ import annotations

from extensions import db
from models.vocabulary_source import VocabularySource
from services.vocabulary.base_provider import SourceInfo
from services.vocabulary.custom_file_provider import CustomFileProvider
from services.vocabulary.frequency_provider import FrequencyProvider
from services.vocabulary.kaikki_provider import KaikkiProvider
from services.vocabulary.wikidata_provider import WikidataProvider

# name -> SourceInfo.  ``seed`` is the bundled sample list.
KNOWN_SOURCES: dict[str, SourceInfo] = {
    "seed": SourceInfo(
        name="seed",
        kind="file",
        description="Bundled sample vocabulary shipped with the application.",
        license_name="Project sample data",
        attribution="Codenames Live sample list (development / first run).",
    ),
    KaikkiProvider.source.name: KaikkiProvider.source,
    WikidataProvider.source.name: WikidataProvider.source,
    FrequencyProvider.source.name: FrequencyProvider.source,
    CustomFileProvider.source.name: CustomFileProvider.source,
}


def source_info(name: str) -> SourceInfo:
    return KNOWN_SOURCES.get(name, SourceInfo(name=name))


def ensure_source_rows() -> None:
    """Create/refresh the ``vocabulary_sources`` registry rows."""
    for name, info in KNOWN_SOURCES.items():
        row = VocabularySource.query.filter_by(name=name).first()
        if row is None:
            row = VocabularySource(name=name)
            db.session.add(row)
        row.kind = info.kind
        row.description = info.description
        row.license_name = info.license_name
        row.license_url = info.license_url
        row.homepage_url = info.homepage_url
        row.dataset_url = info.dataset_url
        row.attribution = info.attribution
    db.session.commit()


def update_source_stats(name: str, word_count: int) -> None:
    from models.constants import utcnow

    row = VocabularySource.query.filter_by(name=name).first()
    if row is None:
        row = VocabularySource(name=name)
        db.session.add(row)
    row.word_count = int(word_count)
    row.last_imported_at = utcnow()
    db.session.commit()
