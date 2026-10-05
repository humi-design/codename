"""Super-admin routes: dashboard, sessions, settings and AdSense."""

from __future__ import annotations

from datetime import timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func

from extensions import db
from models.constants import SessionStatus, utcnow
from models.game_session import GameSession
from models.round import Round
from models.session_player import SessionPlayer
from services.admin_auth import AdminAuth, admin_required
from services.security import login_limiter
from services.session_manager import SessionManager
from services.settings_service import DEFAULTS, SettingsService

admin_bp = Blueprint("admin", __name__)


# ------------------------------------------------------------------- auth
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if AdminAuth.is_authenticated():
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        if not login_limiter.allow(request.remote_addr or "unknown"):
            flash("Too many login attempts. Please wait and try again.", "error")
            return render_template("admin/login.html"), 429
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user_info = AdminAuth.authenticate(username, password)
        if user_info is None:
            current_app.logger.warning("Failed admin login for %r", username)
            flash("Invalid username or password.", "error")
            return render_template("admin/login.html"), 401
        AdminAuth.login(user_info)
        current_app.logger.info("Admin %s signed in", user_info["username"])
        next_url = request.args.get("next") or request.form.get("next")
        if next_url and next_url.startswith("/admin"):
            return redirect(next_url)
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST", "GET"])
def logout():
    AdminAuth.logout()
    flash("Signed out.", "info")
    return redirect(url_for("admin.login"))


# -------------------------------------------------------------- dashboard
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    stats = {
        "active_sessions": GameSession.query.filter_by(
            status=SessionStatus.ACTIVE).count(),
        "total_sessions": GameSession.query.count(),
        "players_today": SessionPlayer.query.filter(
            SessionPlayer.joined_at >= day_ago).count(),
        "rounds_today": Round.query.filter(Round.created_at >= day_ago).count(),
        "total_players": SessionPlayer.query.count(),
        "total_rounds": Round.query.count(),
    }
    active_sessions = (
        GameSession.query.filter_by(status=SessionStatus.ACTIVE)
        .order_by(GameSession.last_activity_at.desc())
        .limit(50)
        .all()
    )
    return render_template("admin/dashboard.html", stats=stats,
                           active_sessions=active_sessions)


@admin_bp.route("/sessions")
@admin_required
def sessions():
    query = GameSession.query
    status = request.args.get("status")
    if status in SessionStatus.ALL:
        query = query.filter_by(status=status)
    search = (request.args.get("q") or "").strip().upper()
    if search:
        query = query.filter(
            db.or_(
                GameSession.session_code.like(f"%{search}%"),
                GameSession.host_name.like(f"%{search}%"),
            )
        )
    page = max(1, int(request.args.get("page", 1)))
    per_page = 25
    pagination = query.order_by(GameSession.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template("admin/sessions.html", pagination=pagination,
                           sessions=pagination.items, status=status, search=search)


@admin_bp.route("/sessions/<int:session_id>")
@admin_required
def session_detail(session_id: int):
    game_session = GameSession.query.get(session_id)
    if game_session is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin.sessions"))
    events = (
        game_session.events[-100:] if game_session.events else []
    )
    return render_template(
        "admin/session_detail.html",
        game_session=game_session,
        summary=SessionManager.session_summary(game_session),
        rounds=game_session.rounds,
        players=game_session.players,
        events=events,
    )


@admin_bp.route("/sessions/<int:session_id>/terminate", methods=["POST"])
@admin_required
def terminate_session(session_id: int):
    game_session = GameSession.query.get(session_id)
    if game_session is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin.sessions"))
    if game_session.status == SessionStatus.ACTIVE:
        SessionManager.end_session(game_session)
        current_app.logger.warning("Admin terminated session %s",
                                   game_session.session_code)
        flash(f"Session {game_session.session_code} terminated.", "success")
    else:
        flash("Session already ended.", "info")
    return redirect(url_for("admin.sessions"))


# --------------------------------------------------------------- settings
@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        values = {}
        for key in DEFAULTS:
            if key.startswith("adsense_"):
                continue
            if key in request.form:
                values[key] = request.form.get(key)
            elif DEFAULTS[key][1]:  # boolean checkbox not present => off
                values[key] = "0"
        SettingsService.set_many(values)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", settings=SettingsService.all())


@admin_bp.route("/adsense", methods=["GET", "POST"])
@admin_required
def adsense():
    if request.method == "POST":
        SettingsService.set("adsense_enabled",
                            "1" if request.form.get("adsense_enabled") else "0")
        for key in (
            "adsense_publisher_id",
            "adsense_slot_home",
            "adsense_slot_join",
            "adsense_slot_player_top",
            "adsense_slot_player_bottom",
            "adsense_slot_session_summary",
        ):
            SettingsService.set(key, (request.form.get(key) or "").strip())
        db.session.commit()
        flash("AdSense settings saved.", "success")
        return redirect(url_for("admin.adsense"))

    return render_template("admin/adsense.html", settings=SettingsService.all(),
                           adsense=SettingsService.adsense_config())


# ------------------------------------------------------------ health/api
@admin_bp.route("/health")
@admin_required
def health():
    db_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:  # pragma: no cover - only on DB outage
        db_ok = False
    return jsonify(
        database="ok" if db_ok else "error",
        active_sessions=GameSession.query.filter_by(
            status=SessionStatus.ACTIVE).count(),
        server_time=utcnow().isoformat(),
    )
