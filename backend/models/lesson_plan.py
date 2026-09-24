import json
from datetime import datetime

from extensions import db

class LessonPlan(db.Model):
    __tablename__ = "lesson_plans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    format_id = db.Column(db.Integer, db.ForeignKey("lesson_plan_formats.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(120))
    grade_level = db.Column(db.String(50))
    quarter = db.Column(db.String(50))
    date = db.Column(db.String(50))
    field_values = db.Column(db.Text, nullable=False, default="{}")
    # Sanitized rich-text HTML (bold/italic/underline/bullet/numbered lists —
    # see docx_service.parse_rich_value) for any field the teacher styled
    # directly in the live document editor, keyed by field_key. A field with
    # no entry here was never manually styled and exports as plain text.
    rich_field_values = db.Column(db.Text)
    generation_mode = db.Column(db.String(10), nullable=False, default="full")
    docx_path = db.Column(db.String(255))

    # Student -> teacher submission workflow
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | submitted | reviewed
    teacher_feedback = db.Column(db.Text)
    score = db.Column(db.Integer, nullable=True)  # 1-100, set by the teacher on review
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)

    # Any author (student or teacher) can share their own plan publicly so
    # it shows up for everyone in the "Public plans" list.
    is_public = db.Column(db.Boolean, nullable=False, default=False)

    # The mode the teacher is NOT currently in. field_values/rich_field_values
    # always hold the active mode's content, which is what export, submission and
    # every plan saved before this column existed rely on; this carries the other
    # mode's copy so Guided and Building Proficiency can be two drafts of the same
    # plan instead of overwriting each other. Shape:
    # {"field_values": {...}, "rich_field_values": {...}, "step_index": int}
    mode_values = db.Column(db.Text)

    # Everything the "Before we start" step asked for, stored verbatim as JSON:
    # the topic, the level and its parts, the section, and the chosen course
    # guide. None of it had a home before, so reopening a saved plan dropped the
    # teacher back into that form with the fields blank. grade_level is not a
    # substitute: it holds a display string ("Grade 7 - Campos") that cannot be
    # split back into the dropdowns it came from, and the course guide the gate
    # insists on was never stored at all.
    setup_context = db.Column(db.Text)

    # The teacher's own edits to the document body: the labels, headings and
    # table text around the AI's field slots. Stored as a list of
    # {anchor_index, text, bold, italic, underline, align, heading, list} against
    # the same positions the format builder addresses, and replayed onto a fresh
    # copy of the reference file at export, so the .docx keeps its original
    # fonts and table layout while carrying the teacher's wording. Per plan, so
    # one teacher's rewording never reaches the shared format.
    doc_edits = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_values(self):
        return json.loads(self.field_values or "{}")

    def set_values(self, values: dict):
        self.field_values = json.dumps(values)

    def get_rich_values(self):
        return json.loads(self.rich_field_values or "{}")

    def set_rich_values(self, values: dict):
        self.rich_field_values = json.dumps(values or {})

    def get_doc_edits(self):
        """The document edits, or [] when there are none.

        [] rather than None for a plan saved before this column existed, and for
        unparseable content, so export never needs a null check and corruption
        degrades to "no edits" instead of a failed download.
        """
        try:
            value = json.loads(self.doc_edits or "[]")
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    def set_doc_edits(self, value):
        self.doc_edits = json.dumps(value or [])

    def get_setup_context(self):
        """The saved setup step, or {} when there isn't one.

        Returns {} rather than None for a plan saved before this column existed
        and for unparseable content, so the page never needs a null check.
        """
        try:
            value = json.loads(self.setup_context or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_setup_context(self, value: dict):
        self.setup_context = json.dumps(value or {})

    def get_mode_values(self):
        """The inactive mode's slot, or {} when there isn't one.

        Returns {} rather than None for a plan saved before this column existed,
        and also for unparseable content, so callers never need a null check and a
        corrupted value degrades to "no other mode" instead of an error.
        """
        try:
            value = json.loads(self.mode_values or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_mode_values(self, values: dict):
        self.mode_values = json.dumps(values or {})

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "author_name": self.user.full_name if self.user else None,
            "format_id": self.format_id,
            "title": self.title,
            "subject": self.subject,
            "grade_level": self.grade_level,
            "quarter": self.quarter,
            "date": self.date,
            "field_values": self.get_values(),
            "rich_field_values": self.get_rich_values(),
            "generation_mode": self.generation_mode,
            "docx_path": self.docx_path,
            "section_id": self.section_id,
            "section_name": self.section.name if self.section else None,
            "status": self.status,
            "teacher_feedback": self.teacher_feedback,
            "score": self.score,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "is_public": bool(self.is_public),
            "mode_values": self.get_mode_values(),
            "setup_context": self.get_setup_context(),
            "doc_edits": self.get_doc_edits(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
