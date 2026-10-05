"""Session player model - a lightweight, account-less participant."""

from extensions import db
from models.constants import utcnow


class SessionPlayer(db.Model):
    __tablename__ = "session_players"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("game_sessions.id"), nullable=False, index=True
    )
    display_name = db.Column(db.String(64), nullable=False)
    player_token_hash = db.Column(db.String(255), nullable=False)
    is_connected = db.Column(db.Boolean, nullable=False, default=False)
    is_host = db.Column(db.Boolean, nullable=False, default=False)
    joined_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    round_players = db.relationship(
        "RoundPlayer", backref="player", lazy="select",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("session_id", "display_name", name="uq_player_name_session"),
    )

    def touch(self) -> None:
        self.last_seen_at = utcnow()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SessionPlayer {self.display_name} session={self.session_id}>"
