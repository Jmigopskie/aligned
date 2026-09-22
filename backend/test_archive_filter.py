"""Self-check for the archive view on GET /api/admin/users.

Archiving an account is stored as is_active=False (the same flag that already
blocks sign-in), and the admin archive screen is just that list filtered by
the new `active` parameter — so this pins down that the filter selects the
right side, still composes with `role`, and ignores a junk value instead of
erroring. Run it directly: `venv/Scripts/python test_archive_filter.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User


def main():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        # create_app() bootstraps a default admin into the empty database, so
        # that account is the one signed in below and shows up in unfiltered
        # and active-only listings.
        admin_id = User.query.filter_by(role="admin").first().id

        for name, role, active in [
            ("Live Student", "student", True),
            ("Archived Student", "student", False),
            ("Archived Teacher", "teacher", False),
        ]:
            user = User(
                full_name=name,
                email=name.replace(" ", ".").lower() + "@example.test",
                role=role,
                is_active=active,
            )
            user.set_password("password123")
            db.session.add(user)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = admin_id

        def names(qs):
            res = client.get("/api/admin/users" + qs)
            assert res.status_code == 200, res.status_code
            return sorted(u["full_name"] for u in res.get_json()["users"])

        assert names("?active=0") == ["Archived Student", "Archived Teacher"], names("?active=0")
        assert names("?active=1") == ["Live Student", "System Administrator"], names("?active=1")
        assert names("?active=0&role=student") == ["Archived Student"], names("?active=0&role=student")
        assert len(names("")) == 4, names("")            # no filter: unchanged behaviour
        assert len(names("?active=bogus")) == 4          # junk value ignored, not an error

    print("archive filter OK")


main()
