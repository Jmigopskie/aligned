"""Self-check for "Forgot password?": a 6-digit code is emailed (through
Resend) to an active account, then the code and a new password reset it. The
reply never says whether an email has an account; codes are hashed, expire in
15 minutes, allow 5 tries, and can be asked for once a minute.

Run it directly: `python test_password_reset.py`.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from models.password_reset import PasswordReset
from services import mail


def main():
    app = create_app()
    app.config.update(TESTING=True, RESEND_API_KEY="test-key")
    sent = []
    mail.send_email = lambda to, subject, text, html=None: sent.append((to, subject, text))

    with app.app_context():
        user = User(full_name="Ana Student", email="ana@example.test", role="student")
        user.set_password("oldpassword")
        off = User(full_name="Off User", email="off@example.test", role="student", is_active=False)
        off.set_password("oldpassword")
        db.session.add_all([user, off])
        db.session.commit()
        client = app.test_client()
        forgot = lambda email: client.post("/api/forgot-password", json={"email": email})
        reset = lambda code, pw="newpassword1": client.post(
            "/api/reset-password", json={"email": "ANA@example.test ", "code": code, "password": pw})
        code_in = lambda text: next(w for w in text.split() if w.isdigit() and len(w) == 6)

        # --- The reply is the same whether or not the account exists ---
        a, b, c = forgot("Ana@Example.test"), forgot("nobody@example.test"), forgot("off@example.test")
        assert a.status_code == b.status_code == c.status_code == 200
        assert a.get_json() == b.get_json() == c.get_json(), (a.get_json(), b.get_json())
        assert [s[0] for s in sent] == ["ana@example.test"], sent
        assert "AlignED" in sent[0][1]
        first = code_in(sent[0][2])
        stored = PasswordReset.query.filter_by(user_id=user.id).one()
        assert first not in stored.code_hash, "the code is stored hashed"
        print("  code sent only to an active account OK")

        # --- Once a minute ---
        forgot("ana@example.test")
        assert len(sent) == 1, "a second request inside a minute sends nothing"
        stored.created_at -= timedelta(minutes=2)
        db.session.commit()
        forgot("ana@example.test")
        assert len(sent) == 2
        code = code_in(sent[1][2])
        print("  once a minute OK")

        # --- The older code stops working once a new one is sent ---
        if first != code:
            assert reset(first).status_code == 400

        # --- Wrong code, short password, then the right one ---
        wrong = "000000" if code != "000000" else "111111"
        res = reset(wrong)
        assert res.status_code == 400 and "code" in res.get_json()["message"].lower(), res.get_json()
        res = reset(code, "short")
        assert res.status_code == 400 and "8" in res.get_json()["message"], res.get_json()
        res = reset(code)
        assert res.status_code == 200, res.get_json()
        db.session.refresh(user)
        assert user.check_password("newpassword1") and not user.check_password("oldpassword")
        assert reset(code, "another-password").status_code == 400, "a used code is spent"
        assert client.post("/api/login", json={"email": "ana@example.test", "password": "newpassword1"}).status_code == 200
        print("  reset with the code OK")

        # --- Five wrong tries burn the code; an old code has expired ---
        latest = PasswordReset.query.filter_by(user_id=user.id).order_by(PasswordReset.id.desc()).first()
        latest.created_at -= timedelta(minutes=2)
        db.session.commit()
        forgot("ana@example.test")
        code = code_in(sent[-1][2])
        for _ in range(5):
            reset(wrong)
        assert reset(code).status_code == 400, "five wrong tries burn the code"
        latest = PasswordReset.query.filter_by(user_id=user.id).order_by(PasswordReset.id.desc()).first()
        latest.created_at -= timedelta(minutes=2)
        db.session.commit()
        forgot("ana@example.test")
        code = code_in(sent[-1][2])
        latest = PasswordReset.query.filter_by(user_id=user.id).order_by(PasswordReset.id.desc()).first()
        latest.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        assert reset(code).status_code == 400, "an expired code fails"
        print("  tries and expiry OK")

        # --- No mail set up: say so instead of pretending ---
        app.config["RESEND_API_KEY"] = ""
        res = forgot("ana@example.test")
        assert res.status_code == 503, res.status_code

    print("password reset OK")


if __name__ == "__main__":
    main()
