"""Self-check for the coherence check (Batch 1): one review of the whole plan
that lists each mismatch with its fix: complete content in Building
Proficiency, an instruction in Guided and for locked parts.

No provider or network: ai_service._call is stubbed.
Run it directly: `python test_coherence_check.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea", locked=False, parts=None):
        self.field_key, self.label, self.field_type = field_key, label, field_type
        self.ai_hint, self.locked = None, locked
        self.parts_list = parts or []


FIELDS = [Field("objectives", "Objectives", "list"), Field("lesson_proper", "Lesson Proper"),
          Field("evaluation", "Evaluation", locked=True),
          Field("procedure", "Procedure", "weekly", parts=["Monday", "Tuesday"])]
VALUES = {"objectives": "identify the parts of a tape\ndesign a flyer on kitchen safety",
          "lesson_proper": "What is a measuring tape?", "evaluation": "1. What is ...?",
          "procedure": ["Recall the tools", "Measure the table"]}
CTX = {"topic": "Measuring tools"}

prompts = []


def stub(reply):
    def call(system, parts, label):
        prompts.append(system + "\n" + "\n".join(parts))
        return reply
    return call


def main():
    real = ai_service._call
    try:
        ai_service._call = stub({"coherent": False, "summary": "Objective 2 isn't assessed.", "issues": [
            {"part_key": "evaluation", "problem": "Nothing checks objective 2.", "fix": "Add a task ..."},
            {"part_key": "lesson_proper", "problem": "Flyers aren't taught.", "fix": "Teach flyer layout ..."},
            {"part_key": "made_up", "problem": "x", "fix": "y"}]})
        out = ai_service.check_coherence(CTX, FIELDS, VALUES)
        # issues_cleaned
        assert [i["part_key"] for i in out["issues"]] == ["evaluation", "lesson_proper"], out
        assert out["issues"][0]["part_label"] == "Evaluation" and out["coherent"] is False, out
        prompt = prompts[-1]
        # exact text for the part + locked_fix_is_instruction (user, 2026-11-24)
        assert "exact text" in prompt, prompt[:400]
        assert "Locked parts (their fix is an instruction only): Evaluation" in prompt, prompt
        assert [i["locked"] for i in out["issues"]] == [True, False], out
        # Only real mismatches: a plan that lines up comes back coherent.
        assert "Never report wording, style" in prompt and '"issues": []' in prompt, prompt[:1500]
        # weekly_values_flattened
        assert "Monday: Recall the tools" in prompt and "Tuesday: Measure the table" in prompt, prompt
        assert "['Recall" not in prompt and '["Recall' not in prompt
        # the checks and the taxonomies
        assert ai_service.taxonomy_text() in prompt and "taught" in prompt and "next lesson" in prompt
        print("  issues cleaned, plan flattened, Building Proficiency gets complete fixes OK")

        # The model says "not coherent" but lists nothing: it lines up.
        ai_service._call = stub({"coherent": False, "summary": "Some things could be better.", "issues": []})
        assert ai_service.check_coherence(CTX, FIELDS, VALUES) == {
            "coherent": True, "summary": "Everything lines up.", "issues": []}
        print("  the listed issues decide, not the model's yes/no OK")

        ai_service._call = stub({"coherent": True, "summary": "Everything lines up.", "issues": []})
        out = ai_service.check_coherence(CTX, FIELDS, VALUES)
        assert out == {"coherent": True, "summary": "Everything lines up.", "issues": []}, out
        print("  a coherent plan OK")
    finally:
        ai_service._call = real
    check_route()
    print("coherence check OK")


def check_route():
    """POST /api/lesson-plans/coherence: refused until there is something to
    check, otherwise the review of the page's current values."""
    from app import create_app
    from extensions import db
    from models.format import FormatField, LessonPlanFormat
    from models.user import User

    app = create_app()
    app.config.update(TESTING=True)
    real = ai_service._call
    with app.app_context():
        teacher = User(full_name="Tess", email="tess@coh.test", role="teacher")
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=teacher.id, name="DLP")
        db.session.add(fmt)
        db.session.commit()
        for i, (key, label) in enumerate([("objectives", "Objectives"), ("evaluation", "Evaluation")]):
            db.session.add(FormatField(format_id=fmt.id, field_key=key, label=label, field_type="textarea", sort_order=i))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = teacher.id
        res = client.post("/api/lesson-plans/coherence", json={"format_id": fmt.id, "field_values": {}, "mode": "full"})
        assert res.status_code == 400 and "objectives" in res.get_json()["message"].lower(), res.get_json()
        try:
            ai_service._call = stub({"coherent": True, "summary": "Everything lines up.", "issues": []})
            res = client.post("/api/lesson-plans/coherence", json={
                "format_id": fmt.id, "mode": "step", "topic": "Measuring tools",
                "field_values": {"objectives": "identify the parts", "evaluation": "1. Which part ...?"}})
        finally:
            ai_service._call = real
        body = res.get_json()
        assert res.status_code == 200 and body["status"] == "ok" and body["coherent"] is True, body
        assert "identify the parts" in prompts[-1] and "exact text" in prompts[-1]   # Guided too
    print("  coherence route OK")


if __name__ == "__main__":
    main()
