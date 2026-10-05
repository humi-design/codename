"""Super-admin authentication.

Completely separate from the game host.  Supports two sources:
  1. Environment bootstrap credentials (``SUPER_ADMIN_USERNAME`` /
     ``SUPER_ADMIN_PASSWORD_HASH``) - useful on first deploy.
  2. Rows in the ``users`` table.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash

from extensions import db
from models.constants import UserRole
from models.user import User


class AdminAuth:
    SESSION_KEY = "admin_user"

    @staticmethod
    def authenticate(username: str, password: str) -> dict | None:
        username = (username or "").strip()
        if not username or not password:
            return None

        # 1. Bootstrap credential from the environment.
        bootstrap_user = current_app.config.get("SUPER_ADMIN_USERNAME")
        bootstrap_hash = current_app.config.get("SUPER_ADMIN_PASSWORD_HASH")
        if bootstrap_hash and username == bootstrap_user:
            try:
                if check_password_hash(bootstrap_hash, password):
                    return {"username": username, "role": UserRole.SUPER_ADMIN}
            except (ValueError, TypeError):
                pass

        # 2. Database user.
        user = User.query.filter_by(username=username).first()
        if user is not None and user.check_password(password):
            return {"username": user.username, "role": user.role, "id": user.id}
        return None

    @staticmethod
    def login(user_info: dict) -> None:
        session[AdminAuth.SESSION_KEY] = user_info
        session.permanent = True
        session.modified = True

    @staticmethod
    def logout() -> None:
        session.pop(AdminAuth.SESSION_KEY, None)
        session.modified = True

    @staticmethod
    def current() -> dict | None:
        data = session.get(AdminAuth.SESSION_KEY)
        return data if isinstance(data, dict) else None

    @staticmethod
    def is_authenticated() -> bool:
        return AdminAuth.current() is not None

    @staticmethod
    def ensure_bootstrap_user() -> None:
        """Optionally create the env-configured admin as a DB row."""
        username = current_app.config.get("SUPER_ADMIN_USERNAME")
        password_hash = current_app.config.get("SUPER_ADMIN_PASSWORD_HASH")
        if not (username and password_hash):
            return
        if User.query.filter_by(username=username).first() is None:
            db.session.add(
                User(username=username, password_hash=password_hash,
                     role=UserRole.SUPER_ADMIN)
            )
            db.session.commit()


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not AdminAuth.is_authenticated():
            if request.path.startswith("/admin/api"):
                abort(403)
            flash("Please sign in to access the admin panel.", "info")
            return redirect(url_for("admin.login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper
