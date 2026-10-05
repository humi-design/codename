"""Application configuration.

All secrets are read from the environment (see ``.env.example``).  Nothing
sensitive is hard-coded so the project can be deployed to shared hosting
without leaking credentials into version control.
"""

import os

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_db_url(url: str) -> str:
    """Allow the common ``mysql://`` shorthand used by many hosts."""
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://") :]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-key-change-me"

    _default_db = "mysql+pymysql://cnuser:cnpass123@127.0.0.1/codenames_live?charset=utf8mb4"
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL") or _default_db
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # ``pool_pre_ping`` keeps stale connections from breaking shared hosting.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 5,
        "max_overflow": 10,
    }

    # ------------------------------------------------------------------ auth
    SUPER_ADMIN_USERNAME = os.environ.get("SUPER_ADMIN_USERNAME", "admin")
    SUPER_ADMIN_PASSWORD_HASH = os.environ.get("SUPER_ADMIN_PASSWORD_HASH", "")

    # ------------------------------------------------------------- cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 hours

    # -------------------------------------------------------------- socketio
    SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE") or None
    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")

    # ------------------------------------------------------------------ game
    DEFAULT_BOARD_SIZE = 5
    DEFAULT_TIMER_DURATION = 180  # seconds
    SESSION_IDLE_TIMEOUT_HOURS = 12
    MAX_PLAYERS_PER_SESSION = 40

    # ------------------------------------------------------------------ misc
    PROXY_FIX = _env_bool("PROXY_FIX", False)
    JSON_SORT_KEYS = False


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("TEST_DATABASE_URL")
        or "mysql+pymysql://cnuser:cnpass123@127.0.0.1/codenames_test?charset=utf8mb4"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
