"""Codenames Live - a real-time, Codenames-style multiplayer web app."""

import logging
import os
import sys

from flask import Flask, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config_by_name
from extensions import csrf, db, migrate, socketio


def create_app(config_name: str | None = None) -> Flask:
    """Application factory."""
    config_name = config_name or os.environ.get("FLASK_CONFIG", "default")
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    _configure_logging(app)

    if app.config.get("PROXY_FIX"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ---------------------------------------------------------------- ext
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    socketio.init_app(
        app,
        async_mode=app.config["SOCKETIO_ASYNC_MODE"],
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
        cors_allowed_origins=None,
        logger=False,
        engineio_logger=False,
    )

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_template_helpers(app)

    # Import models so Alembic / create_all can see them.
    import models  # noqa: F401

    from sockets import register_socket_handlers

    register_socket_handlers(socketio)

    with app.app_context():
        from services.settings_service import SettingsService

        SettingsService.ensure_defaults()

    @app.route("/healthz")
    def healthz():  # pragma: no cover - trivial
        return jsonify(status="ok")

    return app


def _register_blueprints(app: Flask) -> None:
    from routes.admin import admin_bp
    from routes.captain import captain_bp
    from routes.host import host_bp
    from routes.main import main_bp
    from routes.player import player_bp
    from routes.session import session_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(captain_bp)
    app.register_blueprint(host_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # The JSON action APIs authenticate with an opaque token sent in a custom
    # header (X-Host-Token / X-Player-Token).  Browsers cannot set custom
    # headers cross-site, so these endpoints are CSRF-safe without a form
    # token.  The HTML form blueprints keep CSRF protection enabled.
    csrf.exempt(host_bp)
    csrf.exempt(player_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(err):
        if _wants_json():
            return jsonify(error="You are not authorized to perform this action."), 403
        return render_template("error.html", code=403,
                               message="You are not authorized to perform this action."), 403

    @app.errorhandler(404)
    def not_found(err):
        if _wants_json():
            return jsonify(error="Not found."), 404
        return render_template("error.html", code=404,
                               message="The page you were looking for does not exist."), 404

    @app.errorhandler(429)
    def rate_limited(err):
        if _wants_json():
            return jsonify(error="Too many requests. Please slow down."), 429
        return render_template("error.html", code=429,
                               message="Too many requests. Please slow down."), 429

    @app.errorhandler(500)
    def server_error(err):  # pragma: no cover - exercised manually
        app.logger.exception("Unhandled server error")
        if _wants_json():
            return jsonify(error="Something went wrong. Please try again."), 500
        return render_template("error.html", code=500,
                               message="Something went wrong. Please try again."), 500


def _wants_json() -> bool:
    return (
        request.path.startswith("/api/")
        or request.accept_mimetypes.best == "application/json"
        or request.is_json
    )


def _register_template_helpers(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        from services.settings_service import SettingsService

        return {
            "adsense": SettingsService.adsense_config(),
            "app_name": "Codenames Live",
        }

    @app.template_filter("datetimeformat")
    def datetimeformat(value, fmt="%d %b %Y, %H:%M"):
        if not value:
            return "-"
        return value.strftime(fmt)


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    app.logger.handlers = [handler]
    app.logger.setLevel(level)


app = create_app()


if __name__ == "__main__":
    socketio.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=app.config.get("DEBUG", False),
        allow_unsafe_werkzeug=True,
    )
