from datetime import datetime

from extensions import db, iso_utc
from services import field_roles

class LessonPlanFormat(db.Model):
    __tablename__ = "lesson_plan_formats"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    source_file_path = db.Column(db.String(255))
    # Auto-generated, cached .docx version of source_file_path when the
    # uploaded reference file was a PDF — lets exports fill the real
    # template layout even though the original upload wasn't an editable
    # Word document. Left blank when source_file_path is already .docx/.dotx.
    template_docx_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fields = db.relationship(
        "FormatField",
        backref="format",
        lazy=True,
        order_by="FormatField.sort_order",
        cascade="all, delete-orphan",
    )
    lesson_plans = db.relationship("LessonPlan", backref="format", lazy=True)

    def to_dict(self, include_fields=False):
        data = {
            "id": self.id,
            "owner_id": self.owner_id,
            "owner_name": self.owner.full_name if self.owner else None,
            "name": self.name,
            "is_public": self.is_public,
            "source_file_path": self.source_file_path,
            "has_source_file": bool(self.source_file_path),
            "has_template_docx": bool(self.template_docx_path),
            "created_at": iso_utc(self.created_at),
        }
        if include_fields:
            data["fields"] = [f.to_dict() for f in self.fields]
        return data

class FormatField(db.Model):
    __tablename__ = "format_fields"
    __table_args__ = (db.UniqueConstraint("format_id", "field_key"),)

    id = db.Column(db.Integer, primary_key=True)
    format_id = db.Column(db.Integer, db.ForeignKey("lesson_plan_formats.id"), nullable=False)
    field_key = db.Column(db.String(120), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default="textarea")
    section_group = db.Column(db.String(120))
    sort_order = db.Column(db.Integer, default=0)
    is_required = db.Column(db.Boolean, default=True)
    ai_hint = db.Column(db.Text)
    # Exact position of this field in the reference file, as an index into
    # docx_service._iter_items() — recorded when the teacher clicked this
    # spot in the format builder's live document editor. Lets the field be
    # located directly instead of by fuzzy keyword matching against its
    # label. Null for fields on a format with no reference file, or fields
    # saved before this existed (those still fall back to keyword matching).
    anchor_index = db.Column(db.Integer)
    # Overrides the keyword-based guess in services/field_roles: "heavy" means
    # Guided walks the teacher through this field and Building Proficiency only
    # writes it when asked, "easy" means the reverse. NULL (the default for
    # every field) leaves the decision to the keywords.
    role = db.Column(db.String(10))

    def to_dict(self):
        return {
            "id": self.id,
            "format_id": self.format_id,
            "field_key": self.field_key,
            "label": self.label,
            "field_type": self.field_type,
            "section_group": self.section_group,
            "sort_order": self.sort_order,
            "is_required": self.is_required,
            "ai_hint": self.ai_hint,
            "anchor_index": self.anchor_index,
            # The resolved role, not the raw override, so the browser reads one
            # value and never needs the keyword list.
            "role": field_roles.role_for(self),
            # The raw override, for the format builder's own select. The page
            # needs to tell "decide automatically" apart from an explicit choice
            # that happens to match what the keywords would have picked.
            "role_override": self.role,
        }
