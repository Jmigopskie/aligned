"""Self-check: built-in formats belong to the admin. They start on hold
(teachers and students don't see them), the admin reworks their fields and
what goes in each, switches them on or off, and can add new ones; seeding no
longer overwrites a reworked built-in. Teachers keep their own formats.

Run it directly: `python test_builtin_admin.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import FormatField, LessonPlanFormat
from models.section import Section, SectionMembership
from models.user import User
from services import builtins


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        # The in-memory database starts empty here: an admin to own the
        # built-ins, then the seeded built-ins themselves.
        admin = User.query.filter_by(role="admin").first()
        if admin is None:
            admin = User(full_name="Ada Admin", email="ada.bi@example.test", role="admin")
            admin.set_password("password123")
            db.session.add(admin)
            db.session.commit()
        builtins.seed_builtins()
        db.session.commit()
        tina = User(full_name="Tina Teacher", email="tina.bi@example.test", role="teacher")
        sam = User(full_name="Sam Student", email="sam.bi@example.test", role="student")
        for u in (tina, sam):
            u.set_password("password123")
        db.session.add_all([tina, sam])
        db.session.commit()
        sec = Section(teacher_id=tina.id, name="7-A", join_code="BIA001")
        db.session.add(sec)
        db.session.commit()
        db.session.add(SectionMembership(section_id=sec.id, student_id=sam.id))
        own = LessonPlanFormat(name="Tina's own", owner_id=tina.id)
        db.session.add(own)
        db.session.flush()
        db.session.add(FormatField(format_id=own.id, field_key="flow", label="Flow"))
        db.session.commit()
        ids = {"admin": admin.id, "tina": tina.id, "sam": sam.id}
        dlp = LessonPlanFormat.query.filter_by(builtin_key="dlp").one()
        dlp_id, own_id = dlp.id, own.id
        client = app.test_client()

        def login(name):
            with client.session_transaction() as s:
                s["user_id"] = ids[name]

        def names(name):
            login(name)
            return {f["name"] for f in client.get("/api/formats").get_json()["formats"]}

        # --- Seeded built-ins start on hold: only the admin sees them ---
        assert dlp.available is False
        assert "Detailed Lesson Plan (DLP)" not in names("tina") and "Tina's own" in names("tina")
        assert "Detailed Lesson Plan (DLP)" not in names("sam") and "Tina's own" in names("sam")
        assert "Detailed Lesson Plan (DLP)" in names("admin")
        login("admin")
        listed = client.get("/api/admin/builtin-formats").get_json()["formats"]
        assert len(listed) == 6 and not any(f["available"] for f in listed), listed
        login("tina")
        assert client.get("/api/admin/builtin-formats").status_code == 403
        # A plan already made with a held format still opens it.
        assert client.get(f"/api/formats/{dlp_id}").status_code == 200
        print("  on hold by default OK")

        # --- Teachers can't touch built-ins; the admin reworks fields + context ---
        fields = client.get(f"/api/formats/{dlp_id}").get_json()["format"]["fields"]
        setup = [{"field_key": f["field_key"], "label": f["label"], "anchor_index": f["anchor_index"],
                  "guided": True, "locked": False} for f in fields]
        setup[0]["context"] = "  The school's   full name.  "
        assert client.put(f"/api/formats/{dlp_id}/field-setup", json={"fields": setup}).status_code == 403
        login("admin")
        res = client.put(f"/api/formats/{dlp_id}/field-setup", json={"fields": setup})
        assert res.status_code == 200, res.get_json()
        hint = {f["field_key"]: f["ai_hint"] for f in res.get_json()["format"]["fields"]}[setup[0]["field_key"]]
        assert hint == "The school's full name.", hint
        print("  admin reworks fields and context OK")

        # --- Seeding keeps the admin's rework ---
        db.session.expire_all()
        builtins.seed_builtins()
        db.session.commit()
        f0 = FormatField.query.filter_by(format_id=dlp_id, field_key=setup[0]["field_key"]).one()
        assert f0.ai_hint == "The school's full name.", f0.ai_hint
        print("  seeding keeps the rework OK")

        # --- On and off ---
        assert client.patch(f"/api/formats/{dlp_id}/availability", json={"available": True}).status_code == 200
        assert "Detailed Lesson Plan (DLP)" in names("sam") and "Detailed Lesson Plan (DLP)" in names("tina")
        login("tina")
        assert client.patch(f"/api/formats/{dlp_id}/availability", json={"available": False}).status_code == 403
        login("admin")
        assert client.patch(f"/api/formats/{dlp_id}/availability", json={"available": False}).status_code == 200
        assert "Detailed Lesson Plan (DLP)" not in names("sam")
        login("admin")
        assert client.patch(f"/api/formats/{own_id}/availability", json={"available": False}).status_code == 400
        assert client.delete(f"/api/formats/{dlp_id}").status_code == 400  # ships with the app: switch it off
        print("  switching on and off OK")

        # --- Teachers' own field context works the same way ---
        login("tina")
        own_fields = client.get(f"/api/formats/{own_id}").get_json()["format"]["fields"]
        assert own_fields
        # (No document to place fields in, so field-setup refuses; context is for document formats.)
        res = client.put(f"/api/formats/{own_id}/field-setup", json={"fields": [{"field_key": "flow", "label": "Flow",
                                                                                 "anchor_index": 0, "context": "x"}]})
        assert res.status_code == 400
        print("  teachers keep their own formats OK")

        # --- An admin's new built-in starts on hold ---
        login("admin")
        res = client.post("/api/formats", json={"name": "Admin's built-in", "builtin": True,
                                                "fields": [{"label": "Objectives"}]})
        assert res.status_code == 201, res.get_json()
        made = res.get_json()["format"]
        assert made["is_builtin"] and made["available"] is False, made
        assert "Admin's built-in" not in names("tina")
        login("tina")
        res = client.post("/api/formats", json={"name": "Not built in", "builtin": True, "fields": [{"label": "A"}]})
        assert res.get_json()["format"]["is_builtin"] is False  # only an admin makes built-ins
        print("  admin uploads built-ins OK")
    print("builtin admin OK")


if __name__ == "__main__":
    main()
