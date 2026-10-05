"""Session lifecycle tests: create, join, invalid code, end, isolation."""

import pytest

from services.session_manager import SessionError, SessionManager


def test_create_session_generates_code_and_tokens(db):
    result = SessionManager.create_session("Somil")
    session = result["session"]
    assert session.session_code
    assert len(session.session_code) == 5
    assert session.status == "ACTIVE"
    assert result["host_token"]
    # Ambiguous characters are excluded.
    for ch in session.session_code:
        assert ch not in "0O1I"


def test_session_code_is_unique(db, session_factory):
    a = session_factory("Host A", players=())
    b = session_factory("Host B", players=())
    assert a["code"] != b["code"]


def test_join_session_success(db, session_factory):
    data = session_factory("Host", players=())
    joined = SessionManager.join_session(data["code"], "Rahul")
    assert joined["player"].display_name == "Rahul"
    assert joined["player_token"]


def test_join_invalid_code(db):
    with pytest.raises(SessionError):
        SessionManager.join_session("ZZZZZ", "Rahul")


def test_join_duplicate_name_rejected(db, session_factory):
    data = session_factory("Host", players=())
    SessionManager.join_session(data["code"], "Rahul")
    with pytest.raises(SessionError):
        SessionManager.join_session(data["code"], "Rahul")


def test_join_invalid_name_rejected(db, session_factory):
    data = session_factory("Host", players=())
    with pytest.raises(SessionError):
        SessionManager.join_session(data["code"], "   ")


def test_end_session_disables_invite(db, session_factory):
    data = session_factory("Host", players=("Rahul",))
    SessionManager.end_session(data["session"])
    assert data["session"].status == "ENDED"
    with pytest.raises(SessionError):
        SessionManager.join_session(data["code"], "NewPlayer")


def test_cannot_join_ended_session_via_service(db, session_factory):
    data = session_factory("Host", players=())
    SessionManager.end_session(data["session"])
    with pytest.raises(SessionError, match="ended"):
        SessionManager.get_active_by_code(data["code"])


def test_host_token_validation(db, session_factory):
    data = session_factory("Host", players=())
    assert SessionManager.is_host(data["session"], data["host_token"]) is True
    assert SessionManager.is_host(data["session"], "not-a-token") is False


def test_player_token_validation(db, session_factory):
    data = session_factory("Host", players=("Rahul",))
    token = data["players"][0]["player_token"]
    player = SessionManager.authenticate_player(data["session"], token)
    assert player is not None
    assert player.display_name == "Rahul"
    assert SessionManager.authenticate_player(data["session"], "bad") is None


def test_player_token_not_valid_in_other_session(db, session_factory):
    """A player token from session A must not authenticate in session B."""
    a = session_factory("Host A", players=("Rahul",))
    b = session_factory("Host B", players=())
    token = a["players"][0]["player_token"]
    assert SessionManager.authenticate_player(b["session"], token) is None


def test_session_summary_counts(db, session_factory):
    data = session_factory("Host", players=("Rahul", "Priya"))
    summary = SessionManager.session_summary(data["session"])
    assert summary["code"] == data["code"]
    assert summary["players"] == 3  # host + 2 players
    assert summary["rounds_played"] == 0
