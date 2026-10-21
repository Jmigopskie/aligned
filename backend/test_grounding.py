"""Self-check for grounding the recap, assignment and timing in what Alan
asked during setup: the previous topic, the next topic and the duration.

Without these the recap ("Review of the Previous Lesson", ILAW's "Pre-Lesson")
and the assignment were written blind. The instructions are appended to each
matching field in the prompt, so this checks the exact wording per field.

Run it directly: `python test_grounding.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.ai_service import _grounding_directive, _schema_block


class Field:
    """Stands in for a FormatField row: only these attributes are read."""

    def __init__(self, field_key, label, field_type="text"):
        self.field_key = field_key
        self.label = label
        self.field_type = field_type
        self.ai_hint = None
        self.parts_list = ["Day 1", "Day 2"] if field_type == "weekly" else []


def main():
    review = Field("review_of_the_previous_lesson", "Review of the Previous Lesson")
    ctx = {"topic": "Cell formulas", "previous_topic": "Basic formatting"}
    got = _grounding_directive(review, ctx)
    assert "previous lesson was: Basic formatting" in got, got
    assert "today's topic, Cell formulas" in got, got

    got = _grounding_directive(review, {"topic": "Cell formulas", "previous_topic": ""})
    assert "This is the first lesson on this topic" in got, got
    assert "previous lesson was" not in got, got
    # A request that never asked (older drafts) gets no recap line at all.
    assert _grounding_directive(review, {"topic": "Cell formulas"}) == ""
    assert _grounding_directive(Field("assignment", "Assignment"), {"topic": "Cell formulas"}) == ""
    print("  recap OK")

    pre = Field("pre_lesson", "Pre-Lesson", "weekly")
    got = _grounding_directive(pre, ctx)
    assert "previous lesson was: Basic formatting" in got and "Only day 1 recaps" in got, got
    print("  weekly recap OK")

    assignment = Field("assignment", "Assignment")
    got = _grounding_directive(assignment, {"topic": "Cell formulas", "next_topic": "Charts"})
    assert "The next lesson is: Charts" in got, got
    got = _grounding_directive(assignment, {"topic": "Cell formulas", "next_topic": ""})
    assert got == " Base the assignment on today's topic.", repr(got)
    extended = Field("extended_learning_opportunities", "Extended Learning Opportunities", "weekly")
    got = _grounding_directive(extended, {"topic": "Cell formulas", "next_topic": "Charts"})
    assert "The next lesson is: Charts" in got and "Only the last day's assignment" in got, got
    print("  assignment OK")

    proper = Field("lesson_proper", "Lesson Proper")
    got = _grounding_directive(proper, {"duration_minutes": 45})
    assert "lasts 45 minutes" in got, got
    assert _grounding_directive(proper, {}) == "", "no duration, no timing line"
    print("  timing OK")

    assert _grounding_directive(Field("materials", "Materials"), ctx) == ""
    block = _schema_block([review], {"previous_topic": "X", "topic": "Y"})
    assert "previous lesson was: X" in block, block
    assert "previous lesson was" not in _schema_block([review]), "no context, no recap line"
    print("  schema block OK")

    print("grounding OK")


if __name__ == "__main__":
    main()
