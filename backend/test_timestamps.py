"""Self-check that timestamps reach the browser as UTC, not as bare local-looking text.

Every datetime in this app is stored naive UTC (datetime.utcnow), and to_dict
used to send it as a bare "2026-09-24T12:29:36". JavaScript parses a date-time
string with no timezone marker as LOCAL time, so a teacher in UTC+8 saw every
timestamp shifted eight hours into the past: a plan edited moments ago read
"edited 8 hours ago" on the Continue where you left off card. The offset in the
error was exactly the reader's own timezone offset.

Run it directly: `venv/Scripts/python test_timestamps.py`.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db, iso_utc
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.section import Section
from models.course_guide import CourseGuide
from models.notification import Notification
from models.announcement import Announcement


def check_helper():
    naive = datetime(2026, 9, 24, 12, 29, 36)
    out = iso_utc(naive)
    assert out.endswith("Z"), out
    assert out == "2026-09-24T12:29:36Z", out

    # Parsed back as UTC, it is the same instant, not shifted.
    parsed = datetime.fromisoformat(out.replace("Z", "+00:00"))
    assert parsed == naive.replace(tzinfo=timezone.utc), parsed

    # An already-aware datetime is not shifted twice.
    aware = datetime(2026, 9, 24, 12, 29, 36, tzinfo=timezone.utc)
    assert iso_utc(aware) == "2026-09-24T12:29:36Z", iso_utc(aware)

    assert iso_utc(None) is None
    print("  helper OK")


def check_every_model_marks_utc():
    """The bug was one missing suffix repeated across every model, so the check
    covers all of them rather than the one that happened to be reported."""
    app = create_app()
    with app.app_context():
        u = User(full_name="T", email="ts@example.test", role="teacher")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()

        fmt = LessonPlanFormat(owner_id=u.id, name="F")
        db.session.add(fmt)
        db.session.commit()

        plan = LessonPlan(user_id=u.id, format_id=fmt.id, title="P")
        sec = Section(teacher_id=u.id, name="S", join_code="TSJOIN")
        guide = CourseGuide(title="G", subject="ICT", uploader_id=u.id, file_path="x.pdf")
        note = Notification(user_id=u.id, type="review", title="t", message="m")
        ann = Announcement(author_id=u.id, title="a", message="m")
        db.session.add_all([plan, sec, guide, note, ann])
        db.session.commit()

        checks = {
            "user.created_at": u.to_dict()["created_at"],
            "plan.created_at": plan.to_dict()["created_at"],
            "plan.updated_at": plan.to_dict()["updated_at"],
            "format.created_at": fmt.to_dict()["created_at"],
            "section.created_at": sec.to_dict()["created_at"],
            "guide.created_at": guide.to_dict()["created_at"],
            "notification.created_at": note.to_dict()["created_at"],
            "announcement.created_at": ann.to_dict()["created_at"],
        }
        bare = [name for name, value in checks.items() if value and not str(value).endswith("Z")]
        assert not bare, f"these still ship without a UTC marker: {bare}"

        # A null timestamp stays null rather than becoming the string "None".
        assert plan.to_dict()["submitted_at"] is None
    print("  every model marks UTC OK")


def check_freshness_reads_correctly():
    """The reported symptom: a plan saved now must read as saved now."""
    app = create_app()
    with app.app_context():
        u = User(full_name="T2", email="ts2@example.test", role="teacher")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        fmt = LessonPlanFormat(owner_id=u.id, name="F2")
        db.session.add(fmt)
        db.session.commit()
        plan = LessonPlan(user_id=u.id, format_id=fmt.id, title="Just saved")
        db.session.add(plan)
        db.session.commit()

        sent = plan.to_dict()["updated_at"]
        parsed = datetime.fromisoformat(sent.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        assert abs(age) < 60, f"a plan saved now reads as {age / 3600:.1f}h old"
    print("  freshness OK")


check_helper()
check_every_model_marks_utc()
check_freshness_reads_correctly()
print("timestamps OK")
