from datetime import datetime

from extensions import db, iso_utc


class ActivityLog(db.Model):
    """What a user did and when, for the admin (services/activity.py writes
    it). user_id is empty for a failed login; the email tried is in detail."""

    __tablename__ = "activity_logs"
    __table_args__ = (db.Index("ix_activity_user_time", "user_id", "created_at"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.String(255))
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else None,
            "user_email": self.user.email if self.user else None,
            "role": self.user.role if self.user else None,
            "action": self.action,
            "detail": self.detail,
            "ip": self.ip,
            "created_at": iso_utc(self.created_at),
        }
