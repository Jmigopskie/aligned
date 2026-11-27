"""The admin's activity log (the user's request, 2026-11-22): what a user did
with AlignED (RELEVANT below), plus failed logins, in plain words with a
timestamp. One hook for all routes; a new route is logged once it is added
to RELEVANT.

ponytail: rows are kept forever; add a purge (e.g. older than a year) when the
table grows large enough to matter.
"""
import re

from flask import g, request, session

from extensions import db

# What the admin sees (the user's request, 2026-11-28): only the actions that
# say what someone did with AlignED, each in plain words and under a kind.
# Anything not listed (autosaves, Alan's chat, tidying, picture uploads,
# banners, onboarding) isn't logged. Route function -> (words, kind).
RELEVANT = {
    "login": ("Logged in", "sign-in"), "logout": ("Logged out", "account"),
    "signup": ("Signed up", "account"), "reset_password": ("Reset their password", "account"),
    "change_password": ("Changed their password", "account"), "update_me": ("Updated their profile", "account"),
    "save_lesson_plan": ("Saved a lesson plan", "plan"),
    "generate_full": ("Had Alan write a lesson plan", "plan"),
    "generate_full_stream": ("Had Alan write a lesson plan", "plan"),
    "export_lesson_plan": ("Downloaded a lesson plan (Word)", "download"),
    "submit_lesson_plan": ("Submitted a lesson plan", "submit"),
    "review_lesson_plan": ("Reviewed a submission", "review"),
    "rate_lesson_plan": ("Rated a lesson plan", "review"),
    "set_lesson_plan_visibility": ("Changed a lesson plan's visibility", "plan"),
    "delete_lesson_plan": ("Deleted a lesson plan", "plan"),
    "join_section": ("Joined a class", "class"), "leave_section": ("Left a class", "class"),
    "create_section": ("Created a section", "class"), "delete_section": ("Deleted a section", "class"),
    "remove_student": ("Removed a student from a section", "class"), "give_points": ("Gave points", "class"),
    "create_format": ("Uploaded a format", "library"), "delete_format": ("Deleted a format", "library"),
    "upload_course_guide": ("Uploaded a course guide", "library"),
    "create_user": ("Created an account", "admin"), "update_user": ("Changed an account", "admin"),
    "delete_user": ("Deleted an account", "admin"), "bulk_archive": ("Archived or restored accounts", "admin"),
    "admin_delete_lesson_plan": ("Deleted a user's lesson plan", "admin"),
    "create_announcement": ("Posted an announcement", "admin"),
    "admin_create_announcement": ("Posted an announcement", "admin"),
    "set_format_availability": ("Turned a built-in format on or off", "admin"),
}
FAILED_LOGIN = "Failed login"
# Every action the admin's page shows (older rows with other wordings, like
# autosave edits, stay in the table but out of sight).
SHOWN_ACTIONS = {label for label, _ in RELEVANT.values()} | {FAILED_LOGIN}
KIND_OF = {**{label: kind for label, kind in RELEVANT.values()}, FAILED_LOGIN: "sign-in"}

_DETAIL_KEYS = (("plan_id", "Lesson plan"), ("section_id", "Section"), ("format_id", "Format"),
                ("user_id", "User"), ("guide_id", "Guide"), ("announcement_id", "Announcement"))


def _detail(name: str, response) -> str:
    parts = [f"{label} #{request.view_args[key]}" for key, label in _DETAIL_KEYS
             if request.view_args and key in request.view_args]
    body = request.get_json(silent=True) or {}
    if name in ("login", "signup", "reset_password"):
        email = str(body.get("email") or "").strip().lower()[:120]
        # Only something that looks like an email: a password typed into the
        # email box must never end up in the log.
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            parts.append(email)
        elif email:
            parts.append("(not an email address)")
    if name == "set_lesson_plan_visibility":
        parts.append("made public" if body.get("is_public") else "made private")
    if name == "rate_lesson_plan" and isinstance(body.get("stars"), int):
        parts.append(f"{body['stars']} of 5 stars")
    if name == "save_lesson_plan":
        # A new plan has no id in the URL; its JSON reply says which (this
        # route never streams, so reading the reply is safe).
        plan = (response.get_json(silent=True) or {}).get("lesson_plan") or {}
        if plan.get("id"):
            parts.append(f"Lesson plan #{plan['id']}: {str(plan.get('title') or '')[:80]}")
    return ", ".join(parts)[:255]


def _ip() -> str:
    from routes.auth_routes import client_ip
    return client_ip()


def remember_user():
    """Before the request: who was signed in (logout clears it)."""
    g.activity_user = session.get("user_id")


def log_response(response):
    """After the request: write the entry, never failing the response."""
    endpoint = request.endpoint or ""
    name = endpoint.rsplit(".", 1)[-1]
    if not request.path.startswith("/api/"):
        return response
    failed_login = name == "login" and response.status_code == 401
    if not failed_login and (name not in RELEVANT or response.status_code >= 400):
        return response
    user_id = None if failed_login else (session.get("user_id") or getattr(g, "activity_user", None))
    action = FAILED_LOGIN if failed_login else RELEVANT[name][0]
    try:
        from models.activity_log import ActivityLog
        db.session.add(ActivityLog(user_id=user_id, action=action, detail=_detail(name, response), ip=_ip()))
        db.session.commit()
    except Exception:  # noqa: BLE001 - the log must never break what the user did
        db.session.rollback()
    return response
