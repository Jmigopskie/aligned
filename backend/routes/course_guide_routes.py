import hashlib
import os

from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import case, func, or_
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, UnidentifiedImageError

from extensions import db
from models.course_guide import CourseGuide, GuideFolder, TYPE_LABELS, normalize_type, type_label
from models.supplementary_source import SupplementarySource
import uuid
from routes.auth_routes import login_required, staff_required, current_user
from services import text_extract

course_guide_bp = Blueprint("course_guides", __name__)

ALLOWED_EXTENSIONS = {"docx", "dotx", "pdf"}

def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _guides_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "course_guides")
    os.makedirs(path, exist_ok=True)
    return path

# The generator's subject values, and the other names the same subject goes by
# in document titles and in what teachers type when they upload.
# Matching is by substring, so every alias is specific: a bare "IA" or "HE"
# would match "Social" or "the". The curriculum guide covers every component
# ("ICT / CP / AFA / FCS / IA"), and Grades 4 to 8 publish one combined
# "AFA / FCS / IA" file per grade, so those strings are aliases too.
_CG = "ICT / CP / AFA / FCS / IA"
_COMBINED = "AFA / FCS / IA"
SUBJECT_ALIASES = {
    "cp (comprog)": ["CP (ComProg)", "Computer Programming", "ComProg", "Programming", _CG],
    "ict": ["ICT", "Information and Communications Technology", _CG],
    "afa": ["AFA", "Agri-Fishery", _COMBINED],
    "he (fcs)": ["FCS", "Home Economics", "Family and Consumer", _COMBINED],
    "ia": ["TLE: IA", "Industrial Arts", _COMBINED],
    "electrical (ees)": ["Electrical", "Electronics Servicing", _COMBINED],
}

DOC_TYPES = {"budget_of_work", "curriculum_guide"}
GRADE_BANDS = {"4-6", "7-8", "9-10", "SHS"}

def _matches(value):
    terms = SUBJECT_ALIASES.get(value.lower(), [value])
    return or_(*[col.ilike(f"%{t}%") for t in terms for col in (CourseGuide.subject, CourseGuide.title)])

@course_guide_bp.get("/course-guides")
@login_required
def search_course_guides():
    """Search the shared library. Official DepEd guides always come first.

    subject: a generator subject value (or any text), matched with its aliases
    against subject and title. q: free text, matched the same way.
    grade_band: a filter (a guide's grade_band may list several bands,
    comma-separated, so it matches each); only official guides carry one, so
    setting it narrows the results to official guides. doc_type: a filter too,
    but an upload with no type (one from before uploads were typed) matches
    either kind. prefer_grade_band:
    not a filter, it only ranks that band's guides above the rest, which is
    what the generator wants when it knows the grade but a guide for another
    band could still help.
    """
    subject = (request.args.get("subject") or "").strip()
    q = (request.args.get("q") or "").strip()
    grade_band = (request.args.get("grade_band") or "").strip()
    doc_type = (request.args.get("doc_type") or "").strip()
    prefer = (request.args.get("prefer_grade_band") or "").strip()

    query = CourseGuide.query
    if subject:
        query = query.filter(_matches(subject))
    if q:
        query = query.filter(_matches(q))
    if grade_band in GRADE_BANDS:
        query = query.filter(CourseGuide.grade_band.like(f"%{grade_band}%"))
    doc_type = normalize_type(doc_type)
    if doc_type == _UNTYPED:
        query = query.filter(CourseGuide.doc_type.is_(None))
    elif doc_type in DOC_TYPES:
        # Uploads from before the Budget of Work / Curriculum Guide split carry
        # no type, so they stay findable from either picker.
        query = query.filter(or_(CourseGuide.doc_type == doc_type, CourseGuide.doc_type.is_(None)))
    elif doc_type:
        query = query.filter(func.lower(CourseGuide.doc_type) == doc_type.lower())

    order = [CourseGuide.is_builtin.desc()]
    if prefer in GRADE_BANDS:
        order.append(case((CourseGuide.grade_band.like(f"%{prefer}%"), 0), else_=1))
    if subject:
        # A subject's own guides (and the curriculum guide that covers them
        # all) before guides it only shares, like the combined AFA / FCS / IA
        # files: Electrical's own Budget of Work leads, not Grade 4's.
        order.append(case((or_(CourseGuide.subject == subject,
                               CourseGuide.doc_type == "curriculum_guide"), 0), else_=1))
    # Official guides keep their catalogue order (the curriculum guide, then
    # Grade 4 upwards, as seeded); teachers' uploads stay newest first.
    order += [case((CourseGuide.is_builtin.is_(True), CourseGuide.id), else_=None).asc(),
              CourseGuide.created_at.desc()]

    guides = query.order_by(*order).limit(50).all()
    return jsonify({"status": "ok", "course_guides": [g.to_dict() for g in guides]})

