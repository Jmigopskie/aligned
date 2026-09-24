from datetime import datetime

from extensions import db, iso_utc


class Notification(db.Model):
    """A personal, in-app notification for one user — a submission landing in
    a teacher's inbox, a review coming back to a student, or a new
    announcement reaching its audience. Unlike an Announcement (a public
    banner everyone signed-in sees while it's active), a notification belongs
    to exactly one user and is read once, via the bell icon."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # submission | review | announcement
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255))  # relative page to open when clicked, e.g. "submissions.html"
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": iso_utc(self.created_at),
        }
