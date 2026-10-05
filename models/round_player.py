"""Per-round player assignment (team + role can change every round)."""

from extensions import db
from models.constants import Role, Team


class RoundPlayer(db.Model):
    __tablename__ = "round_players"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=False, index=True
    )
    player_id = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=False, index=True
    )
    team = db.Column(db.String(8), nullable=False, default=Team.RED)
    role = db.Column(db.String(16), nullable=False, default=Role.PLAYER)

    __table_args__ = (
        db.UniqueConstraint("round_id", "player_id", name="uq_round_player"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RoundPlayer r={self.round_id} p={self.player_id} {self.team}/{self.role}>"
