"""Self-check for services/field_roles: which fields Guided walks the teacher
through, and which ones Building Proficiency fills in without asking.

The six field types the user named are only part of the story. Their own live
format calls its procedures field "Flow" and its objectives-side fields
"Learning Competency" and "Learning Objectives", so matching on those six words
alone would classify 2 of its 9 thinking-heavy fields correctly. The ILAW table
below is the real format, pinned here as fixtures so this check never depends on
a database.

Run it directly: `venv/Scripts/python test_field_roles.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import field_roles


class Field:
    """Stands in for a FormatField row: only these three attributes are read."""

    def __init__(self, field_key, label, role=None):
        self.field_key = field_key
        self.label = label
        self.role = role


# The user's real ILAW format, in document order: (key, label, expected role).
ILAW = [
    ("name_of_lesson", "Name of Lesson", "easy"),
    ("learning_area_s", "Learning Area/s", "easy"),
    ("designed_by_teacher_s", "Designed by Teacher/s", "easy"),
    ("designed_for_which_grade_level_section", "Designed for which Grade Level & Section", "easy"),
    ("no_of_sessions", "No. of Sessions", "self"),
    ("references", "References", "easy"),
    ("declaration_of_ai_use", "Declaration of AI use", "easy"),
    ("learning_competency", "Learning Competency", "heavy"),
    ("learning_objectives", "Learning Objectives", "heavy"),
    ("learner_context", "Learner Context", "heavy"),
    ("pre_lesson", "Pre-lesson", "heavy"),
    ("flow", "Flow", "heavy"),
    ("learning_resources", "Learning Resources", "easy"),
    ("opportunities_for_integration", "Opportunities for integration", "heavy"),
    ("formative_assessment", "Formative Assessment", "heavy"),
    ("extended_learning_opportunities", "Extended learning opportunities", "heavy"),
    ("reflections", "Reflections", "heavy"),
]


def check_named_six():
    """The six types the user asked Guided to target."""
    for label in ["Objectives", "Learning Objectives", "Content", "Subject Matter",
                  "Procedures", "Procedure", "Assignment", "Application",
                  "Activity", "Activities", "Assessment"]:
        field = Field(label.lower().replace(" ", "_"), label)
        assert field_roles.role_for(field) == "heavy", label
    print("  named six OK")


def check_real_format():
    """Every field of the user's actual format lands on the right side."""
    wrong = []
    for key, label, expected in ILAW:
        got = field_roles.role_for(Field(key, label))
        if got != expected:
            wrong.append((label, expected, got))
    assert not wrong, f"misclassified: {wrong}"

    # The split this format should produce, in document order, because Guided
    # walks the heavy ones in exactly that order.
    heavy = [l for k, l, _ in ILAW if field_roles.role_for(Field(k, l)) == "heavy"]
    easy = [l for k, l, _ in ILAW if field_roles.role_for(Field(k, l)) == "easy"]
    assert len(heavy) == 9, heavy
    assert len(easy) == 7, easy  # Name of Lesson is now AI-filled from the topic
    assert heavy[0] == "Learning Competency", heavy
    assert heavy[-1] == "Reflections", heavy
    print("  real format OK")


def check_self_fields():
    """The session number is the student's own to write (only their schedule
    knows it): not filled in automatically, offered to the AI only if they tick
    it. The lesson title follows from the topic, so the AI fills it."""
    for key, label in [("session_no", "Session No."), ("no_of_sessions", "No. of Sessions"),
                       ("session_number", "Session Number")]:
        assert field_roles.role_for(Field(key, label)) == "self", label
    for key, label in [("lesson_title", "Lesson Title"), ("name_of_lesson", "Name of Lesson")]:
        assert field_roles.role_for(Field(key, label)) != "self", label
    # An explicit override still wins over the keywords.
    assert field_roles.role_for(Field("session_no", "Session No.", role="easy")) == "easy"
    print("  self fields OK")


def check_easy_default():
    """Anything the keywords do not recognise is easy: the teacher can answer an
    unknown short field faster than the AI can be asked about it."""
    for label in ["Name", "Date", "Quarter", "School Year", "Signature",
                  "Checked by", "Page", "Remarks column"]:
        assert field_roles.role_for(Field("x", label)) == "easy", label
    print("  easy default OK")


