"""Session event model - lightweight audit log."""

from extensions import db
from models.constants import utcnow


class SessionEvent(db.Model):
    __tablename__ = "session_events"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("game_sessions.id"), nullable=False, index=True
    )
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=True, index=True
    )
    player_id = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=True
    )
    event_type = db.Column(db.String(48), nullable=False, index=True)
    event_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SessionEvent {self.event_type} session={self.session_id}>"
