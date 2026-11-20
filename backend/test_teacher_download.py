"""Self-check: a teacher can download (Word export) a lesson plan a student
submitted to their section, and no one else's teacher can.

Run it directly: `python test_teacher_download.py`.
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


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        def make_user(name, role):
            u = User(full_name=name, email=f"{name.lower()}@example.test", role=role)
            u.set_password("password123")
            db.session.add(u)
            db.session.commit()
            return u

        teacher = make_user("Tess", "teacher")
        other = make_user("Otto", "teacher")
        student = make_user("Sam", "student")
        section = Section(teacher_id=teacher.id, name="TLE 7-A", join_code="TDL001")
        db.session.add(section)
        db.session.commit()
        db.session.add(SectionMembership(section_id=section.id, student_id=student.id))
        fmt = LessonPlanFormat(owner_id=teacher.id, name="DLP")
        db.session.add(fmt)
        db.session.commit()
        plan = LessonPlan(user_id=student.id, format_id=fmt.id, title="Measuring tools")
        db.session.add(plan)
        db.session.commit()
        plan_id = plan.id

        client = app.test_client()

        def login(user):
            with client.session_transaction() as sess:
                sess["user_id"] = user.id

        def export_status():
            res = client.get(f"/api/lesson-plans/{plan_id}/export")
            res.close()
            return res.status_code

        # A draft stays the student's own: their teacher can't pull it yet.
        login(teacher)
        assert export_status() == 403

        login(student)
        res = client.post(f"/api/lesson-plans/{plan_id}/submit", json={"section_id": section.id})
        assert res.status_code == 200, res.get_json()

        # Submitted: the section's teacher downloads it; another teacher can't.
        login(teacher)
        assert export_status() == 200
        login(other)
        assert export_status() == 403

        path = LessonPlan.query.get(plan_id).docx_path
        if path and os.path.exists(path):
            os.remove(path)  # export writes into the real generated folder

    print("teacher download OK")


main()
