from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, Response, stream_with_context, current_app
import json

from extensions import db
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.course_guide import CourseGuide
from models.section import Section, SectionMembership
from routes.auth_routes import login_required, current_user
from services import ai_service, docx_service
from services.notify import notify

generate_bp = Blueprint("generate", __name__)


def _can_access_plan(user, plan):
    """A plan is visible to its author, to the teacher of the section it was
    submitted to, to any admin, or to anyone at all once the author has made
    it public."""
    if user.role == "admin":
        return True
    if plan.user_id == user.id:
        return True
    if plan.is_public:
        return True
    if user.role == "teacher" and plan.section_id:
        section = Section.query.get(plan.section_id)
        return bool(section and section.teacher_id == user.id)
    return False

def _resolve_course_guide(data):
    course_guide_id = data.get("course_guide_id")
    if not course_guide_id:
        return None, None

    guide = CourseGuide.query.get(course_guide_id)
    if not guide:
        return None, (jsonify({
            "status": "error",
            "message": "That course guide couldn't be found. Try searching again.",
        }), 404)
    return guide, None

def _build_context(data, guide):
    context = dict(data.get("context") or {})
    if data.get("teacher_name"):
        context["teacher_name"] = data["teacher_name"]
    if data.get("subject"):
        context["subject"] = data["subject"]
    if guide:
        context["course_guide_title"] = guide.title
    return context

def _include_keys(data, fmt):
    """The field_keys this request wants generated, or None for all of them.

    Validated against the format so an unknown key is dropped rather than
    reaching the prompt. An empty list is preserved as an empty list: it means
    "generate nothing", which is different from "generate everything".
    """
    raw = data.get("include_keys")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    valid = {f.field_key for f in fmt.fields}
    return [str(k) for k in raw if str(k) in valid]

@generate_bp.post("/generate/full")
@login_required
def generate_full():
    data = request.get_json(silent=True) or {}
    fmt = LessonPlanFormat.query.get_or_404(data.get("format_id"))

    guide, err = _resolve_course_guide(data)
    if err:
        return err

    context = _build_context(data, guide)
    course_guide_text = guide.extracted_text if guide else ""

    field_values = ai_service.generate_full(
        context, fmt.fields, course_guide_text=course_guide_text,
        include_keys=_include_keys(data, fmt),
    )
    return jsonify({"status": "ok", "field_values": field_values})

@generate_bp.post("/generate/full-stream")
@login_required
def generate_full_stream():
    data = request.get_json(silent=True) or {}
    fmt = LessonPlanFormat.query.get_or_404(data.get("format_id"))

    guide, err = _resolve_course_guide(data)
    if err:
        return err

    context = _build_context(data, guide)
    course_guide_text = guide.extracted_text if guide else ""
    fields = fmt.fields
    # Read here, not inside _stream(): the generator runs after the request
    # context is gone, so `request`/`data` can't be touched from inside it.
    include_keys = _include_keys(data, fmt)

    def _stream():
        try:
            for event in ai_service.generate_full_streaming(
                context, fields, course_guide_text=course_guide_text, include_keys=include_keys,
            ):
                yield json.dumps(event) + "\n"
        except Exception as exc:
            current_app.logger.exception("Streamed generation failed")
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return Response(stream_with_context(_stream()), mimetype="application/x-ndjson")

_CHAT_HISTORY_TURNS = 8
_CHAT_TEXT_LIMIT = 600


@generate_bp.post("/generate/chat")
@login_required
def owl_chat():
    """Guided mode: one turn of the teacher's chat with the owl about the
    field they're currently writing. The owl answers briefly and offers
    choices, some of which the page can insert straight into the field."""
    data = request.get_json(silent=True) or {}
    fmt = LessonPlanFormat.query.get_or_404(data.get("format_id"))
    field = next((f for f in fmt.fields if f.field_key == data.get("field_key")), None)
    if not field:
        return jsonify({"status": "error", "message": "That field isn't part of this format."}), 400

    message = str(data.get("message") or "").strip()[:_CHAT_TEXT_LIMIT]
    if not message:
        return jsonify({"status": "error", "message": "Type a question for the owl first."}), 400

    guide, err = _resolve_course_guide(data)
    if err:
        return err

    history = [
        {"role": "teacher" if t.get("role") == "teacher" else "owl", "text": str(t.get("text") or "")[:_CHAT_TEXT_LIMIT]}
        for t in (data.get("history") or [])[-_CHAT_HISTORY_TURNS:]
        if isinstance(t, dict) and str(t.get("text") or "").strip()
    ]
    context = _build_context(data, guide)
    course_guide_text = guide.extracted_text if guide else ""
    prior_values = data.get("prior_values") or {}

    answer = ai_service.owl_chat(context, field, prior_values, course_guide_text, history, message)
    return jsonify({"status": "ok", **answer})

