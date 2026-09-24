from datetime import timezone
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS

db = SQLAlchemy()
bcrypt = Bcrypt()
cors = CORS()


def iso_utc(value):
    """Serialise a stored timestamp for the browser, marked as UTC.

    Every datetime in this app is written with datetime.utcnow(), so it is UTC
    but carries no tzinfo. isoformat() on that produces "2026-09-24T12:29:36",
    and JavaScript parses a date-time string with no timezone marker as LOCAL
    time. A teacher in UTC+8 therefore saw every timestamp shifted eight hours
    into the past, and a plan they had just saved reported itself as edited
    eight hours ago. The offset in the error was exactly their own.

    Appending the marker is the whole fix. An already-aware value is converted
    rather than assumed, so this stays correct if any column ever starts storing
    tz-aware datetimes.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + "Z"
