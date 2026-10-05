"""Super-admin routes: dashboard, sessions, settings, AdSense and vocabulary."""

from __future__ import annotations

import os
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
from werkzeug.utils import secure_filename

from extensions import db
from models.constants import SessionStatus, utcnow
from models.game_session import GameSession
from models.round import Round
from models.session_player import SessionPlayer
from models.vocabulary_import import VocabularyImport
from models.vocabulary_source import VocabularySource
from services.admin_auth import AdminAuth, admin_required
from services.security import login_limiter
from services.session_manager import SessionManager
from services.settings_service import DEFAULTS, SettingsService
from services.vocabulary.datasets import dataset_dir
from services.vocabulary.import_manager import ImportError_, ImportManager
from services.vocabulary.sources import ensure_source_rows
from services.word_engine import WordEngine

admin_bp = Blueprint("admin", __name__)

_ALLOWED_UPLOAD_EXT = {".csv", ".txt", ".jsonl", ".json", ".tsv"}


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
            # AdSense and vocabulary settings have their own dedicated pages.
            if key.startswith("adsense_") or key.startswith("vocab_"):
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


# ----------------------------------------------------------- vocabulary
@admin_bp.route("/vocabulary")
@admin_required
def vocabulary():
    try:
        ensure_source_rows()
    except Exception:  # pragma: no cover - table may not exist pre-migration
        db.session.rollback()
    status = ImportManager.status()
    stats = WordEngine.statistics()
    sources = VocabularySource.query.order_by(VocabularySource.name).all()
    running = status["running_import"]
    last = status["last_import"]
    return render_template(
        "admin/vocabulary.html",
        vocab=status,
        stats=stats,
        sources=sources,
        running=running,
        last_import=last,
        settings=SettingsService.all(),
        dataset_dir=dataset_dir(SettingsService.get("vocab_dataset_dir")),
    )


@admin_bp.route("/vocabulary/status")
@admin_required
def vocabulary_status():
    """Polled by the vocabulary page to show live import progress."""
    status = ImportManager.status()
    running = status["running_import"]
    payload = {
        "status": status["status"],
        "total": status["total"],
        "active": status["active"],
        "inactive": status["inactive"],
    }
    if running is not None:
        processed = int(running.total_processed or 0)
        payload["import"] = {
            "id": running.id,
            "source": running.source,
            "status": running.status,
            "mode": running.mode,
            "processed": processed,
            "imported": running.total_imported,
            "updated": running.total_updated,
            "duplicates": running.total_duplicates,
            "rejected": running.total_rejected,
            "errors": running.total_errors,
            "started_at": (running.started_at.isoformat()
                           if running.started_at else None),
        }
    elif status["last_import"] is not None:
        last = status["last_import"]
        payload["import"] = {
            "id": last.id,
            "source": last.source,
            "status": last.status,
            "mode": last.mode,
            "processed": last.total_processed,
            "imported": last.total_imported,
            "updated": last.total_updated,
            "duplicates": last.total_duplicates,
            "rejected": last.total_rejected,
            "errors": last.total_errors,
            "started_at": (last.started_at.isoformat()
                           if last.started_at else None),
            "completed_at": (last.completed_at.isoformat()
                             if last.completed_at else None),
            "error_message": last.error_message,
        }
    return jsonify(payload)


@admin_bp.route("/vocabulary/import", methods=["POST"])
@admin_required
def vocabulary_import():
    source = (request.form.get("source") or "kaikki").strip().lower()
    mode = (request.form.get("mode") or "initial").strip().lower()
    if mode not in ("initial", "update"):
        mode = "initial"
    try:
        ImportManager.start(source, mode=mode, background=True)
        flash(f"Vocabulary import started from source '{source}'.", "success")
    except ImportError_ as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.vocabulary"))


@admin_bp.route("/vocabulary/upload", methods=["POST"])
@admin_required
def vocabulary_upload():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Please choose a file to upload.", "error")
        return redirect(url_for("admin.vocabulary"))

    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_UPLOAD_EXT:
        flash(f"Unsupported file type '{ext or 'unknown'}'. "
              "Use .csv, .txt, .jsonl or .json.", "error")
        return redirect(url_for("admin.vocabulary"))

    target_dir = dataset_dir(SettingsService.get("vocab_dataset_dir"))
    target = os.path.join(target_dir, f"custom_{utcnow():%Y%m%d%H%M%S}_{filename}")
    upload.save(target)

    try:
        ImportManager.start("custom", mode="update", path=target,
                            label=f"upload: {filename}", background=True)
        flash(f"Uploaded '{filename}' and started import.", "success")
    except ImportError_ as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.vocabulary"))


@admin_bp.route("/vocabulary/imports")
@admin_required
def vocabulary_imports():
    page = max(1, int(request.args.get("page", 1)))
    pagination = VocabularyImport.query.order_by(
        VocabularyImport.id.desc()
    ).paginate(page=page, per_page=25, error_out=False)
    return render_template("admin/vocabulary_imports.html",
                           pagination=pagination, imports=pagination.items)


@admin_bp.route("/vocabulary/imports/<int:import_id>/cancel", methods=["POST"])
@admin_required
def vocabulary_cancel(import_id: int):
    if ImportManager.cancel(import_id):
        flash("Cancelling import...", "info")
    else:
        flash("That import is not running.", "error")
    return redirect(url_for("admin.vocabulary"))


@admin_bp.route("/vocabulary/imports/<int:import_id>/retry", methods=["POST"])
@admin_required
def vocabulary_retry(import_id: int):
    record = db.session.get(VocabularyImport, import_id)
    if record is None:
        flash("Import not found.", "error")
        return redirect(url_for("admin.vocabulary_imports"))
    try:
        ImportManager.start(
            record.source, mode="update", path=record.path,
            dataset_url=record.dataset_url,
            label=record.label, background=True,
        )
        flash("Retry started.", "success")
    except ImportError_ as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.vocabulary"))


@admin_bp.route("/vocabulary/filters", methods=["POST"])
@admin_required
def vocabulary_filters():
    """Update the word-quality filters used by the board generator."""
    SettingsService.set("vocab_max_chars", request.form.get("vocab_max_chars", "24"))
    SettingsService.set("vocab_max_words", request.form.get("vocab_max_words", "3"))
    SettingsService.set("vocab_min_frequency",
                        request.form.get("vocab_min_frequency", "0"))
    SettingsService.set("vocab_language",
                        (request.form.get("vocab_language") or "en").strip()[:8])
    SettingsService.set("vocab_allow_proper_nouns",
                        "1" if request.form.get("vocab_allow_proper_nouns") else "0")
    SettingsService.set("vocab_allow_multiword",
                        "1" if request.form.get("vocab_allow_multiword") else "0")
    db.session.commit()
    flash("Vocabulary filters saved.", "success")
    return redirect(url_for("admin.vocabulary"))
