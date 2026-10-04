import os
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, session, current_app, send_file
from PIL import Image, UnidentifiedImageError

from extensions import db
from models.user import User

auth_bp = Blueprint("auth", __name__)

_AVATAR_SIZE = 256
_BANNER_SIZE = (1600, 500)

def _avatars_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "avatars")
    os.makedirs(path, exist_ok=True)
    return path

def _banners_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "banners")
    os.makedirs(path, exist_ok=True)
    return path

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"status": "error", "message": "Not authenticated."}), 401
        return view_func(*args, **kwargs)
    return wrapper

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"status": "error", "message": "Not authenticated."}), 401
        user = current_user()
        if not user or user.role != "admin":
            return jsonify({"status": "error", "message": "Admin access required."}), 403
        return view_func(*args, **kwargs)
    return wrapper

def current_user():
    user_id = session.get("user_id")
    return User.query.get(user_id) if user_id else None

@auth_bp.post("/signup")
def signup():
    """Public self-signup only ever creates student accounts. Teacher and
    admin accounts must be created by an administrator from the admin panel
    so not just anyone can register as a teacher."""
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not full_name or not email or not password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "Email is already registered."}), 409

    user = User(full_name=full_name, email=email, role="student")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"status": "error", "message": "Invalid email or password."}), 401

    if not user.is_active:
        return jsonify({
            "status": "error",
            "message": "Your account has been disabled. Contact your administrator.",
        }), 403

    session["user_id"] = user.id
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify({"status": "ok"})

@auth_bp.get("/me")
@login_required
def me():
    user = current_user()
    if not user or not user.is_active:
        session.pop("user_id", None)
        return jsonify({"status": "error", "message": "Not authenticated."}), 401
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.patch("/me")
@login_required
def update_me():
    """Let a signed-in user edit their own profile — full name and email.
    Role and active status are managed by an admin, never here."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    if "full_name" in data:
        full_name = (data.get("full_name") or "").strip()
        if not full_name:
            return jsonify({"status": "error", "message": "Full name can't be empty."}), 400
        user.full_name = full_name

    if "email" in data:
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"status": "error", "message": "Email can't be empty."}), 400
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user.id:
            return jsonify({"status": "error", "message": "That email is already in use."}), 409
        user.email = email

    db.session.commit()
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.post("/me/onboarded")
@login_required
def mark_onboarded():
    """The owl's first-sign-in tour was finished or skipped: never start it on
    its own again, on any device. (It can still be replayed from the FAQ.)"""
    user = current_user()
    if user.onboarded_at is None:
        user.onboarded_at = datetime.utcnow()
        db.session.commit()
    return jsonify({"status": "ok", "user": user.to_dict()})


@auth_bp.post("/me/password")
@login_required
def change_password():
    user = current_user()
    data = request.get_json(silent=True) or {}

    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not user.check_password(current_password):
        return jsonify({"status": "error", "message": "Current password is incorrect."}), 400
    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "New password must be at least 8 characters."}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({"status": "ok"})

@auth_bp.post("/me/avatar")
@login_required
def upload_avatar():
    user = current_user()
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"status": "error", "message": "No file selected."}), 400

    try:
        image = Image.open(file.stream)
        image.load()
    except (UnidentifiedImageError, OSError):
        return jsonify({"status": "error", "message": "That doesn't look like a valid image file."}), 400

    # Center-crop to a square, then downscale to one fixed size — keeps every
    # profile picture small and consistent regardless of what was actually
    # uploaded (a wide screenshot, a full-resolution phone photo, etc.).
    image = image.convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize(
        (_AVATAR_SIZE, _AVATAR_SIZE), Image.LANCZOS
    )

    save_path = os.path.join(_avatars_dir(), f"user_{user.id}.jpg")
    image.save(save_path, "JPEG", quality=88)

    user.avatar_path = save_path
    db.session.commit()
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.delete("/me/avatar")
@login_required
def delete_avatar():
    user = current_user()
    old_path = user.avatar_path
    user.avatar_path = None
    db.session.commit()
    if old_path and os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.get("/avatars/<int:user_id>")
@login_required
def get_avatar(user_id):
    user = User.query.get_or_404(user_id)
    if not user.avatar_path or not os.path.isfile(user.avatar_path):
        return jsonify({"status": "error", "message": "No profile picture."}), 404
    return send_file(user.avatar_path, mimetype="image/jpeg", max_age=3600)

@auth_bp.post("/me/banner")
@login_required
def upload_banner():
    """Only teachers have a dashboard banner — a student's banner is always
    borrowed from their teacher (see User.effective_banner), so a student
    uploading their own would never be seen."""
    user = current_user()
    if user.role != "teacher":
        return jsonify({"status": "error", "message": "Only teachers can set a dashboard banner."}), 403

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"status": "error", "message": "No file selected."}), 400

    try:
        image = Image.open(file.stream)
        image.load()
    except (UnidentifiedImageError, OSError):
        return jsonify({"status": "error", "message": "That doesn't look like a valid image file."}), 400

    # Center-crop to the banner's wide aspect ratio, then downscale — keeps
    # every banner the same shape regardless of what was actually uploaded.
    image = image.convert("RGB")
    target_w, target_h = _BANNER_SIZE
    width, height = image.size
    target_ratio = target_w / target_h
    current_ratio = width / height
    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        image = image.crop((left, 0, left + new_width, height))
    else:
        new_height = int(width / target_ratio)
        top = (height - new_height) // 2
        image = image.crop((0, top, width, top + new_height))
    image = image.resize(_BANNER_SIZE, Image.LANCZOS)

    save_path = os.path.join(_banners_dir(), f"user_{user.id}.jpg")
    image.save(save_path, "JPEG", quality=88)

    user.banner_path = save_path
    db.session.commit()
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.delete("/me/banner")
@login_required
def delete_banner():
    user = current_user()
    old_path = user.banner_path
    user.banner_path = None
    db.session.commit()
    if old_path and os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
    return jsonify({"status": "ok", "user": user.to_dict()})

@auth_bp.get("/banners/<int:user_id>")
@login_required
def get_banner(user_id):
    user = User.query.get_or_404(user_id)
    if not user.banner_path or not os.path.isfile(user.banner_path):
        return jsonify({"status": "error", "message": "No banner set."}), 404
    return send_file(user.banner_path, mimetype="image/jpeg", max_age=3600)
