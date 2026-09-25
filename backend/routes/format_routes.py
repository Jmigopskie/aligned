import os
import re
import uuid

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename

from extensions import db
from models.format import LessonPlanFormat, FormatField
from models.lesson_plan import LessonPlan
from routes.auth_routes import login_required, current_user
from services import ai_service, docx_service

format_bp = Blueprint("formats", __name__)

ALLOWED_EXTENSIONS = {"docx", "dotx", "pdf"}

def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _slugify(label):
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return slug or "field"

def _build_format_fields(format_id, fields_payload):
    """Turn the client's field list into FormatField rows, deriving a safe,
    unique field_key server-side (from the label) instead of trusting
    whatever — or nothing — the client sent for it."""
    rows = []
    used_keys = set()
    for i, f in enumerate(fields_payload):
        label = (f.get("label") or "").strip()
        if not label:
            continue

        key = (f.get("field_key") or "").strip() or _slugify(label)
        final_key = key
        suffix = 2
        while final_key in used_keys:
            final_key = f"{key}_{suffix}"
            suffix += 1
        used_keys.add(final_key)

        anchor_index = f.get("anchor_index")
        try:
            anchor_index = int(anchor_index) if anchor_index is not None else None
        except (TypeError, ValueError):
            anchor_index = None

        # Normalize role override: only "heavy" and "easy" are valid; anything else
        # or an empty string falls back to keyword-based classification.
        role = (f.get("role") or "").strip().lower()
        if role not in ("heavy", "easy"):
            role = None

        rows.append(FormatField(
            format_id=format_id,
            field_key=final_key,
            label=label,
            field_type=f.get("field_type", "textarea"),
            section_group=f.get("section_group"),
            sort_order=f.get("sort_order", i),
            is_required=bool(f.get("is_required", True)),
            ai_hint=f.get("ai_hint"),
            anchor_index=anchor_index,
            role=role,
        ))
    return rows

def _reject_if_builtin(fmt):
    """The ready-made formats are shared by everyone and seeded from files in
    the repository, so nobody may change them, not even the admin account
    that nominally owns them. Checked before ownership so the answer is the
    same for every user. Returns an error response, or None to carry on."""
    if fmt.is_builtin:
        return jsonify({
            "status": "error",
            "message": "Built-in formats are read-only. Make your own with New format to change a layout.",
        }), 403
    return None

def _tmp_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "tmp")
    os.makedirs(path, exist_ok=True)
    return path

@format_bp.get("/formats")
@login_required
def list_formats():
    user = current_user()
    formats = LessonPlanFormat.query.filter(
        (LessonPlanFormat.owner_id == user.id) | (LessonPlanFormat.is_public.is_(True))
    ).order_by(LessonPlanFormat.created_at.desc()).all()
    return jsonify({"status": "ok", "formats": [f.to_dict() for f in formats]})

def _suggest_fields(renderable_path):
    """AI proposes which label-like spots in the real document are fields
    worth filling, each anchored to a real position (docx_service already
    limits the model to choosing among the document's actual label lines).
    Every returned index is re-validated here against that same list before
    it's trusted, so a misbehaving model still can't point at, or invent, a
    position that doesn't genuinely exist in the file."""
    lines = docx_service.candidate_label_lines(renderable_path)
    if not lines:
        return [], None

    try:
        raw = ai_service.suggest_field_anchors(lines)
    except Exception:
        current_app.logger.exception("AI field suggestion failed")
        return [], "AI couldn't suggest fields automatically — define them by clicking the document below."

    valid_indices = {l["index"] for l in lines}
    fields = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        try:
            idx = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        if idx not in valid_indices:
            continue
        label = (s.get("label") or "").strip()
        if not label:
            continue
        fields.append({
            "anchor_index": idx,
            "label": label,
            "field_type": s.get("field_type") if s.get("field_type") in ("text", "textarea", "list", "table") else "textarea",
            "is_required": bool(s.get("is_required", True)),
        })
    return fields, None

