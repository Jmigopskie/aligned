"""Self-check for Regenerate (Batch 1): once a plan's first build has finished,
every Building Proficiency write costs a student 5 points (decided by the
server), refunded when the write fails or comes back empty. The first build,
and retrying it after a failure, stay free; teachers never pay.

The provider is never called: ai_service.generate_full_streaming is stubbed.
Run it directly: `python test_regenerate_points.py`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import FormatField, LessonPlanFormat
from models.points import Build, PointEvent
from models.section import Section, SectionMembership
from models.user import User
from services import ai_service

BEHAVIOUR = {"mode": "ok"}


def fake_stream(context, fields, course_guide_text="", include_keys=None, course_guide_citation="", written=None):
    if BEHAVIOUR["mode"] == "raise":
        raise RuntimeError("model down")
    values = {"motivation": "" if BEHAVIOUR["mode"] == "empty" else "A short game."}
    yield {"type": "section_done", "section": "x", "index": 1, "total": 1, "values": values}
    yield {"type": "complete", "values": values, "missing": [], "missing_labels": []}


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        tina = User(full_name="Tina", email="tina.regen@example.test", role="teacher")
        ana = User(full_name="Ana", email="ana.regen@example.test", role="student", points=40)
        for u in (tina, ana):
            u.set_password("password123")
        db.session.add_all([tina, ana])
        db.session.commit()
        sec = Section(teacher_id=tina.id, name="7-A", join_code="RGN001")
        db.session.add(sec)
        db.session.commit()
        db.session.add(SectionMembership(section_id=sec.id, student_id=ana.id))
        fmt = LessonPlanFormat(name="Plain", owner_id=tina.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="motivation", label="Motivation"))
        db.session.commit()
        ids, fid = {"tina": tina.id, "ana": ana.id}, fmt.id
        ai_service.generate_full_streaming = fake_stream
        client = app.test_client()

        def login(name):
            with client.session_transaction() as s:
                s["user_id"] = ids[name]

        def points():
            return db.session.get(User, ids["ana"]).points

        def write(run_key="r-1", mode="ok"):
            BEHAVIOUR["mode"] = mode
            res = client.post("/api/generate/full-stream", json={
                "format_id": fid, "include_keys": ["motivation"], "context": {"topic": "Parts"}, "run_key": run_key})
            body = res.get_data(as_text=True)
            db.session.expire_all()
            return res.status_code, [json.loads(l) for l in body.splitlines() if l.strip()] if res.status_code == 200 else body

        login("ana")
        assert client.post("/api/builds", json={"run_key": "r-1"}).get_json()["charged"] is True
        assert points() == 10  # 40 - 30 for the first build

        # first_build_free: a first build that fails is retried free...
        status, events = write(mode="raise")
        assert status == 200 and events[-1]["type"] == "error" and points() == 10, (events, points())
        assert db.session.query(Build).filter_by(run_key="r-1").one().completed_at is None
        # ...and the first one that finishes is free too, and marks the build finished.
        status, events = write()
        assert status == 200 and events[-1]["type"] == "complete" and points() == 10, (events, points())
        assert db.session.query(Build).filter_by(run_key="r-1").one().completed_at is not None
        print("  first build free, finished once it completes OK")

        # regenerate_charged
        status, events = write()
        assert status == 200 and points() == 5, points()
        print("  a regenerate costs 5 OK")

        # refund_on_failure: an error mid-way, or the parts back empty, returns the 5.
        status, events = write(mode="raise")
        assert events[-1]["type"] == "error" and points() == 5, points()
        status, events = write(mode="empty")
        assert points() == 5, points()
        print("  failed or empty regenerates refunded OK")

        # short_points_refused: 5 - 5 = 0 after one more; then refused.
        assert write()[0] == 200 and points() == 0
        status, body = write()
        assert status == 402 and "5 points" in json.loads(body)["message"] and points() == 0, body
        print("  too few points refused OK")

        reasons = [(e.reason, e.delta) for e in PointEvent.query.filter_by(student_id=ids["ana"]).order_by(PointEvent.id)]
        assert reasons == [("build", -30), ("regenerate", -5), ("regenerate", -5), ("regenerate_refund", 5),
                           ("regenerate", -5), ("regenerate_refund", 5), ("regenerate", -5)], reasons

        # teacher_never_charged
        login("tina")
        for _ in range(3):
            assert write(run_key="t-1")[0] == 200
        assert PointEvent.query.filter(PointEvent.student_id == ids["tina"]).count() == 0
        print("  teachers never charged OK")
    print("regenerate points OK")


if __name__ == "__main__":
    main()
