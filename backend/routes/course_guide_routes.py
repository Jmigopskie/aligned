import hashlib
import os

from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import case, or_
from werkzeug.utils import secure_filename

from extensions import db
from models.course_guide import CourseGuide
from models.supplementary_source import SupplementarySource
import uuid
from routes.auth_routes import login_required, current_user
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
    if doc_type in DOC_TYPES:
        # Uploads from before the Budget of Work / Curriculum Guide split carry
        # no type, so they stay findable from either picker.
        query = query.filter(or_(CourseGuide.doc_type == doc_type, CourseGuide.doc_type.is_(None)))

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
    # Which picker it was dropped on: a Budget of Work or a Curriculum Guide.
    doc_type = (request.form.get("doc_type") or "").strip()
    doc_type = doc_type if doc_type in DOC_TYPES else None

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
