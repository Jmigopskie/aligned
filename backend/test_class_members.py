"""Self-check: a student who joined a class sees its teacher and members
(names only, never classmates' emails, A to Z, themselves marked); a student
who didn't join sees nothing. Run: `python test_class_members.py`."""
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
        def user(name, role):
            u = User(full_name=name, email=f"{name.split()[0].lower()}@example.test", role=role)
            u.set_password("password123")
            db.session.add(u)
            return u
        teacher, ana, ben, out = user("Tess Teacher", "teacher"), user("Ana Cruz", "student"), \
            user("Ben Reyes", "student"), user("Olly Out", "student")
        db.session.commit()
        sec = Section(teacher_id=teacher.id, name="ICT 7-A", join_code="ICT7AA")
        db.session.add(sec)
        db.session.commit()
        db.session.add_all([SectionMembership(section_id=sec.id, student_id=s.id) for s in (ben, ana)])
        db.session.commit()
        client = app.test_client()

        with client.session_transaction() as s:
            s["user_id"] = ana.id
        data = client.get(f"/api/sections/{sec.id}").get_json()["section"]
        assert data["teacher_name"] == "Tess Teacher"
        assert data["members"] == [{"name": "Ana Cruz", "you": True}, {"name": "Ben Reyes", "you": False}], data["members"]
        assert "@" not in str(data["members"]), "no classmates' emails"

        with client.session_transaction() as s:
            s["user_id"] = out.id
        assert client.get(f"/api/sections/{sec.id}").status_code == 403
    print("class members OK")


if __name__ == "__main__":
    main()
