from flask import Blueprint, jsonify

from extensions import db
from models.notification import Notification
from routes.auth_routes import login_required, current_user

notification_bp = Blueprint("notifications", __name__)


@notification_bp.get("/notifications")
@login_required
def list_notifications():
    user = current_user()
    notifications = (
        Notification.query.filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return jsonify({
        "status": "ok",
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": unread_count,
    })


@notification_bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    user = current_user()
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != user.id:
        return jsonify({"status": "error", "message": "That's not your notification."}), 403
    notification.is_read = True
    db.session.commit()
    return jsonify({"status": "ok"})


@notification_bp.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    user = current_user()
    Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"status": "ok"})
