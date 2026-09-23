# Generator Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two generation modes independent — Guided walks the thinking-heavy fields, Building Proficiency auto-fills the easy ones and offers the heavy ones as a checklist — while fixing the bug that makes answered fields silently uneditable and the toolbar vanish in fullscreen.

**Architecture:** A single `field_roles` module classifies every field `heavy` or `easy`, resolved server-side and shipped in the field's API payload so the browser never re-implements the rule. The generator keeps one state slot per mode and swaps them on switch, persisting the inactive slot in a new `mode_values` column so `field_values` keeps meaning "what the active mode shows" and export, submission and existing saved plans are untouched.

**Tech Stack:** Flask + SQLAlchemy (MySQL in production, SQLite for self-checks), vanilla ES5-ish browser JS with no build step, `python-docx` for export. Self-checks are plain `assert`-based scripts run directly with `venv/Scripts/python <file>.py`, matching the existing `test_*.py` in `backend/`.

**Spec:** `docs/superpowers/specs/2026-09-23-generator-modes-design.md`

## Global Constraints

- Python is run via `backend/venv/Scripts/python` on Windows, `backend/venv/bin/python` on the VPS. Never assume a global `python`.
- Tests are standalone scripts, not pytest. Each sets `os.environ["DATABASE_URL"] = "sqlite://"` **before** importing `app`, prints `<name> OK` on success, and is run as `venv/Scripts/python test_x.py`.
- New DB columns go through `_add_column(table, column, ddl_type)` in `backend/app.py`. Never write a bare `ALTER TABLE`: three gunicorn workers boot at once and a bare ALTER races.
- Frontend has no bundler. New JS files are plain `<script src>` tags added to each page that needs them, before the page's own script.
- No new dependencies, frontend or backend. The VPS has 1 GB RAM shared across several apps.
- UI copy is formal and contains no em dashes.
- Never give a card, panel or banner a single-sided accent border. Status is carried by a word, icon or tinted fill with a complete border on all four sides.
- Never overwrite `backend/.env` when deploying; it holds the live DB credentials and AI key.
- Verify every behaviour claim by running it. Do not report a step passing without its command output.

---

### Task 1: Field role classification

**Files:**
- Create: `backend/services/field_roles.py`
- Test: `backend/test_field_roles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `field_roles.role_for(field) -> "heavy" | "easy"`, where `field` is any object with `.field_key`, `.label` and optionally `.role`. Also `field_roles.HEAVY = "heavy"` and `field_roles.EASY = "easy"`.

- [ ] **Step 1: Write the failing test**

Create `backend/test_field_roles.py`:

```python
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
    ("no_of_sessions", "No. of Sessions", "easy"),
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
    assert len(easy) == 8, easy
    assert heavy[0] == "Learning Competency", heavy
    assert heavy[-1] == "Reflections", heavy
    print("  real format OK")


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


