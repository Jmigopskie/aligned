"""Self-check: setup step 8 finds where the topic sits in the picked
curriculum (text search, no AI) and the kind of lesson chosen there reaches
every prompt; a plan without one reads as before.
Run: `python test_lesson_stage.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.course_guide import CourseGuide
from models.user import User
from services import ai_service


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        tess = User(full_name="Tess", email="tess.stage@example.test", role="teacher")
        tess.set_password("password123")
        db.session.add(tess)
        db.session.commit()
        bow = CourseGuide.query.filter(CourseGuide.title.ilike("%G7%ICT%Budget%")).first()
        assert bow, "the shipped G7 ICT Budget of Work"
        calls = []
        real = ai_service._call
        ai_service._call = lambda *a, **k: calls.append(1) or {}
        try:
            client = app.test_client()
            with client.session_transaction() as s:
                s["user_id"] = tess.id
            res = client.post("/api/curriculum-match", json={
                "guide_ids": [bow.id], "context": {"topic": "Computer number systems", "main_topic": "Computer systems",
                                                   "grade_level": "Grade 7"}}).get_json()
            m = res["matches"][0]
            assert m["how"] == "exact" and "number systems" in m["line"].lower(), m
            res = client.post("/api/curriculum-match", json={
                "guide_ids": [bow.id], "context": {"topic": "Pagluluto ng adobo", "main_topic": "Cookery"}}).get_json()
            assert res["matches"][0]["how"] == "none", res
            assert not calls, "no AI call for the lookup"
        finally:
            ai_service._call = real

        block = ai_service._lesson_block({"topic": "Cell formulas", "lesson_stage": "application"}, "")
        assert "Kind of lesson: APPLICATION" in block
        assert "Kind of lesson" not in ai_service._lesson_block({"topic": "Cell formulas"}, "")
    print("lesson stage OK")


if __name__ == "__main__":
    main()
