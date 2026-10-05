"""Guess model - a pending / resolved word guess."""

from extensions import db
from models.constants import GuessStatus, utcnow


class Guess(db.Model):
    __tablename__ = "guesses"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=False, index=True
    )
    player_id = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=False, index=True
    )
    card_id = db.Column(db.Integer, db.ForeignKey("round_cards.id"), nullable=True)
    word = db.Column(db.String(64), nullable=False)
    normalized_word = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(
        db.String(16), nullable=False, default=GuessStatus.PENDING, index=True
    )
    submitted_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(
        db.Integer, db.ForeignKey("session_players.id"), nullable=True
    )

    player = db.relationship("SessionPlayer", foreign_keys=[player_id])
    card = db.relationship("RoundCard", foreign_keys=[card_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Guess {self.word} {self.status}>"
