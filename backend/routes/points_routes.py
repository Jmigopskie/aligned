"""Points: teachers allot them to their students; having Alan write a lesson
plan (Building Proficiency) costs a student BUILD_COST, once per plan. Guided
is free (models/points.py)."""
from flask import Blueprint, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.lesson_plan import LessonPlan
from models.points import BUILD_COST, POINTS_STARTED_UTC, Build, PointEvent
from models.section import Section, SectionMembership
from models.user import User
from routes.auth_routes import current_user, enrollment_required, login_required

points_bp = Blueprint("points", __name__)

NO_POINTS_MESSAGE = (f"Having Alan write a lesson plan uses {BUILD_COST} points, and you don't have enough. "
                     "Ask your teacher for more points, or write it with Alan in Guided mode, which is free.")


def _run_key(data):
    key = str((data or {}).get("run_key") or "").strip()
    return key[:64] if key else ""


def _own_plan(user, data):
    plan_id = (data or {}).get("plan_id")
    if not isinstance(plan_id, int) or isinstance(plan_id, bool):
        return None
    return LessonPlan.query.filter_by(id=plan_id, user_id=user.id).first()


def _plan_paid(plan):
    """A saved plan Alan may write for free: it carries its build, or it was
    saved before points existed."""
    return plan.build_id is not None or (plan.created_at is not None and plan.created_at < POINTS_STARTED_UTC)


def paid_build(user, data):
    """True when Alan may write this plan for the student: its run key was
    paid for, or the saved plan is (see _plan_paid). Teachers and admins
    always may."""
    if user.role != "student":
        return True
    plan = _own_plan(user, data)
    if plan and _plan_paid(plan):
        return True
    key = _run_key(data)
    return bool(key) and Build.query.filter_by(student_id=user.id, run_key=key).first() is not None


def require_paid_build(user, data):
    """None when allowed; otherwise the 402 response to send."""
    if paid_build(user, data):
        return None
    return jsonify({"status": "error", "code": "no_points", "message": NO_POINTS_MESSAGE,
                    "points": user.points or 0, "cost": BUILD_COST}), 402


def build_for(user, data):
    """The student's paid build for this request's run, if any."""
    key = _run_key(data)
    if user.role != "student" or not key:
        return None
    return Build.query.filter_by(student_id=user.id, run_key=key).first()


@points_bp.post("/builds")
@login_required
@enrollment_required
def start_build():
    """Before Alan writes a plan. A student pays BUILD_COST the first time
    for a plan; the same run, a plan already paid for and a plan from before
    points existed are free. A saved plan (from Guided, which is free) is
    charged once and keeps the build. Teachers don't pay."""
    user = current_user()
    data = request.get_json(silent=True) or {}
    if user.role != "student":
        return jsonify({"status": "ok", "charged": False, "cost": 0})
    plan = _own_plan(user, data)
    if plan and _plan_paid(plan):
        return jsonify({"status": "ok", "charged": False, "points": user.points or 0, "cost": BUILD_COST})
    key = _run_key(data)
    if not key:
        return jsonify({"status": "error", "message": "This lesson plan has no run to charge."}), 400
    existing = Build.query.filter_by(student_id=user.id, run_key=key).first()
    if existing:
        if plan and plan.build_id is None:
            plan.build_id = existing.id
            db.session.commit()
        return jsonify({"status": "ok", "charged": False, "points": user.points or 0, "cost": BUILD_COST})

    # One atomic UPDATE, so two tabs (or a double click) can't both spend
    # the same points: the balance never goes below zero.
    taken = db.session.execute(
        text("UPDATE users SET points = points - :cost WHERE id = :id AND points >= :cost"),
        {"cost": BUILD_COST, "id": user.id},
    ).rowcount
    if not taken:
        db.session.rollback()
        return jsonify({"status": "error", "code": "no_points", "message": NO_POINTS_MESSAGE,
                        "points": user.points or 0, "cost": BUILD_COST}), 402
    build = Build(student_id=user.id, run_key=key, points=BUILD_COST)
    db.session.add(build)
    try:
        db.session.flush()
    except IntegrityError:
        # The same run started twice at once: the other request paid.
        db.session.rollback()
        return jsonify({"status": "ok", "charged": False, "points": User.query.get(user.id).points, "cost": BUILD_COST})
    db.session.add(PointEvent(student_id=user.id, delta=-BUILD_COST, reason="build", build_id=build.id))
    if plan:
        plan.build_id = build.id
    db.session.commit()
    db.session.refresh(user)
    return jsonify({"status": "ok", "charged": True, "points": user.points, "cost": BUILD_COST,
                    "build": build.to_dict()})


def _owned_section(section_id):
    user = current_user()
    section = Section.query.get(section_id)
    if not section or user.role not in ("teacher", "admin") or (user.role == "teacher" and section.teacher_id != user.id):
        return None, (jsonify({"status": "error", "message": "Only this section's teacher can manage its points."}), 403)
    return section, None


def _roster(section):
    rows = (db.session.query(User).join(SectionMembership, SectionMembership.student_id == User.id)
            .filter(SectionMembership.section_id == section.id).order_by(User.full_name).all())
    return jsonify({"status": "ok", "cost": BUILD_COST, "students": [
        {"id": u.id, "full_name": u.full_name, "email": u.email, "points": u.points or 0} for u in rows]})


@points_bp.get("/sections/<int:section_id>/points")
@login_required
def section_points(section_id):
    section, err = _owned_section(section_id)
    return err or _roster(section)


@points_bp.post("/sections/<int:section_id>/points")
@login_required
def give_points(section_id):
    """Add points to (or, with a negative amount, take them from) students in
    the teacher's own section. A balance never goes below zero."""
    section, err = _owned_section(section_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ids = data.get("student_ids")
    add = data.get("add")
    if not isinstance(ids, list) or not ids or not isinstance(add, int) or isinstance(add, bool) \
            or add == 0 or abs(add) > 10000:
        return jsonify({"status": "error", "message": "Pick at least one student and an amount of points."}), 400
    members = {m.student_id for m in SectionMembership.query.filter_by(section_id=section.id).all()}
    targets = [i for i in ids if isinstance(i, int) and i in members]
    if len(targets) != len(ids):
        return jsonify({"status": "error", "message": "Some of those students aren't in this section."}), 400
    teacher = current_user()
    for student in User.query.filter(User.id.in_(targets)).all():
        before = student.points or 0
        student.points = max(0, before + add)
        if student.points != before:
            db.session.add(PointEvent(student_id=student.id, delta=student.points - before,
                                      reason="grant", by_user_id=teacher.id))
    db.session.commit()
    return _roster(section)
