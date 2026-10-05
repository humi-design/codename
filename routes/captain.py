"""Captain (spymaster) view with the secret key."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, redirect, render_template, url_for

from routes.helpers import load_session_or_404, resolve_player_token
from services.serializers import VIEWER_CAPTAIN, build_state
from services.session_manager import SessionManager

captain_bp = Blueprint("captain", __name__)


def _resolve_captain(code: str):
    game_session = load_session_or_404(code)
    token = resolve_player_token(code)
    player = SessionManager.authenticate_player(game_session, token) if token else None
    if player is None:
        return game_session, None, None

    round_obj = game_session.live_round() or game_session.current_round()
    if round_obj is None:
        return game_session, player, None
    rp = next((x for x in round_obj.round_players if x.player_id == player.id), None)
    if rp is None or rp.role != "CAPTAIN":
        return game_session, player, None
    return game_session, player, token


@captain_bp.route("/captain/<session_code>")
def view(session_code: str):
    code = session_code.strip().upper()
    game_session, player, token = _resolve_captain(code)
    if player is None:
        return redirect(url_for("session.join", session_code=code))

    round_obj = game_session.live_round() or game_session.current_round()
    if round_obj is None:
        return redirect(url_for("session.lobby", session_code=code))

    rp = next((x for x in round_obj.round_players if x.player_id == player.id), None)
    if rp is None or rp.role != "CAPTAIN":
        # No longer a captain -> fall back to the player view.
        return redirect(url_for("player.view", session_code=code))

    state = build_state(game_session, VIEWER_CAPTAIN, player)
    return render_template(
        "captain.html",
        game_session=game_session,
        player=player,
        player_token=token,
        state=state,
        round_obj=round_obj,
    )


@captain_bp.route("/api/captain/<session_code>/state")
def state_api(session_code: str):
    code = session_code.strip().upper()
    game_session, player, token = _resolve_captain(code)
    if player is None or token is None:
        return jsonify(error="You are not a member of this session."), 403
    round_obj = game_session.live_round() or game_session.current_round()
    if round_obj is None:
        return jsonify(error="No active round."), 404
    rp = next((x for x in round_obj.round_players if x.player_id == player.id), None)
    if rp is None or rp.role != "CAPTAIN":
        return jsonify(error="You are not a captain in this round."), 403
    return jsonify(build_state(game_session, VIEWER_CAPTAIN, player))
