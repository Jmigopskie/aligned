"""Self-check for supplementary sources: files a student uploads in the
Create Lesson Plan flow (step 6, beside the Budget of Work). They are private
to the uploader, Alan reads their text when writing the plan, and nobody else
can use or delete them.

Run it directly: `python test_supplementary_sources.py`.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

import docx

from app import create_app
from extensions import db
from models.user import User
from models.course_guide import CourseGuide
from models.supplementary_source import SupplementarySource
from routes.generate_routes import _resolve_guides, _resolve_sources


def make_user(name, role):
    user = User(full_name=name, email=name.replace(" ", ".").lower() + "@example.test", role=role)
    user.set_password("password123")
    db.session.add(user)
    return user


def docx_bytes(text):
    d = docx.Document()
    if text:
        d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        owner = make_user("Ana Student", "student")
        other = make_user("Ben Other", "student")
        db.session.commit()
        owner_id, other_id = owner.id, other.id
        client = app.test_client()

        def login(user_id):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

        def upload(data, name):
            return client.post("/api/sources", data={"file": (io.BytesIO(data), name)},
                               content_type="multipart/form-data")

        # --- Upload: text is read and kept, private to the uploader ---
        login(owner_id)
        res = upload(docx_bytes("Binary to decimal practice sheet with worked examples."), "notes.docx")
        assert res.status_code == 201, res.get_json()
        source = res.get_json()["source"]
        assert source["name"] == "notes.docx" and source["id"], source
        row = db.session.get(SupplementarySource, source["id"])
        assert row.owner_id == owner_id and "Binary to decimal" in row.extracted_text
        print("  upload OK")

        res = upload(b"plain text", "notes.txt")
        assert res.status_code == 400, res.status_code
        res = upload(docx_bytes(""), "empty.docx")
        assert res.status_code == 400 and "read" in res.get_json()["message"], res.get_json()
        print("  bad files refused OK")

        # --- Generation reads only the requester's own sources ---
        login(other_id)
        mine = upload(docx_bytes("Other student's private notes."), "theirs.docx").get_json()["source"]["id"]
        got = _resolve_sources({"source_ids": [source["id"], mine]}, db.session.get(User, owner_id))
        assert got == [("Supplementary source: notes.docx", row.extracted_text)], got
        assert _resolve_sources({}, db.session.get(User, owner_id)) == []
        assert _resolve_sources({"source_ids": "nonsense"}, db.session.get(User, owner_id)) == []
        print("  only own sources resolved OK")

        # --- Library sources: any number of Curriculum Guides and Budgets of
        # Work, Budget of Work first; the old single-id keys still work ---
        def guide(title, kind):
            g = CourseGuide(uploader_id=owner_id, subject="ICT", title=title, file_path="x", doc_type=kind)
            db.session.add(g)
            db.session.commit()
            return g.id
        cg, bow1, bow2 = guide("ICT CG", "curriculum_guide"), guide("G7 BoW", "budget_of_work"), guide("G8 BoW", "budget_of_work")
        with app.test_request_context():
            got, err = _resolve_guides({"guide_ids": [cg, bow1, bow2, bow1, "junk"]})
            assert err is None and [g.title for g in got] == ["G7 BoW", "G8 BoW", "ICT CG"], got
            got, err = _resolve_guides({"budget_of_work_id": bow1, "course_guide_id": cg})
            assert [g.title for g in got] == ["G7 BoW", "ICT CG"], got
            assert _resolve_guides({}) == ([], None)
            _, err = _resolve_guides({"guide_ids": [99999]})
            assert err is not None and err[1] == 404
        print("  several library sources OK")

        # --- Delete: owner only ---
        res = client.delete(f"/api/sources/{source['id']}")
        assert res.status_code == 404, res.status_code
        login(owner_id)
        res = client.delete(f"/api/sources/{source['id']}")
        assert res.status_code == 200, res.status_code
        assert db.session.get(SupplementarySource, source["id"]) is None
        print("  delete owner-only OK")

    print("supplementary sources OK")


if __name__ == "__main__":
    main()