_UNTYPED = "untyped"  # the folder for uploads that never got a type
_BANNER_SIZE = (960, 540)

def _banners_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "guide_banners")
    os.makedirs(path, exist_ok=True)
    return path

def _can_edit_folder(user, key, folder):
    """Admins change any banner. A teacher changes the built-in folders,
    "Other", their own folders and ones no teacher owns yet (a type that so
    far only has uploads); another teacher's folder stays theirs."""
    if user.role == "admin":
        return True
    if user.role == "student":
        return False
    return folder is None or folder.created_by in (None, user.id)

def _save_banner(folder, file):
    """Crop and size a banner picture for a folder box. Returns an error
    message, or None once it is saved on the folder."""
    try:
        image = Image.open(file.stream)
        image.load()
    except (UnidentifiedImageError, OSError):
        return "That doesn't look like a picture. Use a .jpg or .png."
    image = ImageOps.fit(image.convert("RGB"), _BANNER_SIZE, Image.LANCZOS)
    path = os.path.join(_banners_dir(), f"folder_{folder.id}.jpg")
    image.save(path, "JPEG", quality=86)
    folder.banner_path = path
    return None

def _type_entry(key, label, count, folder, user):
    if folder and folder.banner_path and os.path.isfile(folder.banner_path):
        banner = f"/api/course-guides/folders/{folder.id}/banner?v={int(os.path.getmtime(folder.banner_path))}"
    else:
        banner = f"img/guide-banners/{key if key in TYPE_LABELS else 'folder'}.svg"
    return {"value": key, "label": label, "count": count, "banner_url": banner,
            "folder_id": folder.id if folder else None, "can_edit": _can_edit_folder(user, key, folder)}

@course_guide_bp.get("/course-guides/types")
@login_required
def list_guide_types():
    """Every folder in the library, the built-in two first: each type in use,
    each folder a teacher made (even before anything is in it), and "Other"
    for untyped uploads, with how many documents it holds and its banner."""
    user = current_user()
    counts = dict(db.session.query(CourseGuide.doc_type, func.count(CourseGuide.id)).group_by(CourseGuide.doc_type).all())
    folders = {f.type_key: f for f in GuideFolder.query.all()}
    found = ({t for t in counts if t} | set(folders)) - {_UNTYPED}
    ordered = [t for t in TYPE_LABELS if t in found] + sorted(found - set(TYPE_LABELS), key=str.lower)
    types = [_type_entry(t, type_label(t), counts.get(t, 0), folders.get(t), user) for t in ordered]
    if counts.get(None):
        types.append(_type_entry(_UNTYPED, "Other", counts[None], folders.get(_UNTYPED), user))
    return jsonify({"status": "ok", "types": types})

