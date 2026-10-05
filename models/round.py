"""Round model - one individual Codenames game inside a session."""

from extensions import db
from models.constants import RoundStatus, Team, utcnow


class Round(db.Model):
    __tablename__ = "rounds"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("game_sessions.id"), nullable=False, index=True
    )
    round_number = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(
        db.String(16), nullable=False, default=RoundStatus.SETUP, index=True
    )
    captain_player_id = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=True
    )
    current_team = db.Column(db.String(8), nullable=False, default=Team.RED)
    board_size = db.Column(db.Integer, nullable=False, default=5)
    word_mode = db.Column(db.String(16), nullable=False, default="NORMAL")

    timer_duration = db.Column(db.Integer, nullable=False, default=180)
    timer_started_at = db.Column(db.DateTime, nullable=True)
    timer_paused_at = db.Column(db.DateTime, nullable=True)

    red_score = db.Column(db.Integer, nullable=False, default=0)
    blue_score = db.Column(db.Integer, nullable=False, default=0)
    winner = db.Column(db.String(8), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    captain = db.relationship("SessionPlayer", foreign_keys=[captain_player_id])
    cards = db.relationship(
        "RoundCard", backref="round", lazy="select",
        order_by="RoundCard.position", cascade="all, delete-orphan",
    )
    round_players = db.relationship(
        "RoundPlayer", backref="round", lazy="select", cascade="all, delete-orphan"
    )
    guesses = db.relationship(
        "Guess", backref="round", lazy="select", cascade="all, delete-orphan"
    )

    # ------------------------------------------------------------- helpers
    def players_for(self, team: str):
        return [rp for rp in self.round_players if rp.team == team]

    def captain_for(self, team: str):
        for rp in self.round_players:
            if rp.team == team and rp.role == "CAPTAIN":
                return rp
        return None

    def remaining(self, team: str) -> int:
        """Cards of ``team`` colour that are not revealed yet."""
        return sum(
            1 for c in self.cards if c.card_type == team and not c.is_revealed
        )

    def total_for(self, team: str) -> int:
        return sum(1 for c in self.cards if c.card_type == team)

    @property
    def is_live(self) -> bool:
        return self.status in (RoundStatus.ACTIVE, RoundStatus.PAUSED)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Round #{self.round_number} session={self.session_id} {self.status}>"
