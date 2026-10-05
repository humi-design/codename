"""Socket.IO broadcast layer.

Three distinct rooms exist per session so that each viewer role receives only
the payload it is allowed to see:

    session:<CODE>            -> player-safe state (everyone)
    session:<CODE>:captain    -> captain state (spymaster key)
    session:<CODE>:host       -> host state (full control view)

Socket.IO already isolates rooms, so events from one session can never reach
another.  Every emit here is scoped to a specific session's rooms.
"""

from __future__ import annotations

from extensions import socketio
from services.serializers import (
    VIEWER_CAPTAIN,
    VIEWER_HOST,
    VIEWER_PLAYER,
    build_state,
)


def player_room(code: str) -> str:
    return f"session:{code}"


def captain_room(code: str) -> str:
    return f"session:{code}:captain"


def host_room(code: str) -> str:
    return f"session:{code}:host"


class Broadcaster:
    # -------------------------------------------------------- state pushes
    @staticmethod
    def push_state(session) -> None:
        """Emit role-appropriate full state to each room."""
        code = session.session_code
        socketio.emit(
            "session_state",
            build_state(session, VIEWER_PLAYER),
            to=player_room(code),
        )
        socketio.emit(
            "captain_state",
            build_state(session, VIEWER_CAPTAIN),
            to=captain_room(code),
        )
        socketio.emit(
            "host_state",
            build_state(session, VIEWER_HOST),
            to=host_room(code),
        )

    @staticmethod
    def push_state_to_player(session, player_id: int, viewer_role: str) -> None:
        """Emit full state to a single player's private room (reconnect)."""
        socketio.emit(
            f"{viewer_role.lower()}_state",
            build_state(session, viewer_role),
            to=f"player:{player_id}",
        )

    # --------------------------------------------------------- notifications
    @staticmethod
    def notify(session, message: str, level: str = "info") -> None:
        socketio.emit(
            "notify",
            {"message": message, "level": level},
            to=player_room(session.session_code),
        )

    @staticmethod
    def event(session, name: str, payload: dict | None = None) -> None:
        """Broadcast a lightweight, player-safe event to the whole session."""
        socketio.emit(name, payload or {}, to=player_room(session.session_code))

    # ------------------------------------------------------------- targeted
    @staticmethod
    def to_player(player_id: int, name: str, payload: dict | None = None) -> None:
        socketio.emit(name, payload or {}, to=f"player:{player_id}")
