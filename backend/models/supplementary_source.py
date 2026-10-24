from datetime import datetime

from sqlalchemy.dialects.mysql import MEDIUMTEXT

from extensions import db, iso_utc


class SupplementarySource(db.Model):
    """A file a student uploads beside the Budget of Work in the Create Lesson
    Plan flow. Private to its uploader; Alan reads its text when writing."""

    __tablename__ = "supplementary_sources"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    extracted_text = db.Column(db.Text().with_variant(MEDIUMTEXT(), "mysql"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.filename, "created_at": iso_utc(self.created_at)}
