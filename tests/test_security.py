"""Security tests: hidden cards, authorization, isolation, CSRF."""

import json

from services.game_manager import GameManager
from services.serializers import (
    VIEWER_CAPTAIN,
    VIEWER_HOST,
    VIEWER_PLAYER,
    build_state,
)


def _setup(app, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    ids = {p["player"].display_name: p["player"].id for p in data["players"]}
    red = [ids["A"], ids["B"]]
    blue = [ids["C"], ids["D"]]
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    GameManager.start_round(data["session"], rnd)
    return data, rnd, ids


# ------------------------------------------------- hidden card serialization
def test_player_state_hides_unrevealed_card_types(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["D"])
    state = build_state(data["session"], VIEWER_PLAYER, player)
    for card in state["round"]["board"]:
        assert card["revealed"] is False
        assert "card_type" not in card
        assert card["revealed_type"] is None
        assert "word" in card


def test_player_state_shows_type_only_after_reveal(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    card = next(c for c in rnd.cards if c.card_type == "RED")
    GameManager.reveal_card(data["session"], rnd, card.id, None)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["D"])
    state = build_state(data["session"], VIEWER_PLAYER, player)
    revealed = next(c for c in state["round"]["board"] if c["id"] == card.id)
    assert revealed["revealed"] is True
    assert revealed["revealed_type"] == "RED"
    # Even after reveal we never leak the hidden key field.
    assert "card_type" not in revealed


def test_captain_state_includes_hidden_key(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    captain = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    state = build_state(data["session"], VIEWER_CAPTAIN, captain)
    for card in state["round"]["board"]:
        assert "card_type" in card
        assert card["card_type"] in ("RED", "BLUE", "NEUTRAL", "ASSASSIN")


def test_host_state_includes_hidden_key(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    state = build_state(data["session"], VIEWER_HOST)
    for card in state["round"]["board"]:
        assert "card_type" in card


def test_player_payload_never_contains_full_key_anywhere(app, session_factory):
    """Regression guard: the raw JSON must not contain hidden type keywords
    for unrevealed cards."""
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["D"])
    state = build_state(data["session"], VIEWER_PLAYER, player)
    blob = json.dumps(state)
    # card_type key must be entirely absent from a player payload.
    assert "card_type" not in blob


# ----------------------------------------------------- API authorization
def _create_via_client(client, host_name="Host", players=("A", "B")):
    resp = client.post("/create", data={"host_name": host_name}, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["Location"]
    code = location.rstrip("/").split("/")[-1]
    tokens = []
    for name in players:
        r = client.post(f"/join/{code}", data={"display_name": name})
        assert r.status_code == 302
    # Pull tokens from the signed session cookie by reading the Flask session.
    return code


def test_host_api_requires_token(app, client):
    # Set up through the client so we have real tokens in the session cookie.
    code = _create_via_client(client)
    with client.session_transaction() as sess:
        host_token = sess["host_tokens"][code]
    # No token header -> forbidden.
    resp = client.get(f"/api/host/{code}/state")
    assert resp.status_code == 403
    # Correct token header -> ok.
    resp = client.get(f"/api/host/{code}/state", headers={"X-Host-Token": host_token})
    assert resp.status_code == 200


def test_player_token_cannot_access_host_api(app, client):
    code = _create_via_client(client)
    with client.session_transaction() as sess:
        player_token = sess["player_tokens"][code]
    resp = client.get(f"/api/host/{code}/state", headers={"X-Host-Token": player_token})
    assert resp.status_code == 403


def test_player_cannot_create_round(app, client):
    code = _create_via_client(client)
    with client.session_transaction() as sess:
        player_token = sess["player_tokens"][code]
    resp = client.post(
        f"/api/host/{code}/rounds",
        json={"red_player_ids": [1], "blue_player_ids": [2]},
        headers={"X-Host-Token": player_token},
    )
    assert resp.status_code == 403


def test_host_api_rejects_cookie_only_request(app, client):
    """CSRF guard: a cookie without the custom header must not authorize."""
    code = _create_via_client(client)
    # The client keeps the cookie in its jar, but sends no X-Host-Token header.
    resp = client.post(
        f"/api/host/{code}/end",
        json={},
    )
    assert resp.status_code == 403


def test_wrong_host_token_for_session_rejected(app, client):
    code_a = _create_via_client(client, "HostA", ("A",))
    with client.session_transaction() as sess:
        token_a = sess["host_tokens"][code_a]
    code_b = _create_via_client(client, "HostB", ("B",))
    resp = client.get(f"/api/host/{code_b}/state", headers={"X-Host-Token": token_a})
    assert resp.status_code == 403


def test_unknown_session_api_returns_404(app, client):
    resp = client.get("/api/host/ZZZZZ/state", headers={"X-Host-Token": "x"})
    assert resp.status_code == 404


def test_player_state_api_hides_key(app, client):
    code = _create_via_client(client, "Host", ("A",))
    with client.session_transaction() as sess:
        player_token = sess["player_tokens"][code]
    resp = client.get(
        f"/api/session/{code}/state",
        headers={"X-Player-Token": player_token},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "card_type" not in body


# ------------------------------------------------------------- isolation
def test_two_sessions_have_independent_state(app, session_factory):
    a = session_factory("HostA", players=("A", "B", "C", "D"))
    b = session_factory("HostB", players=("E", "F", "G", "H"))
    ids_a = {p["player"].display_name: p["player"].id for p in a["players"]}
    ids_b = {p["player"].display_name: p["player"].id for p in b["players"]}
    ra = GameManager.create_round(
        a["session"], captain_player_id=ids_a["A"],
        red_player_ids=[ids_a["A"], ids_a["B"]],
        blue_player_ids=[ids_a["C"], ids_a["D"]], board_size=5)
    rb = GameManager.create_round(
        b["session"], captain_player_id=ids_b["E"],
        red_player_ids=[ids_b["E"], ids_b["F"]],
        blue_player_ids=[ids_b["G"], ids_b["H"]], board_size=5)
    GameManager.start_round(a["session"], ra)
    GameManager.start_round(b["session"], rb)
    words_a = {c.word for c in ra.cards}
    words_b = {c.word for c in rb.cards}
    # Boards are independent (extremely unlikely to be identical).
    assert words_a != words_b
    assert ra.id != rb.id
    # Revealing in A must not affect B.
    card_a = next(c for c in ra.cards if c.card_type == "RED")
    GameManager.reveal_card(a["session"], ra, card_a.id, None)
    assert ra.remaining("RED") == 8
    assert rb.remaining("RED") == 9


def test_player_token_isolation_between_sessions(app, session_factory):
    from services.session_manager import SessionManager

    a = session_factory("HostA", players=("A",))
    b = session_factory("HostB", players=("B",))
    token_a = a["players"][0]["player_token"]
    # Token A must not resolve to a player in session B.
    assert SessionManager.authenticate_player(b["session"], token_a) is None


def test_ended_session_join_page_shows_ended(app, client, session_factory):
    data = session_factory("Host", players=())
    from services.session_manager import SessionManager

    SessionManager.end_session(data["session"])
    resp = client.get(f"/join/{data['code']}")
    assert resp.status_code == 410
    assert "ended" in resp.get_data(as_text=True).lower()
