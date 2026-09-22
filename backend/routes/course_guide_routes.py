import hashlib
import os

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from extensions import db
from models.course_guide import CourseGuide
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

@course_guide_bp.get("/course-guides")
@login_required
def search_course_guides():
    subject = (request.args.get("subject") or "").strip()

    query = CourseGuide.query
    if subject:
        query = query.filter(CourseGuide.subject.ilike(f"%{subject}%"))

    guides = query.order_by(CourseGuide.created_at.desc()).limit(25).all()
    return jsonify({"status": "ok", "course_guides": [g.to_dict() for g in guides]})

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

    if file.filename == "" or not _allowed(file.filename):
        return jsonify({"status": "error", "message": "Only .docx, .dotx, or .pdf files are allowed."}), 400
    if not subject:
        return jsonify({"status": "error", "message": "Tell us which subject this course guide is for."}), 400

    file_bytes = file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    existing = CourseGuide.query.filter(CourseGuide.file_hash == file_hash).first()
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
    )
    db.session.add(guide)
    db.session.commit()

    return jsonify({"status": "ok", "course_guide": guide.to_dict(), "duplicate": False}), 201
