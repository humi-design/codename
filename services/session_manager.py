"""Session manager - creation, joining, and token-based authentication.

One session == one invite code that stays valid for the whole Starmaker
session (many rounds).  Only the host can end it.
"""

from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError

from extensions import db
from models.constants import EventType, SessionStatus, utcnow
from models.game_session import GameSession
from models.session_player import SessionPlayer
from services.event_logger import EventLogger
from services.security import generate_session_code, generate_token, hash_token, verify_token

NAME_RE = re.compile(r"^[\w .\-']{1,32}$", re.UNICODE)


class SessionError(Exception):
    """User-facing session error (safe to show to the user)."""


class SessionManager:
    # ------------------------------------------------------------- lookup
    @staticmethod
    def get_by_code(code: str) -> GameSession | None:
        if not code:
            return None
        return GameSession.query.filter_by(session_code=code.strip().upper()).first()

    @staticmethod
    def get_active_by_code(code: str) -> GameSession:
        session = SessionManager.get_by_code(code)
        if session is None:
            raise SessionError("Session not found. Check the game code and try again.")
        if session.status != SessionStatus.ACTIVE:
            raise SessionError("This session has ended.")
        return session

    # ------------------------------------------------------------- create
    @staticmethod
    def create_session(host_name: str) -> dict:
        host_name = (host_name or "").strip()
        if not NAME_RE.match(host_name):
            raise SessionError("Please enter a valid name (max 32 characters).")

        host_token = generate_token()
        player_token = generate_token()

        session = None
        for _ in range(10):
            code = generate_session_code()
            if GameSession.query.filter_by(session_code=code).first() is None:
                session = GameSession(
                    session_code=code,
                    host_token_hash=hash_token(host_token),
                    host_name=host_name,
                    status=SessionStatus.ACTIVE,
                )
                db.session.add(session)
                try:
                    db.session.flush()
                    break
                except IntegrityError:
                    db.session.rollback()
                    session = None
            session = None
        if session is None:
            raise SessionError("Could not create a session. Please try again.")

        host_player = SessionPlayer(
            session_id=session.id,
            display_name=host_name,
            player_token_hash=hash_token(player_token),
            is_connected=True,
            is_host=True,
        )
        db.session.add(host_player)
        db.session.flush()

        EventLogger.log(
            session.id,
            EventType.PLAYER_JOINED,
            player_id=host_player.id,
            data={"name": host_name, "is_host": True},
        )
        db.session.commit()

        return {
            "session": session,
            "host_token": host_token,
            "player_token": player_token,
            "host_player": host_player,
        }

    # --------------------------------------------------------------- join
    @staticmethod
    def join_session(code: str, display_name: str) -> dict:
        session = SessionManager.get_active_by_code(code)
        display_name = (display_name or "").strip()
        if not NAME_RE.match(display_name):
            raise SessionError("Please enter a valid name (max 32 characters).")

        if len(session.players) >= 40:
            raise SessionError("This session is full.")

        existing = next(
            (p for p in session.players if p.display_name.lower() == display_name.lower()),
            None,
        )
        if existing is not None:
            raise SessionError(
                "That name is already taken in this session. "
                "If it is you, reconnect from the same device or pick another name."
            )

        player_token = generate_token()
        player = SessionPlayer(
            session_id=session.id,
            display_name=display_name,
            player_token_hash=hash_token(player_token),
            is_connected=True,
            is_host=False,
        )
        db.session.add(player)
        session.touch()
        db.session.flush()

        EventLogger.log(
            session.id,
            EventType.PLAYER_JOINED,
            player_id=player.id,
            data={"name": display_name},
        )
        db.session.commit()

        return {"session": session, "player_token": player_token, "player": player}

    # ---------------------------------------------------------------- auth
    @staticmethod
    def is_host(session: GameSession, host_token: str) -> bool:
        return verify_token(host_token, session.host_token_hash)

    @staticmethod
    def authenticate_player(session: GameSession, player_token: str) -> SessionPlayer | None:
        """Find the player in ``session`` whose token matches."""
        if not player_token:
            return None
        for player in session.players:
            if verify_token(player_token, player.player_token_hash):
                return player
        return None

    @staticmethod
    def require_player(session: GameSession, player_token: str) -> SessionPlayer:
        player = SessionManager.authenticate_player(session, player_token)
        if player is None:
            raise SessionError("You are not a member of this session.")
        return player

    @staticmethod
    def require_host(session: GameSession, host_token: str) -> None:
        if not SessionManager.is_host(session, host_token):
            raise SessionError("You are not authorized to perform this action.")

    # ---------------------------------------------------------------- end
    @staticmethod
    def end_session(session: GameSession) -> None:
        if session.status == SessionStatus.ENDED:
            return
        # End any live round first.
        from services.game_manager import GameManager

        live = session.live_round()
        if live is not None:
            GameManager.end_round(session, live, winner=live.winner, reason="SESSION_ENDED")
        session.status = SessionStatus.ENDED
        session.ended_at = utcnow()
        session.touch()
        EventLogger.log(session.id, EventType.SESSION_ENDED, data={})
        db.session.commit()

    # ------------------------------------------------------------ presence
    @staticmethod
    def set_connected(player: SessionPlayer, connected: bool) -> None:
        player.is_connected = connected
        player.touch()

    @staticmethod
    def session_summary(session: GameSession) -> dict:
        rounds = session.rounds
        red_wins = sum(1 for r in rounds if r.winner == "RED")
        blue_wins = sum(1 for r in rounds if r.winner == "BLUE")
        return {
            "code": session.session_code,
            "host": session.host_name,
            "players": len(session.players),
            "rounds_played": len(rounds),
            "red_wins": red_wins,
            "blue_wins": blue_wins,
            "status": session.status,
            "created_at": session.created_at,
            "ended_at": session.ended_at,
        }
