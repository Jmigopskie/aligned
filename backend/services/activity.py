"""The admin's activity log (the user's request, 2026-11-22): every successful
change a user makes through the API, plus failed logins and downloads, in
plain words with a timestamp. One hook for all routes, so a new route is
logged without anyone remembering to.

ponytail: rows are kept forever; add a purge (e.g. older than a year) when the
table grows large enough to matter.
"""
from datetime import datetime, timedelta

from flask import g, request, session

from extensions import db

# Route function -> what the admin reads. Anything else falls back to its
# function name in words ("create_section" -> "Create section").
_LABELS = {
    "login": "Logged in", "logout": "Logged out", "signup": "Signed up",
    "signup_code": "Asked for a sign-up code", "forgot_password": "Asked for a password reset code",
    "reset_password": "Reset their password", "update_me": "Updated their profile",
    "change_password": "Changed their password", "upload_avatar": "Changed their profile picture",
    "save_lesson_plan": "Saved a lesson plan", "update_lesson_plan": "Edited a lesson plan",
    "delete_lesson_plan": "Deleted a lesson plan", "export_lesson_plan": "Downloaded a lesson plan (Word)",
    "submit_lesson_plan": "Submitted a lesson plan", "review_lesson_plan": "Reviewed a submission",
    "set_lesson_plan_visibility": "Changed a lesson plan's visibility",
    "generate_full": "Had Alan write a lesson plan", "generate_full_stream": "Had Alan write a lesson plan",
    "owl_chat": "Asked Alan for help (Guided)", "check_coherence": "Checked a plan's coherence",
    "start_build": "Started a Building Proficiency plan", "give_points": "Gave points",
    "join_section": "Joined a class", "create_section": "Created a section",
}
# Said again and again while working (autosave, chatting): logged once per
# 10 minutes for the same user and thing.
_REPEATING = {"Edited a lesson plan", "Asked Alan for help (Guided)", "Checked a plan's coherence"}
_REPEAT_WINDOW = timedelta(minutes=10)
# Reading and housekeeping that says nothing about what the user did.
_SKIP = {"mark_onboarded", "mark_read", "mark_all_read", "health"}
_DETAIL_KEYS = (("plan_id", "Lesson plan"), ("section_id", "Section"), ("format_id", "Format"),
                ("user_id", "User"), ("guide_id", "Guide"), ("announcement_id", "Announcement"))


def _label(endpoint: str) -> str:
    name = endpoint.rsplit(".", 1)[-1]
    return _LABELS.get(name) or name.replace("_", " ").strip().capitalize()


def _detail(name: str, response) -> str:
    parts = [f"{label} #{request.view_args[key]}" for key, label in _DETAIL_KEYS
             if request.view_args and key in request.view_args]
    if name in ("login", "signup", "signup_code", "forgot_password", "reset_password"):
        email = str((request.get_json(silent=True) or {}).get("email") or "").strip().lower()[:120]
        if email:
            parts.append(email)
    if name == "save_lesson_plan":
        # A new plan has no id in the URL; its JSON reply says which (this
        # route never streams, so reading the reply is safe).
        plan = (response.get_json(silent=True) or {}).get("lesson_plan") or {}
        if plan.get("id"):
            parts.append(f"Lesson plan #{plan['id']}: {str(plan.get('title') or '')[:80]}")
    return ", ".join(parts)[:255]


def _ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() or request.remote_addr or "")[:45]


def remember_user():
    """Before the request: who was signed in (logout clears it)."""
    g.activity_user = session.get("user_id")


def log_response(response):
    """After the request: write the entry, never failing the response."""
    endpoint = request.endpoint or ""
    name = endpoint.rsplit(".", 1)[-1]
    if not request.path.startswith("/api/") or name in _SKIP or endpoint.startswith("notification"):
        return response
    failed_login = name == "login" and response.status_code == 401
    changes = request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400
    download = name == "export_lesson_plan" and response.status_code < 400
    if not (failed_login or changes or download):
        return response
    user_id = None if failed_login else (session.get("user_id") or getattr(g, "activity_user", None))
    action = "Failed login" if failed_login else _label(endpoint)
    detail = _detail(name, response)
    try:
        from models.activity_log import ActivityLog
        if action in _REPEATING:
            last = (ActivityLog.query.filter_by(user_id=user_id, action=action, detail=detail)
                    .order_by(ActivityLog.id.desc()).first())
            if last and last.created_at and datetime.utcnow() - last.created_at < _REPEAT_WINDOW:
                return response
        db.session.add(ActivityLog(user_id=user_id, action=action, detail=detail, ip=_ip()))
        db.session.commit()
    except Exception:  # noqa: BLE001 - the log must never break what the user did
        db.session.rollback()
    return response
