"""Self-check for bulk archive/restore on POST /api/admin/bulk-archive.

Archiving is is_active=False on the row itself, for both accounts (the same
flag auth_routes already refuses sign-in on) and sections (new). What needs
pinning down is the guards: the batch must never lock every admin out, must not
fail wholesale because one id in it was bad, and an archived section must drop
out of the teacher's and the student's lists and refuse new joins.

Run it directly: `venv/Scripts/python test_bulk_archive.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.section import Section, SectionMembership


def make_user(name, role, active=True):
    user = User(
        full_name=name,
        email=name.replace(" ", ".").lower() + "@example.test",
        role=role,
        is_active=active,
    )
    user.set_password("password123")
    db.session.add(user)
    return user


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        root_admin_id = User.query.filter_by(role="admin").first().id

        second_admin = make_user("Second Admin", "admin")
        teacher = make_user("Tess Teacher", "teacher")
        s1 = make_user("Stu One", "student")
        s2 = make_user("Stu Two", "student")
        s3 = make_user("Stu Three", "student")
        db.session.commit()
        second_admin_id, teacher_id = second_admin.id, teacher.id
        s1_id, s2_id, s3_id = s1.id, s2.id, s3.id

        db.session.add_all([
            Section(teacher_id=teacher_id, name="Live Class", join_code="LIVE01"),
            Section(teacher_id=teacher_id, name="Doomed Class", join_code="DOOM01"),
        ])
        db.session.commit()
        doomed = Section.query.filter_by(join_code="DOOM01").first()
        doomed_id, doomed_code = doomed.id, doomed.join_code

        db.session.add(SectionMembership(section_id=doomed_id, student_id=s1_id))
        db.session.commit()

        client = app.test_client()

        def login(user_id):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

        def bulk(payload):
            return client.post("/api/admin/bulk-archive", json=payload)

        login(root_admin_id)

        # --- Validation ---
        assert bulk({"kind": "nope", "ids": [1], "is_active": False}).status_code == 400
        assert bulk({"kind": "users", "ids": [], "is_active": False}).status_code == 400
        assert bulk({"kind": "users", "ids": [1]}).status_code == 400, "missing is_active must be rejected"
        assert bulk({"kind": "users", "ids": ["abc"], "is_active": False}).status_code == 400
        assert bulk({"kind": "users", "ids": list(range(600)), "is_active": False}).status_code == 400

        # --- Archiving several accounts at once ---
        body = bulk({"kind": "users", "ids": [s1_id, s2_id, s3_id], "is_active": False}).get_json()
        assert body["updated_count"] == 3, body
        assert sorted(body["updated"]) == sorted([s1_id, s2_id, s3_id]), body
        assert User.query.get(s1_id).is_active is False

        # A duplicate id counts once, and a row already in the requested state
        # is not reported as an update.
        assert bulk({"kind": "users", "ids": [s1_id, s1_id], "is_active": False}).get_json()["updated_count"] == 0

        # --- Restore works the same way ---
        assert bulk({"kind": "users", "ids": [s1_id, s2_id], "is_active": True}).get_json()["updated_count"] == 2
        assert User.query.get(s2_id).is_active is True

        # --- Guard: an admin can't archive themselves, and one bad id must not
        # discard the valid picks alongside it ---
        body = bulk({"kind": "users", "ids": [root_admin_id, s1_id, 99999], "is_active": False}).get_json()
        assert body["updated"] == [s1_id], body
        reasons = {entry["id"]: entry["reason"] for entry in body["skipped"]}
        assert root_admin_id in reasons and "own account" in reasons[root_admin_id], reasons
        assert 99999 in reasons, reasons
        assert User.query.get(root_admin_id).is_active is True

        # --- Guard: archiving every admin in one batch must leave one standing ---
        assert User.query.filter_by(role="admin", is_active=True).count() == 2
        body = bulk({"kind": "users", "ids": [second_admin_id, root_admin_id], "is_active": False}).get_json()
        assert User.query.filter_by(role="admin", is_active=True).count() >= 1, body
        assert any("last active admin" in e["reason"] or "own account" in e["reason"]
                   for e in body["skipped"]), body
        bulk({"kind": "users", "ids": [second_admin_id], "is_active": True})

        # --- Sections ---
        assert bulk({"kind": "sections", "ids": [doomed_id], "is_active": False}).get_json()["updated_count"] == 1
        assert Section.query.get(doomed_id).is_active is False
        # Nothing is deleted: the membership row survives archiving.
        assert SectionMembership.query.filter_by(section_id=doomed_id).count() == 1

        def admin_section_names(qs):
            res = client.get("/api/admin/sections" + qs)
            assert res.status_code == 200, res.status_code
            return sorted(s["name"] for s in res.get_json()["sections"])

        assert admin_section_names("?active=0") == ["Doomed Class"], admin_section_names("?active=0")
        assert admin_section_names("?active=1") == ["Live Class"], admin_section_names("?active=1")
        assert admin_section_names("") == ["Doomed Class", "Live Class"]
        assert admin_section_names("?active=bogus") == ["Doomed Class", "Live Class"]
        assert admin_section_names("?q=doomed") == ["Doomed Class"]
        assert admin_section_names("?q=tess") == ["Doomed Class", "Live Class"], "search covers teacher name"

        # The teacher no longer sees the archived class.
        login(teacher_id)
        res = client.get("/api/sections")
        assert [s["name"] for s in res.get_json()["sections"]] == ["Live Class"], res.get_json()

        # Neither does the student who was enrolled in it.
        login(s1_id)
        assert client.get("/api/sections").get_json()["sections"] == []

        # Its code no longer admits anyone, with the same message a nonexistent
        # code gives so an archived class can't be probed for existence.
        res = client.post("/api/sections/join", json={"code": doomed_code})
        assert res.status_code == 404, res.status_code
        assert "No class found" in res.get_json()["message"], res.get_json()

        # Restoring brings all of it back.
        login(root_admin_id)
        bulk({"kind": "sections", "ids": [doomed_id], "is_active": True})
        login(teacher_id)
        names = sorted(s["name"] for s in client.get("/api/sections").get_json()["sections"])
        assert names == ["Doomed Class", "Live Class"], names

        # --- A non-admin must not reach the endpoint at all ---
        login(teacher_id)
        assert bulk({"kind": "users", "ids": [s1_id], "is_active": False}).status_code in (401, 403)

    print("bulk archive OK")


main()
