"""Self-check for points: teachers allot them, and Alan writing a student's
lesson plan (Building Proficiency) costs 30 points once — writing it again is
free, a new one with too few points is refused, Guided (its chat and saving
the plan) is free, a Guided plan Alan later writes is charged once, and
teachers never pay.

The provider is never called: ai_service._call is stubbed. Run it directly:
`python test_points.py`.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import FormatField, LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.points import Build, PointEvent
from models.section import Section, SectionMembership
from models.user import User
from services import ai_service


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        tina = User(full_name="Tina Teacher", email="tina.pts@example.test", role="teacher")
        oscar = User(full_name="Oscar Other", email="oscar.pts@example.test", role="teacher")
        ana = User(full_name="Ana Student", email="ana.pts@example.test", role="student")
        ben = User(full_name="Ben Student", email="ben.pts@example.test", role="student")
        for u in (tina, oscar, ana, ben):
            u.set_password("password123")
        db.session.add_all([tina, oscar, ana, ben])
        db.session.commit()
        sec = Section(teacher_id=tina.id, name="7-A", join_code="PTS001")
        db.session.add(sec)
        db.session.commit()
        db.session.add_all([SectionMembership(section_id=sec.id, student_id=s.id) for s in (ana, ben)])
        fmt = LessonPlanFormat(name="Plain", owner_id=tina.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="motivation", label="Motivation"))
        legacy = LessonPlan(user_id=ben.id, format_id=fmt.id, title="Made before points",
                            created_at=datetime(2026, 10, 20))
        db.session.add(legacy)
        db.session.commit()
        ids = {"tina": tina.id, "oscar": oscar.id, "ana": ana.id, "ben": ben.id}
        sec_id, fid, legacy_id = sec.id, fmt.id, legacy.id
        ai_service._call = lambda system, parts, label: {"motivation": "A short game."}
        ai_service.owl_chat = lambda *a, **k: {"reply": "Try a short game.", "choices": []}
        client = app.test_client()

        def login(name):
            with client.session_transaction() as s:
                s["user_id"] = ids[name]

        def points(name):
            return db.session.get(User, ids[name]).points

        def generate(**extra):
            return client.post("/api/generate/full", json={"format_id": fid, "include_keys": ["motivation"],
                                                           "context": {"topic": "Parts"}, **extra})

        # --- No points: Alan won't write a plan, with the reason; Guided is free ---
        login("ana")
        res = client.post("/api/builds", json={"run_key": "run-1"})
        assert res.status_code == 402 and res.get_json()["code"] == "no_points", res.get_json()
        assert "Guided" in res.get_json()["message"]
        assert generate(run_key="run-1").status_code == 402
        chat = client.post("/api/generate/chat", json={"format_id": fid, "field_key": "motivation",
                                                       "message": "Ideas?", "run_key": "g-1"})
        assert chat.status_code == 200, chat.get_json()
        res = client.post("/api/lesson-plans", json={"format_id": fid, "title": "Guided", "run_key": "g-1",
                                                     "generation_mode": "step"})
        assert res.status_code == 201 and res.get_json()["lesson_plan"]["build_id"] is None, res.get_json()
        guided_id = res.get_json()["lesson_plan"]["id"]
        # Having Alan write that Guided plan later still costs points.
        assert generate(plan_id=guided_id).status_code == 402
        assert points("ana") == 0
        print("  no points: Building refused, Guided free OK")

        # --- The section's teacher gives points; another teacher can't ---
        login("oscar")
        assert client.post(f"/api/sections/{sec_id}/points", json={"student_ids": [ids["ana"]], "add": 30}).status_code == 403
        login("tina")
        res = client.post(f"/api/sections/{sec_id}/points", json={"student_ids": [ids["ana"], ids["ben"]], "add": 45})
        assert res.status_code == 200, res.get_json()
        got = {s["id"]: s["points"] for s in res.get_json()["students"]}
        assert got == {ids["ana"]: 45, ids["ben"]: 45} and res.get_json()["cost"] == 30, got
        assert client.post(f"/api/sections/{sec_id}/points", json={"student_ids": [ids["tina"]], "add": 5}).status_code == 400
        res = client.post(f"/api/sections/{sec_id}/points", json={"student_ids": [ids["ben"]], "add": -100})
        assert {s["id"]: s["points"] for s in res.get_json()["students"]}[ids["ben"]] == 0  # never below zero
        assert client.get(f"/api/sections/{sec_id}/points").status_code == 200
        print("  teacher allots points OK")

        # --- Starting a plan costs 30, once; coming back is free ---
        login("ana")
        assert client.get("/api/me").get_json()["user"]["points"] == 45
        res = client.post("/api/builds", json={"run_key": "run-1"})
        assert res.status_code == 200 and res.get_json()["charged"] is True and res.get_json()["points"] == 15, res.get_json()
        again = client.post("/api/builds", json={"run_key": "run-1"}).get_json()
        assert again["charged"] is False and points("ana") == 15, again
        assert generate(run_key="run-1").status_code == 200
        res = client.post("/api/lesson-plans", json={"format_id": fid, "title": "Plan 1", "run_key": "run-1"})
        assert res.status_code == 201, res.get_json()
        plan_id = res.get_json()["lesson_plan"]["id"]
        assert res.get_json()["lesson_plan"]["build_id"] == Build.query.filter_by(run_key="run-1").one().id
        # Reopened later (no run key, just the plan): no second build charge,
        # but its first build finished, so writing again is a regenerate (5).
        assert client.post("/api/builds", json={"plan_id": plan_id}).get_json()["charged"] is False
        assert generate(plan_id=plan_id).status_code == 200
        assert points("ana") == 10
        # A second plan needs 30 more, and only 10 are left.
        assert client.post("/api/builds", json={"run_key": "run-2"}).status_code == 402
        assert generate(run_key="run-2").status_code == 402
        assert points("ana") == 10
        print("  one charge per plan, 5 per regenerate OK")

        # --- The Guided plan, written by Alan once there are points: charged once ---
        login("tina")
        client.post(f"/api/sections/{sec_id}/points", json={"student_ids": [ids["ana"]], "add": 20})
        login("ana")
        res = client.post("/api/builds", json={"plan_id": guided_id, "run_key": "g-1"})
        assert res.status_code == 200 and res.get_json()["charged"] is True and points("ana") == 0, res.get_json()
        assert db.session.get(LessonPlan, guided_id).build_id is not None
        assert client.post("/api/builds", json={"plan_id": guided_id}).get_json()["charged"] is False
        assert generate(plan_id=guided_id).status_code == 200
        print("  Guided plan written by Alan later OK")

        # --- Someone else's plan or run is no way in; an older plan needs no
        # build, but it was written before, so rewriting it is a regenerate ---
        login("ben")
        assert generate(plan_id=plan_id).status_code == 402
        assert generate(run_key="run-1").status_code == 402
        res = generate(plan_id=legacy_id)  # Ben has 0 points left
        assert res.status_code == 402 and "Regenerating uses 5 points" in res.get_json()["message"], res.get_json()
        print("  others' plans and older plans OK")

        # --- Teachers never pay ---
        login("tina")
        assert client.post("/api/builds", json={"run_key": "t-1"}).get_json()["charged"] is False
        assert generate().status_code == 200
        assert client.post("/api/lesson-plans", json={"format_id": fid, "title": "T"}).status_code == 201
        print("  teachers free OK")

        events = [(e.reason, e.delta) for e in PointEvent.query.filter_by(student_id=ids["ana"]).order_by(PointEvent.id)]
        assert events == [("grant", 45), ("build", -30), ("regenerate", -5), ("grant", 20), ("build", -30)], events
    print("points OK")


if __name__ == "__main__":
    main()
