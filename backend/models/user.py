import os
from datetime import datetime

from extensions import db, bcrypt, iso_utc


def _versioned(url, path):
    """The picture's address plus the file's modified time: a new upload
    overwrites the same file, and without a new address the browser keeps
    showing its cached copy of the old picture."""
    try:
        return f"{url}?v={os.stat(path).st_mtime_ns}"
    except OSError:
        return url

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # admin | teacher | student
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    avatar_path = db.Column(db.String(255))
    banner_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # When the owl's first-sign-in tour was finished or skipped; blank means a
    # new account that hasn't seen it yet.
    onboarded_at = db.Column(db.DateTime, nullable=True)

    formats = db.relationship("LessonPlanFormat", backref="owner", lazy=True)
    lesson_plans = db.relationship("LessonPlan", backref="user", lazy=True)

    def set_password(self, raw_password):
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8")

    def check_password(self, raw_password):
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    def effective_banner(self):
        """A teacher sees their own dashboard banner. A student sees the banner of
        the teacher whose section they most recently joined, so joining a class
        immediately re-skins the student's dashboard to match that teacher —
        with no separate sync step needed since this is resolved fresh on every
        read instead of copied onto the student's own row."""
        if self.role == "teacher":
            return self if self.banner_path else None

        if self.role == "student":
            membership = max(self.section_memberships, key=lambda m: m.joined_at, default=None)
            teacher = membership.section.teacher if membership else None
            return teacher if teacher and teacher.banner_path else None

        return None

    def to_dict(self):
        banner_owner = self.effective_banner()
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "avatar_url": _versioned(f"/api/avatars/{self.id}", self.avatar_path) if self.avatar_path else None,
            "banner_url": _versioned(f"/api/banners/{banner_owner.id}", banner_owner.banner_path) if banner_owner else None,
            "created_at": iso_utc(self.created_at),
            "onboarded": self.onboarded_at is not None,
        }
