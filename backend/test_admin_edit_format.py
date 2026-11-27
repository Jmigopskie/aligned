"""Self-check: an admin edits any teacher's format in the system (user,
2026-11-28: names that came with a school's file, like the two signatories at
the end of the TUP-Cavite DLP, are removed from its document); other teachers
still can't. Admin > Formats lists teachers' formats to open.
Run: `python test_admin_edit_format.py`."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

import docx  # noqa: E402

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models.format import LessonPlanFormat  # noqa: E402
from models.user import User  # noqa: E402


def main():
    upload = tempfile.mkdtemp()
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=upload)
    from config import Config
    Config.UPLOAD_FOLDER = upload
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        tess, otto = (User(full_name=n, email=f"{n}@example.test", role="teacher") for n in ("tess", "otto"))
        for u in (tess, otto):
            u.set_password("password123")
            db.session.add(u)
        db.session.commit()
        path = os.path.join(upload, "tup.docx")
        d = docx.Document()
        for line in ("DETAILED LESSON PLAN", "Topic:", "Prepared by:", "Ma. Teacher Name", "Prof. Supervisor Name"):
            d.add_paragraph(line)
        d.save(path)
        fmt = LessonPlanFormat(name="Detailed Lesson Plan (TUP-Cavite)", owner_id=tess.id, source_file_path=path,
                               fields_reviewed=True)
        db.session.add(fmt)
        db.session.commit()
        fid = fmt.id
        client = app.test_client()

        def as_(user):
            with client.session_transaction() as s:
                s["user_id"] = user.id

        as_(otto)
        assert client.patch(f"/api/formats/{fid}/content",
                            json={"edits": [{"anchor_index": 4, "action": "delete"}]}).status_code == 403
        as_(admin)
        listed = client.get("/api/admin/teacher-formats").get_json()["formats"]
        assert [f["name"] for f in listed] == ["Detailed Lesson Plan (TUP-Cavite)"], listed
        # The two names at the end go, last first so the positions hold.
        for anchor in (4, 3):
            res = client.patch(f"/api/formats/{fid}/content", json={"edits": [{"anchor_index": anchor, "action": "delete"}]})
            assert res.status_code == 200, res.get_json()
        text = "\n".join(p.text for p in docx.Document(db.session.get(LessonPlanFormat, fid).source_file_path).paragraphs)
        assert "Teacher Name" not in text and "Supervisor Name" not in text and "Prepared by:" in text, text
        assert client.patch(f"/api/formats/{fid}", json={"name": "TUP-Cavite DLP"}).status_code == 200
    print("admin edits a teacher's format OK")


if __name__ == "__main__":
    main()