@generate_bp.get("/lesson-plans")
@login_required
def list_lesson_plans():
    """The signed-in user's own plans, newest edit first. `status` narrows to
    one stage (the Create Lesson Plan page asks for status=draft to show
    unfinished work), and `limit` caps the list for that same preview strip so
    it doesn't fetch a teacher's entire history to show three cards."""
    user = current_user()
    query = LessonPlan.query.filter_by(user_id=user.id)

    status_filter = (request.args.get("status") or "").strip()
    if status_filter in ("draft", "submitted", "reviewed"):
        query = query.filter_by(status=status_filter)

    query = query.order_by(LessonPlan.updated_at.desc())

    try:
        limit = int(request.args.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit > 0:
        query = query.limit(min(limit, 100))

    return jsonify({"status": "ok", "lesson_plans": [p.to_dict() for p in query.all()]})


# Statuses whose content is settled: a student has handed the plan in, or a
# teacher has already graded it. Editing then would change what was assessed
# out from under the teacher, so the autosave is refused rather than silently
# rewriting a submission.
_LOCKED_STATUSES = ("submitted", "reviewed")


@generate_bp.patch("/lesson-plans/<int:plan_id>")
@login_required
def update_lesson_plan(plan_id):
    """Owner-only update of a plan already saved, which is what makes the
    generator's autosave possible: the first edit creates the row via POST and
    every edit after it comes back here, so an unfinished plan keeps one draft
    row instead of piling up a new one per save."""
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if plan.user_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403

    if plan.status in _LOCKED_STATUSES:
        return jsonify({
            "status": "error",
            "message": "This plan has already been submitted, so it can no longer be edited.",
        }), 409

    data = request.get_json(silent=True) or {}

    # Only the fields actually present are touched, so an autosave carrying
    # just the field values can't blank out the title alongside them.
    if "title" in data:
        title = (data.get("title") or "").strip()
        plan.title = title or "Untitled Lesson Plan"
    for attr in ("subject", "grade_level", "quarter", "date", "generation_mode"):
        if attr in data:
            setattr(plan, attr, data.get(attr))
    if "section_id" in data:
        plan.section_id = data.get("section_id")
    if "is_public" in data:
        plan.is_public = bool(data.get("is_public"))
    if "field_values" in data:
        plan.set_values(data.get("field_values") or {})
    if "rich_field_values" in data:
        plan.set_rich_values(data.get("rich_field_values") or {})
    if "mode_values" in data:
        plan.set_mode_values(data.get("mode_values") or {})
    # Key presence, not truthiness: an autosave carrying only field values must
    # not wipe the setup step the teacher already filled in.
    if "setup_context" in data:
        plan.set_setup_context(data.get("setup_context") or {})
    if "doc_edits" in data:
        plan.set_doc_edits(data.get("doc_edits") or [])

    db.session.commit()
    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()})

@generate_bp.post("/lesson-plans")
@login_required
def save_lesson_plan():
    user = current_user()
    data = request.get_json(silent=True) or {}

    plan = LessonPlan(
        user_id=user.id,
        format_id=data.get("format_id"),
        title=data.get("title", "Untitled Lesson Plan"),
        subject=data.get("subject"),
        grade_level=data.get("grade_level"),
        quarter=data.get("quarter"),
        date=data.get("date"),
        generation_mode=data.get("generation_mode", "full"),
        section_id=data.get("section_id"),
        is_public=bool(data.get("is_public")),
    )
    plan.set_values(data.get("field_values") or {})
    plan.set_rich_values(data.get("rich_field_values") or {})
    plan.set_mode_values(data.get("mode_values") or {})
    plan.set_setup_context(data.get("setup_context") or {})
    plan.set_doc_edits(data.get("doc_edits") or [])

    db.session.add(plan)
    db.session.commit()

    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()}), 201

