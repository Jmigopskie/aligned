from datetime import datetime

from extensions import db


class SignupCode(db.Model):
    """A 6-digit code emailed to a @gsfe.tupcavite.edu.ph address before it
    can sign up (the same rules as PasswordReset: only the hash is kept, it
    expires, allows a few tries, and is spent once used or replaced)."""

    __tablename__ = "signup_codes"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used_at = db.Column(db.DateTime)
    # Who asked (the address the proxy saw), for the per-IP sending limit.
    ip = db.Column(db.String(45), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
