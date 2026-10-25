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


def check_standards_only_from_a_guide():
    """Standards and competencies are copied from a Budget of Work or
    Curriculum Guide or left blank: with no guide they are never asked of the
    model, and the page is told why they are blank. With one, they are the
    guide's own words."""
    fields = FIELDS + [Field("cs", "Content Standard"), Field("lc", "Learning Competency")]
    guide = ("Content Standard The learners demonstrate an understanding of basic spreadsheet "
             "formulas and functions. Learning Competency 1. create simple formulas to compute totals and averages.")
    seen = []

    def fake_call(system_instruction, parts, label):
        asked = [f.field_key for f in fields if f.field_key in " ".join(parts)]
        seen.extend(asked)
        made = {"cs": "demonstrate understanding of spreadsheet formulas and functions",
                "lc": "create simple formulas to compute totals and averages",
                "objectives": "Identify the parts\nExplain their use\nValue careful work"}
        return {k: made.get(k, f"content for {k}") for k in asked}

    ai_service._call = fake_call
    final = [e for e in ai_service.generate_full_streaming({"topic": "Spreadsheets"}, fields, course_guide_text="")
             if e["type"] == "complete"][-1]
    assert "cs" not in seen and "lc" not in seen, seen
    assert not final["values"].get("cs") and not final["values"].get("lc"), final["values"]
    assert final["needs_guide"] == ["cs", "lc"] and "cs" not in final["missing"], final
    assert final["values"].get("objectives"), final["values"]  # objectives are still written
    assert "cs" not in ai_service.generate_full({"topic": "Spreadsheets"}, fields, course_guide_text="")

    final = [e for e in ai_service.generate_full_streaming({"topic": "Spreadsheets"}, fields,
                                                           course_guide_text=[("BoW", guide)])
             if e["type"] == "complete"][-1]
    assert final["needs_guide"] == [], final
    assert final["values"]["cs"] == "The learners demonstrate an understanding of basic spreadsheet formulas and functions.", final["values"]
    assert final["values"]["lc"] == "create simple formulas to compute totals and averages.", final["values"]
    print("  standards only from a guide OK")


def check_owl_options_explained():
    """Alan's options carry a line on why they fit; follow-up questions don't."""
    out = ai_service._clean_owl_reply({"reply": "Two ways in.", "choices": [
        {"type": "use", "label": "A video hook", "text": "Show a 1-minute clip.", "why": "It gets attention fast."},
        {"type": "ask", "label": "Any shorter?", "text": "Any shorter?", "why": "ignored"},
        {"type": "use", "label": "A question", "text": "Ask what they know."},
    ]})
    use, ask, bare = out["choices"]
    assert use["why"] == "It gets attention fast." and "why" not in ask and "why" not in bare, out
    print("  owl options explained OK")


check_owl_options_explained()
check_standards_only_from_a_guide()
check_subset_only()
check_missing_counts_requested_only()
check_absent_means_everything()
check_unknown_keys_ignored()
check_empty_selection()
check_select_fields_helper()
print("generate selection OK")
