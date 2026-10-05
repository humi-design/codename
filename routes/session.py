"""Join flow and the shared session lobby."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from routes.helpers import (
    get_host_token,
    get_player_token,
    load_session_or_404,
    resolve_host_token,
    resolve_player_token,
    store_player_token,
)
from services.security import join_limiter
from services.session_manager import SessionError, SessionManager

session_bp = Blueprint("session", __name__)


def _post_join_redirect(game_session, player):
    """Route the player to the right view based on their round role."""
    code = game_session.session_code
    round_obj = game_session.live_round() or game_session.current_round()
    if round_obj is None:
        return redirect(url_for("session.lobby", session_code=code))
    rp = next((x for x in round_obj.round_players if x.player_id == player.id), None)
    if rp is not None and rp.role == "CAPTAIN":
        return redirect(url_for("captain.view", session_code=code))
    return redirect(url_for("player.view", session_code=code))


@session_bp.route("/join/<session_code>", methods=["GET", "POST"])
def join(session_code: str):
    code = session_code.strip().upper()
    game_session = load_session_or_404(code)

    if game_session.status != "ACTIVE":
        return render_template("join.html", game_session=game_session,
                               ended=True, session_code=code), 410

    # Already joined on this device?
    existing_token = get_player_token(code)
    if existing_token:
        player = SessionManager.authenticate_player(game_session, existing_token)
        if player is not None:
            return _post_join_redirect(game_session, player)

    if request.method == "POST":
        if not join_limiter.allow(request.remote_addr or "unknown"):
            flash("Too many join attempts. Please wait a moment.", "error")
            return render_template("join.html", game_session=game_session,
                                   session_code=code), 429
        display_name = (request.form.get("display_name") or "").strip()
        try:
            result = SessionManager.join_session(code, display_name)
        except SessionError as exc:
            flash(str(exc), "error")
            return render_template("join.html", game_session=game_session,
                                   session_code=code), 400

        store_player_token(code, result["player_token"])
        current_app.logger.info("Player %s joined session %s", display_name, code)
        return _post_join_redirect(result["session"], result["player"])

    return render_template("join.html", game_session=game_session, session_code=code)


@session_bp.route("/session/<session_code>")
def lobby(session_code: str):
    """Shared lobby: host gets controls, players get presence + status."""
    code = session_code.strip().upper()
    game_session = load_session_or_404(code)

    host_token = resolve_host_token(code)
    is_host = bool(host_token and SessionManager.is_host(game_session, host_token))

    player = None
    player_token = resolve_player_token(code)
    if player_token:
        player = SessionManager.authenticate_player(game_session, player_token)

    if not is_host and player is None:
        flash("Please join this session first.", "info")
        return redirect(url_for("session.join", session_code=code))

    round_obj = game_session.live_round() or game_session.current_round()
    return render_template(
        "lobby.html",
        game_session=game_session,
        is_host=is_host,
        host_token=host_token if is_host else None,
        player=player,
        player_token=player_token if player else None,
        round_obj=round_obj,
    )