@generate_bp.get("/lesson-plans/public")
@login_required
def list_public_lesson_plans():
    """Every logged-in user can browse plans any author has chosen to
    share, regardless of who wrote them."""
    plans = (
        LessonPlan.query.filter_by(is_public=True)
        .order_by(LessonPlan.updated_at.desc())
        .all()
    )
    return jsonify({"status": "ok", "lesson_plans": [p.to_dict() for p in plans]})

@generate_bp.patch("/lesson-plans/<int:plan_id>/visibility")
@login_required
def set_lesson_plan_visibility(plan_id):
    """Owner-only: share a lesson plan publicly, or make it private again."""
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if plan.user_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403

    data = request.get_json(silent=True) or {}
    plan.is_public = bool(data.get("is_public"))
    db.session.commit()

    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()})

@generate_bp.get("/lesson-plans/<int:plan_id>")
@login_required
def get_lesson_plan(plan_id):
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if not _can_access_plan(user, plan):
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403
    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()})

@generate_bp.delete("/lesson-plans/<int:plan_id>")
@login_required
def delete_lesson_plan(plan_id):
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if plan.user_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403
    db.session.delete(plan)
    db.session.commit()
    return jsonify({"status": "ok"})

@generate_bp.get("/lesson-plans/<int:plan_id>/export")
@login_required
def export_lesson_plan(plan_id):
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if not _can_access_plan(user, plan):
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403

    fmt = LessonPlanFormat.query.get_or_404(plan.format_id)

    path = docx_service.export_lesson_plan(plan, fmt)
    plan.docx_path = path
    db.session.commit()

    return send_file(path, as_attachment=True)

@generate_bp.post("/lesson-plans/<int:plan_id>/submit")
@login_required
def submit_lesson_plan(plan_id):
    """Student: send a lesson plan to their teacher via a joined section."""
    user = current_user()
    plan = LessonPlan.query.get_or_404(plan_id)
    if plan.user_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this lesson plan."}), 403

    data = request.get_json(silent=True) or {}
    section_id = data.get("section_id") or plan.section_id
    if not section_id:
        return jsonify({"status": "error", "message": "Choose a class to submit this to."}), 400

    membership = SectionMembership.query.filter_by(section_id=section_id, student_id=user.id).first()
    if not membership:
        return jsonify({"status": "error", "message": "You haven't joined that class."}), 403

    # An archived class stops accepting work. Checked here as well as in the
    # section listing, because a stale page could still hold its id.
    target_section = Section.query.get(section_id)
    if target_section and not target_section.is_active:
        return jsonify({
            "status": "error",
            "message": "That class has been archived, so it's no longer accepting submissions.",
        }), 409

    plan.section_id = section_id
    plan.status = "submitted"
    plan.submitted_at = datetime.utcnow()
    plan.teacher_feedback = None
    plan.score = None
    plan.reviewed_at = None

    section = Section.query.get(section_id)
    if section:
        notify(
            section.teacher_id,
            "submission",
            "New submission",
            f"{user.full_name} submitted \"{plan.title}\" to {section.name}.",
            link="submissions.html",
        )

    db.session.commit()

    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()})

@generate_bp.post("/lesson-plans/<int:plan_id>/review")
@login_required
def review_lesson_plan(plan_id):
    """Teacher: mark a submitted lesson plan reviewed, with a 0-100 score
    and optional feedback."""
    user = current_user()
    if user.role != "teacher":
        return jsonify({"status": "error", "message": "Only teachers can review submissions."}), 403

    plan = LessonPlan.query.get_or_404(plan_id)
    section = Section.query.get(plan.section_id) if plan.section_id else None
    if not section or section.teacher_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this submission."}), 403

    data = request.get_json(silent=True) or {}

    score_raw = data.get("score")
    if score_raw is None or str(score_raw).strip() == "":
        return jsonify({"status": "error", "message": "Give this lesson plan a score from 1 to 100."}), 400
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Score must be a whole number from 1 to 100."}), 400
    if score < 1 or score > 100:
        return jsonify({"status": "error", "message": "Score must be between 1 and 100."}), 400

    plan.status = "reviewed"
    plan.teacher_feedback = (data.get("feedback") or "").strip() or None
    plan.score = score
    plan.reviewed_at = datetime.utcnow()

    notify(
        plan.user_id,
        "review",
        "Lesson plan reviewed",
        f"{user.full_name} reviewed \"{plan.title}\" — score: {score}/100.",
        link="lesson-plan-list.html",
    )

    db.session.commit()

    return jsonify({"status": "ok", "lesson_plan": plan.to_dict()})
