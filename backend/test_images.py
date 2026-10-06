"""Self-check for image upload.

Teachers insert pictures into formats and plans. What must hold: a real image
is stored and served back, anything that is not an image (whatever its name
says) or is too big is refused before it reaches disk, WebP comes back as PNG
because Word export can't embed WebP, and only a logged-in user can read one.

Run it directly: `venv/Scripts/python test_images.py`.
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from PIL import Image

from app import create_app
from extensions import db
from models.user import User
from services import image_store


def png_bytes(fmt="PNG", size=(40, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def main():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        u = User(full_name="Img", email="img@example.test", role="teacher")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        uid = u.id

    anon = app.test_client()
    res = anon.post("/api/images", data={"file": (io.BytesIO(png_bytes()), "a.png")})
    assert res.status_code == 401, res.status_code

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post("/api/images", data={"file": (io.BytesIO(png_bytes()), "a.png")})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert len(body["id"]) == 32 and body["width_px"] == 40 and body["height_px"] == 20
    assert body["url"] == f"/api/images/{body['id']}"
    got = client.get(body["url"])
    assert got.status_code == 200 and got.data == png_bytes()
    got.close()
    assert anon.get(body["url"]).status_code == 401
    print("  png round trip OK")

    res = client.post("/api/images", data={"file": (io.BytesIO(b"not an image at all"), "evil.png")})
    assert res.status_code == 400, res.status_code
    big = b"\0" * (image_store.MAX_IMAGE_BYTES + 1)
    res = client.post("/api/images", data={"file": (io.BytesIO(big), "big.png")})
    assert res.status_code == 400, res.status_code
    with app.app_context():
        stored = os.listdir(os.path.join(app.config["UPLOAD_FOLDER"], "images"))
    assert len(stored) == 1, stored  # only the one good PNG
    print("  rejects junk and oversize OK")

    res = client.post("/api/images", data={"file": (io.BytesIO(png_bytes("WEBP")), "a.webp")})
    assert res.status_code == 200, res.get_json()
    with app.app_context():
        path = image_store.image_path(res.get_json()["id"])
    assert path.endswith(".png"), path
    print("  webp re-encoded to png OK")

    with app.app_context():
        assert image_store.image_path("../../etc/passwd") is None
        assert image_store.image_path("0" * 32) is None
    assert client.get("/api/images/" + "0" * 32).status_code == 404
    print("  lookups are safe OK")


if __name__ == "__main__":
    main()
    print("test_images: all OK")
