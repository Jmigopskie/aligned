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

        # --- Per-mode progress -------------------------------------------------
        # field_values keeps holding whatever the active mode shows, so export and
        # submission are untouched; the other mode's work rides along in
        # mode_values. This is what lets Guided and Building Proficiency be two
        # drafts of the plan rather than one shared one.
        login(student_id)
        res = client.post("/api/lesson-plans", json={
            "format_id": format_id,
            "title": "Two modes",
            "generation_mode": "full",
            "field_values": {"flow": "written by Building Proficiency"},
            "mode_values": {
                "field_values": {"flow": "written in Guided"},
                "rich_field_values": {"flow": "<b>written in Guided</b>"},
                "step_index": 2,
            },
        })
        assert res.status_code == 201, res.status_code
        two = res.get_json()["lesson_plan"]
        two_id = two["id"]
        assert two["field_values"]["flow"] == "written by Building Proficiency"
        assert two["mode_values"]["field_values"]["flow"] == "written in Guided", two["mode_values"]
        assert two["mode_values"]["step_index"] == 2

        # Switching mode swaps the two slots, which is one ordinary PATCH.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={
            "generation_mode": "step",
            "field_values": {"flow": "written in Guided"},
            "rich_field_values": {"flow": "<b>written in Guided</b>"},
            "mode_values": {"field_values": {"flow": "written by Building Proficiency"},
                            "rich_field_values": {}, "step_index": 0},
        })
        assert res.status_code == 200, res.status_code
        swapped = res.get_json()["lesson_plan"]
        assert swapped["generation_mode"] == "step"
        assert swapped["field_values"]["flow"] == "written in Guided"
        assert swapped["mode_values"]["field_values"]["flow"] == "written by Building Proficiency"

        # A PATCH that omits mode_values leaves the stored slot alone, so an
        # autosave carrying only the active mode cannot wipe the other one.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={"title": "Renamed"})
        kept = res.get_json()["lesson_plan"]
        assert kept["title"] == "Renamed"
        assert kept["mode_values"]["field_values"]["flow"] == "written by Building Proficiency", kept["mode_values"]

        # The guard must be `if "mode_values" in data:` not `if data.get("mode_values"):`.
        # The latter would silently drop intentional clears (key present, value falsy),
        # so a PATCH sending {"mode_values": {}} would lose data. This check pins the
        # distinction: an explicit empty dict must be written, not skipped.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={"mode_values": {}})
        cleared = res.get_json()["lesson_plan"]
        assert cleared["mode_values"] == {}, f"Expected empty dict, got {cleared['mode_values']}"
        # The next PATCH omits the key entirely, so it must not repopulate the slot;
        # the cleared value must persist. This pins the other side of the guard.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={"title": "Double-check"})
        still_clear = res.get_json()["lesson_plan"]
        assert still_clear["mode_values"] == {}, "Omitting mode_values must not restore a cleared slot"

        # A plan saved before this existed reads as an empty slot rather than
        # None, so the page can use it without a null check.
        plain = LessonPlan(user_id=student_id, format_id=format_id, title="Old plan")
        plain.set_values({"flow": "legacy"})
        db.session.add(plain)
        db.session.commit()
        assert plain.to_dict()["mode_values"] == {}, plain.to_dict()["mode_values"]

        # Junk in the column does not crash a read.
        plain.mode_values = "not json"
        db.session.commit()
        assert plain.to_dict()["mode_values"] == {}

        # Valid JSON that is not an object (e.g., an array) degrades to {}.
        plain.mode_values = "[1, 2, 3]"
        db.session.commit()
        assert plain.to_dict()["mode_values"] == {}

        # --- Setup context round trip -----------------------------------------
        # Reopening a saved plan used to drop the teacher straight back into the
        # "Before we start" form, because the only setup detail the row kept was
        # grade_level, and that as a display string ("Grade 7 - Campos") rather
        # than its parts. The course guide in particular is required by the
        # page's gate, so a plan with no stored guide could never reopen past
        # setup no matter how much content it held. The whole setup block now
        # rides along verbatim.
        login(student_id)
        setup_ctx = {
            "setup": {
                "teacher": "John Mark V. Aguirre",
                "subject": "ICT",
                "topic": "Conversion of number system",
                "levelType": "k12",
                "collegeProgram": "",
                "collegeYear": "",
                "k12Grade": "Grade 7",
                "section": "Campos",
            },
            "courseGuide": {"id": 3, "title": "ICT Grade 7 Guide", "subject": "ICT"},
        }
        res = client.post("/api/lesson-plans", json={
            "format_id": format_id,
            "title": "With setup",
            "subject": "ICT",
            "setup_context": setup_ctx,
        })
        assert res.status_code == 201, res.status_code
        ctx_id = res.get_json()["lesson_plan"]["id"]

        got = client.get(f"/api/lesson-plans/{ctx_id}").get_json()["lesson_plan"]
        assert got["setup_context"]["setup"]["topic"] == "Conversion of number system", got["setup_context"]
        assert got["setup_context"]["setup"]["k12Grade"] == "Grade 7"
        assert got["setup_context"]["setup"]["section"] == "Campos"
        # The guide is the one the gate insists on, so it must survive.
        assert got["setup_context"]["courseGuide"]["id"] == 3, got["setup_context"]

        # A PATCH that omits it leaves it alone, exactly like mode_values: the
        # autosave sometimes carries only field values.
        res = client.patch(f"/api/lesson-plans/{ctx_id}", json={"title": "Renamed again"})
        kept = res.get_json()["lesson_plan"]
        assert kept["setup_context"]["courseGuide"]["id"] == 3, kept["setup_context"]

        # Present but empty clears it, which is a deliberate instruction.
        res = client.patch(f"/api/lesson-plans/{ctx_id}", json={"setup_context": {}})
        assert res.get_json()["lesson_plan"]["setup_context"] == {}

        # A plan saved before this column existed reads as {}, never None, so
        # the page can use it without a null check.
        legacy = LessonPlan(user_id=student_id, format_id=format_id, title="Legacy")
        db.session.add(legacy)
        db.session.commit()
        assert legacy.to_dict()["setup_context"] == {}, legacy.to_dict()["setup_context"]

        # Junk degrades to {} rather than raising.
        legacy.setup_context = "not json"
        db.session.commit()
        assert legacy.to_dict()["setup_context"] == {}

    print("lesson plan drafts OK")


main()
