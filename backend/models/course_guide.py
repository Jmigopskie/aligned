from datetime import datetime

from extensions import db

class CourseGuide(db.Model):

    __tablename__ = "course_guides"

    id = db.Column(db.Integer, primary_key=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_hash = db.Column(db.String(64), index=True)  # sha256 of file bytes, used to dedupe uploads
    extracted_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploader = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "title": self.title,
            "uploaded_by": self.uploader.full_name if self.uploader else None,
            "created_at": self.created_at.isoformat(),
        }
