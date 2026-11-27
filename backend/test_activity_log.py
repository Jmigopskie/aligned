"""Self-check for the admin's activity log (Batch 2): what each user did and
when, seen only by admins. Every successful change through the API is logged
in plain words (plus failed logins); autosave edits don't flood it.

Run it directly: `python test_activity_log.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models.activity_log import ActivityLog  # noqa: E402
from models.format import LessonPlanFormat  # noqa: E402
from models.user import User  # noqa: E402


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        tess = User(full_name="Tess Teacher", email="tess.log@example.test", role="teacher")
        for u in (tess, admin):
            u.set_password("password123")
        db.session.add(tess)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=tess.id, name="DLP")
        db.session.add(fmt)
        db.session.commit()
        client = app.test_client()

        # A failed login is logged with the email tried, no user.
        client.post("/api/login", json={"email": "tess.log@example.test", "password": "wrong"})
        client.post("/api/login", json={"email": "tess.log@example.test", "password": "password123"})
        res = client.post("/api/lesson-plans", json={"format_id": fmt.id, "title": "Measuring tools"})
        plan_id = res.get_json()["lesson_plan"]["id"]
        for n in range(5):  # autosave: one entry, not five
            client.patch(f"/api/lesson-plans/{plan_id}", json={"title": f"Measuring tools {n}"})
        client.get(f"/api/lesson-plans/{plan_id}")  # reading isn't logged
        client.post("/api/logout")

        rows = ActivityLog.query.order_by(ActivityLog.id).all()
        got = [(r.user_id, r.action) for r in rows]
        # Autosave edits aren't activity worth showing: not logged at all.
        assert got == [(None, "Failed login"), (tess.id, "Logged in"), (tess.id, "Saved a lesson plan"),
                       (tess.id, "Logged out")], got
        assert "tess.log@example.test" in rows[0].detail and f"#{plan_id}" in rows[2].detail, rows[2].detail
        assert all(r.created_at for r in rows) and rows[1].ip
        assert "password" not in " ".join(r.detail or "" for r in rows).lower()
        print("  actions logged in plain words, autosave not flooding OK")

        # Only an admin reads it; filters by user and action; newest first.
        with client.session_transaction() as s:
            s["user_id"] = tess.id
        assert client.get("/api/admin/activity").status_code == 403
        with client.session_transaction() as s:
            s["user_id"] = admin.id
        data = client.get("/api/admin/activity").get_json()
        assert data["status"] == "ok" and data["total"] >= 4, data
        # A row from before the cleanup that isn't relevant stays out of sight.
        db.session.add(ActivityLog(user_id=tess.id, action="Edited a lesson plan", detail=f"Lesson plan #{plan_id}"))
        db.session.commit()
        assert all(e["action"] != "Edited a lesson plan"
                   for e in client.get(f"/api/admin/activity?user_id={tess.id}").get_json()["entries"])
        # Her timeline: her failed sign-in too, and the plan by its title.
        timeline = client.get(f"/api/admin/activity?user_id={tess.id}").get_json()["entries"]
        assert [e["action"] for e in timeline] == ["Logged out", "Saved a lesson plan", "Logged in", "Failed login"], timeline
        assert '"Measuring tools 4"' in timeline[1]["detail"], timeline[1]["detail"]
        # People: one row each, with counts by kind.
        people = client.get("/api/admin/activity/people?q=tess").get_json()["people"]
        assert len(people) == 1 and people[0]["counts"]["sign-in"] == 1 and people[0]["counts"]["plan"] == 1, people
        assert people[0]["last_active"]
        print("  people summary, relevant-only timeline, plan titles OK")
        first = data["entries"][0]
        assert {"user_name", "user_email", "role", "action", "detail", "ip", "created_at"} <= set(first), first
        mine = client.get(f"/api/admin/activity?user_id={tess.id}").get_json()["entries"]
        assert mine and all(e["user_email"] == "tess.log@example.test" for e in mine if e["user_id"])
        assert mine[0]["action"] == "Logged out", "newest first"
        found = client.get("/api/admin/activity?q=failed").get_json()["entries"]
        assert [e["action"] for e in found] == ["Failed login"], found
        print("  admin-only list, filters, newest first OK")

        # The IP is the one the proxy saw (the last X-Forwarded-For entry), not
        # one the client typed in; a failed login's non-email text isn't kept.
        client.post("/api/logout")
        client.post("/api/login", json={"email": "MyPassw0rd!", "password": "x"},
                    headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})
        row = ActivityLog.query.order_by(ActivityLog.id.desc()).first()
        assert row.action == "Failed login" and row.ip == "198.51.100.7", (row.action, row.ip)
        assert "MyPassw0rd" not in (row.detail or ""), row.detail
        print("  real IP, no typed secrets OK")
    print("activity log OK")


if __name__ == "__main__":
    main()
