"""Self-check: a student creates lesson plans only once enrolled in a section
(an active one). Not enrolled, the plan can't be created and nothing is
generated for it; teachers are not affected, and a student can still open
and edit plans they already have.

Run it directly: `python test_enrollment_gate.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import LessonPlanFormat, FormatField
from models.lesson_plan import LessonPlan
from models.section import Section, SectionMembership
from models.user import User


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        teacher = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        alone = User(full_name="Al Alone", email="al@example.test", role="student")
        archived = User(full_name="Ari Archived", email="ari@example.test", role="student")
        enrolled = User(full_name="Eva Enrolled", email="eva@example.test", role="student")
        for u in (teacher, alone, archived, enrolled):
            u.set_password("password123")
        db.session.add_all([teacher, alone, archived, enrolled])
        db.session.commit()
        active = Section(teacher_id=teacher.id, name="7-A", join_code="ACT001")
        old = Section(teacher_id=teacher.id, name="7-Old", join_code="OLD001", is_active=False)
        db.session.add_all([active, old])
        db.session.commit()
        db.session.add_all([SectionMembership(section_id=active.id, student_id=enrolled.id),
                            SectionMembership(section_id=old.id, student_id=archived.id)])
        fmt = LessonPlanFormat(name="Plain", owner_id=teacher.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="topic", label="Topic", field_type="text"))
        old_plan = LessonPlan(user_id=alone.id, format_id=fmt.id, title="Made before")
        db.session.add(old_plan)
        db.session.commit()
        fid, plan_id = fmt.id, old_plan.id
        client = app.test_client()

        def login(u):
            with client.session_transaction() as sess:
                sess["user_id"] = u.id

        def create():
            return client.post("/api/lesson-plans", json={"format_id": fid, "title": "New plan", "field_values": {"topic": "x"}})

        def generate():
            return client.post("/api/generate/full", json={"format_id": fid, "include_keys": []})

        def chat():
            return client.post("/api/generate/chat", json={"format_id": fid, "field_key": "topic", "message": "Help"})

        # --- Not enrolled (or only in an archived section): refused, with a reason ---
        for student in (alone, archived):
            login(student)
            me = client.get("/api/me").get_json()["user"]
            assert me["enrolled"] is False, me
            for call in (create, generate, chat):
                res = call()
                assert res.status_code == 403 and res.get_json().get("code") == "not_enrolled", (student.full_name, call.__name__, res.get_json())
        print("  not enrolled: refused OK")

        # --- Their existing plans still open and save ---
        login(alone)
        assert client.get(f"/api/lesson-plans/{plan_id}").status_code == 200
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "Made before", "field_values": {"topic": "edited"}})
        assert res.status_code == 200, res.get_json()
        print("  existing plans still editable OK")

        # --- Enrolled students and teachers create as before ---
        login(enrolled)
        assert client.get("/api/me").get_json()["user"]["enrolled"] is True
        assert create().status_code in (200, 201), create().get_json()
        login(teacher)
        assert create().status_code in (200, 201)
        print("  enrolled student and teacher create OK")

    print("enrollment gate OK")


if __name__ == "__main__":
    main()
