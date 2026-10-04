"""Self-check for the owl's one-time onboarding tour.

Only accounts made after the tour existed should see it: the migration marks
every existing account onboarded. A new account is not, /api/me says so, and
finishing or skipping the tour marks it, so it never shows again on any device.

Run it directly: `venv/Scripts/python test_onboarding.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import text

from app import create_app
from extensions import db
from models.user import User


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        # A database from before the tour has no onboarded_at column. Adding
        # it marks every account already there; a later boot, with the column
        # in place, must not mark anyone (or new accounts would never see it).
        admin = User.query.filter_by(role="admin").first()
        db.session.execute(text("ALTER TABLE users DROP COLUMN onboarded_at"))
        db.session.commit()
        from app import _migrate_user_columns
        _migrate_user_columns()
        db.session.expire_all()
        assert db.session.get(User, admin.id).onboarded_at is not None, "existing account must not get the tour"

        # A new account has not been through it.
        new = User(full_name="New Teacher", email="new.teacher@example.test", role="teacher")
        new.set_password("password123")
        db.session.add(new)
        db.session.commit()
        _migrate_user_columns()  # the next boot
        db.session.expire_all()
        assert db.session.get(User, new.id).onboarded_at is None, "a later boot must not mark new accounts"
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = new.id
        assert client.get("/api/me").get_json()["user"]["onboarded"] is False

        # Finishing or skipping marks it.
        res = client.post("/api/me/onboarded")
        assert res.status_code == 200, res.get_json()
        assert client.get("/api/me").get_json()["user"]["onboarded"] is True
        assert client.post("/api/me/onboarded").status_code == 200, "marking twice is harmless"
    print("onboarding OK")


if __name__ == "__main__":
    main()
