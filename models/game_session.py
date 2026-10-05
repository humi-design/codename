"""Game session model - one Starmaker session == one invite code."""

from extensions import db
from models.constants import SessionStatus, utcnow


class GameSession(db.Model):
    __tablename__ = "game_sessions"

    id = db.Column(db.Integer, primary_key=True)
    session_code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    host_token_hash = db.Column(db.String(255), nullable=False)
    host_name = db.Column(db.String(64), nullable=False, default="Host")
    status = db.Column(
        db.String(16), nullable=False, default=SessionStatus.ACTIVE, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    players = db.relationship(
        "SessionPlayer", backref="session", lazy="select",
        cascade="all, delete-orphan",
    )
    rounds = db.relationship(
        "Round", backref="session", lazy="select", order_by="Round.round_number",
        cascade="all, delete-orphan",
    )
    events = db.relationship(
        "SessionEvent", backref="session", lazy="select",
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------- helpers
    @property
    def is_active(self) -> bool:
        return self.status == SessionStatus.ACTIVE

    def touch(self) -> None:
        self.last_activity_at = utcnow()

    def active_players(self):
        return [p for p in self.players]

    def current_round(self):
        """Return the most recent round (any status) or ``None``."""
        if not self.rounds:
            return None
        return self.rounds[-1]

    def live_round(self):
        """Return the current non-ended round if one exists."""
        rnd = self.current_round()
        if rnd is not None and rnd.status != "ENDED":
            return rnd
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GameSession {self.session_code} {self.status}>"
