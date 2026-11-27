"""Self-check: a plan isn't written about a topic that is a number, a keyboard
mash or a placeholder; the request is refused with a clear message before any
AI call. Run: `python test_nonsense_topic.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.user import User
from services import ai_service, text_sense


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        tess = User(full_name="Tess", email="tess.topic@example.test", role="teacher")
        tess.set_password("password123")
        db.session.add(tess)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["user_id"] = tess.id
        calls = []
        real = ai_service.generate_full
        ai_service.generate_full = lambda *a, **k: calls.append(1) or {}
        try:
            for path in ("/api/generate/full", "/api/generate/full-stream"):
                for topic in ("12345", "asdfgh", "test"):
                    res = client.post(path, json={"format_id": 1, "context": {"topic": topic, "main_topic": "Spreadsheets"}})
                    assert res.status_code == 400 and "doesn't look like a real topic" in res.get_json()["message"], (path, topic)
            res = client.post("/api/generate/full", json={"format_id": 1, "context": {"topic": "Cell formulas", "main_topic": "qwerty"}})
            assert res.status_code == 400 and "main topic" in res.get_json()["message"]
            assert not calls, "nothing was generated"
        finally:
            ai_service.generate_full = real
        assert text_sense.sensible("Cell formulas") and not text_sense.sensible("99")
    print("nonsense topic OK")


if __name__ == "__main__":
    main()
