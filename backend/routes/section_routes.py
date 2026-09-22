from flask import Blueprint, request, jsonify

from extensions import db
from models.section import Section, SectionMembership, generate_join_code
from models.lesson_plan import LessonPlan
from routes.auth_routes import login_required, current_user

section_bp = Blueprint("sections", __name__)


def _unique_join_code():
    code = generate_join_code()
    while Section.query.filter_by(join_code=code).first():
        code = generate_join_code()
    return code


def _teacher_owned_section_or_error(section_id, user):
    section = Section.query.get(section_id)
    if not section:
        return None, (jsonify({"status": "error", "message": "Section not found."}), 404)
    if section.teacher_id != user.id:
        return None, (
            jsonify({"status": "error", "message": "You don't have access to this section."}),
            403,
        )
    return section, None


@section_bp.post("/sections")
@login_required
def create_section():
    user = current_user()
    if user.role != "teacher":
        return jsonify({"status": "error", "message": "Only teacher accounts can create sections."}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Section name is required."}), 400

    section = Section(
        teacher_id=user.id,
        name=name,
        subject=(data.get("subject") or "").strip() or None,
        grade_level=(data.get("grade_level") or "").strip() or None,
        join_code=_unique_join_code(),
    )
    db.session.add(section)
    db.session.commit()

    return jsonify({"status": "ok", "section": section.to_dict()}), 201


@section_bp.get("/sections")
@login_required
def list_sections():
    user = current_user()

    # A section the admin archived drops out of both lists: the teacher stops
    # seeing it among their classes and the student stops seeing it among
    # theirs. Nothing is deleted, so restoring it brings both views back.
    if user.role == "teacher":
        sections = (
            Section.query.filter_by(teacher_id=user.id, is_active=True)
            .order_by(Section.created_at.desc())
            .all()
        )
        return jsonify({"status": "ok", "sections": [s.to_dict() for s in sections]})

    memberships = (
        SectionMembership.query.filter_by(student_id=user.id)
        .join(Section)
        .filter(Section.is_active.is_(True))
        .order_by(Section.created_at.desc())
        .all()
    )
    return jsonify({"status": "ok", "sections": [m.section.to_dict() for m in memberships]})


@section_bp.get("/sections/<int:section_id>")
@login_required
def get_section(section_id):
    user = current_user()
    section = Section.query.get_or_404(section_id)

    if user.role == "teacher":
        if section.teacher_id != user.id:
            return jsonify({"status": "error", "message": "You don't have access to this section."}), 403
        data = section.to_dict()
        data["students"] = [m.to_dict() for m in section.memberships]
        return jsonify({"status": "ok", "section": data})

    membership = SectionMembership.query.filter_by(section_id=section.id, student_id=user.id).first()
    if not membership:
        return jsonify({"status": "error", "message": "You haven't joined this class."}), 403
    return jsonify({"status": "ok", "section": section.to_dict(include_counts=False)})


@section_bp.post("/sections/<int:section_id>/regenerate-code")
@login_required
def regenerate_code(section_id):
    user = current_user()
    section, err = _teacher_owned_section_or_error(section_id, user)
    if err:
        return err
    section.join_code = _unique_join_code()
    db.session.commit()
    return jsonify({"status": "ok", "section": section.to_dict()})


@section_bp.patch("/sections/<int:section_id>")
@login_required
def update_section(section_id):
    user = current_user()
    section, err = _teacher_owned_section_or_error(section_id, user)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "message": "Section name is required."}), 400
        section.name = name
    if "subject" in data:
        section.subject = (data.get("subject") or "").strip() or None
    if "grade_level" in data:
        section.grade_level = (data.get("grade_level") or "").strip() or None

    db.session.commit()
    return jsonify({"status": "ok", "section": section.to_dict()})


@section_bp.delete("/sections/<int:section_id>")
@login_required
def delete_section(section_id):
    user = current_user()
    section, err = _teacher_owned_section_or_error(section_id, user)
    if err:
        return err
    db.session.delete(section)
    db.session.commit()
    return jsonify({"status": "ok"})


@section_bp.delete("/sections/<int:section_id>/students/<int:student_id>")
@login_required
def remove_student(section_id, student_id):
    user = current_user()
    section, err = _teacher_owned_section_or_error(section_id, user)
    if err:
        return err
    membership = SectionMembership.query.filter_by(
        section_id=section_id, student_id=student_id
    ).first()
    if not membership:
        return jsonify({"status": "error", "message": "That student isn't in this class."}), 404
    db.session.delete(membership)
    db.session.commit()
    return jsonify({"status": "ok"})


@section_bp.get("/sections/<int:section_id>/submissions")
@login_required
def list_submissions(section_id):
    user = current_user()
    section, err = _teacher_owned_section_or_error(section_id, user)
    if err:
        return err

    status_filter = request.args.get("status")
    query = LessonPlan.query.filter(
        LessonPlan.section_id == section_id,
        LessonPlan.status.in_(["submitted", "reviewed"]),
    )
    if status_filter:
        query = query.filter(LessonPlan.status == status_filter)

    plans = query.order_by(LessonPlan.submitted_at.desc()).all()
    return jsonify({"status": "ok", "lesson_plans": [p.to_dict() for p in plans]})


# ---- Student-facing endpoints ----

@section_bp.post("/sections/join")
@login_required
def join_section():
    user = current_user()
    if user.role != "student":
        return jsonify({"status": "error", "message": "Only student accounts can join a class."}), 403

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"status": "error", "message": "Enter a class code."}), 400

    section = Section.query.filter_by(join_code=code).first()
    if not section:
        return jsonify({"status": "error", "message": "No class found with that code."}), 404
    if not section.is_active:
        # Deliberately the same wording as a code that matches nothing, so the
        # code of an archived class can't be probed for existence.
        return jsonify({"status": "error", "message": "No class found with that code."}), 404

    existing = SectionMembership.query.filter_by(section_id=section.id, student_id=user.id).first()
    if existing:
        return jsonify({"status": "error", "message": "You've already joined this class."}), 409

    membership = SectionMembership(section_id=section.id, student_id=user.id)
    db.session.add(membership)
    db.session.commit()

    return jsonify({"status": "ok", "section": section.to_dict(include_counts=False)}), 201


@section_bp.delete("/sections/<int:section_id>/leave")
@login_required
def leave_section(section_id):
    user = current_user()
    membership = SectionMembership.query.filter_by(section_id=section_id, student_id=user.id).first()
    if not membership:
        return jsonify({"status": "error", "message": "You're not in this class."}), 404
    db.session.delete(membership)
    db.session.commit()
    return jsonify({"status": "ok"})
