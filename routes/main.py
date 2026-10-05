"""Landing page, session creation and session summary routes."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from extensions import db
from models.constants import SessionStatus
from routes.helpers import (
    get_host_token,
    load_session_or_404,
    require_host_page,
    store_host_token,
    store_player_token,
)
from services.security import create_limiter
from services.session_manager import SessionError, SessionManager
from services.settings_service import SettingsService

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")


@main_bp.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        if not create_limiter.allow(request.remote_addr or "unknown"):
            flash("Too many sessions created. Please wait a moment.", "error")
            return render_template("create.html"), 429

        host_name = (request.form.get("host_name") or "").strip()
        try:
            result = SessionManager.create_session(host_name)
        except SessionError as exc:
            flash(str(exc), "error")
            return render_template("create.html"), 400

        code = result["session"].session_code
        store_host_token(code, result["host_token"])
        store_player_token(code, result["player_token"])
        current_app.logger.info("Session created: %s by %s", code, host_name)
        return redirect(url_for("main.created", session_code=code))

    return render_template("create.html")


@main_bp.route("/created/<session_code>")
def created(session_code: str):
    """Post-creation screen showing the invite code and share links."""
    game_session = load_session_or_404(session_code)
    token = get_host_token(game_session.session_code)
    if not token or not SessionManager.is_host(game_session, token):
        flash("You are not the host of this session.", "error")
        return redirect(url_for("main.index"))

    invite_url = url_for("session.join", session_code=game_session.session_code,
                         _external=True)
    return render_template(
        "create.html",
        created=True,
        game_session=game_session,
        invite_url=invite_url,
        host_token=token,
    )


@main_bp.route("/session/<session_code>/summary")
def session_summary(session_code: str):
    game_session = load_session_or_404(session_code)
    # Host may view any time; others only after the session ended.
    token = get_host_token(game_session.session_code)
    is_host = bool(token and SessionManager.is_host(game_session, token))
    if not is_host and game_session.status != SessionStatus.ENDED:
        flash("You are not authorized to view this summary.", "error")
        return redirect(url_for("main.index"))

    summary = SessionManager.session_summary(game_session)
    return render_template(
        "session_summary.html",
        game_session=game_session,
        summary=summary,
        rounds=game_session.rounds,
        players=game_session.players,
        is_host=is_host,
    )


@main_bp.route("/rules")
def rules():
    return render_template("rules.html")
