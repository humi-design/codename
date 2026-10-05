"""Vocabulary import history.

One row per import run so the Super Admin can see progress, results and
failures, and so an interrupted run can be resumed.
"""

from extensions import db
from models.constants import ImportStatus, utcnow


class VocabularyImport(db.Model):
    __tablename__ = "vocabulary_imports"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(64), nullable=False, index=True)
    # Human-friendly label, e.g. "Kaikki English", "custom upload".
    label = db.Column(db.String(255), nullable=True)
    status = db.Column(
        db.String(16), nullable=False, default=ImportStatus.QUEUED, index=True
    )
    mode = db.Column(db.String(16), nullable=False, default="initial")

    # Where the data came from.  ``path`` is the local file (if any),
    # ``dataset_url`` the remote source used to fetch it.
    path = db.Column(db.String(512), nullable=True)
    dataset_url = db.Column(db.String(512), nullable=True)

    # Resume support: byte offset already consumed in ``path``.
    resume_offset = db.Column(db.BigInteger, nullable=False, default=0)

    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    total_processed = db.Column(db.BigInteger, nullable=False, default=0)
    total_imported = db.Column(db.BigInteger, nullable=False, default=0)
    total_updated = db.Column(db.BigInteger, nullable=False, default=0)
    total_duplicates = db.Column(db.BigInteger, nullable=False, default=0)
    total_rejected = db.Column(db.BigInteger, nullable=False, default=0)
    total_errors = db.Column(db.BigInteger, nullable=False, default=0)

    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def is_running(self) -> bool:
        return self.status in (ImportStatus.QUEUED, ImportStatus.RUNNING)

    @property
    def accepted(self) -> int:
        return int(self.total_imported or 0) + int(self.total_updated or 0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VocabularyImport {self.source} {self.status}>"
