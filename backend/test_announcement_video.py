"""Self-check for a tutorial video attached to an announcement.

An admin uploads the video in small chunks (gunicorn stops any one request
after 120 s, which a large upload over a school connection would outlast).
What matters: the chunks join into the stored file; anything that is not an
MP4 or WebM is refused and leaves nothing behind; the size cap and chunk order
hold; the upload id can't reach outside its folder; only admins upload; only
the announcement's audience can watch, with seeking (Range); and deleting the
announcement removes its video.

Run it directly: `venv/Scripts/python test_announcement_video.py`.
"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.announcement import Announcement
from models.section import Section
from models.user import User
from routes import announcement_routes

# The first bytes of a real MP4: size, then "ftyp" at offset 4.
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000


def make_user(name, role):
    user = User(full_name=name, email=name.replace(" ", ".").lower() + "@example.test", role=role)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def client_for(app, user):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
    return client


def send(client, ann_id, data, upload_id="upload-0001", size=1500):
    """Upload `data` in `size`-byte chunks; returns the last response."""
    pieces = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
    res = None
    for index, piece in enumerate(pieces):
        res = client.post(f"/api/admin/announcements/{ann_id}/video/chunks", data={
            "upload_id": upload_id, "index": str(index), "total": str(len(pieces)),
            "chunk": (io.BytesIO(piece), "chunk.bin"),
        }, content_type="multipart/form-data")
        if res.status_code != 200:
            return res
    return res


def main():
    app = create_app()
    uploads = tempfile.mkdtemp()
    app.config.update(TESTING=True, UPLOAD_FOLDER=uploads)
    try:
        with app.app_context():
            admin = User.query.filter_by(role="admin").first()
            teacher = make_user("Vid Teacher", "teacher")
            outsider_teacher = make_user("Other Teacher", "teacher")
            section = Section(name="Video 7", teacher_id=teacher.id, join_code="VID777")
            db.session.add(section)
            db.session.commit()

            everyone = Announcement(author_id=admin.id, title="How to use AlignED", message="Watch this.")
            scoped = Announcement(author_id=teacher.id, title="Section only", message="Hi.", section_id=section.id)
            db.session.add_all([everyone, scoped])
            db.session.commit()
            admin_client = client_for(app, admin)

            # Chunks join into the stored file, and the announcement says so.
            res = send(admin_client, everyone.id, MP4)
            assert res.status_code == 200, res.get_json()
            body = res.get_json()["announcement"]
            assert body["has_video"] and body["video_size"] == len(MP4), body
            stored = db.session.get(Announcement, everyone.id).video_path
            assert open(stored, "rb").read() == MP4
            assert not os.listdir(os.path.join(uploads, "videos", "tmp")), "part file left behind"
            print("  chunks join OK")

            # Not a video: refused, nothing left behind, the earlier video kept.
            res = send(admin_client, everyone.id, b"%PDF-1.7 not a video" * 50, upload_id="upload-0002")
            assert res.status_code == 400, res.get_json()
            assert not os.listdir(os.path.join(uploads, "videos", "tmp"))
            assert open(stored, "rb").read() == MP4
            print("  non-video refused OK")

            # Over the size cap, and out-of-order chunks.
            real_cap = announcement_routes.MAX_VIDEO_BYTES
            announcement_routes.MAX_VIDEO_BYTES = 3000
            try:
                res = send(admin_client, everyone.id, MP4, upload_id="upload-0003")
                assert res.status_code == 400, res.get_json()
            finally:
                announcement_routes.MAX_VIDEO_BYTES = real_cap
            res = admin_client.post(f"/api/admin/announcements/{everyone.id}/video/chunks", data={
                "upload_id": "upload-0004", "index": "1", "total": "3",
                "chunk": (io.BytesIO(b"x"), "c.bin")}, content_type="multipart/form-data")
            assert res.status_code == 400, res.get_json()
            print("  size cap and chunk order OK")

            # The upload id is a token, never a path.
            res = send(admin_client, everyone.id, MP4, upload_id="../../evil")
            assert res.status_code == 400, res.get_json()
            print("  upload id checked OK")

            # Only admins upload.
            res = send(client_for(app, teacher), everyone.id, MP4, upload_id="upload-0005")
            assert res.status_code == 403, res.status_code
            print("  admins only OK")

            # Watching: the audience can, with seeking; others can't.
            res = client_for(app, teacher).get(f"/api/announcements/{everyone.id}/video",
                                               headers={"Range": "bytes=0-9"})
            assert res.status_code == 206 and res.data == MP4[:10], res.status_code
            res.close()
            assert send(admin_client, scoped.id, MP4, upload_id="upload-0006").status_code == 200
            res = client_for(app, outsider_teacher).get(f"/api/announcements/{scoped.id}/video")
            assert res.status_code == 404, res.status_code
            res = client_for(app, teacher).get(f"/api/announcements/{scoped.id}/video")
            assert res.status_code == 200, res.status_code
            res.close()
            print("  viewing limited to the audience OK")

            # Removing the video, and deleting the announcement, remove the file.
            res = admin_client.delete(f"/api/admin/announcements/{scoped.id}/video")
            assert res.status_code == 200 and not res.get_json()["announcement"]["has_video"]
            scoped_file = os.path.join(uploads, "videos", f"announcement-{scoped.id}.mp4")
            assert not os.path.exists(scoped_file)
            assert admin_client.delete(f"/api/admin/announcements/{everyone.id}").status_code == 200
            assert not os.path.exists(stored)
            print("  remove and delete clean up OK")
    finally:
        shutil.rmtree(uploads, ignore_errors=True)
    print("announcement video OK")


if __name__ == "__main__":
    main()
