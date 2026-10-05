"""Round card model - one cell on the board."""

from extensions import db
from models.constants import CardType


class RoundCard(db.Model):
    __tablename__ = "round_cards"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=False, index=True
    )
    position = db.Column(db.Integer, nullable=False)
    word = db.Column(db.String(64), nullable=False)
    card_type = db.Column(db.String(16), nullable=False, default=CardType.NEUTRAL)
    is_revealed = db.Column(db.Boolean, nullable=False, default=False)
    revealed_at = db.Column(db.DateTime, nullable=True)
    revealed_by = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=True
    )

    __table_args__ = (
        db.UniqueConstraint("round_id", "position", name="uq_card_position"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RoundCard {self.word} {self.card_type} rev={self.is_revealed}>"
