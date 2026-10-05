"""Pytest fixtures.

Tests run against a real MySQL/MariaDB database (``codenames_test``) so the
ORM behaviour matches production.  Set ``TEST_DATABASE_URL`` to override.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from extensions import db as _db  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    with application.app_context():
        import models  # noqa: F401

        _db.drop_all()
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """Clean all tables before each test for isolation."""
    with app.app_context():
        _db.session.remove()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        yield _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def session_factory(app):
    """Create a session + host + players directly through the service layer."""
    from services.session_manager import SessionManager

    created = []

    def _make(host_name="Host", players=("Somil", "Priya", "Rahul", "Aman", "Neha")):
        result = SessionManager.create_session(host_name)
        game_session = result["session"]
        host_token = result["host_token"]
        joined = []
        for name in players:
            joined.append(SessionManager.join_session(game_session.session_code, name))
        created.append(game_session)
        return {
            "session": game_session,
            "code": game_session.session_code,
            "host_token": host_token,
            "players": joined,
        }

    return _make
