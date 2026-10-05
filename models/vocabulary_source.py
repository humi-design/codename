"""Vocabulary source registry.

Tracks the configured/known vocabulary sources together with their license and
attribution information, so the Super Admin can see where data came from and
what its redistribution terms are.  No dataset is scraped in violation of its
terms - sources are official downloadable datasets or user-provided files.
"""

from extensions import db
from models.constants import utcnow


class VocabularySource(db.Model):
    __tablename__ = "vocabulary_sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True, index=True)
    kind = db.Column(db.String(32), nullable=False, default="file")
    description = db.Column(db.Text, nullable=True)
    license_name = db.Column(db.String(128), nullable=True)
    license_url = db.Column(db.String(512), nullable=True)
    homepage_url = db.Column(db.String(512), nullable=True)
    dataset_url = db.Column(db.String(512), nullable=True)
    attribution = db.Column(db.Text, nullable=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    word_count = db.Column(db.BigInteger, nullable=False, default=0)
    last_imported_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VocabularySource {self.name}>"
