"""Uploaded pictures for formats and plans.

Files are named by a random id under uploads/images/, so the id is the only
handle anyone ever holds. Every lookup checks the id's exact shape first,
which is what stops a crafted id from walking out of the folder.
"""
import io
import os
import re
import uuid

from flask import current_app
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACCEPTED = {"PNG", "JPEG", "GIF", "WEBP"}
# python-docx embeds PNG and JPEG but not WebP, so anything else is re-encoded
# to PNG on the way in rather than failing later at export.
_KEEP_AS = {"PNG": "png", "JPEG": "jpg"}


def images_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "images")
    os.makedirs(path, exist_ok=True)
    return path


def image_path(image_id):
    if not isinstance(image_id, str) or not _ID_RE.match(image_id):
        return None
    for ext in ("png", "jpg"):
        path = os.path.join(images_dir(), f"{image_id}.{ext}")
        if os.path.isfile(path):
            return path
    return None


def save_image(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Images must be 5 MB or smaller.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        img = None
    if img is None or img.format not in _ACCEPTED:
        raise ValueError("That file isn't an image AlignED can use. Use PNG, JPG, GIF or WebP.")

    image_id = uuid.uuid4().hex
    ext = _KEEP_AS.get(img.format)
    if ext:
        with open(os.path.join(images_dir(), f"{image_id}.{ext}"), "wb") as fh:
            fh.write(data)
    else:
        img.convert("RGBA").save(os.path.join(images_dir(), f"{image_id}.png"), "PNG")
    return {"id": image_id, "width_px": img.width, "height_px": img.height}