@course_guide_bp.post("/course-guides/types/banner")
@staff_required
def set_guide_type_banner():
    """Change a folder's banner by its type. The built-in two, "Other" and
    types that so far only have uploads get their folder row here."""
    user = current_user()
    raw = request.form.get("type")
    key = _UNTYPED if raw == _UNTYPED else normalize_type(raw)
    if not key:
        return jsonify({"status": "error", "message": "Pick a folder."}), 400
    folder = GuideFolder.query.filter(func.lower(GuideFolder.type_key) == key.lower()).first()
    if not _can_edit_folder(user, key, folder):
        return jsonify({"status": "error", "message": "Only the teacher who made this folder can change its banner."}), 403
    if not request.files.get("banner"):
        return jsonify({"status": "error", "message": "Choose a picture for the banner."}), 400
    if folder is None:
        # Built-in folders and "Other" belong to everyone; a typed-in one to
        # the teacher who first gives it a banner.
        owner = None if key in TYPE_LABELS or key == _UNTYPED else user.id
        folder = GuideFolder(type_key=key, created_by=owner)
        db.session.add(folder)
        db.session.flush()
    error = _save_banner(folder, request.files["banner"])
    if error:
        db.session.rollback()
        return jsonify({"status": "error", "message": error}), 400
    db.session.commit()
    if key == _UNTYPED:
        count = CourseGuide.query.filter(CourseGuide.doc_type.is_(None)).count()
        return jsonify({"status": "ok", "type": _type_entry(key, "Other", count, folder, user)})
    count = CourseGuide.query.filter(CourseGuide.doc_type == key).count()
    return jsonify({"status": "ok", "type": _type_entry(key, type_label(key), count, folder, user)})

@course_guide_bp.post("/course-guides/folders")
@staff_required
def create_guide_folder():
    """A teacher's own folder (a new type), with an optional banner picture."""
    user = current_user()
    key = normalize_type(request.form.get("name"))
    if not key:
        return jsonify({"status": "error", "message": "Give the folder a name."}), 400
    if key == _UNTYPED or GuideFolder.query.filter(func.lower(GuideFolder.type_key) == key.lower()).first():
        return jsonify({"status": "error", "message": "A folder with that name already exists."}), 409
    if key in TYPE_LABELS and user.role != "admin":
        return jsonify({"status": "error", "message": "That folder is built in. Pick another name."}), 409
    folder = GuideFolder(type_key=key, created_by=user.id)
    db.session.add(folder)
    db.session.flush()
    if request.files.get("banner"):
        error = _save_banner(folder, request.files["banner"])
        if error:
            db.session.rollback()
            return jsonify({"status": "error", "message": error}), 400
    db.session.commit()
    count = CourseGuide.query.filter(CourseGuide.doc_type == key).count()
    return jsonify({"status": "ok", "type": _type_entry(key, type_label(key), count, folder, user)}), 201

@course_guide_bp.post("/course-guides/folders/<int:folder_id>/banner")
@staff_required
def set_guide_folder_banner(folder_id):
    user = current_user()
    folder = GuideFolder.query.get_or_404(folder_id)
    if not _can_edit_folder(user, folder.type_key, folder):
        return jsonify({"status": "error", "message": "Only the teacher who made this folder can change its banner."}), 403
    if not request.files.get("banner"):
        return jsonify({"status": "error", "message": "Choose a picture for the banner."}), 400
    error = _save_banner(folder, request.files["banner"])
    if error:
        return jsonify({"status": "error", "message": error}), 400
    db.session.commit()
    count = CourseGuide.query.filter(CourseGuide.doc_type == folder.type_key).count()
    return jsonify({"status": "ok", "type": _type_entry(folder.type_key, type_label(folder.type_key), count, folder, user)})

@course_guide_bp.get("/course-guides/folders/<int:folder_id>/banner")
@login_required
def get_guide_folder_banner(folder_id):
    folder = GuideFolder.query.get_or_404(folder_id)
    if not folder.banner_path or not os.path.isfile(folder.banner_path):
        return jsonify({"status": "error", "message": "No banner."}), 404
    return send_file(folder.banner_path, mimetype="image/jpeg", max_age=86400)

@course_guide_bp.get("/course-guides/<int:guide_id>/file")
@login_required
def open_course_guide(guide_id):
    """The guide itself, opened in the browser. The library is shared, so any
    signed-in user may read any guide in it."""
    guide = CourseGuide.query.get_or_404(guide_id)
    if not guide.file_path or not os.path.isfile(guide.file_path):
        return jsonify({"status": "error", "message": "This guide's file isn't available on the server."}), 404
    return send_file(guide.file_path, as_attachment=False)

