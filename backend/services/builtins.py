"""Seed the ready-made formats and official DepEd guides shipped in
backend/builtin/ into the database, on every startup.

Each manifest entry is matched to its row by builtin_key, never by name or
file, so a teacher's own format or upload can never be picked up and
overwritten. A missing row is inserted, and an existing one is brought back in
line with the manifest, which is how a corrected field list or title reaches a
server that seeded an older one. Nothing here calls the AI: format fields were
detected once, reviewed, and frozen into formats.json.

All three gunicorn workers run this at the same time. A unique index on
builtin_key (see app._add_unique_index) turns the second insert of the same
entry into an IntegrityError, which is rolled back and skipped: the other
worker's row is already the right one.

A bad entry or missing file is logged and skipped. Seeding must never stop
the app from booting.
"""
import hashlib
import json
import logging
import os
from datetime import date

from sqlalchemy.exc import IntegrityError

from config import BASE_DIR
from extensions import db

_log = logging.getLogger(__name__)

BUILTIN_DIR = os.path.join(BASE_DIR, "builtin")


def seed_builtins(base_dir=BUILTIN_DIR):
    from models.user import User

    owner = User.query.filter_by(role="admin").order_by(User.id).first()
    if owner is None:
        _log.warning("No admin account to own the built-in formats and guides; skipping seeding.")
        return
    _seed_formats(os.path.join(base_dir, "formats"), owner.id)
    _seed_guides(os.path.join(base_dir, "course_guides"), owner.id)


def _load_manifest(folder, filename):
    path = os.path.join(folder, filename)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        _log.exception("Couldn't read built-in manifest %s", path)
        return []


def _seed_each(entries, seed_one, kind):
    """Seed each entry in its own transaction, so one failure costs only that
    entry."""
    for entry in entries:
        key = entry.get("key") if isinstance(entry, dict) else None
        try:
            if seed_one(entry):
                db.session.commit()
        except IntegrityError:
            # Another worker inserted this entry first; its row stands.
            db.session.rollback()
            _log.info("Built-in %s %s was seeded by another worker.", kind, key)
        except Exception:
            db.session.rollback()
            _log.exception("Couldn't seed built-in %s %r; skipped.", kind, key)


def _field_signature(fields):
    # The key counts too: a manifest may pin a field's key so plans saved
    # under an older label keep their answers attached to it.
    from routes.format_routes import _slugify

    return [(f.get("field_key") or _slugify(f["label"]), f["label"], f.get("field_type", "textarea"),
             f.get("anchor_index"), bool(f.get("is_required", True)), f.get("ai_hint") or None,
             f.get("parts") or None)
            for f in fields]


def _seed_formats(folder, owner_id):
    from models.format import LessonPlanFormat
    from routes.format_routes import _build_format_fields

    def seed_one(entry):
        key = entry.get("key")
        source = os.path.join(folder, entry.get("source") or "")
        template = os.path.join(folder, entry.get("template") or "")
        fields = entry.get("fields") or []
        files_ok = (entry.get("source") and os.path.isfile(source)
                    and entry.get("template") and os.path.isfile(template))
        if not key or not files_ok or not fields:
            _log.error("Built-in format %r is missing its files or fields; skipped.", key)
            return False

        fmt = LessonPlanFormat.query.filter_by(builtin_key=key).first()
        if fmt is None:
            fmt = LessonPlanFormat(builtin_key=key, owner_id=owner_id)
            db.session.add(fmt)

        fmt.is_builtin = True
        fmt.is_public = True
        fmt.name = entry.get("name") or key
        fmt.description = entry.get("description")
        # Absolute paths, refreshed every boot, so the row follows the checkout
        # wherever it lives on this machine.
        fmt.source_file_path = source
        fmt.template_docx_path = template
        db.session.flush()

        current = [{"field_key": f.field_key, "label": f.label, "field_type": f.field_type, "anchor_index": f.anchor_index,
                    "is_required": f.is_required, "ai_hint": f.ai_hint, "parts": f.parts_list}
                   for f in fmt.fields]
        if _field_signature(current) != _field_signature(fields):
            for existing in list(fmt.fields):
                db.session.delete(existing)
            db.session.flush()
            for row in _build_format_fields(fmt.id, fields):
                db.session.add(row)
            db.session.flush()
            db.session.expire(fmt, ["fields"])
        return True

    _seed_each(_load_manifest(folder, "formats.json"), seed_one, "format")


def _seed_guides(folder, owner_id):
    from models.course_guide import CourseGuide
    from services import text_extract

    def seed_one(entry):
        key = entry.get("key")
        path = os.path.join(folder, entry.get("file") or "")
        if not key or not entry.get("file") or not os.path.isfile(path):
            _log.error("Built-in guide %r is missing its file; skipped.", key)
            return False

        with open(path, "rb") as fh:
            file_hash = hashlib.sha256(fh.read()).hexdigest()

        guide = CourseGuide.query.filter_by(builtin_key=key).first()
        if guide is None:
            guide = CourseGuide(builtin_key=key, uploader_id=owner_id)
            db.session.add(guide)

        # Only a new or changed file gets its text read. The text ships beside
        # the PDF as <name>.txt, extracted once when the guide was added:
        # extracting a 184-page PDF inside every gunicorn worker's startup
        # could outlast the worker timeout. An empty or failed extraction is
        # kept as it is rather than retried on every boot.
        if guide.file_hash != file_hash:
            cached = os.path.splitext(path)[0] + ".txt"
            try:
                if os.path.isfile(cached):
                    with open(cached, encoding="utf-8") as fh:
                        guide.extracted_text = fh.read()
                else:
                    guide.extracted_text = text_extract.extract_text(path)
            except Exception:
                _log.exception("Text extraction failed for built-in guide %s", key)
                guide.extracted_text = ""
            guide.file_hash = file_hash

        guide.is_builtin = True
        guide.file_path = path
        guide.subject = entry.get("subject") or "ICT"
        guide.title = entry.get("title") or key
        guide.doc_type = entry.get("doc_type")
        guide.grade_band = entry.get("grade_band")
        guide.grades = entry.get("grades")
        guide.curriculum = entry.get("curriculum")
        guide.source_url = entry.get("source_url")
        try:
            guide.retrieved_at = date.fromisoformat(entry["retrieved_at"]) if entry.get("retrieved_at") else None
        except ValueError:
            guide.retrieved_at = None
        return True

    _seed_each(_load_manifest(folder, "guides.json"), seed_one, "guide")
