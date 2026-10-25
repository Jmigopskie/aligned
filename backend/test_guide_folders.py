"""Self-check for the library's folders: one per document type, each with a
banner. Teachers make folders (a name and a banner picture) and change the
banner of their own; the built-in types and untyped uploads have folders too.

Run it directly: `python test_guide_folders.py`.
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
from models.course_guide import CourseGuide
from models.user import User


def png(color=(30, 120, 90), size=(900, 500)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


def main():
    upload = tempfile.mkdtemp()
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=upload)
    with app.app_context():
        tina = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        oscar = User(full_name="Oscar Other", email="oscar@example.test", role="teacher")
        sam = User(full_name="Sam Student", email="sam@example.test", role="student")
        for u in (tina, oscar, sam):
            u.set_password("password123")
        db.session.add_all([tina, oscar, sam])
        db.session.commit()
        db.session.add_all([
            CourseGuide(uploader_id=tina.id, subject="Zeta", title="Zeta BoW", file_path="x", doc_type="budget_of_work"),
            CourseGuide(uploader_id=tina.id, subject="Zeta", title="Zeta loose file", file_path="y", doc_type=None),
        ])
        db.session.commit()
        client = app.test_client()

        def login(u):
            with client.session_transaction() as sess:
                sess["user_id"] = u.id

        def types():
            return {t["label"]: t for t in client.get("/api/course-guides/types").get_json()["types"]}

        # --- Built-in types and untyped uploads show up with default banners ---
        login(tina)
        t = types()
        assert t["Budget of Work"]["banner_url"].endswith("budget_of_work.svg") and t["Budget of Work"]["count"] >= 1, t
        assert t["Other"]["value"] == "untyped" and t["Other"]["count"] >= 1, t
        got = client.get("/api/course-guides", query_string={"subject": "Zeta", "doc_type": "untyped"}).get_json()
        assert [g["title"] for g in got["course_guides"]] == ["Zeta loose file"], got
        print("  built-in and untyped folders OK")

        # --- A teacher makes a folder with a banner; it shows while still empty ---
        res = client.post("/api/course-guides/folders", content_type="multipart/form-data",
                          data={"name": "Learning Activity Sheets", "banner": (png(), "b.png")})
        assert res.status_code == 201, res.get_json()
        las = types()["Learning Activity Sheets"]
        assert las["count"] == 0 and "/api/course-guides/folders/" in las["banner_url"] and las["can_edit"], las
        banner = client.get(las["banner_url"])
        assert banner.status_code == 200 and banner.mimetype == "image/jpeg"
        assert Image.open(io.BytesIO(banner.data)).size == (960, 540)
        dup = client.post("/api/course-guides/folders", content_type="multipart/form-data", data={"name": "learning activity sheets"})
        assert dup.status_code == 409
        bad = client.post("/api/course-guides/folders", content_type="multipart/form-data",
                          data={"name": "Bad", "banner": (io.BytesIO(b"not an image"), "x.png")})
        assert bad.status_code == 400
        print("  teacher folder with banner OK")

        # --- Only its maker (or an admin) changes the banner; students make none ---
        folder_id = las["folder_id"]
        login(oscar)
        assert not types()["Learning Activity Sheets"]["can_edit"]
        res = client.post(f"/api/course-guides/folders/{folder_id}/banner", content_type="multipart/form-data",
                          data={"banner": (png((200, 40, 40)), "r.png")})
        assert res.status_code == 403
        login(sam)
        res = client.post("/api/course-guides/folders", content_type="multipart/form-data", data={"name": "Mine"})
        assert res.status_code == 403
        login(tina)
        res = client.post(f"/api/course-guides/folders/{folder_id}/banner", content_type="multipart/form-data",
                          data={"banner": (png((200, 40, 40)), "r.png")})
        assert res.status_code == 200, res.get_json()
        print("  banner permissions OK")

        # --- Any teacher changes the built-in and "Other" banners, by type ---
        def set_type_banner(key):
            return client.post("/api/course-guides/types/banner", content_type="multipart/form-data",
                               data={"type": key, "banner": (png((40, 40, 200)), "t.png")})

        before = len(types())
        assert types()["Budget of Work"]["can_edit"] and types()["Other"]["can_edit"]
        assert set_type_banner("budget_of_work").status_code == 200
        res = set_type_banner("untyped")
        assert res.status_code == 200 and res.get_json()["type"]["label"] == "Other", res.get_json()
        t = types()
        assert len(t) == before, t  # "Other" got a banner, not a second folder
        assert "/api/course-guides/folders/" in t["Budget of Work"]["banner_url"], t
        assert "/api/course-guides/folders/" in t["Other"]["banner_url"] and t["Other"]["count"] >= 1, t
        login(oscar)
        assert set_type_banner("budget_of_work").status_code == 200  # shared, not Tina's
        assert set_type_banner("Learning Activity Sheets").status_code == 403  # Tina's own
        login(sam)
        assert not types()["Budget of Work"]["can_edit"]
        assert set_type_banner("budget_of_work").status_code == 403
        print("  built-in and Other banners OK")

    print("guide folders OK")


if __name__ == "__main__":
    main()
