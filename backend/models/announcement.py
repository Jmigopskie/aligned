from datetime import datetime

from extensions import db

ANNOUNCEMENT_TYPES = ("info", "maintenance", "urgent")


class Announcement(db.Model):
    """A notice posted by an admin (always system-wide) or a teacher (either
    system-wide or scoped to one of their own sections), e.g. a heads-up
    that the platform will be down, or a note to one class. Shown as a
    banner to whoever it reaches (every signed-in user when section_id is
    blank, or just that section's teacher/students otherwise) while active."""

    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), nullable=False, default="info")  # info | maintenance | urgent

    # Blank means "everyone signed in" (the only option for an admin post).
    # A teacher may instead scope their announcement to one section they own.
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=True)

    # A manual switch plus an optional scheduling window. An announcement is
    # only shown while is_active is true AND the current time falls inside
    # [starts_at, ends_at] (either bound may be left blank).
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User")
    section = db.relationship("Section")

    def is_currently_active(self, now=None):
        now = now or datetime.utcnow()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    def to_dict(self):
        return {
            "id": self.id,
            "author_id": self.author_id,
            "author_name": self.author.full_name if self.author else None,
            "title": self.title,
            "message": self.message,
            "type": self.type,
            "section_id": self.section_id,
            "section_name": self.section.name if self.section else None,
            "is_active": self.is_active,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