def check_override_wins():
    """An explicit role beats the keywords in both directions, which is the
    whole point of the override."""
    assert field_roles.role_for(Field("flow", "Flow", role="easy")) == "easy"
    assert field_roles.role_for(Field("no_of_sessions", "No. of Sessions", role="heavy")) == "heavy"
    # A blank or unrecognised override falls back to the keywords rather than
    # erroring, so a stale page cannot break classification.
    assert field_roles.role_for(Field("flow", "Flow", role="")) == "heavy"
    assert field_roles.role_for(Field("flow", "Flow", role="banana")) == "heavy"
    assert field_roles.role_for(Field("flow", "Flow", role=None)) == "heavy"
    print("  override OK")


def check_key_and_label_both_read():
    """The key alone is enough, and so is the label alone: auto-detected fields
    sometimes have a tidy key and an untidy label, or the reverse."""
    assert field_roles.role_for(Field("lesson_procedures", "Part III")) == "heavy"
    assert field_roles.role_for(Field("part_iii", "Lesson Procedures")) == "heavy"
    print("  key and label OK")


def check_missing_attributes():
    """A field with no label must not raise."""
    class Bare:
        field_key = "flow"
        label = None

    assert field_roles.role_for(Bare()) == "heavy"
    print("  missing attributes OK")


def check_to_dict_resolves():
    """to_dict() ships the resolved role, so the browser never has to know the
    keyword list. A stored override shows through; a stored NULL resolves."""
    os.environ["DATABASE_URL"] = "sqlite://"
    from app import create_app
    from extensions import db
    from models.format import FormatField, LessonPlanFormat
    from models.user import User

    app = create_app()
    with app.app_context():
        owner = User(full_name="T", email="roles.t@example.test", role="teacher")
        owner.set_password("password123")
        db.session.add(owner)
        db.session.commit()

        fmt = LessonPlanFormat(owner_id=owner.id, name="Roles")
        db.session.add(fmt)
        db.session.commit()

        auto = FormatField(format_id=fmt.id, field_key="flow", label="Flow", sort_order=0)
        forced = FormatField(format_id=fmt.id, field_key="flow2", label="Flow", role="easy", sort_order=1)
        plain = FormatField(format_id=fmt.id, field_key="quarter", label="Quarter", sort_order=2)
        db.session.add_all([auto, forced, plain])
        db.session.commit()

        assert auto.to_dict()["role"] == "heavy", auto.to_dict()
        assert forced.to_dict()["role"] == "easy", forced.to_dict()
        assert plain.to_dict()["role"] == "easy", plain.to_dict()
        # The raw override ships too, for the builder's select to tell "decide
        # automatically" apart from an explicit choice that happens to match.
        assert auto.to_dict()["role_override"] is None, auto.to_dict()
        assert forced.to_dict()["role_override"] == "easy", forced.to_dict()
        assert plain.to_dict()["role_override"] is None, plain.to_dict()
    print("  to_dict resolves OK")


def check_role_endpoint():
    """The override is saved by field_key, owner-only, and validated against the
    two real roles so a hand-edited request cannot store nonsense."""
    os.environ["DATABASE_URL"] = "sqlite://"
    from app import create_app
    from extensions import db
    from models.format import FormatField, LessonPlanFormat
    from models.user import User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        owner = User(full_name="Owner", email="roles.owner@example.test", role="teacher")
        owner.set_password("password123")
        other = User(full_name="Other", email="roles.other@example.test", role="teacher")
        other.set_password("password123")
        db.session.add_all([owner, other])
        db.session.commit()
        owner_id, other_id = owner.id, other.id

        fmt = LessonPlanFormat(owner_id=owner_id, name="Roles")
        db.session.add(fmt)
        db.session.commit()
        fmt_id = fmt.id
        db.session.add_all([
            FormatField(format_id=fmt_id, field_key="flow", label="Flow", sort_order=0),
            FormatField(format_id=fmt_id, field_key="quarter", label="Quarter", sort_order=1),
        ])
        db.session.commit()

        client = app.test_client()

        def login(uid):
            with client.session_transaction() as sess:
                sess["user_id"] = uid

        url = f"/api/formats/{fmt_id}/field-roles"

        # Someone else's format is off limits.
        login(other_id)
        assert client.patch(url, json={"roles": {"flow": "easy"}}).status_code == 403

        login(owner_id)

        # Flip both directions.
        res = client.patch(url, json={"roles": {"flow": "easy", "quarter": "heavy"}})
        assert res.status_code == 200, res.status_code
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key == {"flow": "easy", "quarter": "heavy"}, by_key

        # null clears the override, so the keywords decide again.
        res = client.patch(url, json={"roles": {"flow": None, "quarter": None}})
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key == {"flow": "heavy", "quarter": "easy"}, by_key

        # Junk values must not overwrite valid stored roles: set flow to easy,
        # then send junk for flow alongside a valid change for quarter.
        # flow must stay easy (junk ignored) while quarter must change.
        res = client.patch(url, json={"roles": {"flow": "easy"}})
        assert res.status_code == 200
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key["flow"] == "easy", by_key
        res = client.patch(url, json={"roles": {"flow": "banana", "quarter": "heavy"}})
        assert res.status_code == 200
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key == {"flow": "easy", "quarter": "heavy"}, by_key

        # Clear flow back to None before the next assertions.
        client.patch(url, json={"roles": {"flow": None}})

        # Junk values and unknown keys are ignored rather than stored or fatal.
        assert client.patch(url, json={"roles": {"flow": "banana"}}).status_code == 200
        assert FormatField.query.filter_by(format_id=fmt_id, field_key="flow").first().role is None
        assert client.patch(url, json={"roles": {"nope": "heavy"}}).status_code == 200
        assert client.patch(url, json={}).status_code == 400
    print("  role endpoint OK")


