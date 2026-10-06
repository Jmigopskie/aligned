from flask import Blueprint, request, jsonify

import os

from extensions import db
from models.user import User
from models.section import Section, SectionMembership
from models.lesson_plan import LessonPlan
from models.course_guide import CourseGuide
from routes.auth_routes import admin_required, current_user

admin_bp = Blueprint("admin", __name__)

ALLOWED_ROLES = ("admin", "teacher", "student")


@admin_bp.get("/admin/stats")
@admin_required
def stats():
    return jsonify({
        "status": "ok",
        "stats": {
            "total_users": User.query.count(),
            "teachers": User.query.filter_by(role="teacher").count(),
            "students": User.query.filter_by(role="student").count(),
            "admins": User.query.filter_by(role="admin").count(),
            "sections": Section.query.count(),
            "lesson_plans": LessonPlan.query.count(),
            "course_guides": CourseGuide.query.count(),
            "submitted": LessonPlan.query.filter_by(status="submitted").count(),
            "reviewed": LessonPlan.query.filter_by(status="reviewed").count(),
        },
    })


# ---- User management ----

@admin_bp.get("/admin/users")
@admin_required
def list_users():
    role = request.args.get("role")
    q = (request.args.get("q") or "").strip().lower()
    # "Archived" is not a separate flag: an archived account is simply one
    # with is_active off, which auth_routes already refuses to log in. Adding
    # a second column would let the two drift apart, so the archive view is
    # just this filter over the state that already gates sign-in.
    active = request.args.get("active")

    query = User.query
    if role in ALLOWED_ROLES:
        query = query.filter_by(role=role)
    if active in ("0", "1"):
        query = query.filter_by(is_active=(active == "1"))
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.full_name.ilike(like), User.email.ilike(like)))

    users = query.order_by(User.created_at.desc()).all()
    return jsonify({"status": "ok", "users": [u.to_dict() for u in users]})


@admin_bp.post("/admin/users")
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "").strip().lower()

    if not full_name or not email or not password:
        return jsonify({"status": "error", "message": "Name, email, and password are required."}), 400
    if role not in ALLOWED_ROLES:
        return jsonify({"status": "error", "message": "Role must be admin, teacher, or student."}), 400
    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "Email is already registered."}), 409

    user = User(full_name=full_name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({"status": "ok", "user": user.to_dict()}), 201


@admin_bp.patch("/admin/users/<int:user_id>")
@admin_required
def update_user(user_id):
    acting_admin = current_user()
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if "full_name" in data:
        full_name = (data.get("full_name") or "").strip()
        if not full_name:
            return jsonify({"status": "error", "message": "Name can't be empty."}), 400
        user.full_name = full_name

    if "email" in data:
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"status": "error", "message": "Email can't be empty."}), 400
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user.id:
            return jsonify({"status": "error", "message": "Email is already registered."}), 409
        user.email = email

    if "role" in data:
        role = (data.get("role") or "").strip().lower()
        if role not in ALLOWED_ROLES:
            return jsonify({"status": "error", "message": "Role must be admin, teacher, or student."}), 400
        if user.id == acting_admin.id and role != "admin" and User.query.filter_by(role="admin").count() <= 1:
            return jsonify({"status": "error", "message": "You can't remove the last remaining admin."}), 400
        user.role = role

    if "is_active" in data:
        if user.id == acting_admin.id and not data.get("is_active"):
            return jsonify({"status": "error", "message": "You can't disable your own account."}), 400
        user.is_active = bool(data.get("is_active"))

    if "password" in data and data.get("password"):
        if len(data["password"]) < 8:
            return jsonify({"status": "error", "message": "Password must be at least 8 characters."}), 400
        user.set_password(data["password"])

    db.session.commit()
    return jsonify({"status": "ok", "user": user.to_dict()})


