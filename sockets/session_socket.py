"""Socket.IO connection, room membership and presence handling.

Authentication uses the same opaque tokens as HTTP: the client sends its
``host_token`` or ``player_token`` when joining a socket room.  A socket may
join multiple private rooms (player-safe, captain, host) only when it presents
the matching credential, so a malicious player can never subscribe to the
captain or host stream of their session.
"""

from __future__ import annotations

from flask import request
from flask_socketio import emit, join_room, leave_room

from extensions import db, socketio
from models.constants import EventType
from services.broadcaster import Broadcaster, captain_room, host_room, player_room
from services.event_logger import EventLogger
from services.serializers import VIEWER_CAPTAIN, VIEWER_HOST, VIEWER_PLAYER, build_state
from services.session_manager import SessionManager


def _private_room(player_id: int) -> str:
    return f"player:{player_id}"


@socketio.on("connect")
def handle_connect():
    # Connections are accepted, but nothing is visible until join_session
    # proves the caller's identity.
    return True


@socketio.on("join_session")
def handle_join_session(data):
    data = data or {}
    code = (data.get("session_code") or "").strip().upper()
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        emit("error_message", {"message": "Session not found."})
        return

    joined = False
    role = VIEWER_PLAYER
    player = None

    host_token = data.get("host_token")
    player_token = data.get("player_token")

    if host_token and SessionManager.is_host(game_session, host_token):
        join_room(host_room(code))
        role = VIEWER_HOST
        joined = True
        emit("session_state", build_state(game_session, VIEWER_HOST))
    elif player_token:
        player = SessionManager.authenticate_player(game_session, player_token)
        if player is not None:
            join_room(player_room(code))
            join_room(_private_room(player.id))
            SessionManager.set_connected(player, True)
            db.session.commit()
            Broadcaster.event(
                game_session, "player_joined",
                {"id": player.id, "name": player.display_name},
            )
            EventLogger.log(game_session.id, EventType.PLAYER_JOINED,
                            player_id=player.id, data={"name": player.display_name,
                                                       "reconnect": True})
            db.session.commit()

            # A captain also gets the spymaster key stream.
            round_obj = game_session.live_round() or game_session.current_round()
            rp = None
            if round_obj is not None:
                rp = next(
                    (x for x in round_obj.round_players if x.player_id == player.id),
                    None,
                )
            if rp is not None and rp.role == "CAPTAIN":
                join_room(captain_room(code))
                role = VIEWER_CAPTAIN
                emit("captain_state", build_state(game_session, VIEWER_CAPTAIN, player))
            else:
                emit("session_state", build_state(game_session, VIEWER_PLAYER, player))
            joined = True

    if not joined:
        emit("error_message", {"message": "You are not a member of this session."})
        return

    record_presence(request.sid, code, player.id if player else None)
    emit("joined", {"role": role, "session_code": code})
    Broadcaster.push_state(game_session)


@socketio.on("request_state")
def handle_request_state(data):
    data = data or {}
    code = (data.get("session_code") or "").strip().upper()
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        emit("error_message", {"message": "Session not found."})
        return

    host_token = data.get("host_token")
    player_token = data.get("player_token")

    if host_token and SessionManager.is_host(game_session, host_token):
        emit("session_state", build_state(game_session, VIEWER_HOST))
        return

    player = (SessionManager.authenticate_player(game_session, player_token)
              if player_token else None)
    if player is None:
        emit("error_message", {"message": "You are not a member of this session."})
        return

    round_obj = game_session.live_round() or game_session.current_round()
    rp = None
    if round_obj is not None:
        rp = next((x for x in round_obj.round_players if x.player_id == player.id), None)
    if rp is not None and rp.role == "CAPTAIN":
        emit("captain_state", build_state(game_session, VIEWER_CAPTAIN, player))
    else:
        emit("session_state", build_state(game_session, VIEWER_PLAYER, player))


@socketio.on("ping_state")
def handle_ping(data):
    """Lightweight heartbeat - keeps presence fresh without DB churn."""
    data = data or {}
    code = (data.get("session_code") or "").strip().upper()
    game_session = SessionManager.get_by_code(code)
    if game_session is None:
        return
    player_token = data.get("player_token")
    player = (SessionManager.authenticate_player(game_session, player_token)
              if player_token else None)
    if player is not None:
        SessionManager.set_connected(player, True)
        db.session.commit()
    emit("pong_state", {"ok": True})


@socketio.on("disconnect")
def handle_disconnect():
    # We cannot trust room membership after disconnect, so mark any matching
    # player offline by scanning the socket's rooms recorded at join time.
    # Flask-SocketIO exposes the rooms this sid belonged to via request.sid.
    sid = request.sid
    from flask import current_app

    state = current_app.extensions.get("socket_presence", {})
    info = state.pop(sid, None)
    if not info:
        return
    game_session = SessionManager.get_by_code(info.get("session_code", ""))
    if game_session is None:
        return
    player_id = info.get("player_id")
    if player_id:
        player = next((p for p in game_session.players if p.id == player_id), None)
        if player is not None:
            SessionManager.set_connected(player, False)
            db.session.commit()
            Broadcaster.event(game_session, "player_left",
                              {"id": player.id, "name": player.display_name})
            EventLogger.log(game_session.id, EventType.PLAYER_LEFT,
                            player_id=player.id, data={"name": player.display_name})
            db.session.commit()
    Broadcaster.push_state(game_session)


def record_presence(sid: str, session_code: str, player_id: int | None) -> None:
    from flask import current_app

    state = current_app.extensions.setdefault("socket_presence", {})
    state[sid] = {"session_code": session_code, "player_id": player_id}
