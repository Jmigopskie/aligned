"""Self-check for grounding the recap, assignment and timing in what Alan
asked during setup: the previous topic, the next topic and the duration.

Without these the recap ("Review of the Previous Lesson", ILAW's "Pre-Lesson")
and the assignment were written blind. The instructions are appended to each
matching field in the prompt, so this checks the exact wording per field.

Run it directly: `python test_topic_grounding.py`.
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
    # One part of the procedure (4A's "Activity") must not be told it is the
    # whole discussion, or it may take all the minutes.
    assert _grounding_directive(Field("activity", "Activity"), {"duration_minutes": 45}) == ""
    assert _grounding_directive(Field("motivational_activity", "Motivational Activity"), {"duration_minutes": 45}) == ""
    print("  timing OK")

    assert _grounding_directive(Field("materials", "Materials"), ctx) == ""
    block = _schema_block([review], {"previous_topic": "X", "topic": "Y"})
    assert "previous lesson was: X" in block, block
    assert "previous lesson was" not in _schema_block([review]), "no context, no recap line"
    print("  schema block OK")

    # The session cap follows the discussion length Alan asked for (45 by default).
    from services.ai_service import _session_minutes, _timing_problems
    assert _session_minutes({"duration_minutes": 60}) == 60
    assert _session_minutes({}) == 45
    assert _session_minutes({"duration_minutes": "abc"}) == 45
    assert _session_minutes({"duration_minutes": 999}) == 45
    pre = Field("pre_lesson", "Pre-Lesson")
    flow = Field("flow", "Flow")
    day = {"pre_lesson": "Routine and review (5 minutes)", "flow": "Discussion (30 minutes)\nPractice (20 minutes)"}
    assert _timing_problems(day, [pre, flow], 60) == [], "55 minutes fits a 60-minute discussion"
    assert _timing_problems(day, [pre, flow], 45) == [(0, 55, True)], "55 minutes breaks a 45-minute one"
    print("  session cap OK")

    # Step 6's term and week point Alan at that row of the Budget of Work.
    from services.ai_service import _lesson_block
    block = _lesson_block({"topic": "Cell formulas", "term": "2nd Term", "week": "3"}, "Week 3 ... competency")
    assert "2nd Term, Week 3" in block and "that term and week" in block, block[:300]
    assert "that term and week" not in _lesson_block({"topic": "Cell formulas"}, "guide text")
    typed = _lesson_block({"topic": "Cell formulas", "term": "2nd Term", "week": "Week 4"}, "guide")
    assert "2nd Term, Week 4." in typed and "Week Week" not in typed, typed[:300]
    print("  term and week OK")

    print("grounding OK")


if __name__ == "__main__":
    main()