@admin_bp.delete("/admin/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    acting_admin = current_user()
    user = User.query.get_or_404(user_id)

    if user.id == acting_admin.id:
        return jsonify({"status": "error", "message": "You can't delete your own account."}), 400
    if user.role == "admin" and User.query.filter_by(role="admin").count() <= 1:
        return jsonify({"status": "error", "message": "You can't delete the last remaining admin."}), 400

    # The built-in formats and guides need an owner (both foreign keys are
    # NOT NULL) and are seeded under the first admin, so they pass to the
    # admin doing the deleting instead of blocking the delete.
    from models.course_guide import CourseGuide
    from models.format import LessonPlanFormat
    LessonPlanFormat.query.filter_by(owner_id=user.id, is_builtin=True).update({"owner_id": acting_admin.id})
    CourseGuide.query.filter_by(uploader_id=user.id, is_builtin=True).update({"uploader_id": acting_admin.id})
    db.session.flush()
    db.session.expire(user)

    db.session.delete(user)
    db.session.commit()
    return jsonify({"status": "ok"})


# ---- Read-only oversight of sections & lesson plans ----

@admin_bp.get("/admin/sections")
@admin_required
def list_all_sections():
    """Every section across all teachers. Mirrors the filters on
    /admin/users so the archive view is the same list narrowed by
    is_active rather than a separate screen with its own query."""
    active = request.args.get("active")
    q = (request.args.get("q") or "").strip().lower()

    query = Section.query
    if active in ("0", "1"):
        query = query.filter_by(is_active=(active == "1"))
    if q:
        like = f"%{q}%"
        query = query.join(User, Section.teacher_id == User.id).filter(
            db.or_(
                Section.name.ilike(like),
                Section.subject.ilike(like),
                Section.grade_level.ilike(like),
                User.full_name.ilike(like),
            )
        )

    sections = query.order_by(Section.created_at.desc()).all()
    return jsonify({"status": "ok", "sections": [s.to_dict() for s in sections]})


# ---- Bulk archive / restore ----

# One request can only ever touch this many rows. Keeps a runaway or
# hand-edited request from rewriting the whole table in one go.
BULK_LIMIT = 500


def _bulk_archive_users(ids, is_active, acting_admin):
    """Archive or restore accounts, refusing the two cases that would lock
    everyone out: an admin archiving themselves, and archiving the last
    active admin. Refusals are reported per id instead of failing the whole
    batch, so one bad pick doesn't discard a valid selection."""
    users = User.query.filter(User.id.in_(ids)).all()
    found = {u.id for u in users}
    skipped = [{"id": i, "reason": "That account no longer exists."} for i in ids if i not in found]

    # Counted once up front, then decremented as admins in this batch are
    # archived, so archiving several admins at once can't slip past the check
    # by each one individually seeing the others as still active.
    active_admins = User.query.filter_by(role="admin", is_active=True).count()

    updated = []
    for user in users:
        if user.is_active == is_active:
            continue  # already in the requested state; nothing to do
        if not is_active:
            if user.id == acting_admin.id:
                skipped.append({"id": user.id, "reason": "You can't archive your own account."})
                continue
            if user.role == "admin" and active_admins <= 1:
                skipped.append({"id": user.id, "reason": "You can't archive the last active admin."})
                continue
            if user.role == "admin":
                active_admins -= 1
        elif user.role == "admin":
            active_admins += 1
        user.is_active = is_active
        updated.append(user.id)

    return updated, skipped


def _bulk_archive_sections(ids, is_active):
    """Archive or restore sections. A section keeps its students, lesson
    plans and submissions either way — archiving only takes it out of the
    active lists and stops new students joining by code."""
    sections = Section.query.filter(Section.id.in_(ids)).all()
    found = {sec.id for sec in sections}
    skipped = [{"id": i, "reason": "That section no longer exists."} for i in ids if i not in found]

    updated = []
    for section in sections:
        if section.is_active == is_active:
            continue
        section.is_active = is_active
        updated.append(section.id)

    return updated, skipped


@admin_bp.post("/admin/bulk-archive")
@admin_required
def bulk_archive():
    """Archive or restore many accounts or sections in one request, so the
    admin can tick a batch instead of clicking through them one at a time.

    Body: {"kind": "users"|"sections", "ids": [int, ...], "is_active": bool}
    Returns the ids actually changed plus a per-id reason for any the guards
    refused, so a partly-valid selection still applies and says what it left
    alone rather than silently dropping it."""
    acting_admin = current_user()
    data = request.get_json(silent=True) or {}

    kind = (data.get("kind") or "").strip().lower()
    if kind not in ("users", "sections"):
        return jsonify({"status": "error", "message": "Choose either accounts or sections."}), 400

    if "is_active" not in data:
        return jsonify({"status": "error", "message": "Say whether to archive or restore."}), 400
    is_active = bool(data.get("is_active"))

    raw_ids = data.get("ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"status": "error", "message": "Select at least one item first."}), 400
    if len(raw_ids) > BULK_LIMIT:
        return jsonify({
            "status": "error",
            "message": f"You can only archive {BULK_LIMIT} items at a time.",
        }), 400

    # Deduplicated so a repeated id can't be counted twice, and validated
    # here rather than trusted, since these go straight into an IN clause.
    ids, seen = [], set()
    for raw in raw_ids:
        if isinstance(raw, bool):
            return jsonify({"status": "error", "message": "Every id must be a whole number."}), 400
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Every id must be a whole number."}), 400
        if value not in seen:
            seen.add(value)
            ids.append(value)

    if kind == "users":
        updated, skipped = _bulk_archive_users(ids, is_active, acting_admin)
    else:
        updated, skipped = _bulk_archive_sections(ids, is_active)

    db.session.commit()

    return jsonify({
        "status": "ok",
        "kind": kind,
        "is_active": is_active,
        "updated": updated,
        "updated_count": len(updated),
        "skipped": skipped,
    })


@admin_bp.get("/admin/lesson-plans")
@admin_required
def list_all_lesson_plans():
    status_filter = request.args.get("status")
    query = LessonPlan.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    plans = query.order_by(LessonPlan.updated_at.desc()).limit(500).all()
    return jsonify({"status": "ok", "lesson_plans": [p.to_dict() for p in plans]})


@admin_bp.delete("/admin/lesson-plans/<int:plan_id>")
@admin_required
def admin_delete_lesson_plan(plan_id):
    """Admin cleanup: remove a lesson plan regardless of who created it —
    e.g. unused drafts or ones stuck in a broken/error state."""
    plan = LessonPlan.query.get_or_404(plan_id)

    docx_path = plan.docx_path
    db.session.delete(plan)
    db.session.commit()

    if docx_path and os.path.isfile(docx_path):
        try:
            os.remove(docx_path)
        except OSError:
            pass

    return jsonify({"status": "ok"})


@admin_bp.get("/admin/course-guides")
@admin_required
def list_all_course_guides():
    subject = (request.args.get("subject") or "").strip()
    query = CourseGuide.query
    if subject:
        query = query.filter(CourseGuide.subject.ilike(f"%{subject}%"))
    guides = query.order_by(CourseGuide.created_at.desc()).limit(500).all()
    return jsonify({"status": "ok", "course_guides": [g.to_dict() for g in guides]})
