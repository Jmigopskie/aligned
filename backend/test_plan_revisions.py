"""Self-check for the stale-device guard on PATCH /api/lesson-plans/<id> and
the paper-size picker's export.

The same account open on a laptop and a phone used to be last-write-wins: an
older tab's autosave quietly replaced what the other device had just saved.
Each save now carries the revision it last saw, and a stale one is refused
with the newer plan instead of overwriting it.

Run it directly: `venv/Scripts/python test_plan_revisions.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document
from docx.shared import Inches

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from services.docx_service import apply_paper_size


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        user = User(full_name="Tess Teacher", email="tess@example.test", role="teacher")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=user.id, name="DLP")
        db.session.add(fmt)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user.id

        plan = client.post("/api/lesson-plans", json={
            "format_id": fmt.id, "field_values": {"objectives": "v0"},
        }).get_json()["lesson_plan"]
        plan_id = plan["id"]
        assert plan["revision"] == 0, plan

        # Laptop and phone both opened revision 0. The phone saves first.
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={
            "field_values": {"objectives": "phone"}, "base_revision": 0,
        })
        assert res.status_code == 200, res.get_json()
        assert res.get_json()["lesson_plan"]["revision"] == 1

        # The laptop, still on revision 0, is refused and handed the phone's copy.
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={
            "field_values": {"objectives": "stale laptop"}, "base_revision": 0,
        })
        assert res.status_code == 409, res.status_code
        body = res.get_json()
        assert body["code"] == "stale", body
        assert body["lesson_plan"]["field_values"]["objectives"] == "phone", body
        assert LessonPlan.query.get(plan_id).get_values()["objectives"] == "phone"

        # Caught up, the laptop saves normally.
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={
            "field_values": {"objectives": "laptop"}, "base_revision": 1,
        })
        assert res.status_code == 200 and res.get_json()["lesson_plan"]["revision"] == 2

        # A page from before this change sends no base_revision: still saves,
        # still bumps, so the newer pages notice it.
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "Old page"})
        assert res.status_code == 200 and res.get_json()["lesson_plan"]["revision"] == 3

        assert client.patch(f"/api/lesson-plans/{plan_id}", json={"base_revision": "x"}).status_code == 400

        # Paper size: portrait and landscape both get the chosen paper, and an
        # unknown or empty key leaves the format's own size.
        doc = Document()
        apply_paper_size(doc, "legal")
        s = doc.sections[0]
        assert (s.page_width, s.page_height) == (Inches(8.5), Inches(14))
        s.page_width, s.page_height = s.page_height, s.page_width
        apply_paper_size(doc, "folio")
        assert (s.page_width, s.page_height) == (Inches(13), Inches(8.5))
        apply_paper_size(doc, "tabloid")
        apply_paper_size(doc, None)
        assert (s.page_width, s.page_height) == (Inches(13), Inches(8.5))

        # Export picks it up from the saved plan.
        client.patch(f"/api/lesson-plans/{plan_id}", json={"setup_context": {"pageSize": "a4"}})
        res = client.get(f"/api/lesson-plans/{plan_id}/export")
        assert res.status_code == 200, res.status_code
        exported = Document(LessonPlan.query.get(plan_id).docx_path)
        assert abs(exported.sections[0].page_width.mm - 210) < 0.1, exported.sections[0].page_width.mm
        res.close()

    print("plan revisions + paper size OK")


main()
