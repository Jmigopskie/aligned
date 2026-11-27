"""Self-check: a teacher's format is deleted only after an admin approves.
The uploader asks, admins are notified, an admin approves (gone) or declines
(kept); the uploader is told either way and can take the request back.
Run: `python test_format_deletion.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.notification import Notification


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        tess, otto = (User(full_name=n, email=f"{n}@example.test", role="teacher") for n in ("tess", "otto"))
        for u in (tess, otto):
            u.set_password("password123")
            db.session.add(u)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=tess.id, name="My DLP")
        used = LessonPlanFormat(owner_id=tess.id, name="Used")
        db.session.add_all([fmt, used])
        db.session.commit()
        db.session.add(LessonPlan(user_id=tess.id, format_id=used.id, title="Plan"))
        db.session.commit()
        fid, used_id = fmt.id, used.id
        client = app.test_client()

        def as_(user):
            with client.session_transaction() as s:
                s["user_id"] = user.id

        as_(otto)
        assert client.delete(f"/api/formats/{fid}").status_code == 403  # not theirs
        as_(tess)
        res = client.delete(f"/api/formats/{fid}").get_json()
        assert res["pending"] and res["format"]["delete_requested_at"], res
        assert db.session.get(LessonPlanFormat, fid), "still there until an admin approves"
        assert Notification.query.filter_by(user_id=admin.id, title="Format deletion request").count() == 1
        assert client.delete(f"/api/formats/{used_id}").status_code == 400  # in use: not even asked

        # She takes it back, then asks again.
        assert client.delete(f"/api/formats/{fid}/delete-request").get_json()["format"]["delete_requested_at"] is None
        client.delete(f"/api/formats/{fid}")

        as_(tess)
        assert client.get("/api/admin/format-deletions").status_code == 403
        as_(admin)
        pending = client.get("/api/admin/format-deletions").get_json()["formats"]
        assert [f["id"] for f in pending] == [fid], pending
        # Declined: kept, request cleared, she's told.
        assert client.post(f"/api/admin/formats/{fid}/deletion", json={"approve": False}).get_json()["deleted"] is False
        db.session.expire_all()
        assert db.session.get(LessonPlanFormat, fid).delete_requested_at is None
        assert Notification.query.filter_by(user_id=tess.id, title="Format kept").count() == 1
        assert client.post(f"/api/admin/formats/{fid}/deletion", json={"approve": True}).status_code == 400  # no request
        # Asked again and approved: gone, she's told.
        as_(tess)
        client.delete(f"/api/formats/{fid}")
        as_(admin)
        assert client.post(f"/api/admin/formats/{fid}/deletion", json={"approve": True}).get_json()["deleted"] is True
        db.session.expire_all()
        assert db.session.get(LessonPlanFormat, fid) is None
        assert Notification.query.filter_by(user_id=tess.id, title="Format deleted").count() == 1
    print("format deletion OK")


if __name__ == "__main__":
    main()
