from datetime import datetime

from flask import Blueprint, request, jsonify

from extensions import db
from models.announcement import Announcement, ANNOUNCEMENT_TYPES
from models.section import Section, SectionMembership
from models.user import User
from routes.auth_routes import login_required, admin_required, current_user
from services.notify import notify_many

announcement_bp = Blueprint("announcements", __name__)


def _parse_dt(value):
    """Parse an ISO datetime string from the client. Returns None for
    blank/absent values and raises ValueError for anything unparsable."""
    if not value:
        return None
    # Support the trailing "Z" some <input type="datetime-local"> / JS
    # Date#toISOString() values include.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _visible_section_ids(user):
    """Section-scoped announcements this user should ever see: the ones they
    teach, or the ones they've joined as a student."""
    if user.role == "teacher":
        return [s.id for s in Section.query.filter_by(teacher_id=user.id).all()]
    if user.role == "student":
        return [m.section_id for m in SectionMembership.query.filter_by(student_id=user.id).all()]
    return []


def _can_manage_announcement(user, announcement):
    return user.role == "admin" or announcement.author_id == user.id


def _notify_announcement_audience(announcement, current_user_id):
    """Alongside the banner, also drop a personal notification in the bell
    for everyone the announcement reaches, so it's still surfaced even after
    the banner itself has been dismissed."""
    if announcement.section_id:
        recipient_ids = [
            m.student_id for m in SectionMembership.query.filter_by(section_id=announcement.section_id).all()
        ]
    else:
        recipient_ids = [u.id for u in User.query.filter_by(is_active=True).all()]
    notify_many(
        recipient_ids,
        "announcement",
        f"New announcement: {announcement.title}",
        announcement.message[:200],
        exclude_id=current_user_id,
    )


# ---- Everyone signed in: what should show in the banner right now ----

@announcement_bp.get("/announcements/active")
@login_required
def list_active_announcements():
    user = current_user()
    now = datetime.utcnow()
    visible_section_ids = _visible_section_ids(user)
    candidates = Announcement.query.filter(
        db.or_(
            Announcement.section_id.is_(None),
            Announcement.section_id.in_(visible_section_ids),
        )
    ).filter_by(is_active=True).order_by(Announcement.created_at.desc()).all()
    active = [a for a in candidates if a.is_currently_active(now)]
    return jsonify({"status": "ok", "announcements": [a.to_dict() for a in active]})


# ---- Everyone signed in: their own announcements history/tab (not just the
# currently-active banner) — every system-wide post plus whatever section(s)
# they teach or belong to. Teachers additionally see their own posts here
# even if expired/inactive, so they can find and manage them. ----

@announcement_bp.get("/announcements/mine")
@login_required
def list_my_announcements():
    user = current_user()
    visible_section_ids = _visible_section_ids(user)
    announcements = Announcement.query.filter(
        db.or_(
            Announcement.section_id.is_(None),
            Announcement.section_id.in_(visible_section_ids),
            Announcement.author_id == user.id,
        )
    ).order_by(Announcement.created_at.desc()).all()
    return jsonify({"status": "ok", "announcements": [a.to_dict() for a in announcements]})


# ---- Teacher (and admin) self-service create/edit/delete — separate from
# the admin-only /admin/announcements below, which can manage anyone's post.
# A teacher may only post to "everyone" or to a section they own; an admin's
# post here is always system-wide, matching the admin console's behavior. ----

