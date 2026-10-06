import os
import re
from datetime import datetime

from flask import Blueprint, current_app, request, jsonify, send_file

from extensions import db
from models.announcement import Announcement, ANNOUNCEMENT_TYPES
from models.section import Section, SectionMembership
from models.user import User
from routes.auth_routes import login_required, admin_required, current_user
from services.notify import notify_many

announcement_bp = Blueprint("announcements", __name__)

# A tutorial video arrives in chunks: gunicorn stops any one request after
# 120 s, which a single large upload over a school connection would outlast.
MAX_VIDEO_BYTES = 500 * 1024 * 1024
_UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _video_kind(head):
    """"mp4" or "webm" from a file's first bytes, or None for anything else:
    the extension a browser reports is not trusted."""
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def _video_dir():
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "videos")
    os.makedirs(os.path.join(folder, "tmp"), exist_ok=True)
    return folder


def _remove_video(announcement):
    if announcement.video_path and os.path.isfile(announcement.video_path):
        os.remove(announcement.video_path)
    announcement.video_path = announcement.video_name = announcement.video_size = None


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
    _remove_video(announcement)
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
    _remove_video(announcement)
    db.session.delete(announcement)
    db.session.commit()
    return jsonify({"status": "ok"})


# ---- A tutorial video on an announcement ----

def _bad_upload(part, message):
    for path in (part, part + ".n"):
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"status": "error", "message": message}), 400


@announcement_bp.post("/admin/announcements/<int:announcement_id>/video/chunks")
@admin_required
def admin_upload_video_chunk(announcement_id):
    """One chunk of a video, in order. The last one is checked (a real MP4 or
    WebM, within the size limit) and then becomes the announcement's video,
    replacing any earlier one. A bad upload leaves nothing behind."""
    announcement = Announcement.query.get_or_404(announcement_id)
    upload_id = request.form.get("upload_id") or ""
    chunk = request.files.get("chunk")
    try:
        index = int(request.form.get("index", ""))
        total = int(request.form.get("total", ""))
    except ValueError:
        index = total = -1
    if not _UPLOAD_ID_RE.match(upload_id) or chunk is None or total < 1 or not 0 <= index < total:
        return jsonify({"status": "error", "message": "That upload didn't arrive properly. Try again."}), 400

    folder = _video_dir()
    part = os.path.join(folder, "tmp", f"{announcement_id}-{upload_id}.part")
    received = 0
    if index > 0 and os.path.exists(part + ".n"):
        with open(part + ".n") as fh:
            received = int(fh.read() or 0)
    if index != received:
        return _bad_upload(part, "Parts of the video arrived out of order. Try the upload again.")

    data = chunk.read()
    if (os.path.getsize(part) if index > 0 and os.path.exists(part) else 0) + len(data) > MAX_VIDEO_BYTES:
        return _bad_upload(part, f"Videos can be up to {MAX_VIDEO_BYTES // (1024 * 1024)} MB.")
    with open(part, "ab" if index > 0 else "wb") as fh:
        fh.write(data)
    with open(part + ".n", "w") as fh:
        fh.write(str(index + 1))

    if index < total - 1:
        return jsonify({"status": "ok", "received": index + 1})

    with open(part, "rb") as fh:
        kind = _video_kind(fh.read(12))
    if kind is None:
        return _bad_upload(part, "That file isn't an MP4 or WebM video.")
    os.remove(part + ".n")
    dest = os.path.join(folder, f"announcement-{announcement.id}.{kind}")
    if announcement.video_path and announcement.video_path != dest and os.path.isfile(announcement.video_path):
        os.remove(announcement.video_path)
    os.replace(part, dest)
    announcement.video_path = dest
    announcement.video_name = (request.form.get("filename") or f"video.{kind}")[:255]
    announcement.video_size = os.path.getsize(dest)
    db.session.commit()
    return jsonify({"status": "ok", "announcement": announcement.to_dict()})


@announcement_bp.delete("/admin/announcements/<int:announcement_id>/video")
@admin_required
def admin_delete_video(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    _remove_video(announcement)
    db.session.commit()
    return jsonify({"status": "ok", "announcement": announcement.to_dict()})


@announcement_bp.get("/announcements/<int:announcement_id>/video")
@login_required
def watch_video(announcement_id):
    """The video, for whoever the announcement reaches. conditional=True
    answers Range requests, so the player can seek without downloading it all."""
    user = current_user()
    announcement = Announcement.query.get_or_404(announcement_id)
    allowed = (user.role == "admin" or announcement.author_id == user.id
               or announcement.section_id is None
               or announcement.section_id in _visible_section_ids(user))
    if not allowed or not announcement.video_path or not os.path.isfile(announcement.video_path):
        return jsonify({"status": "error", "message": "Video not found."}), 404
    return send_file(announcement.video_path, conditional=True)
