"""Player game view and player-safe state API."""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, url_for

from routes.helpers import (
    get_player_token,
    load_session_or_404,
    resolve_player_header,
    resolve_player_token,
)
from services.serializers import VIEWER_PLAYER, build_state
from services.session_manager import SessionManager

player_bp = Blueprint("player", __name__)


@player_bp.route("/player/<session_code>")
def view(session_code: str):
    code = session_code.strip().upper()
    game_session = load_session_or_404(code)
    token = resolve_player_token(code)
    player = SessionManager.authenticate_player(game_session, token) if token else None
    if player is None:
        return redirect(url_for("session.join", session_code=code))

    round_obj = game_session.live_round() or game_session.current_round()
    if round_obj is None:
        return redirect(url_for("session.lobby", session_code=code))

    state = build_state(game_session, VIEWER_PLAYER, player)
    return render_template(
        "player.html",
        game_session=game_session,
        player=player,
        player_token=token,
        state=state,
        round_obj=round_obj,
    )


@player_bp.route("/api/session/<session_code>/state")
def state_api(session_code: str):
    """Player-safe state refresh endpoint (used as a socket fallback)."""
    code = session_code.strip().upper()
    game_session = load_session_or_404(code)
    token = resolve_player_token(code)
    player = SessionManager.authenticate_player(game_session, token) if token else None
    if player is None:
        return jsonify(error="You are not a member of this session."), 403
    return jsonify(build_state(game_session, VIEWER_PLAYER, player))


@player_bp.route("/api/session/<session_code>/guess", methods=["POST"])
def guess_api(session_code: str):
    """Submit a guess over HTTP (fallback when websockets are unavailable).

    Authenticates with the ``X-Player-Token`` header so it is CSRF-safe.
    """
    from flask import request

    from services.broadcaster import Broadcaster
    from services.game_manager import GameError, GameManager
    from services.security import guess_limiter

    code = session_code.strip().upper()
    game_session = load_session_or_404(code)
    token = resolve_player_header(code)
    player = SessionManager.authenticate_player(game_session, token) if token else None
    if player is None:
        return jsonify(error="You are not a member of this session."), 403
    if not guess_limiter.allow(f"guess:{player.id}"):
        return jsonify(error="Too many guesses. Please slow down."), 429

    round_obj = game_session.live_round()
    if round_obj is None:
        return jsonify(error="No active round."), 400
    data = request.get_json(silent=True) or {}
    try:
        GameManager.submit_guess(game_session, round_obj, player, data.get("word"))
    except GameError as exc:
        return jsonify(error=str(exc)), 400

    Broadcaster.push_state(game_session)
    return jsonify(ok=True)
