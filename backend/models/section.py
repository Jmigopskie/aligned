import secrets
import string
from datetime import datetime

from extensions import db, iso_utc

JOIN_CODE_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LENGTH = 6


def generate_join_code():
    """Generate a random, human-friendly class join code (e.g. 7K2QXB)."""
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


class Section(db.Model):
    __tablename__ = "sections"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(120))
    grade_level = db.Column(db.String(50))
    join_code = db.Column(db.String(10), nullable=False, unique=True)
    # Archiving a section is stored the same way as archiving an account
    # (User.is_active): the row and every submission linked to it are kept,
    # the section simply stops appearing in active lists and stops accepting
    # new joins. One flag rather than a separate archived_at column, so the
    # two can never drift apart.
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship("User", backref="sections_taught")
    memberships = db.relationship(
        "SectionMembership", backref="section", cascade="all, delete-orphan", lazy=True
    )
    lesson_plans = db.relationship("LessonPlan", backref="section", lazy=True)

    def to_dict(self, include_counts=True):
        data = {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "name": self.name,
            "subject": self.subject,
            "grade_level": self.grade_level,
            "join_code": self.join_code,
            "is_active": bool(self.is_active),
            "created_at": iso_utc(self.created_at),
        }
        if include_counts:
            data["student_count"] = len(self.memberships)
            data["pending_count"] = sum(
                1 for p in self.lesson_plans if p.status == "submitted"
            )
        return data


class SectionMembership(db.Model):
    __tablename__ = "section_memberships"

    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("User", backref="section_memberships")

    __table_args__ = (
        db.UniqueConstraint("section_id", "student_id", name="uq_section_student"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "section_id": self.section_id,
            "student_id": self.student_id,
            "student_name": self.student.full_name if self.student else None,
            "student_email": self.student.email if self.student else None,
            "joined_at": iso_utc(self.joined_at),
        }
