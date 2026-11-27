"""Self-check: teachers rate students' plans 1-5 stars once public or submitted
to their class; one rating per teacher, re-rating replaces it; the average shows
on the plan. Run: `python test_plan_rating.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan, PlanRating
from models.section import Section


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        def user(name, role):
            u = User(full_name=name, email=f"{name}@example.test", role=role)
            u.set_password("password123")
            db.session.add(u)
            return u
        stu, t1, t2, t3 = user("stu", "student"), user("t1", "teacher"), user("t2", "teacher"), user("t3", "teacher")
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=t1.id, name="F")
        sec = Section(teacher_id=t3.id, name="A", join_code="AAA111")
        db.session.add_all([fmt, sec])
        db.session.commit()
        public = LessonPlan(user_id=stu.id, format_id=fmt.id, title="Pub", is_public=True)
        private = LessonPlan(user_id=stu.id, format_id=fmt.id, title="Priv")
        submitted = LessonPlan(user_id=stu.id, format_id=fmt.id, title="Sub", section_id=sec.id, status="submitted")
        teachers_own = LessonPlan(user_id=t1.id, format_id=fmt.id, title="Mine", is_public=True)
        db.session.add_all([public, private, submitted, teachers_own])
        db.session.commit()

        client = app.test_client()

        def rate(uid, plan, stars):
            with client.session_transaction() as sess:
                sess["user_id"] = uid
            return client.post(f"/api/lesson-plans/{plan.id}/rating", json={"stars": stars})

        assert rate(t1.id, public, 4).status_code == 200
        res = rate(t2.id, public, 5)
        assert res.get_json()["lesson_plan"]["rating_avg"] == 4.5
        res = rate(t1.id, public, 2)  # re-rate replaces
        body = res.get_json()["lesson_plan"]
        assert (body["rating_avg"], body["rating_count"]) == (3.5, 2), body
        assert rate(t1.id, private, 3).status_code == 403
        assert rate(t1.id, submitted, 3).status_code == 403  # not their class
        assert rate(t3.id, submitted, 3).status_code == 200
        assert rate(t2.id, teachers_own, 3).status_code == 403  # teachers' plans aren't rated
        assert rate(stu.id, public, 5).status_code == 403
        assert rate(t1.id, public, 6).status_code == 400
        assert rate(t1.id, public, True).status_code == 400

        db.session.delete(public)
        db.session.commit()
        assert PlanRating.query.filter_by(plan_id=public.id).count() == 0
    print("plan rating OK")


if __name__ == "__main__":
    main()
