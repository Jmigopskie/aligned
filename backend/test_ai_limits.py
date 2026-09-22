"""Self-check for services/ai_limits: the trimming and completeness rules
applied to whatever the model returns.

This is the half of the "AI says it's done over blank fields" fix that can be
checked without a provider key. What matters is that a placeholder answer counts
as unanswered (so the retry fires and the page doesn't celebrate), that the
length ceilings actually cut, and that markdown and stray bullet markers are
stripped rather than shown literally to a teacher.

Run it directly: `venv/Scripts/python test_ai_limits.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import ai_limits

CAPS = dict(max_items=5, max_item_words=15, max_sentences=3, max_prose_words=60)


class Field:
    """Stands in for a format's FormatField row: ai_limits only reads these
    three attributes, so there's no need for a database here."""

    def __init__(self, key, field_type="text", label=None):
        self.field_key = key
        self.field_type = field_type
        self.label = label or key.replace("_", " ").title()


def check_is_answered():
    assert ai_limits.is_answered("Photosynthesis converts light to sugar.")
    assert ai_limits.is_answered(["One", "Two"])
    assert ai_limits.is_answered("0"), "a literal zero is real content"

    # Nothing at all.
    for empty in [None, "", "   ", "\n\n", [], ["", "  "]]:
        assert not ai_limits.is_answered(empty), repr(empty)

    # Non-empty but says nothing. These are the ones that used to sail through
    # as answers and let the plan be reported complete.
    for placeholder in ["N/A", "n/a", "NA", "None", "-", "--", "TBD", "tba",
                        "To be determined", "Not applicable", "placeholder",
                        "Lorem ipsum", "TODO", "pending"]:
        assert not ai_limits.is_answered(placeholder), placeholder

    # Still caught with a bullet or numbering in front, or trailing punctuation.
    for decorated in ["- N/A", "1. TBD", "• To be determined", "N/A.", "  * none  "]:
        assert not ai_limits.is_answered(decorated), decorated

    # A placeholder word inside real content is not a placeholder answer.
    assert ai_limits.is_answered("Pending tasks are reviewed at the start of class.")
    print("  is_answered OK")


def check_list_trimming():
    # Too many items: cut to the cap, in order.
    many = "\n".join(f"Item {i}" for i in range(1, 10))
    out = ai_limits.clean_value(many, "list", **CAPS)
    lines = out.split("\n")
    assert len(lines) == 5, lines
    assert lines[0] == "Item 1" and lines[-1] == "Item 5", lines

    # Over-long items are clipped to the word cap.
    wordy = "word " * 40
    out = ai_limits.clean_value([wordy, "Short one"], "list", **CAPS)
    first = out.split("\n")[0]
    assert len(first.split()) <= 16, first  # 15 words, a trailing period may join the last

    # Bullet and number markers the model added are stripped, not shown.
    messy = "- Laptop\n* Whiteboard\n1. Printed handouts\n• Projector"
    out = ai_limits.clean_value(messy, "list", **CAPS)
    assert out.split("\n") == ["Laptop", "Whiteboard", "Printed handouts", "Projector"], out

    # A real list arriving as a Python list works the same way.
    assert ai_limits.clean_value(["A", "B"], "list", **CAPS) == "A\nB"

    # Blank lines between items don't become empty bullets.
    assert ai_limits.clean_value("A\n\n\nB", "list", **CAPS) == "A\nB"

    # A multi-line answer in a field the format calls "text" is still treated
    # as a list, because that is plainly what the model returned.
    assert ai_limits.clean_value("One\nTwo\nThree", "text", **CAPS) == "One\nTwo\nThree"
    # A numbered procedure keeps its numbering, re-numbered cleanly, because the
    # order is the point: step 3 is "third", not just "the line after step 2".
    steps = "1. Open the app\n2. Create a sheet\n3. Enter the data"
    assert ai_limits.clean_value(steps, "list", **CAPS) == steps, ai_limits.clean_value(steps, "list", **CAPS)

    # Sloppy or out-of-order numbering is normalised rather than passed through.
    messy_numbers = "1) First thing\n3) Second thing\n7) Third thing"
    assert ai_limits.clean_value(messy_numbers, "list", **CAPS) == (
        "1. First thing\n2. Second thing\n3. Third thing"
    ), ai_limits.clean_value(messy_numbers, "list", **CAPS)

    # Numbering past the item cap is renumbered within what survives, so the
    # list never starts at 1 and then skips.
    long_steps = "\n".join(f"{i}. Step {i}" for i in range(1, 9))
    out = ai_limits.clean_value(long_steps, "list", **CAPS)
    assert out.split("\n")[-1].startswith("5. "), out

    # One stray number in front of a single line is not a procedure.
    assert ai_limits.clean_value("1. Only one line", "list", **CAPS) == "Only one line"

    print("  list trimming OK")


