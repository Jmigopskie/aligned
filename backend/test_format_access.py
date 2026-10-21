"""Self-check for who may upload formats and which formats a student sees.

Students cannot upload, edit or delete a format: only teachers upload. A
student picks from the built-in formats and the formats their own teacher
uploaded (the teacher of any class they joined), shared or not, and never
sees other teachers' public formats. Formats a student uploaded before this
rule stay openable so their old plans still work, but are no longer listed.

Run it directly: `python test_format_access.py`.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.section import Section, SectionMembership

REFUSAL = "Only teachers can upload or change formats. Pick a built-in format or one from your teacher."


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
        other = make_user("Otto Other", "teacher")
        student = make_user("Stu Student", "student")
        loner = make_user("Nina None", "student")
        db.session.commit()

        def fmt(owner, name, public=False, builtin=False):
            row = LessonPlanFormat(owner_id=owner.id, name=name, is_public=public, is_builtin=builtin)
            db.session.add(row)
            return row

        fmt(teacher, "T-private")
        fmt(teacher, "T-public", public=True)
        fmt(other, "O-public", public=True)
        fmt(other, "Test built-in", public=True, builtin=True)
        s_old = fmt(student, "S-old")
        section = Section(teacher_id=teacher.id, name="Class A", join_code="CLSA01")
        db.session.add(section)
        db.session.commit()
        db.session.add(SectionMembership(section_id=section.id, student_id=student.id))
        db.session.commit()

        builtins = {f.name for f in LessonPlanFormat.query.filter_by(is_builtin=True).all()}
        t_private_id = LessonPlanFormat.query.filter_by(name="T-private").one().id
        ids = {"teacher": teacher.id, "student": student.id, "loner": loner.id, "s_old": s_old.id}

        client = app.test_client()

        def login(user_id):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

        def names():
            res = client.get("/api/formats")
            assert res.status_code == 200, res.status_code
            return {f["name"] for f in res.get_json()["formats"]}

        # --- What each account sees ---
        login(ids["student"])
        got = names()
        assert got == {"T-private", "T-public"} | builtins, got
        print("  student sees built-ins and their teacher's formats OK")

        login(ids["loner"])
        got = names()
        assert got == builtins, got
        print("  student in no class sees only built-ins OK")

        login(ids["teacher"])
        got = names()
        assert {"T-private", "T-public", "O-public"} | builtins <= got, got
        print("  teacher list unchanged OK")

        # --- A student cannot write formats ---
        login(ids["student"])
        res = client.post("/api/formats", json={"name": "x", "fields": [{"label": "A"}]})
        assert res.status_code == 403, res.status_code
        assert res.get_json()["message"] == REFUSAL, res.get_json()
        assert LessonPlanFormat.query.filter_by(name="x").count() == 0
        res = client.post("/api/formats/scan", data={"file": (io.BytesIO(b"PK\x03\x04"), "f.docx")},
                          content_type="multipart/form-data")
        assert res.status_code == 403, res.status_code
        res = client.patch(f"/api/formats/{t_private_id}", json={"name": "hacked"})
        assert res.status_code == 403, res.status_code
        res = client.delete(f"/api/formats/{t_private_id}")
        assert res.status_code == 403, res.status_code
        print("  student format writes refused OK")

        # --- A student's old upload still opens for old plans ---
        res = client.get(f"/api/formats/{ids['s_old']}")
        assert res.status_code == 200, res.status_code
        print("  old student upload still opens OK")

    print("format access OK")


if __name__ == "__main__":
    main()