@course_guide_bp.post("/course-guides")
@login_required
def upload_course_guide():
    """Add a course guide to the shared library. If the exact same file has
    already been uploaded by anyone — under any subject — reuse that existing
    entry instead of storing a duplicate row, so the library and search
    results stay clean. A file's content doesn't change depending on which
    lesson someone happened to be building when they (re-)uploaded it."""
    user = current_user()

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded."}), 400

    file = request.files["file"]
    subject = (request.form.get("subject") or "").strip()
    title = (request.form.get("title") or "").strip() or file.filename
    # Budget of Work, Curriculum Guide, or any type the teacher names.
    doc_type = normalize_type(request.form.get("doc_type"))

    if file.filename == "" or not _allowed(file.filename):
        return jsonify({"status": "error", "message": "Only .docx, .dotx, or .pdf files are allowed."}), 400
    if not subject:
        return jsonify({"status": "error", "message": "Tell us which subject this course guide is for."}), 400

    file_bytes = file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # The official copy wins when a teacher uploads a file that is already
    # one of the built-in DepEd guides.
    existing = (CourseGuide.query.filter(CourseGuide.file_hash == file_hash)
                .order_by(CourseGuide.is_builtin.desc()).first())
    if existing:
        return jsonify({"status": "ok", "course_guide": existing.to_dict(), "duplicate": True}), 200

    filename = secure_filename(f"{user.id}_{file.filename}")
    save_path = os.path.join(_guides_dir(), filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    try:
        extracted = text_extract.extract_text(save_path)
    except Exception as exc:
        current_app.logger.warning("Course guide text extraction failed: %s", exc)
        extracted = ""

    guide = CourseGuide(
        uploader_id=user.id,
        subject=subject,
        title=title,
        file_path=save_path,
        file_hash=file_hash,
        extracted_text=extracted,
        doc_type=doc_type,
    )
    db.session.add(guide)
    db.session.commit()

    return jsonify({"status": "ok", "course_guide": guide.to_dict(), "duplicate": False}), 201


# ---- Supplementary sources: a student's own files beside the Budget of Work.
# Private to the uploader (never in the shared library); Alan reads their text.

def _sources_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "sources")
    os.makedirs(path, exist_ok=True)
    return path


@course_guide_bp.post("/sources")
@login_required
def upload_source():
    user = current_user()
    file = request.files.get("file")
    if not file or file.filename == "" or not _allowed(file.filename):
        return jsonify({"status": "error", "message": "Only .docx, .dotx, or .pdf files are allowed."}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    save_path = os.path.join(_sources_dir(), f"{user.id}_{uuid.uuid4().hex}.{ext}")
    file.save(save_path)
    try:
        extracted = text_extract.extract_text(save_path)
    except Exception as exc:
        current_app.logger.warning("Supplementary source text extraction failed: %s", exc)
        extracted = ""
    if not (extracted or "").strip():
        os.remove(save_path)
        return jsonify({
            "status": "error",
            "message": "I couldn't read any text in that file. If it's a scanned PDF, save it from Word as a .docx instead.",
        }), 400

    source = SupplementarySource(owner_id=user.id, filename=secure_filename(file.filename) or file.filename,
                                 file_path=save_path, extracted_text=extracted)
    db.session.add(source)
    db.session.commit()
    return jsonify({"status": "ok", "source": source.to_dict()}), 201


@course_guide_bp.delete("/sources/<int:source_id>")
@login_required
def delete_source(source_id):
    source = SupplementarySource.query.filter_by(id=source_id, owner_id=current_user().id).first()
    if not source:
        return jsonify({"status": "error", "message": "That source couldn't be found."}), 404
    try:
        os.remove(source.file_path)
    except OSError:
        pass
    db.session.delete(source)
    db.session.commit()
    return jsonify({"status": "ok"})
