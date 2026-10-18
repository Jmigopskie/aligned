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
    answers = {k: f"content for {k}" for k in ["teacher", "sessions", "flow", "assessment"]}
    # An objectives field is only complete with at least three objectives.
    answers["objectives"] = "Identify the parts\nExplain their use\nValue careful work"
    stub_answers(answers, seen)
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
