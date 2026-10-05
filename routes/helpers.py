"""Shared helpers for HTTP routes: token storage and authorization.

Tokens live in the signed Flask session cookie (httpOnly) so page access is
authorized server-side.  The same token is also exposed to the owner's own
page (never to other users) so the Socket.IO client can authenticate.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, redirect, request, session, url_for

from models.constants import SessionStatus
from services.session_manager import SessionError, SessionManager


# ------------------------------------------------------------- token store
def _token_map(key: str) -> dict:
    data = session.get(key)
    if not isinstance(data, dict):
        data = {}
    return data


def store_host_token(code: str, token: str) -> None:
    data = _token_map("host_tokens")
    data[code.upper()] = token
    session["host_tokens"] = data
    session.modified = True


def store_player_token(code: str, token: str) -> None:
    data = _token_map("player_tokens")
    data[code.upper()] = token
    session["player_tokens"] = data
    session.modified = True


def get_host_token(code: str) -> str | None:
    return _token_map("host_tokens").get(code.upper())


def get_player_token(code: str) -> str | None:
    return _token_map("player_tokens").get(code.upper())


# --------------------------------------------------------------- resolving
def resolve_host_token(code: str) -> str | None:
    """Prefer an explicit query/header token, then the session cookie."""
    token = request.headers.get("X-Host-Token") or request.args.get("token")
    if token:
        store_host_token(code, token)
        return token
    return get_host_token(code)


def resolve_host_header(code: str) -> str | None:
    """Header-only host token, used for state-changing API calls.

    Requiring a custom header (which cross-site forms cannot set) makes the
    token-authenticated POST APIs immune to CSRF without a CSRF token.
    """
    return request.headers.get("X-Host-Token") or None


def resolve_player_header(code: str) -> str | None:
    return request.headers.get("X-Player-Token") or None


def resolve_player_token(code: str) -> str | None:
    token = request.headers.get("X-Player-Token") or request.args.get("token")
    if token:
        store_player_token(code, token)
        return token
    return get_player_token(code)


# ------------------------------------------------------------- page guards
def load_session_or_404(code: str):
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        abort(404)
    return game_session


def require_host_page(code: str):
    """Return (session, host_token) or redirect/abort."""
    game_session = load_session_or_404(code)
    token = resolve_host_token(code)
    if not token or not SessionManager.is_host(game_session, token):
        abort(403)
    return game_session, token


def require_player_page(code: str):
    game_session = load_session_or_404(code)
    token = resolve_player_token(code)
    if not token:
        abort(403)
    player = SessionManager.authenticate_player(game_session, token)
    if player is None:
        abort(403)
    return game_session, player, token


def require_active_session(game_session):
    if game_session.status != SessionStatus.ACTIVE:
        abort(410)


def json_error(message: str, status: int = 400):
    from flask import jsonify

    return jsonify(error=message), status


def host_action(fn):
    """Decorator for JSON host action endpoints.

    Authenticates via the ``X-Host-Token`` header only (never the cookie), so a
    cross-site request cannot forge it.  Converts ``SessionError``/``GameError``
    into clean JSON errors (never tracebacks).
    """

    @wraps(fn)
    def wrapper(session_code, *args, **kwargs):
        from services.game_manager import GameError

        game_session = SessionManager.get_by_code(session_code)
        if game_session is None:
            return json_error("Session not found.", 404)
        token = resolve_host_header(session_code)
        if not token or not SessionManager.is_host(game_session, token):
            return json_error("You are not authorized to perform this action.", 403)
        try:
            return fn(game_session, *args, **kwargs)
        except (SessionError, GameError) as exc:
            return json_error(str(exc), 400)

    return wrapper
