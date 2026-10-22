from datetime import datetime

from sqlalchemy.dialects.mysql import MEDIUMTEXT

from extensions import db, iso_utc

class CourseGuide(db.Model):

    __tablename__ = "course_guides"

    id = db.Column(db.Integer, primary_key=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_hash = db.Column(db.String(64), index=True)  # sha256 of file bytes, used to dedupe uploads
    # MEDIUMTEXT on MySQL, whose TEXT stops at 64 KB; see app._widen_course_guide_text.
    extracted_text = db.Column(db.Text().with_variant(MEDIUMTEXT(), "mysql"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Official DepEd documents shipped in backend/builtin/course_guides and
    # seeded on startup (services/builtins). Read-only, and listed first.
    is_builtin = db.Column(db.Boolean, nullable=False, default=False)
    builtin_key = db.Column(db.String(64))
    doc_type = db.Column(db.String(20))  # "budget_of_work" or "curriculum_guide"
    grade_band = db.Column(db.String(20))  # "4-6", "7-8", "9-10", "SHS", or several comma-separated
    grades = db.Column(db.String(20))  # the exact grades covered, e.g. "9-10"
    curriculum = db.Column(db.String(20))  # "MATATAG" or "K to 12"
    source_url = db.Column(db.String(500))
    retrieved_at = db.Column(db.Date)

    uploader = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "title": self.title,
            "uploaded_by": self.uploader.full_name if self.uploader else None,
            "created_at": iso_utc(self.created_at),
            "is_builtin": bool(self.is_builtin),
            "doc_type": self.doc_type,
            "grade_band": self.grade_band,
            "grades": self.grades,
            "curriculum": self.curriculum,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
        }