check_named_six()
check_real_format()
check_easy_default()
check_override_wins()
check_key_and_label_both_read()
check_missing_attributes()
print("field roles OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.field_roles'`

- [ ] **Step 3: Write the implementation**

Create `backend/services/field_roles.py`:

```python
"""Which fields need a teacher's pedagogical thinking, and which are quick facts.

The two generation modes have opposite purposes, so they should target opposite
halves of a format. Guided walks the teacher through the thinking-heavy fields
one at a time with the owl's help; Building Proficiency fills in the quick facts
without asking and offers the heavy ones as an opt-in checklist.

The classification is keyword-based because it has to work on formats that
already exist, with no setup and no per-field curation. A field may override it
outright (FormatField.role), which is what a school whose wording this module
does not recognise should reach for.

The keywords deliberately cover DepEd lesson-plan vocabulary rather than only
the obvious six words: a real format in use calls its procedures section "Flow"
and its objectives "Learning Competency", neither of which contains "procedure"
or "objective".
"""

HEAVY = "heavy"
EASY = "easy"

# Matched as plain substrings against "<field_key> <label>", lowercased with
# underscores turned into spaces. Substrings rather than whole words so
# "learning_objectives", "Objectives:" and "objective" all match one entry.
_HEAVY_KEYWORDS = (
    # Objectives and content
    "objective", "competency", "competencies", "content", "subject matter",
    "topic outline",
    # Procedures
    "procedure", "flow", "learning task", "lesson proper", "sequence", "steps",
    # Activity and motivation
    "activity", "activities", "motivation", "pre-lesson", "pre lesson",
    "energizer", "warm-up", "warm up", "icebreaker", "routine", "drill",
    # Application, analysis, abstraction (the DepEd 4A's)
    "application", "integration", "abstraction", "analysis", "generalization",
    "generalisation", "valuing",
    # Assessment and assignment
    "assignment", "assessment", "evaluation", "extended learning",
    "enrichment", "agreement", "remediation",
    # Reflection and learner context
    "reflection", "learner context",
)


def _haystack(field) -> str:
    key = getattr(field, "field_key", "") or ""
    label = getattr(field, "label", "") or ""
    return f"{key} {label}".replace("_", " ").lower()


def role_for(field) -> str:
    """HEAVY or EASY for one field.

    An explicit field.role wins outright. Anything the keywords do not recognise
    is EASY: an unfamiliar short field is quicker for the teacher to type than to
    be walked through, and treating unknowns as heavy would drag every stray
    "Remarks" column into the Guided walkthrough.
    """
    override = (getattr(field, "role", None) or "").strip().lower()
    if override in (HEAVY, EASY):
        return override

    haystack = _haystack(field)
    return HEAVY if any(word in haystack for word in _HEAVY_KEYWORDS) else EASY


```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: PASS, ending `field roles OK`

If `check_real_format` fails, do not loosen the test — the ILAW table is ground truth taken from the live database. Add the missing vocabulary to `_HEAVY_KEYWORDS` instead.

- [ ] **Step 5: Commit**

```bash
git add backend/services/field_roles.py backend/test_field_roles.py
git commit -m "Classify format fields as thinking-heavy or quick to answer"
```

---

### Task 2: Store and expose the role

**Files:**
- Modify: `backend/models/format.py` (`FormatField`: add `role` column, add `"role"` to `to_dict()`)
- Modify: `backend/app.py` (new `_migrate_format_field_columns` line)
- Test: `backend/test_field_roles.py` (append a DB-backed check)

**Interfaces:**
- Consumes: `field_roles.role_for` from Task 1.
- Produces: `FormatField.role` (nullable string column, `None` means decide by keyword) and a `"role"` key in `FormatField.to_dict()` holding the **resolved** role, never the raw override. The browser reads only the resolved value.

- [ ] **Step 1: Write the failing test**

Append to `backend/test_field_roles.py`, before the final `print("field roles OK")` and after the other `check_*()` calls:

```python
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
        plain = FormatField(format_id=fmt.id, field_key="no_of_sessions", label="No. of Sessions", sort_order=2)
        db.session.add_all([auto, forced, plain])
        db.session.commit()

        assert auto.to_dict()["role"] == "heavy", auto.to_dict()
        assert forced.to_dict()["role"] == "easy", forced.to_dict()
        assert plain.to_dict()["role"] == "easy", plain.to_dict()
        # The raw override is not exposed; only the resolved role is.
        assert "role_override" not in auto.to_dict()
    print("  to_dict resolves OK")
```

Add `check_to_dict_resolves()` to the list of calls at the bottom of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: FAIL — `TypeError: 'role' is an invalid keyword argument for FormatField`

- [ ] **Step 3: Write the implementation**

In `backend/models/format.py`, add the import at the top:

```python
from services import field_roles
```

Add the column to `FormatField`, directly after `anchor_index`:

```python
    # Overrides the keyword-based guess in services/field_roles: "heavy" means
    # Guided walks the teacher through this field and Building Proficiency only
    # writes it when asked, "easy" means the reverse. NULL (the default for
    # every field) leaves the decision to the keywords.
    role = db.Column(db.String(10))
```

Add to `FormatField.to_dict()`, after `"anchor_index"`:

```python
            # The resolved role, not the raw override, so the browser reads one
            # value and never needs the keyword list.
            "role": field_roles.role_for(self),
```

In `backend/app.py`, inside `_migrate_format_field_columns()`, add after the existing `anchor_index` line:

```python
    _add_column("format_fields", "role", "VARCHAR(10)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: PASS, ending `field roles OK`

Then confirm nothing else broke and the migration is idempotent:

Run: `cd backend && venv/Scripts/python test_migration_race.py && DATABASE_URL="sqlite://" venv/Scripts/python -c "from app import create_app; create_app(); print('boots OK')"`
Expected: `migration race OK` then `boots OK`

- [ ] **Step 5: Commit**

```bash
git add backend/models/format.py backend/app.py backend/test_field_roles.py
git commit -m "Store a per-field role override and ship the resolved role to the page"
```

---

### Task 3: Saving role overrides

**Files:**
- Modify: `backend/routes/format_routes.py` (accept `role` in the manual fields payload; add the bulk endpoint)
- Test: `backend/test_field_roles.py` (append an endpoint check)

**Interfaces:**
- Consumes: `FormatField.role` from Task 2.
- Produces: `PATCH /api/formats/<int:format_id>/field-roles` with body `{"roles": {"<field_key>": "heavy"|"easy"|null}}`, owner-only, returning `{"status": "ok", "fields": [...]}`. Also the existing manual `fields` payload now honours a per-field `"role"`.

- [ ] **Step 1: Write the failing test**

Append to `backend/test_field_roles.py` and add the call at the bottom:

```python
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
            FormatField(format_id=fmt_id, field_key="no_of_sessions", label="No. of Sessions", sort_order=1),
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
        res = client.patch(url, json={"roles": {"flow": "easy", "no_of_sessions": "heavy"}})
        assert res.status_code == 200, res.status_code
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key == {"flow": "easy", "no_of_sessions": "heavy"}, by_key

        # null clears the override, so the keywords decide again.
        res = client.patch(url, json={"roles": {"flow": None, "no_of_sessions": None}})
        by_key = {f["field_key"]: f["role"] for f in res.get_json()["fields"]}
        assert by_key == {"flow": "heavy", "no_of_sessions": "easy"}, by_key

        # Junk values and unknown keys are ignored rather than stored or fatal.
        assert client.patch(url, json={"roles": {"flow": "banana"}}).status_code == 200
        assert FormatField.query.filter_by(format_id=fmt_id, field_key="flow").first().role is None
        assert client.patch(url, json={"roles": {"nope": "heavy"}}).status_code == 200
        assert client.patch(url, json={}).status_code == 400
    print("  role endpoint OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: FAIL — the PATCH returns 404 because the route does not exist

- [ ] **Step 3: Write the implementation**

In `backend/routes/format_routes.py`, find where the manual fields payload is parsed (the loop building `FormatField(...)` from request JSON) and add `role` alongside `field_type` and `is_required`, accepting only the two valid values:

```python
        role = (item.get("role") or "").strip().lower()
        if role not in ("heavy", "easy"):
            role = None
```

Pass `role=role` into the `FormatField(...)` constructor.

Then add the bulk endpoint. Place it next to the other `/formats/<int:format_id>/...` routes:

```python
@format_bp.patch("/formats/<int:format_id>/field-roles")
@login_required
def set_field_roles(format_id):
    """Override which fields Guided walks the teacher through.

    Keyed by field_key rather than field id because a document-based format
    re-detects its fields whenever the reference file is edited, which gives them
    new ids; the key survives that.

    A null value clears the override and hands the decision back to the keywords
    in services/field_roles. An unrecognised value or unknown key is ignored
    rather than rejected, so one stale entry from an open page cannot lose the
    rest of the teacher's choices.
    """
    user = current_user()
    fmt = LessonPlanFormat.query.get_or_404(format_id)
    if fmt.owner_id != user.id:
        return jsonify({"status": "error", "message": "You don't have access to this format."}), 403

    data = request.get_json(silent=True) or {}
    roles = data.get("roles")
    if not isinstance(roles, dict) or not roles:
        return jsonify({"status": "error", "message": "Send at least one field role."}), 400

    by_key = {f.field_key: f for f in fmt.fields}
    for key, value in roles.items():
        field = by_key.get(key)
        if field is None:
            continue
        if value is None:
            field.role = None
            continue
        normalised = str(value).strip().lower()
        field.role = normalised if normalised in ("heavy", "easy") else None

    db.session.commit()
    return jsonify({"status": "ok", "fields": [f.to_dict() for f in fmt.fields]})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python test_field_roles.py`
Expected: PASS, ending `field roles OK`

- [ ] **Step 5: Commit**

```bash
git add backend/routes/format_routes.py backend/test_field_roles.py
git commit -m "Let a format owner override which fields Guided targets"
```

---

### Task 4: Generate only the requested fields

**Files:**
- Modify: `backend/services/ai_service.py` (`generate_full`, `generate_full_streaming`)
- Modify: `backend/routes/generate_routes.py` (`generate_full`, `generate_full_stream`)
- Test: `backend/test_generate_selection.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: both generation endpoints accept optional `include_keys: [str]`. `ai_service.generate_full_streaming(context, fields, course_guide_text="", include_keys=None)` generates only those keys and its `complete` event's `missing` / `missing_labels` count only the requested fields. A helper `ai_service.select_fields(fields, include_keys)` returns the fields to generate.

- [ ] **Step 1: Write the failing test**

Create `backend/test_generate_selection.py`:

```python
"""Self-check that generation writes only the fields it was asked for.

Building Proficiency always writes the quick fields and offers the
thinking-heavy ones as a checklist, so a request now carries the exact set to
generate. Two things must hold: nothing outside that set is written, and the
"couldn't be generated" report counts only the requested fields — warning a
teacher about a Flow they deliberately kept for themselves would train them to
ignore the warning entirely.

The provider is never called: ai_service._call is replaced with a stub, so this
runs with no API key and no network.

Run it directly: `venv/Scripts/python test_generate_selection.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service


class Field:
    def __init__(self, field_key, label, field_type="textarea", ai_hint=None):
        self.field_key = field_key
        self.label = label
        self.field_type = field_type
        self.ai_hint = ai_hint


FIELDS = [
    Field("teacher", "Designed by Teacher/s", "text"),
    Field("sessions", "No. of Sessions", "text"),
    Field("objectives", "Learning Objectives", "list"),
    Field("flow", "Flow"),
    Field("assessment", "Formative Assessment"),
]


def stub_answers(answers, seen_keys):
    """Replace the provider with a stub that answers from `answers` and records
    which keys it was asked for."""
    def fake_call(system_instruction, parts, label):
        asked = [f.field_key for f in FIELDS if f.field_key in " ".join(parts)]
        seen_keys.extend(asked)
        return {k: answers.get(k, "") for k in asked}

    ai_service._call = fake_call


def run(include_keys):
    seen = []
    stub_answers({k: f"content for {k}" for k in
                  ["teacher", "sessions", "objectives", "flow", "assessment"]}, seen)
    events = list(ai_service.generate_full_streaming(
        {"topic": "Spreadsheets"}, FIELDS, course_guide_text="", include_keys=include_keys))
    final = [e for e in events if e["type"] == "complete"][-1]
    return final, seen


def check_subset_only():
    final, seen = run(["teacher", "sessions", "objectives"])
    assert set(final["values"]) == {"teacher", "sessions", "objectives"}, final["values"]
    assert "flow" not in seen, seen
    assert "assessment" not in seen, seen
    print("  subset only OK")


def check_missing_counts_requested_only():
    """A field left out of the request is not missing — it was never asked for."""
    seen = []
    # Everything answers except "objectives", which comes back empty.
    stub_answers({"teacher": "T", "sessions": "2", "objectives": "", "flow": "F"}, seen)
    events = list(ai_service.generate_full_streaming(
        {"topic": "X"}, FIELDS, course_guide_text="",
        include_keys=["teacher", "sessions", "objectives"]))
    final = [e for e in events if e["type"] == "complete"][-1]
    # flow and assessment were not requested, so they must not be reported.
    assert "flow" not in final["missing"], final["missing"]
    assert "assessment" not in final["missing"], final["missing"]
    # objectives was requested and came back empty, so it must be reported.
    assert "objectives" in final["missing"], final["missing"]
    assert "Learning Objectives" in final["missing_labels"], final["missing_labels"]
    print("  missing accounting OK")


def check_absent_means_everything():
    """No include_keys at all keeps the old behaviour: generate the lot."""
    final, seen = run(None)
    assert set(final["values"]) == {"teacher", "sessions", "objectives", "flow", "assessment"}, final["values"]
    assert final["missing"] == [], final["missing"]
    print("  absent means everything OK")


def check_unknown_keys_ignored():
    final, seen = run(["teacher", "not_a_field"])
    assert set(final["values"]) == {"teacher"}, final["values"]
    assert "not_a_field" not in final["missing"], final["missing"]
    print("  unknown keys ignored OK")


def check_empty_selection():
    """An empty list means generate nothing, and must not raise."""
    final, seen = run([])
    assert final["values"] == {}, final["values"]
    assert final["missing"] == [], final["missing"]
    print("  empty selection OK")


def check_select_fields_helper():
    picked = ai_service.select_fields(FIELDS, ["flow", "teacher"])
    # Document order is preserved, not the order of include_keys.
    assert [f.field_key for f in picked] == ["teacher", "flow"], [f.field_key for f in picked]
    assert len(ai_service.select_fields(FIELDS, None)) == len(FIELDS)
    print("  select_fields OK")


check_subset_only()
check_missing_counts_requested_only()
check_absent_means_everything()
check_unknown_keys_ignored()
check_empty_selection()
check_select_fields_helper()
print("generate selection OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python test_generate_selection.py`
Expected: FAIL — `AttributeError: module 'services.ai_service' has no attribute 'select_fields'`

- [ ] **Step 3: Write the implementation**

In `backend/services/ai_service.py`, add above `generate_full`:

```python
def select_fields(fields, include_keys):
    """The fields to generate, in document order.

    include_keys is None for "generate everything", which is what a page that
    predates the checklist sends. An empty list genuinely means generate nothing.
    Order comes from `fields`, not from include_keys, because the chunking below
    relies on document order for coherent output.
    """
    if include_keys is None:
        return list(fields)
    wanted = set(include_keys)
    return [f for f in fields if f.field_key in wanted]
```

Change `generate_full`'s signature and body to honour it:

```python
def generate_full(context: dict, fields, course_guide_text: str = "", include_keys=None) -> dict:
    targets = select_fields(fields, include_keys)
    if not targets:
        return {}
    lesson = _lesson_block(context, guide_excerpt(course_guide_text, context))
    task = f"""
Fill ONLY the following fields and return strict JSON with field_key as keys:
{_schema_block(targets)}
"""
    values = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], "Building Proficiency"), targets)
    values.update(_fill_gaps(lesson, targets, values, "Building Proficiency"))
    return values
```

Change `generate_full_streaming` the same way. Its signature becomes:

```python
def generate_full_streaming(context: dict, fields, course_guide_text: str = "", include_keys=None):
```

Immediately after the docstring, replace `fields = list(fields)` with:

```python
    # Only the requested fields are generated, and only they are held to account
    # in the completeness report at the end.
    fields = select_fields(fields, include_keys)
    if not fields:
        yield {"type": "complete", "values": {}, "missing": [], "missing_labels": []}
        return
```

Every later use of `fields` in that function (the chunking, the gap-fill call, the two `missing_keys` calls) then already refers to the requested subset, so no other edit is needed inside it.

In `backend/routes/generate_routes.py`, add a parser next to `_build_context`:

```python
def _include_keys(data, fmt):
    """The field_keys this request wants generated, or None for all of them.

    Validated against the format so an unknown key is dropped rather than
    reaching the prompt. An empty list is preserved as an empty list: it means
    "generate nothing", which is different from "generate everything".
    """
    raw = data.get("include_keys")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    valid = {f.field_key for f in fmt.fields}
    return [str(k) for k in raw if str(k) in valid]
```

Then in `generate_full()` pass it through:

```python
    field_values = ai_service.generate_full(
        context, fmt.fields, course_guide_text=course_guide_text,
        include_keys=_include_keys(data, fmt),
    )
```

And in `generate_full_stream()`, compute it before `_stream()` is defined (it must be read outside the generator, while the request context is still live):

```python
    include_keys = _include_keys(data, fmt)
```

then pass `include_keys=include_keys` into the `ai_service.generate_full_streaming(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python test_generate_selection.py`
Expected: PASS, ending `generate selection OK`

Then confirm the AI trimming checks still pass:

Run: `cd backend && venv/Scripts/python test_ai_limits.py && venv/Scripts/python test_rich_export.py`
Expected: `ai limits OK` then `rich export OK`

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_service.py backend/routes/generate_routes.py backend/test_generate_selection.py
git commit -m "Generate only the requested fields and report only those as missing"
```

---

### Task 5: Per-mode values on a plan

**Files:**
- Modify: `backend/models/lesson_plan.py` (add `mode_values`, accessors, `to_dict`)
- Modify: `backend/app.py` (`_migrate_lesson_plan_columns`: one new entry)
- Modify: `backend/routes/generate_routes.py` (`save_lesson_plan`, `update_lesson_plan` accept `mode_values`)
- Test: `backend/test_lesson_plan_drafts.py` (append checks)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `LessonPlan.mode_values` TEXT column holding JSON for the **inactive** mode, `plan.get_mode_values() -> dict`, `plan.set_mode_values(dict)`, and `"mode_values"` in `to_dict()`. Both POST and PATCH accept a `mode_values` object.

- [ ] **Step 1: Write the failing test**

Append to `backend/test_lesson_plan_drafts.py`, inside `main()` just before the final `print(...)`:

```python
        # --- Per-mode progress -------------------------------------------------
        # field_values keeps holding whatever the active mode shows, so export and
        # submission are untouched; the other mode's work rides along in
        # mode_values. This is what lets Guided and Building Proficiency be two
        # drafts of the plan rather than one shared one.
        login(student_id)
        res = client.post("/api/lesson-plans", json={
            "format_id": format_id,
            "title": "Two modes",
            "generation_mode": "full",
            "field_values": {"flow": "written by Building Proficiency"},
            "mode_values": {
                "field_values": {"flow": "written in Guided"},
                "rich_field_values": {"flow": "<b>written in Guided</b>"},
                "step_index": 2,
            },
        })
        assert res.status_code == 201, res.status_code
        two = res.get_json()["lesson_plan"]
        two_id = two["id"]
        assert two["field_values"]["flow"] == "written by Building Proficiency"
        assert two["mode_values"]["field_values"]["flow"] == "written in Guided", two["mode_values"]
        assert two["mode_values"]["step_index"] == 2

        # Switching mode swaps the two slots, which is one ordinary PATCH.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={
            "generation_mode": "step",
            "field_values": {"flow": "written in Guided"},
            "rich_field_values": {"flow": "<b>written in Guided</b>"},
            "mode_values": {"field_values": {"flow": "written by Building Proficiency"},
                            "rich_field_values": {}, "step_index": 0},
        })
        assert res.status_code == 200, res.status_code
        swapped = res.get_json()["lesson_plan"]
        assert swapped["generation_mode"] == "step"
        assert swapped["field_values"]["flow"] == "written in Guided"
        assert swapped["mode_values"]["field_values"]["flow"] == "written by Building Proficiency"

        # A PATCH that omits mode_values leaves the stored slot alone, so an
        # autosave carrying only the active mode cannot wipe the other one.
        res = client.patch(f"/api/lesson-plans/{two_id}", json={"title": "Renamed"})
        kept = res.get_json()["lesson_plan"]
        assert kept["title"] == "Renamed"
        assert kept["mode_values"]["field_values"]["flow"] == "written by Building Proficiency", kept["mode_values"]

        # A plan saved before this existed reads as an empty slot rather than
        # None, so the page can use it without a null check.
        plain = LessonPlan(user_id=student_id, format_id=format_id, title="Old plan")
        plain.set_values({"flow": "legacy"})
        db.session.add(plain)
        db.session.commit()
        assert plain.to_dict()["mode_values"] == {}, plain.to_dict()["mode_values"]

        # Junk in the column does not crash a read.
        plain.mode_values = "not json"
        db.session.commit()
        assert plain.to_dict()["mode_values"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python test_lesson_plan_drafts.py`
Expected: FAIL — `KeyError: 'mode_values'`

- [ ] **Step 3: Write the implementation**

In `backend/models/lesson_plan.py`, add the column after `is_public`:

```python
    # The mode the teacher is NOT currently in. field_values/rich_field_values
    # always hold the active mode's content, which is what export, submission and
    # every plan saved before this column existed rely on; this carries the other
    # mode's copy so Guided and Building Proficiency can be two drafts of the same
    # plan instead of overwriting each other. Shape:
    # {"field_values": {...}, "rich_field_values": {...}, "step_index": int}
    mode_values = db.Column(db.Text)
```

Add the accessors next to `get_rich_values`:

```python
    def get_mode_values(self):
        """The inactive mode's slot, or {} when there isn't one.

        Returns {} rather than None for a plan saved before this column existed,
        and also for unparseable content, so callers never need a null check and a
        corrupted value degrades to "no other mode" instead of an error.
        """
        try:
            value = json.loads(self.mode_values or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_mode_values(self, values: dict):
        self.mode_values = json.dumps(values or {})
```

Add to `to_dict()`, after `"is_public"`:

```python
            "mode_values": self.get_mode_values(),
```

In `backend/app.py`, add to the `new_columns` dict inside `_migrate_lesson_plan_columns()`:

```python
        # The inactive generation mode's values; see LessonPlan.mode_values.
        "mode_values": "TEXT",
```

In `backend/routes/generate_routes.py`, in `save_lesson_plan()` after `plan.set_rich_values(...)`:

```python
    plan.set_mode_values(data.get("mode_values") or {})
```

And in `update_lesson_plan()`, alongside the other `if "..." in data` blocks:

```python
    if "mode_values" in data:
        plan.set_mode_values(data.get("mode_values") or {})
```

Note the `in data` guard: an autosave that carries only the active mode must not clear the other mode's slot.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python test_lesson_plan_drafts.py`
Expected: PASS, ending `lesson plan drafts OK`

- [ ] **Step 5: Commit**

```bash
git add backend/models/lesson_plan.py backend/app.py backend/routes/generate_routes.py backend/test_lesson_plan_drafts.py
git commit -m "Give each generation mode its own saved progress"
```

---

### Task 6: Fullscreen keeps the toolbar

**Files:**
- Modify: `frontend/generator.html` (wrap toolbar + canvas in `#live-doc-stage`)
- Modify: `frontend/format-builder.html` (wrap toolbar + canvas in `#doc-stage`)
- Modify: `frontend/js/doc-toolbar.js` (`initDocViewControls` gains `stageEl`)
- Modify: `frontend/js/generator.js`, `frontend/js/format-builder.js` (pass `stageEl`)
- Modify: `frontend/css/style.css` (stage + sticky toolbar rules)

**Interfaces:**
- Consumes: `initDocViewControls({ toolbarEl, wrapEl, storageKey })` from the existing shared toolbar.
- Produces: `initDocViewControls({ toolbarEl, wrapEl, stageEl, storageKey })`. `stageEl` is what goes fullscreen and defaults to `wrapEl` when omitted, so existing call sites keep working.

- [ ] **Step 1: Wrap the generator's toolbar and canvas in one stage**

In `frontend/generator.html`, replace these two sibling lines:

```html
              <div id="live-doc-toolbar" class="doc-toolbar mt-16" hidden></div>
              <div id="live-doc-wrap" class="lp-doc-wrap" hidden></div>
```

with:

```html
              <!-- Toolbar and canvas share one stage because the stage is what
                   goes fullscreen: fullscreening the canvas alone left the
                   toolbar outside the fullscreened subtree and so invisible. -->
              <div id="live-doc-stage" class="doc-stage" hidden>
                <div id="live-doc-toolbar" class="doc-toolbar"></div>
                <div id="live-doc-wrap" class="lp-doc-wrap"></div>
              </div>
```

- [ ] **Step 2: Wrap the builder's toolbar and canvas the same way**

In `frontend/format-builder.html`, replace:

```html
          <div id="doc-toolbar" class="doc-toolbar"></div>
          <div class="lp-doc-wrap doc-builder-canvas" id="doc-builder-canvas"></div>
```

with:

```html
          <div id="doc-stage" class="doc-stage">
            <div id="doc-toolbar" class="doc-toolbar"></div>
            <div class="lp-doc-wrap doc-builder-canvas" id="doc-builder-canvas"></div>
          </div>
```

- [ ] **Step 3: Teach initDocViewControls about the stage**

In `frontend/js/doc-toolbar.js`, change the signature:

```js
function initDocViewControls({ toolbarEl, wrapEl, stageEl, storageKey }) {
  // What goes fullscreen. The toolbar has to be inside it or it vanishes the
  // moment fullscreen starts, so callers pass the element containing both.
  // Falls back to wrapEl so a caller with no stage still works.
  const fsEl = stageEl || wrapEl;
```

Then replace every remaining use of `wrapEl` **in the fullscreen functions only** (`isFullscreen`, `toggleFullscreen`, and the Escape handler) with `fsEl`. Leave the zoom code, the wheel listener and `applyZoom()` on `wrapEl` — zoom scales the page, not the toolbar.

Concretely, `isFullscreen` becomes:

```js
  function isFullscreen() {
    return document.fullscreenElement === fsEl || fsEl.classList.contains("is-pseudo-fullscreen");
  }
```

`toggleFullscreen`'s three `wrapEl` references become `fsEl`, and the Escape handler's two become `fsEl`.

- [ ] **Step 4: Pass the stage from both pages**

In `frontend/js/generator.js`, add near the other element handles:

```js
const liveDocStage = document.getElementById("live-doc-stage");
```

In `wireLiveDocToolbar()`, change the `initDocViewControls` call to include `stageEl: liveDocStage`.

`liveDocWrap.hidden` and `liveDocToolbar.hidden` are set in exactly one place, `initLiveDocView()`. Replace there:

```js
  liveDocWrap.hidden = false;
```

with:

```js
  liveDocStage.hidden = false;
```

and delete the now-redundant `liveDocToolbar.hidden = false;` line, since the stage carries both.

In `frontend/js/format-builder.js`, change its `initDocViewControls` call to include:

```js
    stageEl: document.getElementById("doc-stage"),
```

- [ ] **Step 5: Add the CSS**

Append to `frontend/css/style.css`:

```css
/* ---------------------------------------------------------------------------
   Document stage: toolbar plus canvas, and the unit that goes fullscreen
   --------------------------------------------------------------------------- */

.doc-stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
  margin-top: 16px;
}

/* Sticky rather than fixed, so the toolbar stays reachable while the document
   scrolls under it both on the page and in fullscreen. */
.doc-stage .doc-toolbar {
  position: sticky;
  top: 0;
  z-index: 20;
  margin-top: 0;
  background: var(--surface);
}

/* In fullscreen the stage IS the screen, so it supplies the page ground and
   owns the scrolling; the canvas inside it scrolls, the toolbar does not. */
.doc-stage:fullscreen {
  padding: 0;
  background: var(--bg);
}

.doc-stage:fullscreen .lp-doc-wrap {
  flex: 1;
  overflow: auto;
  padding: 24px;
  margin: 0;
}

.doc-stage.is-pseudo-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  margin: 0;
  background: var(--bg);
}

.doc-stage.is-pseudo-fullscreen .lp-doc-wrap {
  flex: 1;
  overflow: auto;
  padding: 24px;
  margin: 0;
}
```

Also remove the two now-superseded fullscreen blocks added in the previous change, `.lp-doc-wrap:fullscreen` and `.lp-doc-wrap.is-pseudo-fullscreen`, so the wrapper no longer claims to be the fullscreen element.

- [ ] **Step 6: Verify in a browser**

Start the server: `cd backend && venv/Scripts/python run.py`

Then in the browser, on `generator.html?format_id=<id>`, confirm with this snippet in the console:

```js
const stage = document.getElementById('live-doc-stage');
const bar = document.getElementById('live-doc-toolbar');
console.log('toolbar inside stage:', stage.contains(bar));   // must be true
console.log('zoom target still the wrap:', !!document.getElementById('live-doc-wrap'));
```

Expected: `toolbar inside stage: true`. Then click the fullscreen button and confirm by eye that the toolbar is still visible and its buttons still work, and that Escape leaves fullscreen.

- [ ] **Step 7: Commit**

```bash
git add frontend/generator.html frontend/format-builder.html frontend/js/doc-toolbar.js frontend/js/generator.js frontend/js/format-builder.js frontend/css/style.css
git commit -m "Keep the document toolbar visible in fullscreen"
```

---

### Task 7: Make answered fields editable again, and target Guided at heavy fields

**Files:**
- Modify: `frontend/js/generator.js` (`applyStepLocks`, and where `stepFieldKeys` is built)

**Interfaces:**
- Consumes: the `"role"` key on each field from Task 2.
- Produces: `heavyFieldKeys()` and `easyFieldKeys()` helpers in `generator.js`, and `stepFieldKeys` holding only the heavy keys (falling back to all keys when a format has none).

- [ ] **Step 1: Add the role helpers**

In `frontend/js/generator.js`, add near the other field helpers:

```js
// Which fields each mode is for. The role is resolved server-side and arrives on
// the field, so the keyword list lives in exactly one place (see
// backend/services/field_roles.py).
function fieldsInDocumentOrder() {
  return (fmt.fields || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
}

function heavyFieldKeys() {
  return fieldsInDocumentOrder().filter((f) => f.role === "heavy").map((f) => f.field_key);
}

function easyFieldKeys() {
  return fieldsInDocumentOrder().filter((f) => f.role !== "heavy").map((f) => f.field_key);
}
```

- [ ] **Step 2: Point Guided at the heavy fields**

Find where `stepFieldKeys` is assigned in `init()`:

```js
    stepFieldKeys = fmt.fields.slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)).map((f) => f.field_key);
```

Replace it with:

```js
    // Guided walks the fields that need real thinking. The quick ones are left
    // out of the walkthrough entirely: a teacher does not need to be guided
    // through their own name, and locking those behind a step was most of why
    // fields felt uneditable.
    const heavy = heavyFieldKeys();
    // A format with no heavy fields would leave Guided with nothing to do, so it
    // falls back to walking everything.
    stepFieldKeys = heavy.length ? heavy : fieldsInDocumentOrder().map((f) => f.field_key);
```

- [ ] **Step 3: Stop locking fields the teacher has already answered**

In `applyStepLocks()`, the document branch currently reads:

```js
        } else if (i > stepIndex) {
          el.contentEditable = "false";
          el.classList.add("step-locked");
        } else {
          el.contentEditable = "false";
        }
```

Replace the whole `else if / else` with:

```js
        } else if (i > stepIndex) {
          el.contentEditable = "false";
          el.classList.add("step-locked");
        } else {
          // A field the teacher has already answered stays theirs to correct.
          // It used to be set read-only with no lock styling at all, so it
          // looked perfectly editable and silently swallowed typing, which is
          // what "I can't edit the fields" was.
          el.contentEditable = "true";
        }
```

In the fallback (non-document) branch, `el.disabled = i > stepIndex;` is already correct — a completed field is not disabled there — but fields outside `stepFieldKeys` now return `-1` from `indexOf`, which would make `-1 > stepIndex` false and leave them enabled. That is the wanted behaviour; add a comment so it is not "fixed" later:

```js
      const i = stepFieldKeys.indexOf(el.dataset.fieldKey);
      // A field that is not part of the walkthrough at all (indexOf -> -1) stays
      // enabled, which is exactly right: the quick fields are always editable.
      el.disabled = i > stepIndex;
```

Make the same adjustment in the document branch: it iterates `stepFieldKeys`, so fields outside the walkthrough are never touched and keep the `contenteditable="true"` the server rendered. Add a comment above that loop:

```js
      // Only the walkthrough's own fields are locked or unlocked here. Anything
      // outside it keeps the editability the document was rendered with.
```

- [ ] **Step 4: Verify in a browser**

With the server running, open `generator.html?format_id=<id>` and run:

```js
const btns = [...document.querySelectorAll('[data-mode]')];
btns.find(b => b.dataset.mode === 'step').click();
const canvas = document.querySelector('#live-doc-wrap .lp-doc');
const slots = [...canvas.querySelectorAll('[data-field-key]')];
console.log('total', slots.length);
console.log('locked', slots.filter(el => !el.isContentEditable).length);
console.log('locked but unstyled (must be 0):',
  slots.filter(el => !el.isContentEditable && !el.classList.contains('step-locked')).length);
```

Expected: `locked but unstyled (must be 0): 0`. That is the bug gone: every read-only field now says so.

Then advance a step or two with *Submit & continue* and confirm by typing into an already-answered field that the text changes.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/generator.js
git commit -m "Keep answered fields editable and walk only the thinking-heavy ones in Guided"
```

---

### Task 8: The Building Proficiency checklist

**Files:**
- Modify: `frontend/generator.html` (checklist markup inside `#full-controls`)
- Modify: `frontend/js/generator.js` (render, remember, and send the selection)
- Modify: `frontend/css/style.css` (checklist styling)

**Interfaces:**
- Consumes: `heavyFieldKeys()` / `easyFieldKeys()` from Task 7, and `include_keys` from Task 4.
- Produces: `selectedGenerateKeys()` returning the keys to send, used by `baseGenerationPayload()`.

**Design note:** before writing the CSS, run the `impeccable:impeccable` skill on this panel. It is the one genuinely new piece of UI in this plan and it sits on the screen a teacher uses most.

- [ ] **Step 1: Add the markup**

In `frontend/generator.html`, inside `#full-controls`, above the `.generator-actions` div:

```html
                <div id="generate-scope" class="generate-scope" hidden>
                  <p class="generate-scope-auto" id="generate-scope-auto"></p>
                  <fieldset class="generate-scope-list">
                    <legend>Also write these for me?</legend>
                    <div id="generate-scope-options"></div>
                  </fieldset>
                </div>
```

- [ ] **Step 2: Render it, remember it, and send it**

In `frontend/js/generator.js`, add near the other element handles:

```js
const generateScope = document.getElementById("generate-scope");
const generateScopeAuto = document.getElementById("generate-scope-auto");
const generateScopeOptions = document.getElementById("generate-scope-options");
```

Add the rendering and persistence:

```js
// Which thinking-heavy fields the teacher wants written for them. Remembered per
// format, because a teacher who always writes their own Flow should only have to
// say so once. Ticked by default so a teacher who never opens this panel gets
// what they got before the panel existed.
const SCOPE_PREFIX = "alignedGenScope:v1:";

function scopeStorageKey() {
  return `${SCOPE_PREFIX}${fmt.id}`;
}

function readScopeChoice() {
  try {
    const raw = localStorage.getItem(scopeStorageKey());
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function writeScopeChoice(excluded) {
  try {
    localStorage.setItem(scopeStorageKey(), JSON.stringify(excluded));
  } catch (err) {
    /* private mode or quota: the choice just won't persist */
  }
}

function renderGenerateScope() {
  const heavy = heavyFieldKeys();
  const easy = easyFieldKeys();

  // Nothing to choose between: no heavy fields means the old all-or-nothing
  // behaviour, so the panel stays out of the way.
  if (!heavy.length) {
    generateScope.hidden = true;
    return;
  }

  generateScope.hidden = false;
  generateScopeAuto.textContent = easy.length
    ? `${easy.length} straightforward ${easy.length === 1 ? "field" : "fields"} will be filled in automatically.`
    : "";

  // Previously excluded keys stay excluded; anything new to this format starts
  // ticked.
  const excluded = new Set(readScopeChoice() || []);

  generateScopeOptions.innerHTML = heavy
    .map((key) => {
      const field = fieldByKey(key);
      return `
        <label class="generate-scope-option">
          <input type="checkbox" data-scope-key="${escapeHtml(key)}" ${excluded.has(key) ? "" : "checked"} />
          <span>${escapeHtml(field ? field.label : key)}</span>
        </label>`;
    })
    .join("");

  generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((box) => {
    box.addEventListener("change", () => {
      const next = [];
      generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((b) => {
        if (!b.checked) next.push(b.dataset.scopeKey);
      });
      writeScopeChoice(next);
    });
  });
}

// The keys to generate: every quick field, plus the heavy ones still ticked.
// The page sends the full list rather than letting the server add the easy
// fields, so "generate exactly what was asked for" is the only rule in play.
function selectedGenerateKeys() {
  const ticked = [];
  generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((box) => {
    if (box.checked) ticked.push(box.dataset.scopeKey);
  });
  return easyFieldKeys().concat(ticked);
}
```

Call `renderGenerateScope()` in `init()`, immediately after `stepFieldKeys` is assigned.

In `baseGenerationPayload()`, add the selection:

```js
    include_keys: selectedGenerateKeys(),
```

- [ ] **Step 3: Guard against an empty selection**

In the `generateFullBtn` click handler, after the existing `updateGate()` check, add:

```js
  if (!selectedGenerateKeys().length) {
    showError("Tick at least one field for me to write, or fill the plan in yourself.");
    return;
  }
```

- [ ] **Step 4: Add the CSS**

Run `impeccable:impeccable` on this panel first, then append its result. The baseline, to be refined by that pass:

```css
/* ---------------------------------------------------------------------------
   Building Proficiency: what to generate
   --------------------------------------------------------------------------- */

.generate-scope {
  padding: 14px 16px;
  margin-bottom: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.generate-scope-auto {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-body);
}

.generate-scope-list {
  padding: 0;
  margin: 0;
  border: none;
}

.generate-scope-list legend {
  padding: 0;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-heading);
}

#generate-scope-options {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 6px 14px;
}

.generate-scope-option {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--text-heading);
  cursor: pointer;
}

.generate-scope-option input {
  width: 15px;
  height: 15px;
  accent-color: var(--primary);
  margin: 0;
  flex: 0 0 auto;
}
```

- [ ] **Step 5: Verify in a browser**

With the server running, on the generator:

```js
console.log('panel visible:', !document.getElementById('generate-scope').hidden);
console.log('heavy options:', document.querySelectorAll('[data-scope-key]').length);
// Untick the first one and confirm it leaves the payload.
const first = document.querySelector('[data-scope-key]');
first.checked = false; first.dispatchEvent(new Event('change'));
console.log('excluded now stored:', localStorage.getItem('alignedGenScope:v1:' + fmt.id));
```

Expected: the panel is visible, the option count matches the format's heavy fields, and the unticked key appears in storage. Reload and confirm it is still unticked.

- [ ] **Step 6: Commit**

```bash
git add frontend/generator.html frontend/js/generator.js frontend/css/style.css
git commit -m "Let Building Proficiency choose which high-level fields to write"
```

---

### Task 9: Clear a field and ask again

**Files:**
- Modify: `frontend/js/doc-toolbar.js` (a Clear field button in the shared toolbar)
- Modify: `frontend/js/generator.js` (wire it, plus Guided's Clear & ask again)
- Modify: `frontend/generator.html` (the Guided button)
- Modify: `frontend/js/format-builder.js` (ignore the new button, it is generator-only)

**Interfaces:**
- Consumes: `activeFieldEl()` and `syncFieldFromEl()`, both already in `generator.js`.
- Produces: `clearField(el)` in `generator.js`, and a `[data-clear-field]` button in the shared toolbar markup.

- [ ] **Step 1: Add the toolbar button**

In `frontend/js/doc-toolbar.js`, inside `renderDocToolbar`, add to the group that holds `removeFormat` (the one ending with the clear-formatting button):

```html
      <button type="button" class="doc-tool-btn" data-clear-field="1" data-icon="eraser" title="Clear this field's content"></button>
```

Add the icon to `frontend/js/icons.js`, alongside the others added previously:

```js
  eraser: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 16 6-6 5 5-4 4H7z"/><path d="M11 10 16 5a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3l-5 5"/><path d="M4 21h16"/></svg>`,
```

This button is generator-only: the format builder edits a blank template where there is no field content to clear. In `frontend/js/format-builder.js`, hide it right after `paintDocToolbarIcons(docToolbar)`:

```js
  // Generator-only: this screen edits the blank template, which has no field
  // content to clear.
  const clearFieldBtn = docToolbar.querySelector("[data-clear-field]");
  if (clearFieldBtn) clearFieldBtn.remove();
```

- [ ] **Step 2: Add clearField and wire the toolbar button**

In `frontend/js/generator.js`, add:

```js
// Empties one field so the teacher can write their own answer or ask for a
// different suggestion. Clears the rich value as well as the plain text,
// otherwise the old styled HTML would come back on the next render.
function clearField(el) {
  const key = el.dataset.fieldKey;
  el.innerHTML = "";
  el.classList.remove("lp-filled", "field-needs-answer");
  fieldValues[key] = "";
  delete fieldRichValues[key];
  markDirty();
  if (mode === "step") renderStepFieldNav();
}
```

In `wireLiveDocToolbar()`, after the `data-cmd` wiring:

```js
  const clearFieldBtn = liveDocToolbar.querySelector("[data-clear-field]");
  if (clearFieldBtn) {
    clearFieldBtn.addEventListener("click", () => {
      const el = activeFieldEl();
      if (!el) {
        showToast("Click into the field you want to clear first.", true);
        return;
      }
      clearField(el);
      el.focus();
    });
  }
```

- [ ] **Step 3: Add Guided's Clear & ask again**

In `frontend/generator.html`, inside `#step-controls`'s `.generator-actions`, after the Submit button:

```html
                  <button type="button" id="step-clear-btn" class="btn btn-secondary">Clear &amp; ask again</button>
```

In `frontend/js/generator.js`:

```js
// The owl's suggestion for this field was wrong: wipe it and ask again, rather
// than making the teacher select the text and delete it by hand.
document.getElementById("step-clear-btn").addEventListener("click", () => {
  const key = stepFieldKeys[stepIndex];
  if (!key) return;

  const canvas = liveDocWrap.querySelector(".lp-doc");
  const el = canvas && canvas.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
  if (el) {
    clearField(el);
  } else {
    // Fallback field list: the control is an input/textarea, not a slot.
    const input = resultsEl.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
    if (input) {
      input.value = "";
      fieldValues[key] = "";
      delete fieldRichValues[key];
      markDirty();
    }
  }

  const field = fieldByKey(key);
  setOwlState("guide", `Cleared "${field ? field.label : key}". Ask me for a different suggestion, or write your own.`);

  // introduceFieldInChat() returns early when chat.fieldKey already matches, so
  // clearing chat.fieldKey is what makes it re-open the field instead of doing
  // nothing. Reusing it keeps one path for "the owl is now on this field".
  chat.fieldKey = null;
  introduceFieldInChat();
});
```

- [ ] **Step 4: Verify in a browser**

On the generator with some content in a field:

```js
const canvas = document.querySelector('#live-doc-wrap .lp-doc');
const slot = [...canvas.querySelectorAll('[data-field-key]')].find(el => el.textContent.trim());
console.log('before:', JSON.stringify(slot.textContent.slice(0, 30)));
slot.focus();
document.querySelector('[data-clear-field]').click();
console.log('after:', JSON.stringify(slot.textContent));
console.log('value cleared:', fieldValues[slot.dataset.fieldKey] === '');
```

Expected: `after: ""` and `value cleared: true`.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/doc-toolbar.js frontend/js/icons.js frontend/js/generator.js frontend/generator.html frontend/js/format-builder.js
git commit -m "Let a teacher clear a field and ask the owl again"
```

---

### Task 10: Separate progress per mode in the page

**Files:**
- Modify: `frontend/js/generator.js` (mode state, the switch handler, draft shape, save payload)

**Interfaces:**
- Consumes: `mode_values` from Task 5.
- Produces: `modeSlots` holding `{ full: {...}, step: {...} }`, `captureModeSlot()`, `loadModeSlot(name)`, and `inactiveModeSlot()` used by `planPayload()`.

- [ ] **Step 1: Add the slots and the swap**

In `frontend/js/generator.js`, add near the top with the other state:

```js
// One slot per mode. The two modes have different purposes, so work in one is
// not work in the other: Building Proficiency's draft and Guided's walkthrough
// are two drafts of the same plan. fieldValues/fieldRichValues always hold the
// ACTIVE mode; the other mode's copy waits here and in the plan's mode_values.
let modeSlots = {
  full: { fieldValues: {}, fieldRichValues: {} },
  step: { fieldValues: {}, fieldRichValues: {}, stepIndex: 0 },
};

// Writes whatever is on screen into the active mode's slot.
function captureModeSlot() {
  modeSlots[mode] = {
    fieldValues: JSON.parse(JSON.stringify(fieldValues || {})),
    fieldRichValues: JSON.parse(JSON.stringify(fieldRichValues || {})),
    stepIndex: mode === "step" ? stepIndex : undefined,
  };
}

// Loads a mode's slot into the live values and repaints the editor.
function loadModeSlot(name) {
  const slot = modeSlots[name] || {};
  fieldValues = JSON.parse(JSON.stringify(slot.fieldValues || {}));
  fieldRichValues = JSON.parse(JSON.stringify(slot.fieldRichValues || {}));
  if (name === "step" && typeof slot.stepIndex === "number") stepIndex = slot.stepIndex;

  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (canvas) {
    // Every slot is repainted, including the empty ones, so content from the
    // mode being left behind cannot linger on screen.
    canvas.querySelectorAll("[data-field-key]").forEach((el) => {
      const key = el.dataset.fieldKey;
      const rich = fieldRichValues[key];
      const value = fieldValues[key];
      const text = Array.isArray(value) ? value.join("\n") : (value || "");
      if (rich) {
        el.innerHTML = rich;
      } else {
        el.textContent = text;
      }
      el.classList.toggle("lp-filled", !!text.trim());
    });
  } else {
    renderResults();
  }
}

// The slot to persist alongside the active mode's values.
function inactiveModeSlot() {
  const other = mode === "full" ? "step" : "full";
  const slot = modeSlots[other] || {};
  return {
    field_values: slot.fieldValues || {},
    rich_field_values: slot.fieldRichValues || {},
    step_index: typeof slot.stepIndex === "number" ? slot.stepIndex : 0,
  };
}
```

- [ ] **Step 2: Swap on mode switch**

In the `modeSwitchBtns` click handler, the first lines are currently:

```js
    mode = btn.dataset.mode;
    saveDraft();
```

Replace with:

```js
    if (btn.dataset.mode === mode) return;   // already here, nothing to swap
    // Put the current mode's work away before picking up the other's.
    captureModeSlot();
    mode = btn.dataset.mode;
    loadModeSlot(mode);
    saveDraft();
```

- [ ] **Step 3: Persist both slots**

In `planPayload()`, add:

```js
    mode_values: inactiveModeSlot(),
```

Immediately before `planPayload()` returns, the active slot must be current, so make `planPayload()` start with:

```js
  captureModeSlot();
```

In `saveDraft()`'s stored object, add `modeSlots` alongside `fieldValues`:

```js
        modeSlots,
```

and in `restoreDraft()`, after `fieldRichValues = draft.fieldRichValues || {};`:

```js
    // Both modes' work comes back, not just the one that happened to be active.
    if (draft.modeSlots) modeSlots = draft.modeSlots;
```

In `applyOpenedPlan(plan)`, after `fieldRichValues = plan.rich_field_values || {};`:

```js
    // The active mode's values are in field_values; the other mode's ride in
    // mode_values. An older plan has none, which leaves that slot empty.
    const other = (plan.generation_mode === "step" ? "full" : "step");
    const stored = plan.mode_values || {};
    modeSlots[other] = {
      fieldValues: stored.field_values || {},
      fieldRichValues: stored.rich_field_values || {},
      stepIndex: stored.step_index || 0,
    };
    if (plan.generation_mode) mode = plan.generation_mode;
```

- [ ] **Step 4: Verify in a browser**

On the generator:

```js
// Type into a field in Building Proficiency, switch to Guided, confirm the
// field is empty there, switch back, confirm it returned.
const canvas = document.querySelector('#live-doc-wrap .lp-doc');
const slot = canvas.querySelector('[data-field-key]');
const key = slot.dataset.fieldKey;
slot.textContent = 'BP only text';
slot.dispatchEvent(new Event('input', { bubbles: true }));

const btns = [...document.querySelectorAll('[data-mode]')];
btns.find(b => b.dataset.mode === 'step').click();
const inGuided = canvas.querySelector(`[data-field-key="${key}"]`).textContent;
btns.find(b => b.dataset.mode === 'full').click();
const backInBP = canvas.querySelector(`[data-field-key="${key}"]`).textContent;

console.log('in Guided (should be empty):', JSON.stringify(inGuided));
console.log('back in BP (should be the text):', JSON.stringify(backInBP));
```

Expected: empty in Guided, `"BP only text"` back in Building Proficiency.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/generator.js
git commit -m "Keep Building Proficiency and Guided progress apart in the page"
```

---

### Task 11: The role override UI in the format builder

**Files:**
- Modify: `frontend/format-builder.html` (role select in the field-row template; roles panel for document formats)
- Modify: `frontend/js/format-builder.js` (collect the manual role; render and save the document-format panel)
- Modify: `frontend/js/api.js` (`setFieldRoles`)

**Interfaces:**
- Consumes: `PATCH /api/formats/<id>/field-roles` from Task 3, and `"role"` on each field from Task 2.
- Produces: `Api.setFieldRoles(formatId, roles)`.

- [ ] **Step 1: Add the API method**

In `frontend/js/api.js`, next to the other format methods:

```js
  // roles: { field_key: "heavy" | "easy" | null }. null hands the decision back
  // to the server's keyword matching.
  setFieldRoles: (formatId, roles) =>
    apiFetch(`/api/formats/${formatId}/field-roles`, {
      method: "PATCH",
      body: JSON.stringify({ roles }),
    }),
```

- [ ] **Step 2: Add the role select to the manual field rows**

In `frontend/format-builder.html`, inside `#field-row-template`, after the field-type block:

```html
      <div class="field">
        <label>Which mode writes this</label>
        <select class="field-role">
          <option value="">Decide automatically</option>
          <option value="heavy">Guided walks me through it</option>
          <option value="easy">Filled in automatically</option>
        </select>
      </div>
```

In `frontend/js/format-builder.js`, in `collectManualFields()`, add to the pushed object:

```js
      role: row.querySelector(".field-role").value || null,
```

`enterEditMode(fmt)` in `frontend/js/format-builder.js` is what loads an existing format; it reaches `addFieldRow(field)` for each field. In whichever function populates a row's inputs (it sets `.field-label`, `.field-type` and `.field-required`), add the select alongside them:

```js
    // The stored override, not the resolved role: "decide automatically" has to
    // stay distinguishable from an explicit choice that happens to agree.
    row.querySelector(".field-role").value = field.role_override || "";
```

This needs the raw override, so add it to `FormatField.to_dict()` in `backend/models/format.py` next to the resolved role:

```python
            # The raw override, for the format builder's own select. The page
            # needs to tell "decide automatically" apart from an explicit choice
            # that happens to match what the keywords would have picked.
            "role_override": self.role,
```

- [ ] **Step 3: Add the roles panel for document-based formats**

Document-based formats send no `fields` payload at all, so they need their own control. In `frontend/format-builder.html`, inside `#doc-field-editor` after the stage:

```html
          <section id="field-roles-panel" class="field-roles-panel" hidden>
            <h3 class="field-roles-title">Which mode writes each field</h3>
            <p class="text-sm mt-0">
              Guided walks you through the fields that need real thinking. The rest are filled in
              automatically when you generate a plan. Adjust any field whose wording we read wrongly.
            </p>
            <div id="field-roles-list"></div>
            <div class="flex gap-8 mt-16" style="align-items:center;">
              <span class="text-sm" id="field-roles-status"></span>
              <button type="button" id="field-roles-save-btn" class="btn btn-secondary btn-sm" disabled>
                Save field roles
              </button>
            </div>
          </section>
```

In `frontend/js/format-builder.js`:

```js
const fieldRolesPanel = document.getElementById("field-roles-panel");
const fieldRolesList = document.getElementById("field-roles-list");
const fieldRolesStatus = document.getElementById("field-roles-status");
const fieldRolesSaveBtn = document.getElementById("field-roles-save-btn");

// Pending overrides, keyed by field_key: only what the teacher actually changed
// is sent, so an untouched field keeps whatever it has.
let pendingRoles = {};

function renderFieldRoles(fields) {
  if (!fields || !fields.length) {
    fieldRolesPanel.hidden = true;
    return;
  }
  pendingRoles = {};
  fieldRolesPanel.hidden = false;
  fieldRolesSaveBtn.disabled = true;
  fieldRolesStatus.textContent = "";

  fieldRolesList.innerHTML = fields
    .map(
      (f) => `
      <label class="field-role-row">
        <span class="field-role-label">${escapeHtml(f.label)}</span>
        <select class="field-role-select" data-field-key="${escapeHtml(f.field_key)}">
          <option value=""${f.role_override ? "" : " selected"}>Decide automatically (${escapeHtml(f.role)})</option>
          <option value="heavy"${f.role_override === "heavy" ? " selected" : ""}>Guided walks me through it</option>
          <option value="easy"${f.role_override === "easy" ? " selected" : ""}>Filled in automatically</option>
        </select>
      </label>`
    )
    .join("");

  fieldRolesList.querySelectorAll(".field-role-select").forEach((sel) => {
    sel.addEventListener("change", () => {
      pendingRoles[sel.dataset.fieldKey] = sel.value || null;
      fieldRolesSaveBtn.disabled = false;
      const count = Object.keys(pendingRoles).length;
      fieldRolesStatus.textContent = `${count} unsaved ${count === 1 ? "change" : "changes"}`;
    });
  });
}

fieldRolesSaveBtn.addEventListener("click", async () => {
  if (!editingFormatId || !Object.keys(pendingRoles).length) return;
  setButtonLoading(fieldRolesSaveBtn, true, "Saving");
  try {
    const data = await Api.setFieldRoles(editingFormatId, pendingRoles);
    showToast("Field roles saved.");
    renderFieldRoles(data.fields);
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(fieldRolesSaveBtn, false);
  }
});
```

Call it from `enterEditMode(fmt)` in `frontend/js/format-builder.js`, inside the `if (fmt.has_source_file)` branch (the one that hides `manualFieldEditor` and shows `docFieldEditor`), right after the `renderDocCanvas` try/catch:

```js
    // Only for a format that already exists: roles are saved against a format id,
    // so a brand-new format gets this panel after its first save.
    renderFieldRoles(fmt.fields || []);
```

`enterEditMode` receives the format from `Api.getFormat(formatId)`, which returns fields with both `role` and `role_override`, so no extra request is needed.

- [ ] **Step 4: Add the CSS**

Append to `frontend/css/style.css`:

```css
/* ---------------------------------------------------------------------------
   Format builder: which mode writes each field
   --------------------------------------------------------------------------- */

.field-roles-panel {
  padding: 16px;
  margin-top: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.field-roles-title {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  color: var(--text-heading);
}

.field-role-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}

.field-role-row:last-child {
  border-bottom: none;
}

.field-role-label {
  flex: 1;
  font-size: 13px;
  color: var(--text-heading);
  overflow-wrap: anywhere;
}

.field-role-select {
  flex: 0 0 auto;
  max-width: 240px;
}

@media (max-width: 560px) {
  .field-role-row {
    flex-direction: column;
    align-items: stretch;
    gap: 5px;
  }

  .field-role-select {
    max-width: none;
  }
}
```

- [ ] **Step 5: Verify in a browser**

Open `format-builder.html?format_id=<id>` for a document-based format:

```js
console.log('panel visible:', !document.getElementById('field-roles-panel').hidden);
const sel = document.querySelector('.field-role-select');
sel.value = 'easy'; sel.dispatchEvent(new Event('change'));
console.log('save enabled:', !document.getElementById('field-roles-save-btn').disabled);
```

Click **Save field roles**, then reload and confirm the select still reads "Filled in automatically". Then open the generator for that format and confirm the field moved out of Guided's walkthrough.

- [ ] **Step 6: Commit**

```bash
git add frontend/format-builder.html frontend/js/format-builder.js frontend/js/api.js         backend/models/format.py frontend/css/style.css
git commit -m "Let a teacher correct which mode writes each field"
```

---

### Task 12: Full verification and deploy

**Files:** none changed unless a check fails.

- [ ] **Step 1: Run every backend self-check**

```bash
cd backend
for t in test_archive_filter.py test_bulk_archive.py test_lesson_plan_drafts.py \
         test_ai_limits.py test_rich_export.py test_migration_race.py \
         test_field_roles.py test_generate_selection.py; do
  printf "%-34s " "$t"
  venv/Scripts/python $t 2>&1 | grep -E " OK$" | tail -1 || echo FAILED
done
```

Expected: eight `... OK` lines, no `FAILED`.

- [ ] **Step 2: Check every JS file parses**

```bash
cd frontend && for f in js/*.js; do node --check "$f" || echo "SYNTAX FAIL: $f"; done && echo "all JS parsed"
```

- [ ] **Step 3: Browser pass against the real format**

With the server running, confirm each of these by hand, in one session:

1. Building Proficiency: click into any field and type. The text appears.
2. The checklist lists the format's thinking-heavy fields. Untick one, generate, and confirm that field is left alone and is *not* reported as missing.
3. Guided: the walkthrough covers only the heavy fields. Advance a step, then edit an already-answered field. The edit sticks.
4. No field is read-only without the hatched lock styling.
5. **Clear & ask again** empties the current field and the owl responds.
6. Fullscreen: the toolbar is visible and its buttons work. Escape exits.
7. Type in Building Proficiency, switch to Guided, switch back. The text returned.
8. Format builder: change a field's role, save, reload, and confirm it held.

- [ ] **Step 4: Delete the disposable test account**

A test teacher was created in the local database while reproducing the original bug. Remove it:

```bash
cd backend && venv/Scripts/python -c "
from app import create_app
from extensions import db
from models.user import User
app = create_app()
with app.app_context():
    u = User.query.filter_by(email='claude.repro.test@example.test').first()
    if u:
        db.session.delete(u); db.session.commit(); print('test account deleted')
    else:
        print('already gone')
"
```

- [ ] **Step 5: Deploy**

Follow the established route for this app: `pscp` the changed files to `/var/www/aligned/<same path>`, never touching `backend/.env`, then restart and check. `<password>` below is the live root password: ask the user for it rather than committing it anywhere, and take a backup of `/var/www/aligned` plus a `mysqldump` before the first upload.

```bash
# from the repo root, for each changed file:
pscp -batch -pw "<password>" <file> root@38.60.245.60:/var/www/aligned/<file>

# then
plink -batch -pw "<password>" root@38.60.245.60 \
  'systemctl restart aligned.service; sleep 7; systemctl is-active aligned.service; \
   journalctl -u aligned.service --since "40 seconds ago" --no-pager | grep -iE "error|traceback" | head -5'
```

Expected: `active`, and no error lines. The new `format_fields.role` and `lesson_plans.mode_values` columns are added by the migration on restart; confirm with:

```bash
plink -batch -pw "<password>" root@38.60.245.60 'cd /var/www/aligned/backend && venv/bin/python -c "
from app import create_app
from extensions import db
from sqlalchemy import inspect
app = create_app()
with app.app_context():
    insp = inspect(db.engine)
    print(\"format_fields.role:\", \"role\" in {c[\"name\"] for c in insp.get_columns(\"format_fields\")})
    print(\"lesson_plans.mode_values:\", \"mode_values\" in {c[\"name\"] for c in insp.get_columns(\"lesson_plans\")})
"'
```

Then run the self-checks on the server too, and confirm `https://aligned.ddns.net/api/health` returns 200.

- [ ] **Step 6: Commit any fixes the verification turned up**

```bash
git add -A
git commit -m "Fix issues found in end-to-end verification"
```