@announcement_bp.post("/announcements")
@login_required
def create_announcement():
    user = current_user()
    if user.role not in ("admin", "teacher"):
        return jsonify({"status": "error", "message": "Only teachers and admins can post announcements."}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    message = (data.get("message") or "").strip()
    ann_type = (data.get("type") or "info").strip().lower()
    section_id = data.get("section_id")

    if not title or not message:
        return jsonify({"status": "error", "message": "Title and message are required."}), 400
    if ann_type not in ANNOUNCEMENT_TYPES:
        return jsonify({"status": "error", "message": "Type must be info, maintenance, or urgent."}), 400

    if user.role == "admin":
        section_id = None
    elif section_id:
        section = Section.query.get(section_id)
        if not section or section.teacher_id != user.id:
            return jsonify({"status": "error", "message": "You can only post to a section you teach."}), 403
    else:
        section_id = None

    try:
        starts_at = _parse_dt(data.get("starts_at"))
        ends_at = _parse_dt(data.get("ends_at"))
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date/time format."}), 400
    if starts_at and ends_at and ends_at < starts_at:
        return jsonify({"status": "error", "message": "End time can't be before start time."}), 400

    announcement = Announcement(
        author_id=user.id,
        title=title,
        message=message,
        type=ann_type,
        section_id=section_id,
        is_active=bool(data.get("is_active", True)),
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.session.add(announcement)
    db.session.flush()
    _notify_announcement_audience(announcement, user.id)
    db.session.commit()

    return jsonify({"status": "ok", "announcement": announcement.to_dict()}), 201


@announcement_bp.patch("/announcements/<int:announcement_id>")
@login_required
def update_announcement(announcement_id):
    user = current_user()
    announcement = Announcement.query.get_or_404(announcement_id)
    if not _can_manage_announcement(user, announcement):
        return jsonify({"status": "error", "message": "You can only edit your own announcements."}), 403

    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"status": "error", "message": "Title can't be empty."}), 400
        announcement.title = title

    if "message" in data:
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"status": "error", "message": "Message can't be empty."}), 400
        announcement.message = message

    if "type" in data:
        ann_type = (data.get("type") or "").strip().lower()
        if ann_type not in ANNOUNCEMENT_TYPES:
            return jsonify({"status": "error", "message": "Type must be info, maintenance, or urgent."}), 400
        announcement.type = ann_type

    if "section_id" in data and user.role != "admin":
        section_id = data.get("section_id")
        if section_id:
            section = Section.query.get(section_id)
            if not section or section.teacher_id != user.id:
                return jsonify({"status": "error", "message": "You can only post to a section you teach."}), 403
            announcement.section_id = section_id
        else:
            announcement.section_id = None

    if "is_active" in data:
        announcement.is_active = bool(data.get("is_active"))

    if "starts_at" in data:
        try:
            announcement.starts_at = _parse_dt(data.get("starts_at"))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid start date/time."}), 400

    if "ends_at" in data:
        try:
            announcement.ends_at = _parse_dt(data.get("ends_at"))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid end date/time."}), 400

    if announcement.starts_at and announcement.ends_at and announcement.ends_at < announcement.starts_at:
        return jsonify({"status": "error", "message": "End time can't be before start time."}), 400

    db.session.commit()
    return jsonify({"status": "ok", "announcement": announcement.to_dict()})


@announcement_bp.delete("/announcements/<int:announcement_id>")
@login_required
def delete_announcement(announcement_id):
    user = current_user()
    announcement = Announcement.query.get_or_404(announcement_id)
    if not _can_manage_announcement(user, announcement):
        return jsonify({"status": "error", "message": "You can only delete your own announcements."}), 403
    db.session.delete(announcement)
    db.session.commit()
    return jsonify({"status": "ok"})


# ---- Admin management ----

@announcement_bp.get("/admin/announcements")
@admin_required
def admin_list_announcements():
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return jsonify({"status": "ok", "announcements": [a.to_dict() for a in announcements]})


@announcement_bp.post("/admin/announcements")
@admin_required
def admin_create_announcement():
    user = current_user()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    message = (data.get("message") or "").strip()
    ann_type = (data.get("type") or "info").strip().lower()

    if not title or not message:
        return jsonify({"status": "error", "message": "Title and message are required."}), 400
    if ann_type not in ANNOUNCEMENT_TYPES:
        return jsonify({"status": "error", "message": "Type must be info, maintenance, or urgent."}), 400

    try:
        starts_at = _parse_dt(data.get("starts_at"))
        ends_at = _parse_dt(data.get("ends_at"))
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date/time format."}), 400

    if starts_at and ends_at and ends_at < starts_at:
        return jsonify({"status": "error", "message": "End time can't be before start time."}), 400

    announcement = Announcement(
        author_id=user.id,
        title=title,
        message=message,
        type=ann_type,
        is_active=bool(data.get("is_active", True)),
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.session.add(announcement)
    db.session.flush()
    _notify_announcement_audience(announcement, user.id)
    db.session.commit()

    return jsonify({"status": "ok", "announcement": announcement.to_dict()}), 201


@announcement_bp.patch("/admin/announcements/<int:announcement_id>")
@admin_required
def admin_update_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"status": "error", "message": "Title can't be empty."}), 400
        announcement.title = title

    if "message" in data:
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"status": "error", "message": "Message can't be empty."}), 400
        announcement.message = message

    if "type" in data:
        ann_type = (data.get("type") or "").strip().lower()
        if ann_type not in ANNOUNCEMENT_TYPES:
            return jsonify({"status": "error", "message": "Type must be info, maintenance, or urgent."}), 400
        announcement.type = ann_type

    if "is_active" in data:
        announcement.is_active = bool(data.get("is_active"))

    if "starts_at" in data:
        try:
            announcement.starts_at = _parse_dt(data.get("starts_at"))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid start date/time."}), 400

    if "ends_at" in data:
        try:
            announcement.ends_at = _parse_dt(data.get("ends_at"))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid end date/time."}), 400

    if announcement.starts_at and announcement.ends_at and announcement.ends_at < announcement.starts_at:
        return jsonify({"status": "error", "message": "End time can't be before start time."}), 400

    db.session.commit()
    return jsonify({"status": "ok", "announcement": announcement.to_dict()})


@announcement_bp.delete("/admin/announcements/<int:announcement_id>")
@admin_required
def admin_delete_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    db.session.delete(announcement)
    db.session.commit()
    return jsonify({"status": "ok"})
