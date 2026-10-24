from datetime import datetime

from extensions import db


class PasswordReset(db.Model):
    """A 6-digit code emailed for "Forgot password?". Only its hash is kept;
    it expires, allows a few tries, and is spent once used or replaced."""

    __tablename__ = "password_resets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