@format_bp.post("/formats/scan")
@login_required
def scan_format():
    """Upload a reference file and render it as a live, editable document —
    the same real tables/headers/labels as the source file — so the teacher
    can clean it up (fix typos, delete stray lines, restyle text) before it
    becomes a format. Finding the fillable fields happens later, in
    create_format(), against whatever the teacher leaves after editing —
    doing it here too would mean re-detecting fields all over again once
    editing is done, for suggestions the teacher hasn't even seen yet."""
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "" or not _allowed(file.filename):
        return jsonify({"status": "error", "message": "Only .docx, .dotx, or .pdf files are allowed."}), 400

    token = uuid.uuid4().hex
    ext = file.filename.rsplit(".", 1)[1].lower()
    tmp_path = os.path.join(_tmp_dir(), f"{token}.{ext}")
    file.save(tmp_path)

    renderable_path = tmp_path
    scan_error = None

    if ext == "pdf":
        converted_path = os.path.join(_tmp_dir(), f"{token}_converted.docx")
        try:
            docx_service.convert_pdf_to_docx(tmp_path, converted_path)
            renderable_path = converted_path
        except Exception:
            current_app.logger.exception("Format scan: PDF-to-docx conversion failed for %s", file.filename)
            scan_error = (
                "Couldn't convert this PDF into an editable layout. If it's a scanned PDF "
                "(a photo or image of a page rather than real text), export/print it from "
                "Word instead, or start from a blank sheet."
            )

    preview = None
    if scan_error is None:
        try:
            preview = docx_service.render_reference_html(renderable_path)
        except Exception:
            current_app.logger.exception("Format scan: rendering the reference file failed for %s", file.filename)
            scan_error = "Couldn't read this file as a Word document."

    if preview is None and scan_error is None:
        scan_error = (
            "No content could be found in this file to build a template from. "
            "Try a different file, or start from a blank sheet instead."
        )

    return jsonify({
        "status": "ok",
        "source_temp_token": token,
        "source_filename": secure_filename(file.filename),
        "preview_html": preview["html"] if preview else None,
        "scan_error": scan_error,
    })

