"""Game-related socket handlers: guesses, timer expiry and state sync.

Every handler re-authenticates the caller from its token and delegates the
actual rules to ``GameManager``.  The server is always the source of truth.
"""

from __future__ import annotations

from flask import request
from flask_socketio import emit

from extensions import db, socketio
from services.broadcaster import Broadcaster
from services.game_manager import GameError, GameManager
from services.security import guess_limiter
from services.session_manager import SessionError, SessionManager


def _resolve(data):
    """Return (session, player, error_message)."""
    data = data or {}
    code = (data.get("session_code") or "").strip().upper()
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        return None, None, "Session not found."
    player = SessionManager.authenticate_player(game_session, data.get("player_token"))
    if player is None:
        return game_session, None, "You are not a member of this session."
    return game_session, player, None


@socketio.on("submit_guess")
def handle_submit_guess(data):
    game_session, player, error = _resolve(data)
    if error:
        emit("error_message", {"message": error})
        return
    if not guess_limiter.allow(f"guess:{player.id}"):
        emit("error_message", {"message": "Too many guesses. Please slow down."})
        return

    round_obj = game_session.live_round()
    if round_obj is None:
        emit("error_message", {"message": "No active round."})
        return
    try:
        GameManager.submit_guess(game_session, round_obj, player, data.get("word"))
    except (GameError, SessionError) as exc:
        emit("error_message", {"message": str(exc)})
        return

    Broadcaster.push_state(game_session)
    emit("guess_ack", {"word": data.get("word")})


@socketio.on("notify_timer_expired")
def handle_timer_expired(data):
    """Client reports the countdown hit zero; server validates and acts."""
    data = data or {}
    code = (data.get("session_code") or "").strip().upper()
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        return
    # Only the host may drive timer transitions.
    if not SessionManager.is_host(game_session, data.get("host_token")):
        return
    round_obj = game_session.live_round()
    if round_obj is None:
        return
    result = GameManager.handle_timer_expiry(game_session, round_obj)
    if not result.get("ignored"):
        Broadcaster.push_state(game_session)
        Broadcaster.event(game_session, "turn_changed",
                          {"current_team": round_obj.current_team})
