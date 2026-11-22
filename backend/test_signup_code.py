"""Self-check for sign-up (Batch 2): only @gsfe.tupcavite.edu.ph addresses,
and only with the 6-digit code emailed to that address. Codes expire, allow
five tries, one per minute; accounts made by an admin are not affected.

The mail sender is stubbed. Run it directly: `python test_signup_code.py`.
"""
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models.signup_code import SignupCode  # noqa: E402
from models.user import User  # noqa: E402
from services import mail  # noqa: E402

sent = []


def main():
    real = (mail.configured, mail.send_email)
    mail.configured = lambda: True
    mail.send_email = lambda to, subject, text, html: sent.append((to, text))
    app = create_app()
    app.config.update(TESTING=True)
    try:
        with app.app_context():
            client = app.test_client()
            good = "juan.cruz@gsfe.tupcavite.edu.ph"

            def code_for(email):
                return re.search(r"\b(\d{6})\b", [t for to, t in sent if to == email][-1]).group(1)

            # Only gsfe addresses get a code, and sign up.
            res = client.post("/api/signup/code", json={"email": "juan@gmail.com"})
            assert res.status_code == 400 and "gsfe.tupcavite.edu.ph" in res.get_json()["message"], res.get_json()
            res = client.post("/api/signup", json={"full_name": "Juan", "email": "juan@gmail.com",
                                                   "password": "password123", "code": "123456"})
            assert res.status_code == 400 and "gsfe.tupcavite.edu.ph" in res.get_json()["message"]
            # A look-alike domain is refused too.
            assert client.post("/api/signup/code", json={"email": "x@gsfe.tupcavite.edu.ph.evil.com"}).status_code == 400
            print("  only @gsfe.tupcavite.edu.ph OK")

            res = client.post("/api/signup/code", json={"email": " Juan.Cruz@GSFE.tupcavite.edu.ph "})
            assert res.status_code == 200 and sent and sent[-1][0] == good, (res.get_json(), sent)
            code = code_for(good)
            # Asking again within a minute sends nothing new.
            client.post("/api/signup/code", json={"email": good})
            assert len([s for s in sent if s[0] == good]) == 1
            # No code, a wrong code: refused.
            base = {"full_name": "Juan Cruz", "email": good, "password": "password123"}
            assert client.post("/api/signup", json=base).status_code == 400
            res = client.post("/api/signup", json={**base, "code": "000000" if code != "000000" else "111111"})
            assert res.status_code == 400 and "code" in res.get_json()["message"].lower()
            # The right code makes a student account and signs it in.
            res = client.post("/api/signup", json={**base, "code": code})
            assert res.status_code == 200 and res.get_json()["user"]["role"] == "student", res.get_json()
            assert client.get("/api/me").status_code == 200
            # A used code can't be used again; a registered email gets no code.
            client.post("/api/logout")
            assert client.post("/api/signup", json={**base, "code": code}).status_code in (400, 409)
            assert client.post("/api/signup/code", json={"email": good}).status_code == 409
            print("  code emailed, checked once, account made OK")

            # Five wrong tries spend the code; an expired code is refused.
            other = "ana@gsfe.tupcavite.edu.ph"
            client.post("/api/signup/code", json={"email": other})
            right = code_for(other)
            wrong = "000000" if right != "000000" else "111111"
            for _ in range(5):
                client.post("/api/signup", json={"full_name": "Ana", "email": other, "password": "password123", "code": wrong})
            assert client.post("/api/signup", json={"full_name": "Ana", "email": other, "password": "password123",
                                                    "code": right}).status_code == 400
            row = SignupCode.query.filter_by(email=other).order_by(SignupCode.id.desc()).first()
            row.created_at = row.created_at - timedelta(minutes=2)
            db.session.commit()
            client.post("/api/signup/code", json={"email": other})
            fresh = code_for(other)
            row = SignupCode.query.filter_by(email=other, used_at=None).order_by(SignupCode.id.desc()).first()
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()
            assert client.post("/api/signup", json={"full_name": "Ana", "email": other, "password": "password123",
                                                    "code": fresh}).status_code == 400
            assert User.query.filter_by(email=other).first() is None
            print("  tries and expiry OK")

            # Input checks: a name, a real-looking password, matching rules.
            client.post("/api/signup/code", json={"email": "ben@gsfe.tupcavite.edu.ph"})
            bcode = code_for("ben@gsfe.tupcavite.edu.ph")
            res = client.post("/api/signup", json={"full_name": "", "email": "ben@gsfe.tupcavite.edu.ph",
                                                   "password": "password123", "code": bcode})
            assert res.status_code == 400
            res = client.post("/api/signup", json={"full_name": "Ben", "email": "ben@gsfe.tupcavite.edu.ph",
                                                   "password": "short", "code": bcode})
            assert res.status_code == 400 and "8" in res.get_json()["message"]
            print("  sign-up inputs checked OK")

            # One address gets at most 10 codes a day; one IP at most 10 an hour.
            spam = "spam@gsfe.tupcavite.edu.ph"
            for _ in range(10):
                db.session.add(SignupCode(email=spam, code_hash="x", expires_at=datetime.utcnow(),
                                          created_at=datetime.utcnow() - timedelta(hours=2), used_at=datetime.utcnow()))
            db.session.commit()
            res = client.post("/api/signup/code", json={"email": spam})
            assert res.status_code == 429, res.get_json()
            for n in range(12):
                res = client.post("/api/signup/code", json={"email": f"ip{n}@gsfe.tupcavite.edu.ph"},
                                  environ_base={"REMOTE_ADDR": "203.0.113.9"})
            assert res.status_code == 429, res.get_json()
            print("  daily and per-IP code limits OK")

            # A student keeps a school address when changing it in Settings.
            with client.session_transaction() as s:
                s["user_id"] = User.query.filter_by(email=good).first().id
            assert client.patch("/api/me", json={"email": "juan@gmail.com"}).status_code == 400
            assert client.patch("/api/me", json={"email": "juan2@gsfe.tupcavite.edu.ph"}).status_code == 200
            print("  students keep a school email OK")
    finally:
        mail.configured, mail.send_email = real
    print("signup code OK")


if __name__ == "__main__":
    main()