@format_bp.post("/formats")
@login_required
def create_format():
    """Save a format. When it's built from an uploaded reference file, the
    teacher never hand-picks fields — AI reads whatever the teacher leaves
    after cleaning up the document (see scan_format()) and the resulting
    field list is stored as-is, the same one every future lesson plan
    generated from this format will reuse. A blank-start format (no
    reference file) still takes its fields straight from the client, since
    there's no document for AI to read fields from."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    manual_fields = data.get("fields") or []
    temp_token = (data.get("source_temp_token") or "").strip()
    temp_filename = (data.get("source_filename") or "").strip()

    if not name:
        return jsonify({"status": "error", "message": "Give this format a name."}), 400
    if not temp_token and not manual_fields:
        return jsonify({"status": "error", "message": "Add at least one field with a label."}), 400

    fmt = LessonPlanFormat(name=name, owner_id=user.id, is_public=bool(data.get("is_public", False)))
    db.session.add(fmt)
    db.session.flush()

    if temp_token:
        moved_filename, converted_docx_path = _promote_temp_file(fmt.id, temp_token, temp_filename)
        if moved_filename:
            fmt.source_file_path = moved_filename
        if converted_docx_path:
            # This is the exact .docx the teacher edited in the builder (a
            # PDF reference gets converted once, here) — locking it in now
            # keeps every field's anchor_index valid, instead of letting a
            # later export re-convert the PDF independently and risk a
            # structurally different document.
            fmt.template_docx_path = converted_docx_path

        template_path = docx_service.resolve_template_path(fmt)
        detected_fields, ai_error = _suggest_fields(template_path) if template_path else ([], None)
        if not detected_fields:
            db.session.rollback()
            return jsonify({
                "status": "error",
                "message": ai_error or "Couldn't find any fillable fields in this document. "
                                       "Try cleaning it up further, or start from a blank sheet instead.",
            }), 400
        field_rows = _build_format_fields(fmt.id, detected_fields)
    else:
        field_rows = _build_format_fields(fmt.id, manual_fields)
        if not field_rows:
            db.session.rollback()
            return jsonify({"status": "error", "message": "Add at least one field with a label."}), 400

    for row in field_rows:
        db.session.add(row)

    db.session.commit()
    return jsonify({"status": "ok", "format": fmt.to_dict(include_fields=True)}), 201

def _promote_temp_file(format_id, token, original_filename):
    """Move the originally uploaded reference file — and, if it was a PDF
    that got pre-converted for the builder's live preview, that converted
    .docx too — out of the scratch tmp dir into permanent storage.

    Returns (source_filename, converted_docx_path); either may be None.
    """
    tmp_dir = _tmp_dir()
    source_filename = None
    converted_docx_path = None

    for entry in os.listdir(tmp_dir):
        if entry == f"{token}_converted.docx":
            cache_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "template_docx_cache")
            os.makedirs(cache_dir, exist_ok=True)
            dest = os.path.join(cache_dir, f"format_{format_id}_template.docx")
            os.replace(os.path.join(tmp_dir, entry), dest)
            converted_docx_path = dest
        elif entry.startswith(f"{token}."):
            ext = entry.rsplit(".", 1)[1] if "." in entry else "bin"
            base = original_filename or entry
            filename = secure_filename(f"format_{format_id}_{base}")
            if not filename.lower().endswith(f".{ext}"):
                filename = f"{filename}.{ext}"
            dest = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            os.replace(os.path.join(tmp_dir, entry), dest)
            source_filename = filename

    return source_filename, converted_docx_path
    return None

@format_bp.get("/formats/<int:format_id>")
@login_required
def get_format(format_id):
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    return jsonify({"status": "ok", "format": fmt.to_dict(include_fields=True)})

@format_bp.patch("/formats/<int:format_id>")
@login_required
def update_format(format_id):
    user = current_user()
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    locked = _reject_if_builtin(fmt)
    if locked:
        return locked

    if fmt.owner_id != user.id:
        return jsonify({"status": "error", "message": "Only the teacher who created this format can edit it."}), 403

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "message": "Format name can't be empty."}), 400
        fmt.name = name

    if "is_public" in data:
        fmt.is_public = bool(data.get("is_public"))

    if "fields" in data:
        fields = data.get("fields") or []
        if not fields:
            return jsonify({"status": "error", "message": "A format needs at least one field."}), 400

        field_rows = _build_format_fields(fmt.id, fields)
        if not field_rows:
            return jsonify({"status": "error", "message": "Add at least one field with a label."}), 400

        # Replace the field list wholesale — simplest way to keep sort order,
        # additions, edits, and removals all in sync with what was submitted.
        for existing_field in list(fmt.fields):
            db.session.delete(existing_field)
        db.session.flush()

        for row in field_rows:
            db.session.add(row)

    db.session.commit()
    return jsonify({"status": "ok", "format": fmt.to_dict(include_fields=True)})

@format_bp.delete("/formats/<int:format_id>")
@login_required
def delete_format(format_id):
    user = current_user()
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    locked = _reject_if_builtin(fmt)
    if locked:
        return locked

    if fmt.owner_id != user.id:
        return jsonify({"status": "error", "message": "Only the teacher who created this format can delete it."}), 403

    in_use = LessonPlan.query.filter_by(format_id=fmt.id).count()
    if in_use:
        return jsonify({
            "status": "error",
            "message": f"This format is used by {in_use} lesson plan{'s' if in_use != 1 else ''} and can't be deleted. "
                       f"Unshare it instead if you don't want others to use it.",
        }), 400

    source_path = docx_service.resolve_source_path(fmt)
    cached_template_path = (fmt.template_docx_path or "").strip() or None
    for path in (source_path, cached_template_path):
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass

    db.session.delete(fmt)
    db.session.commit()
    return jsonify({"status": "ok"})

_EDIT_ACTIONS = {"delete", "format"}
_ALIGN_VALUES = {"left", "center", "right", "justify"}
_LIST_VALUES = {"bullet", "number"}

def _sanitize_content_edits(raw_edits):
    """Keep only well-formed edits so a malformed request can't corrupt the
    real reference file: each edit must name a real action and a numeric
    anchor_index (docx_service re-validates that index is actually in range
    for this document); any format fields carry only the accepted values."""
    edits = []
    for e in raw_edits or []:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        if action not in _EDIT_ACTIONS:
            continue
        try:
            idx = int(e.get("anchor_index"))
        except (TypeError, ValueError):
            continue

        edit = {"anchor_index": idx, "action": action}
        if action == "format":
            if "text" in e and isinstance(e["text"], str):
                edit["text"] = e["text"]
            for key in ("bold", "italic", "underline"):
                if key in e:
                    edit[key] = bool(e[key])
            if "align" in e and e["align"] in _ALIGN_VALUES:
                edit["align"] = e["align"]
            if "heading" in e:
                try:
                    level = int(e["heading"])
                    if level in (0, 1, 2, 3):
                        edit["heading"] = level
                except (TypeError, ValueError):
                    pass
            if "list" in e and (e["list"] in _LIST_VALUES or e["list"] is None):
                edit["list"] = e["list"]
            # Font size, text colour and highlight, validated against the same
            # closed vocabulary the toolbar offers and the export understands.
            # Anything outside it is dropped rather than passed through, so an
            # edited request can't put arbitrary styling into the document.
            for key, allowed in (
                ("size", docx_service.FONT_SIZE_CLASSES),
                ("color", docx_service.FONT_COLOR_CLASSES),
                ("highlight", docx_service.HIGHLIGHT_CLASSES),
            ):
                if key in e and e[key] in allowed:
                    edit[key] = e[key]
        edits.append(edit)
    return edits

@format_bp.patch("/formats/<int:format_id>/content")
@login_required
def edit_format_content(format_id):
    """Persist edits made in the format builder's document editor — text,
    bold/italic/underline, alignment, heading level, list style, or deleting
    a line entirely — directly into the format's real reference file, so
    unwanted leftover content actually stays gone on every future render
    and export instead of just being hidden in the browser.

    Fields are never manually curated, so rather than trying to shift old
    anchors onto a now-different document, this re-reads the edited file from
    scratch and replaces the field list wholesale — the same automatic
    detection create_format() runs when the format is first saved."""
    user = current_user()
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    locked = _reject_if_builtin(fmt)
    if locked:
        return locked

    if fmt.owner_id != user.id:
        return jsonify({"status": "error", "message": "Only the teacher who created this format can edit its document."}), 403

    data = request.get_json(silent=True) or {}
    edits = _sanitize_content_edits(data.get("edits"))
    if not edits:
        return jsonify({"status": "error", "message": "No changes to save."}), 400

    template_path = docx_service.resolve_template_path(fmt)
    if not template_path:
        return jsonify({"status": "error", "message": "This format has no reference file to edit."}), 400

    try:
        _deletions, applied = docx_service.apply_content_edits(template_path, edits)
    except Exception:
        current_app.logger.exception("Failed to apply content edits for format %s", format_id)
        return jsonify({"status": "error", "message": "Couldn't save changes to the document."}), 500

    detected_fields, ai_error = _suggest_fields(template_path)
    if not detected_fields:
        return jsonify({
            "status": "error",
            "message": ai_error or "Couldn't find any fillable fields left in this document after that edit.",
        }), 400

    # _suggest_fields()'s payload carries no role, so rebuilding straight from
    # it would silently null out every override the teacher set on the roles
    # panel on this same screen. Keyed by field_key, same as set_field_roles
    # relies on, so an override survives as long as the field itself does; one
    # that no longer exists after re-detection has nothing to restore onto.
    kept_roles = {f.field_key: f.role for f in fmt.fields if f.role}

    for existing_field in list(fmt.fields):
        db.session.delete(existing_field)
    db.session.flush()
    for row in _build_format_fields(fmt.id, detected_fields):
        row.role = kept_roles.get(row.field_key, row.role)
        db.session.add(row)

    db.session.commit()
    return jsonify({"status": "ok", "applied": applied, "format": fmt.to_dict(include_fields=True)})

@format_bp.patch("/formats/<int:format_id>/field-roles")
@login_required
def set_field_roles(format_id):
    """Override which fields Guided walks the teacher through.

    Keyed by field_key rather than field id because a document-based format
    re-detects its fields whenever the reference file is edited, which gives them
    new ids; the key survives that.

    A null value clears the override and hands the decision back to the keywords
    in services/field_roles. An unrecognised value or unknown key is ignored
    rather than rejected, so one stale entry from an open page cannot lose the
    rest of the teacher's choices.
    """
    user = current_user()
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    locked = _reject_if_builtin(fmt)
    if locked:
        return locked
    if fmt.owner_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this format."}), 403

    data = request.get_json(silent=True) or {}
    roles = data.get("roles")
    if not isinstance(roles, dict) or not roles:
        return jsonify({"status": "error", "message": "Send at least one field role."}), 400

    by_key = {f.field_key: f for f in fmt.fields}
    for key, value in roles.items():
        field = by_key.get(key)
        if field is None:
            continue
        if value is None:
            field.role = None
            continue
        normalised = str(value).strip().lower()
        # Ignore junk values entirely; they must not overwrite a valid stored role,
        # since one stale entry from a long-open page must not lose other choices.
        if normalised in ("heavy", "easy"):
            field.role = normalised

    db.session.commit()
    return jsonify({"status": "ok", "fields": [f.to_dict() for f in fmt.fields]})

def _resolve_temp_renderable_path(token):
    """The same file scan_format() rendered for this token: the pre-converted
    .docx when the upload was a PDF, otherwise the uploaded file itself —
    still sitting in the scratch tmp dir since the format hasn't been saved
    (and so promoted out of it) yet."""
    tmp_dir = _tmp_dir()
    converted = os.path.join(tmp_dir, f"{token}_converted.docx")
    if os.path.isfile(converted):
        return converted
    for entry in os.listdir(tmp_dir):
        if entry.startswith(f"{token}."):
            return os.path.join(tmp_dir, entry)
    return None

@format_bp.patch("/formats/scan/content")
@login_required
def edit_scanned_content():
    """The same content-editing toolbar as edit_format_content() above, but
    for a file that was just scanned and hasn't been saved as a format yet —
    there's no FormatField row to remap here (any fields the teacher has
    defined so far still live only in the browser), so this just applies the
    edits to the scratch file and reports back which positions were deleted;
    the caller remaps its own in-progress field list against that."""
    data = request.get_json(silent=True) or {}
    token = (data.get("source_temp_token") or "").strip()
    edits = _sanitize_content_edits(data.get("edits"))
    if not token or not edits:
        return jsonify({"status": "error", "message": "No changes to save."}), 400

    path = _resolve_temp_renderable_path(token)
    if not path:
        return jsonify({"status": "error", "message": "That file isn't available anymore — try uploading it again."}), 404

    try:
        deletions, applied = docx_service.apply_content_edits(path, edits)
    except Exception:
        current_app.logger.exception("Failed to apply content edits to scanned file (token %s)", token)
        return jsonify({"status": "error", "message": "Couldn't save changes to the document."}), 500

    try:
        preview = docx_service.render_reference_html(path)
    except Exception:
        current_app.logger.exception("Failed to re-render scanned file after content edit (token %s)", token)
        preview = None

    return jsonify({
        "status": "ok",
        "applied": applied,
        "deleted_indices": deletions,
        "preview_html": preview["html"] if preview else None,
    })

@format_bp.get("/formats/<int:format_id>/template-html")
@login_required
def get_format_template_html(format_id):
    fmt = LessonPlanFormat.query.get_or_404(format_id)

    try:
        rendered = docx_service.render_template_html(fmt)
    except Exception as exc:
        current_app.logger.exception("Template HTML render failed for format %s", format_id)
        return jsonify({
            "status": "error",
            "message": f"Couldn't render this format's reference file as an editable "
                       f"template ({exc.__class__.__name__}).",
        }), 500

    if rendered is None:
        return jsonify({
            "status": "error",
            "message": "No reference file is on record for this format, so there's no "
                       "real template to render.",
        }), 404

    return jsonify({"status": "ok", **rendered})

@format_bp.get("/formats/<int:format_id>/source")
@login_required
def download_format_source(format_id):
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    path = docx_service.resolve_source_path(fmt)
    if not path:
        return jsonify({
            "status": "error",
            "message": "No reference file is on record for this format — it may have been created without one.",
        }), 404
    # ?inline=1 opens the file in a browser tab (the PDF viewer) instead of
    # downloading it.
    return send_file(path, as_attachment=request.args.get("inline") != "1")
