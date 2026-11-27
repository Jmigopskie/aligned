"""Self-check: Manage Users gets each account's sections (a student's joined
ones, a teacher's taught ones, A to Z) so the page can group by section, and
an account in none has an empty list (Unenrolled).
Run: `python test_admin_user_sections.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.section import Section, SectionMembership


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()

        def user(name, role):
            u = User(full_name=name, email=f"{name.lower()}@example.test", role=role)
            u.set_password("password123")
            db.session.add(u)
            return u
        tess, ana, ben = user("Tess", "teacher"), user("Ana", "student"), user("Ben", "student")
        db.session.commit()
        b7, a7 = Section(teacher_id=tess.id, name="ICT 7-B", join_code="B7B7B7"), \
            Section(teacher_id=tess.id, name="ICT 7-A", join_code="A7A7A7")
        db.session.add_all([b7, a7])
        db.session.commit()
        db.session.add_all([SectionMembership(section_id=b7.id, student_id=ana.id),
                            SectionMembership(section_id=a7.id, student_id=ana.id)])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["user_id"] = admin.id
        users = {u["full_name"]: u for u in client.get("/api/admin/users").get_json()["users"]}
        assert [s["name"] for s in users["Ana"]["sections"]] == ["ICT 7-A", "ICT 7-B"], users["Ana"]
        assert [s["name"] for s in users["Tess"]["sections"]] == ["ICT 7-A", "ICT 7-B"]
        assert users["Ana"]["sections"][0]["teacher_name"] == "Tess"
        assert users["Ben"]["sections"] == [], "Unenrolled"
    print("admin user sections OK")


if __name__ == "__main__":
    main()
