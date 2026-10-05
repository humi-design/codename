"""Word model - the local vocabulary used to build boards."""

from extensions import db
from models.constants import WordMode, utcnow


class Word(db.Model):
    __tablename__ = "words"

    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(64), nullable=False)
    normalized_word = db.Column(db.String(64), nullable=False, index=True)
    language = db.Column(db.String(8), nullable=False, default="en")
    part_of_speech = db.Column(db.String(32), nullable=True)
    definition = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(32), nullable=False, default="OTHER", index=True)
    difficulty = db.Column(db.String(16), nullable=False, default=WordMode.NORMAL, index=True)
    frequency_score = db.Column(db.Float, nullable=False, default=0.0, index=True)
    is_proper_noun = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(64), nullable=False, default="seed")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint("normalized_word", "language", name="uq_word_lang"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Word {self.word} ({self.difficulty})>"
