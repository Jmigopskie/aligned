from extensions import db
from models.notification import Notification


def notify(user_id, notif_type, title, message, link=None):
    """Queue one notification for one user. Caller is responsible for
    committing (usually alongside whatever else it just changed)."""
    n = Notification(user_id=user_id, type=notif_type, title=title, message=message, link=link)
    db.session.add(n)
    return n


def notify_many(user_ids, notif_type, title, message, link=None, exclude_id=None):
    """Queue the same notification for a batch of users (e.g. everyone an
    announcement reaches), skipping duplicates and an optional excluded id
    (typically the author, who doesn't need to be told about their own post)."""
    for uid in {uid for uid in user_ids if uid != exclude_id}:
        notify(uid, notif_type, title, message, link)
