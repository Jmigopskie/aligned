"""Self-check for draft autosave on PATCH /api/lesson-plans/<id> and the
status/limit filters the Create Lesson Plan page's "continue where you left
off" strip reads.

The generator autosaves by creating the row once and PATCHing it thereafter, so
what matters here is that the update is owner-only, that it refuses a plan
already submitted or graded (editing then would change what the teacher
assessed), and that a partial payload updates only the keys it carries instead
of blanking the rest.

Run it directly: `venv/Scripts/python test_lesson_plan_drafts.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.section import Section, SectionMembership


def make_user(name, role):
    user = User(full_name=name, email=name.replace(" ", ".").lower() + "@example.test", role=role)
    user.set_password("password123")
    db.session.add(user)
    return user


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        teacher = make_user("Tess Teacher", "teacher")
        student = make_user("Stu Student", "student")
        other = make_user("Other Student", "student")
        db.session.commit()
        teacher_id, student_id, other_id = teacher.id, student.id, other.id

        fmt = LessonPlanFormat(owner_id=teacher_id, name="DLP")
        db.session.add(fmt)
        db.session.commit()
        format_id = fmt.id

        section = Section(teacher_id=teacher_id, name="Class A", join_code="CLSA01")
        db.session.add(section)
        db.session.commit()
        section_id = section.id
        db.session.add(SectionMembership(section_id=section_id, student_id=student_id))
        db.session.commit()

        client = app.test_client()

        def login(user_id):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

        login(student_id)

        # --- Create: the first autosave makes exactly one draft row ---
        res = client.post("/api/lesson-plans", json={
            "format_id": format_id,
            "title": "Photosynthesis",
            "field_values": {"objectives": "Name the stages."},
        })
        assert res.status_code == 201, res.status_code
        plan = res.get_json()["lesson_plan"]
        plan_id = plan["id"]
        assert plan["status"] == "draft", plan
        assert plan["field_values"] == {"objectives": "Name the stages."}

        # --- Update: subsequent autosaves reuse that row ---
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={
            "field_values": {"objectives": "Name the stages.", "materials": "Leaves"},
        })
        assert res.status_code == 200, res.status_code
        updated = res.get_json()["lesson_plan"]
        assert updated["id"] == plan_id, "autosave must not create a second row"
        assert updated["field_values"]["materials"] == "Leaves"
        # A payload carrying only field_values must leave the title alone.
        assert updated["title"] == "Photosynthesis", updated
        assert LessonPlan.query.filter_by(user_id=student_id).count() == 1

        # An empty title falls back rather than saving a nameless plan.
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "   "})
        assert res.get_json()["lesson_plan"]["title"] == "Untitled Lesson Plan"
        client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "Photosynthesis"})

        # Rich values round-trip (the manually styled HTML the editor keeps).
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={
            "rich_field_values": {"objectives": "<strong>Name</strong> the stages."},
        })
        assert "<strong>" in res.get_json()["lesson_plan"]["rich_field_values"]["objectives"]

        # --- Another user's plan is off limits ---
        login(other_id)
        assert client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "Hijacked"}).status_code == 403
        assert LessonPlan.query.get(plan_id).title == "Photosynthesis"

        # --- A submitted plan stops accepting edits ---
        login(student_id)
        res = client.post(f"/api/lesson-plans/{plan_id}/submit", json={"section_id": section_id})
        assert res.status_code == 200, res.get_json()
        res = client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "Sneaky edit"})
        assert res.status_code == 409, res.status_code
        assert LessonPlan.query.get(plan_id).title == "Photosynthesis"

        # --- And so does a reviewed one ---
        login(teacher_id)
        assert client.post(f"/api/lesson-plans/{plan_id}/review",
                           json={"score": 90, "feedback": "Good"}).status_code == 200
        login(student_id)
        assert client.patch(f"/api/lesson-plans/{plan_id}", json={"title": "After grading"}).status_code == 409

        # --- Filters behind the "continue where you left off" strip ---
        for title in ["Draft One", "Draft Two", "Draft Three"]:
            client.post("/api/lesson-plans", json={"format_id": format_id, "title": title})

        def titles(qs):
            res = client.get("/api/lesson-plans" + qs)
            assert res.status_code == 200, res.status_code
            return [p["title"] for p in res.get_json()["lesson_plans"]]

        drafts = titles("?status=draft")
        assert "Photosynthesis" not in drafts, "the reviewed plan must not show as a draft"
        assert sorted(drafts) == ["Draft One", "Draft Three", "Draft Two"], drafts
        assert titles("?status=reviewed") == ["Photosynthesis"]
        assert len(titles("?status=draft&limit=2")) == 2, "limit caps the strip"
        assert len(titles("")) == 4, "no filter still returns everything"
        assert len(titles("?status=bogus")) == 4, "a junk status is ignored, not an error"
        # Newest edit first, so the strip's first card is the most recent work.
        assert titles("?status=draft")[0] == "Draft Three", titles("?status=draft")

        # A plan that doesn't exist is a 404, not a 500.
        assert client.patch("/api/lesson-plans/99999", json={"title": "Nope"}).status_code == 404

    print("lesson plan drafts OK")


main()
