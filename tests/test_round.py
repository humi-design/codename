"""Round and board generation tests."""

import pytest

from models.constants import CardType
from services.board_generator import BoardConfigError, BoardGenerator
from services.game_manager import GameError, GameManager


def _ids(data, names):
    by_name = {p["player"].display_name: p["player"].id for p in data["players"]}
    return [by_name[n] for n in names]


def test_create_round_with_teams(db, session_factory):
    data = session_factory("Host", players=("Somil", "Priya", "Rahul", "Aman", "Neha"))
    red = _ids(data, ["Somil", "Priya"])
    blue = _ids(data, ["Rahul", "Aman", "Neha"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue,
        board_size=5, timer_duration=180, word_mode="NORMAL",
    )
    assert rnd.round_number == 1
    assert rnd.status == "SETUP"
    assert len(rnd.players_for("RED")) == 2
    assert len(rnd.players_for("BLUE")) == 3
    assert rnd.captain_player_id == red[0]


def test_board_generated_correct_distribution(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    counts = {t: 0 for t in CardType.ALL}
    for card in rnd.cards:
        counts[card.card_type] += 1
    assert counts[CardType.RED] == 9
    assert counts[CardType.BLUE] == 8
    assert counts[CardType.NEUTRAL] == 7
    assert counts[CardType.ASSASSIN] == 1
    assert len(rnd.cards) == 25


def test_board_words_are_unique(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=6,
    )
    words = [c.word for c in rnd.cards]
    assert len(words) == len(set(words)) == 36


def test_board_6x6_distribution(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=6,
    )
    counts = {t: 0 for t in CardType.ALL}
    for card in rnd.cards:
        counts[card.card_type] += 1
    assert counts[CardType.RED] == 11
    assert counts[CardType.BLUE] == 10
    assert counts[CardType.NEUTRAL] == 13
    assert counts[CardType.ASSASSIN] == 2


def test_board_not_regenerated_on_second_call(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    first_words = [c.word for c in rnd.cards]
    again = BoardGenerator.generate_board(rnd.id, board_size=5)
    assert [c.word for c in again] == first_words


def test_invalid_distribution_rejected(db):
    with pytest.raises(BoardConfigError):
        BoardGenerator.validate_distribution(
            5, {"RED": 9, "BLUE": 8, "NEUTRAL": 7, "ASSASSIN": 2}
        )


def test_unsupported_board_size_rejected(db):
    with pytest.raises(BoardConfigError):
        BoardGenerator.distribution_for(7)


def test_create_round_requires_both_teams(db, session_factory):
    data = session_factory("Host", players=("A", "B"))
    red = _ids(data, ["A", "B"])
    with pytest.raises(GameError):
        GameManager.create_round(
            data["session"], captain_player_id=red[0],
            red_player_ids=red, blue_player_ids=[],
        )


def test_create_round_rejects_player_on_both_teams(db, session_factory):
    data = session_factory("Host", players=("A", "B"))
    ids = _ids(data, ["A", "B"])
    with pytest.raises(GameError):
        GameManager.create_round(
            data["session"], captain_player_id=ids[0],
            red_player_ids=ids, blue_player_ids=ids,
        )


def test_start_round_activates_and_starts_timer(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    GameManager.start_round(data["session"], rnd)
    assert rnd.status == "ACTIVE"
    assert rnd.timer_started_at is not None


def test_end_round_records_winner(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    GameManager.start_round(data["session"], rnd)
    GameManager.end_round(data["session"], rnd, winner="RED", reason="MANUAL")
    assert rnd.status == "ENDED"
    assert rnd.winner == "RED"


def test_next_round_number_increments(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    r1 = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    GameManager.start_round(data["session"], r1)
    GameManager.end_round(data["session"], r1, winner="RED")
    r2 = GameManager.create_round(
        data["session"], captain_player_id=blue[0],
        red_player_ids=blue, blue_player_ids=red, board_size=5,
    )
    assert r2.round_number == 2
    assert r2.captain_player_id == blue[0]


def test_update_round_config_changes_captain_and_teams(db, session_factory):
    data = session_factory("Host", players=("A", "B", "C", "D"))
    red = _ids(data, ["A", "B"])
    blue = _ids(data, ["C", "D"])
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue, board_size=5,
    )
    # Swap teams and make C the captain.
    GameManager.update_round_config(
        data["session"], rnd,
        captain_player_id=blue[0],
        red_player_ids=blue, blue_player_ids=red,
    )
    assert rnd.captain_player_id == blue[0]
    assert [rp.player_id for rp in rnd.players_for("RED")] == blue
