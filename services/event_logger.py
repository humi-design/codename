"""Event log helper - appends rows to ``session_events``."""

from __future__ import annotations

from extensions import db
from models.session_event import SessionEvent


class EventLogger:
    @staticmethod
    def log(session_id: int, event_type: str, *, round_id: int | None = None,
            player_id: int | None = None, data: dict | None = None,
            commit: bool = False) -> SessionEvent:
        event = SessionEvent(
            session_id=session_id,
            round_id=round_id,
            player_id=player_id,
            event_type=event_type,
            event_data=data or {},
        )
        db.session.add(event)
        if commit:
            db.session.commit()
        return event
