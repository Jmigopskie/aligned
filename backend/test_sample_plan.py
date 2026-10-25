"""Self-check: a sample lesson plan uploaded in setup reaches the prompt as an
example of what goes in each part, only for the student who uploaded it.

The provider is never called: ai_service._call is stubbed and records the
prompt. Run it directly: `python test_sample_plan.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import LessonPlanFormat, FormatField
from models.section import Section, SectionMembership
from models.supplementary_source import SupplementarySource
from models.user import User
from services import ai_service


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        teacher = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        ana = User(full_name="Ana Student", email="ana@example.test", role="student")
        ben = User(full_name="Ben Student", email="ben@example.test", role="student")
        for u in (teacher, ana, ben):
            u.set_password("password123")
        db.session.add_all([teacher, ana, ben])
        db.session.commit()
        sec = Section(teacher_id=teacher.id, name="7-A", join_code="SMP001")
        db.session.add(sec)
        db.session.commit()
        db.session.add_all([SectionMembership(section_id=sec.id, student_id=s.id) for s in (ana, ben)])
        fmt = LessonPlanFormat(name="Plain", owner_id=teacher.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="motivation", label="Motivation", field_type="textarea"))
        sample = SupplementarySource(owner_id=ana.id, filename="my-sample.docx", file_path="x",
                                     extracted_text="Motivation:\n\n  Show a  picture puzzle of a CPU.  ")
        db.session.add(sample)
        db.session.commit()
        sample_id, fid = sample.id, fmt.id

        prompts = []
        ai_service._call = lambda system, parts, label: (prompts.append(" ".join(parts)), {"motivation": "A short game."})[1]
        client = app.test_client()

        def generate(user):
            with client.session_transaction() as sess:
                sess["user_id"] = user.id
            prompts.clear()
            res = client.post("/api/generate/full", json={"format_id": fid, "include_keys": ["motivation"],
                                                          "context": {"topic": "Computer parts"}, "sample_id": sample_id})
            assert res.status_code == 200, res.get_json()
            return prompts[0]

        mine = generate(ana)
        assert "--- SAMPLE ---" in mine and "Show a picture puzzle of a CPU." in mine, mine
        assert "Lesson details:" in mine and "picture puzzle" not in mine.split("\n")[0], mine.split("\n")[0]
        print("  own sample reaches the prompt OK")

        theirs = generate(ben)
        assert "--- SAMPLE ---" not in theirs and "picture puzzle" not in theirs, theirs
        print("  another student's sample is ignored OK")

    print("sample plan OK")


if __name__ == "__main__":
    main()
