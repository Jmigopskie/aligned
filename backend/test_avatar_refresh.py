"""Self-check: changing the profile photo a second time shows the new photo.
The photo's address carries a version that changes with the file, so the
browser can't keep showing a cached copy of the old one. Same for the banner.

Run it directly: `python test_avatar_refresh.py`.
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


def png(color):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    buf.seek(0)
    return buf


def main():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        user = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user.id

        for kind in ("avatar", "banner"):
            urls, pixels = [], []
            for color in ((255, 0, 0), (0, 0, 255)):
                res = client.post(f"/api/me/{kind}", data={"file": (png(color), "p.png")},
                                  content_type="multipart/form-data")
                assert res.status_code == 200, res.get_json()
                url = res.get_json()["user"][f"{kind}_url"]
                got = client.get(url)
                assert got.status_code == 200, url
                urls.append(url)
                pixels.append(Image.open(io.BytesIO(got.data)).convert("RGB").getpixel((5, 5)))
            assert urls[0] != urls[1], f"{kind}: same address after a second upload: {urls}"
            assert pixels[1][2] > 200 and pixels[1][0] < 60, f"{kind}: second upload not served: {pixels}"
            print(f"  {kind} address changes with each upload OK")

    print("photo refresh OK")


if __name__ == "__main__":
    main()
