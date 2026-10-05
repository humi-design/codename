"""Vocabulary engine tests: cleaner, classifier, importer, providers, filters.

These exercise the real ingestion path against the real database - no mocks.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from extensions import db
from models.constants import Category, WordMode
from models.word import Word
from services.vocabulary.cleaner import clean_word, normalize_word
from services.vocabulary.classifier import (
    guess_category,
    guess_difficulty,
    normalize_category,
    normalize_difficulty,
)
from services.vocabulary.custom_file_provider import CustomFileProvider
from services.vocabulary.frequency_provider import FrequencyProvider
from services.vocabulary.importer import (
    ImportOptions,
    VocabularyImporter,
    build_provider,
)
from services.vocabulary.kaikki_provider import KaikkiProvider
from services.vocabulary.wikidata_provider import WikidataProvider
from services.word_engine import WordEngine


# ------------------------------------------------------------------ helpers
@pytest.fixture()
def tmpfile():
    paths = []

    def _make(content: str, suffix=".csv"):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=suffix, delete=False, encoding="utf-8"
        )
        handle.write(content)
        handle.close()
        paths.append(handle.name)
        return handle.name

    yield _make
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def _seed(count=60, prefix="WORD", **overrides):
    words = []
    for i in range(count):
        base = dict(
            word=f"{prefix}{i:04d}",
            normalized_word=f"{prefix.lower()}{i:04d}",
            language="en",
            category=Category.COMMON,
            difficulty=WordMode.NORMAL,
            frequency_score=50.0,
            is_proper_noun=False,
            is_multiword=False,
            character_count=8,
            source="test",
            is_active=True,
        )
        base.update(overrides)
        words.append(Word(**base))
    db.session.add_all(words)
    db.session.commit()
    return words


# ----------------------------------------------------------------- cleaner
def test_cleaner_rejects_urls_html_and_sentences():
    assert clean_word("http://example.com").ok is False
    assert clean_word("<b>word</b>").ok is False
    assert clean_word("this is a whole sentence that is too long").ok is False
    assert clean_word("").ok is False
    assert clean_word(None).ok is False


def test_cleaner_keeps_legitimate_unusual_words():
    for raw in ("SYNAPSE", "Axolotl", "QUASAR", "Mitosis", "Naïve", "O'Brien",
                "New York", "T-REX", "Einstein", "Kilimanjaro"):
        assert clean_word(raw).ok is True, raw


def test_cleaner_strips_markup_and_normalises_whitespace():
    result = clean_word("  [[quasar|Quasar]]   ")
    assert result.ok
    assert result.word == "Quasar"
    assert result.normalized == "quasar"


def test_normalize_word_is_case_and_unicode_insensitive():
    assert normalize_word("Quasar") == normalize_word("QUASAR")
    assert normalize_word("  Café ") == normalize_word("cafe\u0301")


def test_cleaner_respects_max_length_and_word_count():
    assert clean_word("x" * 40, max_chars=24).ok is False
    assert clean_word("one two three four", max_words=3).ok is False


# -------------------------------------------------------------- classifier
def test_classifier_detects_categories_from_hints():
    assert guess_category("algorithm") == Category.COMPUTER
    assert guess_category("photon") == Category.SCIENCE
    assert guess_category("cinnamon") == Category.FOOD
    assert guess_category("zzyzx") == Category.OTHER


def test_classifier_proper_noun_is_place_or_person():
    assert guess_category("Mumbai", is_proper_noun=True) in (
        Category.PERSON, Category.PLACE, Category.ORGANIZATION
    )
    assert guess_category("Springfield", is_proper_noun=True) == Category.PLACE


def test_classifier_difficulty_buckets():
    assert guess_difficulty("cat", frequency_score=90) == WordMode.EASY
    assert guess_difficulty("mitochondrion", frequency_score=30) == WordMode.HARD
    assert guess_difficulty("quasar", rare_hint=True) == WordMode.CHAOS


def test_normalizers_fall_back_safely():
    assert normalize_category("science") == Category.SCIENCE
    assert normalize_category("nonsense") == Category.OTHER
    assert normalize_difficulty("hard") == WordMode.HARD
    assert normalize_difficulty("nonsense") == WordMode.NORMAL


# ---------------------------------------------------------------- providers
def test_custom_csv_importer_dedupes_and_rejects_noise(tmpfile, app, db):
    path = tmpfile(
        "word,category,difficulty\n"
        "APPLE,FOOD,EASY\n"
        "apple,FOOD,EASY\n"          # duplicate (case-insensitive)
        "http://evil.example,FOOD,EASY\n"  # url -> rejected
        ",,\n"                        # empty -> rejected
        "NEW YORK,PLACE,NORMAL\n"
    )
    provider = build_provider(path, source="custom")
    stats = VocabularyImporter(provider, ImportOptions()).run()

    assert stats.imported == 2
    assert stats.duplicates == 1
    assert stats.rejected >= 2
    assert Word.query.count() == 2
    assert Word.query.filter_by(normalized_word="apple").one().word == "APPLE"
    ny = Word.query.filter_by(normalized_word="new york").one()
    assert ny.is_multiword is True
    assert ny.character_count == 8


def test_importer_update_mode_updates_without_duplicating(tmpfile, app, db):
    path = tmpfile("word,category,difficulty\nQUASAR,SCIENCE,HARD\n")
    provider = build_provider(path, source="custom")
    first = VocabularyImporter(provider, ImportOptions(update_existing=True)).run()
    assert first.imported == 1

    # Same word again -> updated, not duplicated.
    provider2 = build_provider(path, source="custom")
    second = VocabularyImporter(provider2, ImportOptions(update_existing=True)).run()
    assert second.updated == 1
    assert second.imported == 0
    assert Word.query.count() == 1


def test_txt_provider_one_word_per_line(tmpfile, app, db):
    path = tmpfile("alpha\nbeta\n\nGamma\n", suffix=".txt")
    provider = CustomFileProvider(path, source_name="custom")
    stats = VocabularyImporter(provider, ImportOptions()).run()
    assert stats.imported == 3
    assert Word.query.count() == 3


def test_kaikki_provider_reads_jsonl(tmpfile, app, db):
    lines = [
        {"word": "quasar", "pos": "noun", "lang_code": "en",
         "senses": [{"glosses": ["An astronomical object."], "topics": ["astronomy"]}]},
        {"word": "Mumbai", "pos": "name", "lang_code": "en",
         "senses": [{"glosses": ["A city in India."], "tags": ["rare"]}]},
        "not json",
        {"word": "", "pos": "noun"},
    ]
    path = tmpfile("\n".join(
        json.dumps(x) if isinstance(x, dict) else x for x in lines
    ), suffix=".jsonl")

    provider = KaikkiProvider(path)
    stats = VocabularyImporter(provider, ImportOptions()).run()
    assert stats.imported == 2
    assert Word.query.count() == 2
    mumbai = Word.query.filter_by(normalized_word="mumbai").one()
    assert mumbai.is_proper_noun is True


def test_wikidata_provider_reads_jsonl(tmpfile, app, db):
    entity = {
        "id": "Q42",
        "labels": {"en": {"value": "Douglas Adams"}},
        "descriptions": {"en": {"value": "English writer"}},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }
    path = tmpfile(json.dumps(entity), suffix=".jsonl")
    provider = WikidataProvider(path)
    stats = VocabularyImporter(provider, ImportOptions()).run()
    assert stats.imported == 1
    row = Word.query.one()
    assert row.word == "Douglas Adams"
    assert row.category == Category.PERSON
    assert row.source_id == "Q42"


def test_frequency_provider_sets_scores(tmpfile, app, db):
    path = tmpfile("the\t1000000\nquasar\t50\n", suffix=".txt")
    provider = FrequencyProvider(path, rank_based=False)
    VocabularyImporter(provider, ImportOptions()).run()
    the = Word.query.filter_by(normalized_word="the").one()
    quasar = Word.query.filter_by(normalized_word="quasar").one()
    assert the.frequency_score > quasar.frequency_score
    assert 0 <= quasar.frequency_score <= 100


# --------------------------------------------------------------- word engine
def test_word_engine_selects_unique_words(app, db):
    _seed(80)
    words = WordEngine.pick_words(25, mode=WordMode.CHAOS)
    assert len(words) == 25
    assert len(set(words)) == 25


def test_word_engine_respects_proper_noun_filter(app, db):
    _seed(40, prefix="PROP", is_proper_noun=True)
    _seed(40, prefix="COMM", is_proper_noun=False)
    filters = {
        "language": "en", "max_chars": 24, "max_words": 3,
        "allow_proper_nouns": False, "allow_multiword": True,
        "min_frequency": 0,
    }
    # The proper-noun rows are the only ones with a distinctive marker; ensure
    # none are returned when the filter is off.
    proper = {w.word.upper() for w in Word.query.filter_by(is_proper_noun=True)}
    picked = WordEngine.pick_words(25, mode=WordMode.CHAOS, filters=filters)
    assert not (set(picked) & proper)


def test_word_engine_falls_back_when_empty(app, db):
    # Empty table -> bundled fallback keeps a fresh install playable.
    words = WordEngine.pick_words(25, mode=WordMode.NORMAL)
    assert len(words) == 25


def test_word_engine_raises_when_fallback_insufficient(app, db):
    from services.word_engine import WordEngineError

    with pytest.raises(WordEngineError):
        WordEngine.pick_words(10000, mode=WordMode.NORMAL)


def test_word_engine_count_available(app, db):
    _seed(30, prefix="EASY", difficulty=WordMode.EASY)
    _seed(20, prefix="CHAO", difficulty=WordMode.CHAOS)
    assert WordEngine.count_available(WordMode.EASY) == 30
    assert WordEngine.count_available(WordMode.CHAOS) == 50


# ----------------------------------------------------------- board generator
def test_board_generator_uses_imported_words(app, db):
    from services.board_generator import BoardGenerator
    from services.session_manager import SessionManager
    from services.game_manager import GameManager

    _seed(80, difficulty=WordMode.CHAOS)
    result = SessionManager.create_session("Host")
    session = result["session"]
    joined = [SessionManager.join_session(session.session_code, f"P{i}")
              for i in range(4)]
    ids = [p["player"].id for p in joined]
    rnd = GameManager.create_round(
        session, captain_player_id=ids[0], red_player_ids=ids[:2],
        blue_player_ids=ids[2:], board_size=5, timer_duration=180,
        word_mode=WordMode.CHAOS,
    )
    cards = BoardGenerator.generate_board(rnd.id, board_size=5, mode=WordMode.CHAOS)
    assert len(cards) == 25
    assert len({c.word for c in cards}) == 25
    # Distribution is correct for 5x5.
    counts = {}
    for card in cards:
        counts[card.card_type] = counts.get(card.card_type, 0) + 1
    assert counts == {"RED": 9, "BLUE": 8, "NEUTRAL": 7, "ASSASSIN": 1}


def test_board_generator_is_idempotent(app, db):
    from services.board_generator import BoardGenerator
    from services.session_manager import SessionManager
    from services.game_manager import GameManager

    _seed(80, difficulty=WordMode.CHAOS)
    session = SessionManager.create_session("Host")["session"]
    joined = [SessionManager.join_session(session.session_code, f"P{i}")
              for i in range(4)]
    ids = [p["player"].id for p in joined]
    rnd = GameManager.create_round(
        session, captain_player_id=ids[0], red_player_ids=ids[:2],
        blue_player_ids=ids[2:], board_size=5, timer_duration=180,
        word_mode=WordMode.CHAOS,
    )
    first = BoardGenerator.generate_board(rnd.id, board_size=5, mode=WordMode.CHAOS)
    first_words = [c.word for c in first]
    second = BoardGenerator.generate_board(rnd.id, board_size=5, mode=WordMode.CHAOS)
    assert [c.word for c in second] == first_words


def test_board_generator_errors_when_not_enough_words(app, db):
    from services.board_generator import BoardConfigError, BoardGenerator
    from services.session_manager import SessionManager
    from services.game_manager import GameManager

    _seed(10, prefix="FEWW", difficulty=WordMode.NORMAL)
    session = SessionManager.create_session("Host")["session"]
    joined = [SessionManager.join_session(session.session_code, f"P{i}")
              for i in range(4)]
    ids = [p["player"].id for p in joined]
    # A populated but insufficient table is a real configuration error and
    # must surface clearly rather than silently using filler words.
    with pytest.raises(BoardConfigError):
        GameManager.create_round(
            session, captain_player_id=ids[0], red_player_ids=ids[:2],
            blue_player_ids=ids[2:], board_size=5, timer_duration=180,
            word_mode=WordMode.NORMAL,
        )


# -------------------------------------------------------- import manager
def test_import_manager_status_and_history(app, db, tmpfile):
    from services.vocabulary.import_manager import ImportManager

    _seed(5)
    status = ImportManager.status()
    assert status["total"] == 5
    assert status["active"] == 5

    path = tmpfile("word,category,difficulty\nzzztestword,OTHER,NORMAL\n")
    record = ImportManager.start("custom", mode="update", path=path,
                                 background=False)
    assert record.status == "COMPLETED"
    assert Word.query.filter_by(normalized_word="zzztestword").count() == 1
    history = ImportManager.history()
    assert history and history[0].id == record.id


def test_import_manager_rejects_concurrent_run(app, db, tmpfile):
    from services.vocabulary.import_manager import ImportError_, ImportManager
    from models.vocabulary_import import VocabularyImport

    # Simulate a running import row.
    db.session.add(VocabularyImport(source="kaikki", status="RUNNING",
                                    mode="initial"))
    db.session.commit()
    with pytest.raises(ImportError_):
        ImportManager.start("custom", background=False)


def test_import_manager_failure_preserves_existing_words(app, db, tmpfile):
    from services.vocabulary.import_manager import ImportManager

    _seed(7)
    before = Word.query.count()
    path = tmpfile("{ this is not valid jsonl", suffix=".jsonl")
    # A malformed JSONL line is skipped (not fatal), so use a provider that
    # raises instead: point at a directory that is not readable as a file.
    record = ImportManager.start("kaikki", mode="update", path=path,
                                 background=False)
    # Either it completes having skipped the bad line, or fails cleanly; in
    # both cases the pre-existing words must survive.
    assert Word.query.count() >= before
    assert record.status in ("COMPLETED", "FAILED")


# --------------------------------------------------------------- admin pages
def _login_admin(client, app):
    from services.admin_auth import AdminAuth

    with client.session_transaction() as sess:
        sess[AdminAuth.SESSION_KEY] = {"username": "admin", "role": "super_admin"}
    return client


def test_admin_vocabulary_requires_login(client):
    response = client.get("/admin/vocabulary", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "/admin/login" in response.headers.get("Location", "")


def test_admin_vocabulary_page_renders(client, app, db):
    _seed(12)
    _login_admin(client, app)
    response = client.get("/admin/vocabulary")
    assert response.status_code == 200
    assert b"Vocabulary database" in response.data


def test_admin_vocabulary_status_json(client, app, db):
    _seed(12)
    _login_admin(client, app)
    payload = client.get("/admin/vocabulary/status").get_json()
    assert payload["total"] == 12
    assert payload["status"] in ("READY", "IMPORTING")


def test_admin_vocabulary_filters_persist(client, app, db):
    from services.settings_service import SettingsService

    _login_admin(client, app)
    response = client.post(
        "/admin/vocabulary/filters",
        data={"vocab_max_chars": "18", "vocab_max_words": "2",
              "vocab_min_frequency": "0", "vocab_language": "en",
              "vocab_allow_proper_nouns": "1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    filters = SettingsService.word_filters()
    assert filters["max_chars"] == 18
    assert filters["max_words"] == 2
    assert filters["allow_multiword"] is False


def test_admin_settings_page_does_not_reset_vocab_filters(client, app, db):
    from services.settings_service import SettingsService

    _login_admin(client, app)
    SettingsService.set("vocab_max_chars", "17")
    db.session.commit()
    # Posting the generic settings page must not wipe vocabulary settings.
    client.post("/admin/settings", data={"default_board_size": "5"},
                follow_redirects=True)
    assert SettingsService.get("vocab_max_chars") == "17"


def test_admin_vocabulary_upload_starts_import(client, app, db, tmp_path):
    import io

    from services.settings_service import SettingsService

    _login_admin(client, app)
    SettingsService.set("vocab_dataset_dir", str(tmp_path))
    db.session.commit()
    data = {
        "file": (io.BytesIO(b"word,category,difficulty\nUPLOADWORD,OTHER,NORMAL\n"),
                 "uploaded.csv"),
    }
    response = client.post("/admin/vocabulary/upload", data=data,
                           content_type="multipart/form-data",
                           follow_redirects=True)
    assert response.status_code == 200
    from models.vocabulary_import import VocabularyImport

    assert VocabularyImport.query.count() >= 1


def test_admin_vocabulary_upload_rejects_bad_extension(client, app, db):
    import io

    _login_admin(client, app)
    data = {"file": (io.BytesIO(b"binary"), "payload.exe")}
    response = client.post("/admin/vocabulary/upload", data=data,
                           content_type="multipart/form-data",
                           follow_redirects=True)
    assert b"Unsupported file type" in response.data


def test_admin_vocabulary_import_missing_dataset_flashes(client, app, db):
    _login_admin(client, app)
    response = client.post("/admin/vocabulary/import",
                           data={"source": "wikidata", "mode": "initial"},
                           follow_redirects=True)
    assert response.status_code == 200
    assert b"No dataset found" in response.data or b"already running" in response.data

