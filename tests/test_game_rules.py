"""Game rules tests: reveal, score, turn changes, win conditions, guesses."""

import pytest

from extensions import db as _db
from models.constants import CardType, Team
from services.game_manager import GameError, GameManager


def _setup(app, session_factory, board_size=5, mode="NORMAL"):
    """Create a session, a round, and return helpers for tests."""
    data = session_factory("Host", players=("A", "B", "C", "D"))
    ids = {p["player"].display_name: p["player"].id for p in data["players"]}
    red = [ids["A"], ids["B"]]
    blue = [ids["C"], ids["D"]]
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue,
        board_size=board_size, timer_duration=180, word_mode=mode,
    )
    GameManager.start_round(data["session"], rnd)
    return data, rnd, ids


def _card_of_type(rnd, card_type, revealed=False):
    return next(
        c for c in rnd.cards
        if c.card_type == card_type and c.is_revealed == revealed
    )


def _reveal(session, rnd, card):
    return GameManager.reveal_card(session, rnd, card.id, actor_player_id=None)


def test_reveal_red_on_red_turn_keeps_turn(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    rnd.current_team = Team.RED
    card = _card_of_type(rnd, CardType.RED)
    result = _reveal(data["session"], rnd, card)
    assert result["card_type"] == CardType.RED
    assert rnd.current_team == Team.RED
    assert rnd.remaining(CardType.RED) == 8


def test_reveal_blue_on_red_turn_switches_turn(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    rnd.current_team = Team.RED
    card = _card_of_type(rnd, CardType.BLUE)
    _reveal(data["session"], rnd, card)
    assert rnd.current_team == Team.BLUE


def test_reveal_neutral_switches_turn(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    rnd.current_team = Team.RED
    card = _card_of_type(rnd, CardType.NEUTRAL)
    _reveal(data["session"], rnd, card)
    assert rnd.current_team == Team.BLUE


def test_reveal_assassin_ends_round_and_opponent_wins(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    rnd.current_team = Team.RED
    card = _card_of_type(rnd, CardType.ASSASSIN)
    result = _reveal(data["session"], rnd, card)
    assert result["winner"] == Team.BLUE
    assert rnd.status == "ENDED"
    assert rnd.winner == Team.BLUE


def test_revealing_all_red_cards_wins(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    red_cards = [c for c in rnd.cards if c.card_type == CardType.RED]
    for card in red_cards[:-1]:
        GameManager.reveal_card(data["session"], rnd, card.id, None)
    # The last red card triggers the win.
    last = red_cards[-1]
    result = GameManager.reveal_card(data["session"], rnd, last.id, None)
    assert result["winner"] == Team.RED
    assert rnd.status == "ENDED"
    assert rnd.winner == Team.RED


def test_cannot_reveal_same_card_twice(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    card = _card_of_type(rnd, CardType.RED)
    _reveal(data["session"], rnd, card)
    with pytest.raises(GameError):
        _reveal(data["session"], rnd, card)


def test_cannot_reveal_after_round_ended(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    GameManager.end_round(data["session"], rnd, winner="RED")
    card = _card_of_type(rnd, CardType.BLUE)
    with pytest.raises(GameError):
        _reveal(data["session"], rnd, card)


def test_score_counts_only_revealed_team_cards(app, session_factory):
    data, rnd, _ = _setup(app, session_factory)
    red = _card_of_type(rnd, CardType.RED)
    blue = _card_of_type(rnd, CardType.BLUE)
    neutral = _card_of_type(rnd, CardType.NEUTRAL)
    _reveal(data["session"], rnd, red)
    _reveal(data["session"], rnd, blue)
    _reveal(data["session"], rnd, neutral)
    assert rnd.red_score == 1
    assert rnd.blue_score == 1
    assert rnd.remaining(CardType.RED) == 8
    assert rnd.remaining(CardType.BLUE) == 7


# -------------------------------------------------------------- guesses
def test_any_player_can_submit_guess(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["D"])
    card = _card_of_type(rnd, CardType.RED)
    guess = GameManager.submit_guess(data["session"], rnd, player, card.word)
    assert guess.status == "PENDING"
    assert guess.player_id == player.id


def test_duplicate_guess_by_same_player_rejected(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    card = _card_of_type(rnd, CardType.RED)
    GameManager.submit_guess(data["session"], rnd, player, card.word)
    with pytest.raises(GameError):
        GameManager.submit_guess(data["session"], rnd, player, card.word)


def test_two_players_can_guess_same_word(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    p1 = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    p2 = next(p["player"] for p in data["players"] if p["player"].id == ids["B"])
    card = _card_of_type(rnd, CardType.BLUE)
    GameManager.submit_guess(data["session"], rnd, p1, card.word)
    GameManager.submit_guess(data["session"], rnd, p2, card.word)
    pending = [g for g in rnd.guesses if g.status == "PENDING"]
    assert len(pending) == 1  # consolidated into a single pending row


def test_guess_for_word_not_on_board_rejected(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    with pytest.raises(GameError):
        GameManager.submit_guess(data["session"], rnd, player, "NOTONBOARD")


def test_host_reveal_accepts_pending_guess(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    card = _card_of_type(rnd, CardType.RED)
    GameManager.submit_guess(data["session"], rnd, player, card.word)
    result = GameManager.resolve_guess(
        data["session"], rnd, card.word.upper(), host_player_id=None, accept=True
    )
    assert result["accepted"] is True
    assert card.is_revealed is True


def test_host_reject_guess_leaves_card_hidden(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    card = _card_of_type(rnd, CardType.RED)
    GameManager.submit_guess(data["session"], rnd, player, card.word)
    result = GameManager.resolve_guess(
        data["session"], rnd, card.word.upper(), host_player_id=None, accept=False
    )
    assert result["accepted"] is False
    assert card.is_revealed is False
    assert all(g.status == "REJECTED" for g in rnd.guesses)


def test_cannot_guess_after_round_ended(app, session_factory):
    data, rnd, ids = _setup(app, session_factory)
    player = next(p["player"] for p in data["players"] if p["player"].id == ids["A"])
    card = _card_of_type(rnd, CardType.RED)
    GameManager.end_round(data["session"], rnd, winner="RED")
    with pytest.raises(GameError):
        GameManager.submit_guess(data["session"], rnd, player, card.word)
