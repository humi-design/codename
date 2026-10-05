"""Word model - the local vocabulary used to build boards.

The table is the single production source of vocabulary.  External datasets
(Wiktionary/Kaikki, Wikidata, frequency lists, custom files) are only ever
loaded into it by the ingestion engine; gameplay reads from here and never
from a live external API.
"""

from extensions import db
from models.constants import Category, WordMode, utcnow


class Word(db.Model):
    __tablename__ = "words"

    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(128), nullable=False)
    normalized_word = db.Column(db.String(128), nullable=False, index=True)
    language = db.Column(db.String(8), nullable=False, default="en", index=True)
    part_of_speech = db.Column(db.String(32), nullable=True)
    definition = db.Column(db.Text, nullable=True)
    category = db.Column(
        db.String(32), nullable=False, default=Category.OTHER, index=True
    )
    difficulty = db.Column(
        db.String(16), nullable=False, default=WordMode.NORMAL, index=True
    )
    frequency_score = db.Column(db.Float, nullable=False, default=0.0, index=True)
    is_proper_noun = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_multiword = db.Column(db.Boolean, nullable=False, default=False, index=True)
    character_count = db.Column(db.Integer, nullable=False, default=0)
    source = db.Column(
        db.String(64), nullable=False, default="seed", index=True
    )
    source_id = db.Column(db.String(64), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("normalized_word", "language", name="uq_word_lang"),
        db.Index("ix_words_lang_active_diff", "language", "is_active", "difficulty"),
        db.Index("ix_words_lang_active_cat", "language", "is_active", "category"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Word {self.word} ({self.difficulty})>"