def check_content_edit_keeps_roles():
    """Editing a format's document re-detects its fields from scratch, and
    _suggest_fields()'s payload carries no role — the exact input that used to
    null out every override. Driving PATCH /formats/<id>/content through the
    test client needs a real .docx (docx_service.resolve_template_path,
    apply_content_edits) plus a live AI call (_suggest_fields), so instead this
    monkeypatches those three I/O-bound pieces out and runs the actual route,
    which is both truer to the real code path and lighter than faking a .docx.
    """
    os.environ["DATABASE_URL"] = "sqlite://"
    from app import create_app
    from extensions import db
    from models.format import FormatField, LessonPlanFormat
    from models.user import User
    from routes import format_routes

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        owner = User(full_name="T", email="roles.edit@example.test", role="teacher")
        owner.set_password("password123")
        db.session.add(owner)
        db.session.commit()

        fmt = LessonPlanFormat(owner_id=owner.id, name="Roles Edit")
        db.session.add(fmt)
        db.session.commit()
        fmt_id = fmt.id

        # "flow" carries an explicit override; "quarter" does not and
        # will not survive re-detection at all, which is the expected case of
        # a field genuinely going away.
        db.session.add_all([
            FormatField(format_id=fmt_id, field_key="flow", label="Flow", role="easy", sort_order=0),
            FormatField(format_id=fmt_id, field_key="quarter", label="Quarter", sort_order=1),
        ])
        db.session.commit()

        # Re-detection finds "flow" again (same key) plus a brand new field
        # with no override of its own.
        real_resolve = format_routes.docx_service.resolve_template_path
        real_apply = format_routes.docx_service.apply_content_edits
        real_suggest = format_routes._suggest_fields
        format_routes.docx_service.resolve_template_path = lambda f: "fake.docx"
        format_routes.docx_service.apply_content_edits = lambda path, edits: ([], edits)
        format_routes._suggest_fields = lambda path: (
            [
                {"label": "Flow", "field_key": "flow", "anchor_index": 0},
                {"label": "New Field", "field_key": "new_field", "anchor_index": 1},
            ],
            None,
        )
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = owner.id
            res = client.patch(
                f"/api/formats/{fmt_id}/content",
                json={"edits": [{"anchor_index": 0, "action": "format", "text": "x"}]},
            )
        finally:
            format_routes.docx_service.resolve_template_path = real_resolve
            format_routes.docx_service.apply_content_edits = real_apply
            format_routes._suggest_fields = real_suggest

        assert res.status_code == 200, res.get_json()
        by_key = {f["field_key"]: f["role_override"] for f in res.get_json()["format"]["fields"]}
        # The override on a field that still exists after re-detection must
        # survive; a field re-detection did not bring back simply has no row
        # to restore it onto, which is correct.
        assert by_key == {"flow": "easy", "new_field": None}, by_key
    print("  content edit keeps roles OK")


check_named_six()
check_real_format()
check_self_fields()
check_easy_default()
check_override_wins()
check_key_and_label_both_read()
check_missing_attributes()
check_to_dict_resolves()
check_role_endpoint()
check_content_edit_keeps_roles()
print("field roles OK")