def check_prose_trimming():
    # More sentences than allowed: keep the first three.
    five = "One here. Two here. Three here. Four here. Five here."
    out = ai_limits.clean_value(five, "textarea", **CAPS)
    assert out == "One here. Two here. Three here.", out

    # One long rambling sentence is cut by word count, not left alone just
    # because it is a single sentence.
    rambling = "The teacher " + ("explains carefully " * 40)
    out = ai_limits.clean_value(rambling, "textarea", **CAPS)
    assert len(out.split()) <= 61, len(out.split())

    # Short prose is returned untouched.
    fine = "Students identify the parts of a spreadsheet."
    assert ai_limits.clean_value(fine, "textarea", **CAPS) == fine

    # Markdown the model added despite being told not to is stripped.
    assert ai_limits.clean_value("**Bold** and *italic* text.", "textarea", **CAPS) == "Bold and italic text."
    assert ai_limits.clean_value("## Objectives", "textarea", **CAPS) == "Objectives"
    print("  prose trimming OK")


def check_enforce_limits():
    fields = [Field("objectives", "list"), Field("content", "textarea"), Field("materials", "list")]

    values = {
        "objectives": ["- Identify parts", "- Explain uses", "- Apply formulas"],
        "content": "Spreadsheets. Formulas. Charts. Pivot tables. Macros.",
        "materials": "Laptop\nProjector",
        # Not part of this format: the model invented it, and it has nowhere to
        # show, so it must be dropped rather than carried along.
        "invented_field": "Should be dropped",
    }
    out = ai_limits.enforce_limits(values, fields, **CAPS)

    assert set(out) == {"objectives", "content", "materials"}, set(out)
    assert out["objectives"] == "Identify parts\nExplain uses\nApply formulas"
    assert out["content"] == "Spreadsheets. Formulas. Charts."
    assert out["materials"] == "Laptop\nProjector"

    # An empty input map yields an empty result rather than raising.
    assert ai_limits.enforce_limits({}, fields, **CAPS) == {}
    assert ai_limits.enforce_limits(None, fields, **CAPS) == {}
    print("  enforce_limits OK")


def check_missing_keys():
    fields = [Field("a"), Field("b"), Field("c"), Field("d")]

    # b is absent, c is a placeholder, d is whitespace: all three count as
    # unanswered, which is what triggers the retry and the honest report.
    values = {"a": "Real content here.", "c": "N/A", "d": "   "}
    assert ai_limits.missing_keys(values, fields) == ["b", "c", "d"], ai_limits.missing_keys(values, fields)

    # Fully answered: nothing missing, so the page may report it complete.
    full = {"a": "One.", "b": "Two.", "c": "Three.", "d": "Four."}
    assert ai_limits.missing_keys(full, fields) == []

    # Nothing generated at all: every field is missing, in field order.
    assert ai_limits.missing_keys({}, fields) == ["a", "b", "c", "d"]
    print("  missing_keys OK")


check_is_answered()
check_list_trimming()
check_prose_trimming()
check_enforce_limits()
check_missing_keys()
print("ai limits OK")
