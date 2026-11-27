"""Self-check: a public lesson plan is readable by anyone but downloadable only
by its author (or admin / the section's teacher). Run: `python test_public_plan_download.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        author, reader = (User(full_name=n, email=f"{n}@example.test", role="teacher") for n in ("author", "reader"))
        for u in (author, reader):
            u.set_password("password123")
            db.session.add(u)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=author.id, name="F")
        db.session.add(fmt)
        db.session.commit()
        plan = LessonPlan(user_id=author.id, format_id=fmt.id, title="Shared", is_public=True)
        db.session.add(plan)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = reader.id
        assert client.get(f"/api/lesson-plans/{plan.id}").status_code == 200
        res = client.get(f"/api/lesson-plans/{plan.id}/export")
        assert res.status_code == 403, res.status_code
        assert "not downloaded" in res.get_json()["message"]
    print("public plan: viewable, not downloadable OK")


if __name__ == "__main__":
    main()
