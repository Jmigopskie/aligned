from flask import Blueprint, jsonify, request, send_file

from routes.auth_routes import login_required
from services import image_store

image_bp = Blueprint("images", __name__)


@image_bp.post("/images")
@login_required
def upload_image():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "message": "Choose an image to upload."}), 400
    # One byte over the limit is enough to know it's too big, without reading
    # an arbitrarily large body into memory.
    data = file.read(image_store.MAX_IMAGE_BYTES + 1)
    try:
        saved = image_store.save_image(data)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok", "url": f"/api/images/{saved['id']}", **saved})


# Any logged-in user: a public plan or format shows its pictures to everyone
# who can open it, and the id is unguessable.
@image_bp.get("/images/<image_id>")
@login_required
def get_image(image_id):
    path = image_store.image_path(image_id)
    if not path:
        return jsonify({"status": "error", "message": "Image not found."}), 404
    return send_file(path, max_age=86400)
