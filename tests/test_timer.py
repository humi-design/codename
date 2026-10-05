"""Timer tests: start, pause, resume, reset, expiry."""

from datetime import timedelta

from models.constants import Team, utcnow
from services.timer import TimerService


def _make_round(db, session_factory):
    from services.game_manager import GameManager

    data = session_factory("Host", players=("A", "B", "C", "D"))
    ids = {p["player"].display_name: p["player"].id for p in data["players"]}
    red = [ids["A"], ids["B"]]
    blue = [ids["C"], ids["D"]]
    rnd = GameManager.create_round(
        data["session"], captain_player_id=red[0],
        red_player_ids=red, blue_player_ids=blue,
        board_size=5, timer_duration=180,
    )
    GameManager.start_round(data["session"], rnd)
    return data, rnd


def test_timer_starts_running(db, session_factory):
    _, rnd = _make_round(db, session_factory)
    assert TimerService.is_running(rnd) is True
    remaining = TimerService.seconds_remaining(rnd)
    assert remaining is not None and remaining <= 180


def test_timer_pause_freezes_remaining(db, session_factory, monkeypatch):
    _, rnd = _make_round(db, session_factory)
    base = utcnow()
    rnd.timer_started_at = base - timedelta(seconds=60)
    rnd.timer_paused_at = base
    frozen = TimerService.seconds_remaining(rnd)
    assert TimerService.is_running(rnd) is False
    assert frozen == 120
    # Advancing the wall clock must not change the remaining time while paused.
    monkeypatch.setattr("services.timer.utcnow",
                        lambda: base + timedelta(seconds=45))
    assert TimerService.seconds_remaining(rnd) == frozen


def test_timer_resume_shifts_start(db, session_factory):
    _, rnd = _make_round(db, session_factory)
    TimerService.pause(rnd)
    rnd.timer_paused_at = utcnow() - timedelta(seconds=20)
    TimerService.resume(rnd)
    assert rnd.timer_paused_at is None
    assert TimerService.is_running(rnd) is True


def test_timer_reset_clears_state(db, session_factory):
    _, rnd = _make_round(db, session_factory)
    TimerService.reset(rnd, 120)
    assert rnd.timer_duration == 120
    assert rnd.timer_started_at is None
    assert TimerService.seconds_remaining(rnd) is None


def test_timer_expiry_detected(db, session_factory):
    _, rnd = _make_round(db, session_factory)
    rnd.timer_started_at = utcnow() - timedelta(seconds=200)
    assert TimerService.is_expired(rnd) is True


def test_timer_expiry_switches_turn(db, session_factory):
    from services.game_manager import GameManager

    data, rnd = _make_round(db, session_factory)
    rnd.current_team = Team.RED
    rnd.timer_started_at = utcnow() - timedelta(seconds=200)
    result = GameManager.handle_timer_expiry(data["session"], rnd)
    assert result.get("turn_changed") is True
    assert rnd.current_team == Team.BLUE


def test_timer_not_expired_no_change(db, session_factory):
    from services.game_manager import GameManager

    data, rnd = _make_round(db, session_factory)
    rnd.current_team = Team.RED
    result = GameManager.handle_timer_expiry(data["session"], rnd)
    assert result.get("ignored") is True
    assert rnd.current_team == Team.RED
