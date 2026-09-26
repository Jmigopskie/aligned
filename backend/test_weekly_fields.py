"""Self-check for weekly fields and the corrected ILAW format.

A weekly lesson plan (ILAW) answers most rows once per day, in five cells under
MONDAY to FRIDAY. A weekly field is one field whose value has one part per day,
each written into its own cell. What matters here: detection offers every real
ILAW label (including the long "Flow: Describe the activities..." kind) and none
of the page-break fragments; a row of blank day cells becomes a weekly field
with the days named; export and the live document put each part in its own cell;
the AI limits keep a weekly value as a list; the seeded ILAW has the right fields.

Run it directly: `venv/Scripts/python test_weekly_fields.py`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document

from app import create_app
from extensions import db
from models.format import LessonPlanFormat, FormatField
from models.lesson_plan import LessonPlan
from models.user import User
from services import ai_limits, builtins, docx_service

ILAW = os.path.join(builtins.BUILTIN_DIR, "formats", "ilaw-lesson-plan.docx")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

EXPECTED_ILAW = [
    ("Grade Level & Section", "text"),
    ("Teacher", "text"),
    ("Learning Area", "text"),
    ("Week / Teaching Dates and Time", "text"),
    ("Term", "text"),
    ("Name of Teachers", "text"),
    ("Lesson Title", "weekly"),
    ("Session No.", "weekly"),
    ("References", "weekly"),
    ("Declaration of AI Use", "weekly"),
    ("Performance Standards", "weekly"),
    ("Content Standards", "weekly"),
    ("Learning Competencies", "weekly"),
    ("Learning Objectives", "weekly"),
    ("Learner Context", "weekly"),
    ("Pre-Lesson", "weekly"),
    ("Flow", "weekly"),
    ("Learning Resources", "weekly"),
    ("Opportunities for Integration and Contextualization", "weekly"),
    ("Formative Assessment", "weekly"),
    ("Extended Learning Opportunities", "weekly"),
    ("Reflections", "weekly"),
]


def _line(lines, prefix):
    return next(l for l in lines if l["text"].startswith(prefix))


def check_detection():
    lines = docx_service.candidate_label_lines(ILAW)
    texts = [l["text"] for l in lines]
    for label in ("Learning Objectives", "Learner Context", "Flow", "Opportunities for integration",
                  "Formative Assessment", "Extended learning", "Reflections", "Performance Standards",
                  "Content Standards", "Learning Competencies"):
        assert any(t.startswith(label) for t in texts), (label, texts)
    # Page-break spill-overs start mid-sentence, in lowercase.
    assert not any(t[:1].islower() for t in texts), texts

    flow = _line(lines, "Flow")
    assert flow["blank_cells"] == 5 and flow["parts"] == DAYS, flow
    # Its answer cells are in the row under the merged label, not beside it.
    perf = _line(lines, "Performance Standards")
    assert perf["blank_cells"] == 5 and perf["parts"] == DAYS, perf
    content = _line(lines, "Content Standards")
    assert content["parts"] == ["Monday to Tuesday", "Wednesday", "Thursday", "Friday"], content
    teacher = _line(lines, "Teacher")
    assert teacher["blank_cells"] == 1 and not teacher.get("parts"), teacher
    print("  detection OK")


def _weekly_doc(path):
    doc = Document()
    table = doc.add_table(rows=2, cols=6)
    for i, day in enumerate(["", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]):
        table.rows[0].cells[i].text = day
    table.rows[1].cells[0].text = "Flow: Describe the activities you will run each day."
    doc.save(path)


def _make_user(email):
    u = User(full_name="Weekly Check", email=email, role="teacher")
    u.set_password("Password123!")
    db.session.add(u)
    db.session.commit()
    return u


def check_export_and_render(app):
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        _weekly_doc(path)
        items = docx_service._iter_items(Document(path))
        flow_idx = next(i for i, it in enumerate(items)
                        if docx_service._element_text(Document(path), it["el"]).startswith("Flow"))
        user = _make_user("weekly.check@example.test")
        fmt = LessonPlanFormat(owner_id=user.id, name="Weekly", source_file_path=path, template_docx_path=path)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="flow", label="Flow", field_type="weekly",
                                   anchor_index=flow_idx, parts='["Monday","Tuesday","Wednesday","Thursday","Friday"]'))
        db.session.commit()

        rendered = docx_service.render_template_html(fmt)
        for part in range(5):
            assert f'data-field-key="flow" data-part="{part}"' in rendered["html"], rendered["html"][:400]
        assert rendered["matched_fields"] == ["flow"]

        plan = LessonPlan(user_id=user.id, format_id=fmt.id, title="Weekly export")
        plan.set_values({"flow": ["MON-TEXT", "TUE-TEXT", "WED-TEXT", "THU-TEXT", "FRI-TEXT"]})
        db.session.add(plan)
        db.session.commit()
        out = docx_service.export_lesson_plan(plan, fmt)
        row = Document(out).tables[0].rows[1]
        assert row.cells[0].text.startswith("Flow"), row.cells[0].text
        assert [c.text for c in row.cells[1:]] == ["MON-TEXT", "TUE-TEXT", "WED-TEXT", "THU-TEXT", "FRI-TEXT"]
        os.remove(out)

        # Styled parts keep their styling, each in its own cell.
        plan.set_rich_values({"flow": ["<b>Bold Monday</b>", "", "Plain Wednesday", "", ""]})
        plan.set_values({"flow": ["Bold Monday", "", "Plain Wednesday", "", ""]})
        db.session.commit()
        out = docx_service.export_lesson_plan(plan, fmt)
        row = Document(out).tables[0].rows[1]
        assert row.cells[1].paragraphs[0].runs[0].bold, "Monday lost its bold"
        assert row.cells[3].text == "Plain Wednesday" and row.cells[2].text == ""
        os.remove(out)
    finally:
        os.remove(path)
    print("  export and live document OK")


class _Field:
    def __init__(self, key, field_type, parts=None):
        self.field_key, self.field_type, self.label = key, field_type, key
        self.parts_list = parts


def check_limits():
    field = _Field("flow", "weekly", DAYS)
    limits = dict(max_items=6, max_item_words=18, max_sentences=3, max_prose_words=70)
    out = ai_limits.enforce_limits({"flow": ["**Mon** plan", "Tue", "Wed", "Thu", "Fri"]}, [field], **limits)
    assert out["flow"] == ["Mon plan", "Tue", "Wed", "Thu", "Fri"], out
    # Keyed by day, in any order, comes back in day order.
    out = ai_limits.enforce_limits({"flow": {"Tuesday": "T", "Monday": "M", "Friday": "F"}}, [field], **limits)
    assert out["flow"] == ["M", "T", "", "", "F"], out
    # A single string becomes Monday's part rather than being lost.
    out = ai_limits.enforce_limits({"flow": "Only one"}, [field], **limits)
    assert out["flow"] == ["Only one", "", "", "", ""], out
    assert ai_limits.is_answered(["", "x"]) and not ai_limits.is_answered(["", " "])
    print("  AI limits OK")


def check_suggest_marks_weekly(app):
    from routes import format_routes
    from services import ai_service

    lines = docx_service.candidate_label_lines(ILAW)
    flow, teacher = _line(lines, "Flow"), _line(lines, "Teacher")
    real = ai_service.suggest_field_anchors
    ai_service.suggest_field_anchors = lambda numbered: [
        {"index": flow["index"], "label": "Flow", "field_type": "textarea"},
        {"index": teacher["index"], "label": "Teacher", "field_type": "text"},
    ]
    try:
        with app.test_request_context():
            fields, err = format_routes._suggest_fields(ILAW)
    finally:
        ai_service.suggest_field_anchors = real
    by_label = {f["label"]: f for f in fields}
    assert by_label["Flow"]["field_type"] == "weekly" and by_label["Flow"]["parts"] == DAYS, by_label
    assert by_label["Teacher"]["field_type"] == "text" and not by_label["Teacher"].get("parts")
    print("  detection marks day rows as weekly OK")


def check_seeded_ilaw(app):
    fmt = LessonPlanFormat.query.filter_by(builtin_key="ilaw-lesson-plan").one()
    got = [(f.label, f.field_type) for f in fmt.fields]
    assert got == EXPECTED_ILAW, got
    for f in fmt.fields:
        d = f.to_dict()
        if f.field_type == "weekly":
            assert d["parts"] and len(d["parts"]) >= 4, (f.label, d["parts"])
            assert f.ai_hint, f.label
        else:
            assert d["parts"] is None

    # Every weekly field lands in its own day cells on export.
    user = User.query.filter_by(role="admin").first()
    values = {}
    for f in fmt.fields:
        if f.field_type == "weekly":
            values[f.field_key] = [f"{f.field_key}-{i}" for i in range(len(f.to_dict()["parts"]))]
        else:
            values[f.field_key] = f"{f.field_key}-value"
    plan = LessonPlan(user_id=user.id, format_id=fmt.id, title="ILAW export")
    plan.set_values(values)
    db.session.add(plan)
    db.session.commit()
    out = docx_service.export_lesson_plan(plan, fmt)
    doc = Document(out)
    flow_row = next(r for t in doc.tables for r in t.rows if r.cells[0].text.strip().startswith("Flow"))
    assert [c.text for c in flow_row.cells[1:]] == [f"flow-{i}" for i in range(5)], [c.text for c in flow_row.cells]
    all_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    for key, value in values.items():
        for part in (value if isinstance(value, list) else [value]):
            assert part in all_text, (key, part)
    os.remove(out)
    print("  seeded ILAW OK")


def main():
    check_detection()
    check_limits()
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        check_export_and_render(app)
        check_suggest_marks_weekly(app)
        check_seeded_ilaw(app)
    print("weekly fields OK")


if __name__ == "__main__":
    main()
