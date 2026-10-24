"""Self-check: library documents carry any type a teacher names, so step 6
can show one folder per type. "Budget of Work" / "Curriculum Guide" (any
case) map to the built-in keys; anything else is kept as typed.

Run it directly: `python test_guide_types.py`.
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

import docx

from app import create_app
from extensions import db
from models.user import User


def docx_bytes(text):
    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def main():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        teacher = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = teacher.id

        def upload(text, doc_type):
            res = client.post("/api/course-guides", content_type="multipart/form-data", data={
                "file": (io.BytesIO(docx_bytes(text)), "g.docx"), "subject": "Zeta Craft",
                "title": text, "doc_type": doc_type})
            assert res.status_code == 201, res.get_json()
            return res.get_json()["course_guide"]

        las = upload("Zeta LAS one", "  Learning   Activity Sheet ")
        assert las["doc_type"] == "Learning Activity Sheet" and las["type_label"] == "Learning Activity Sheet", las
        bow = upload("Zeta BoW", "budget of work")
        assert bow["doc_type"] == "budget_of_work" and bow["type_label"] == "Budget of Work", bow
        none = upload("Zeta untyped", "")
        assert none["doc_type"] is None and none["type_label"] == "Other", none
        long = upload("Zeta long", "x" * 200)
        assert len(long["doc_type"]) <= 60
        print("  free-text types OK")

        types = client.get("/api/course-guides/types").get_json()["types"]
        labels = [t["label"] for t in types]
        assert "Learning Activity Sheet" in labels and "Budget of Work" in labels, labels
        assert labels.index("Budget of Work") < labels.index("Learning Activity Sheet"), "built-in types first"
        print("  types list OK")

        got = client.get("/api/course-guides", query_string={"subject": "Zeta Craft", "doc_type": "learning activity sheet"})
        titles = [g["title"] for g in got.get_json()["course_guides"]]
        assert titles == ["Zeta LAS one"], titles
        print("  filter by a teacher's type OK")

    print("guide types OK")


if __name__ == "__main__":
    main()
