"""Self-check for the layout of written parts (user report 2026-11-23: "fix the
numberings, bullets, and spacing"), from two live plans:
- a quiz in a part that isn't the evaluation was renumbered line by line
  ("3. a. Binary b. Decimal ...") with its options run together;
- numbered steps written in one sentence ("Direction: 1. Divide ... 2. Give
  ... 3.") were cut off mid-list.

Run it directly: `python test_layout_cleanup.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import ai_limits  # noqa: E402

LIMITS = dict(max_items=8, max_item_words=40, max_sentences=3, max_prose_words=70)


def main():
    quiz = ("Directions: Identify the number system described.\n"
            "Which system uses digits 0-9 and A-F? a. Binary b. Decimal c. Octal d. Hexadecimal\n"
            "What is the base of the binary number system?\na. 2\nb. 8\nc. 10\nd. 16\n"
            "Answer key: 1. d 2. a")
    out = ai_limits.clean_value(quiz, "textarea", **LIMITS).split("\n")
    assert out[0] == "Directions: Identify the number system described.", out
    assert out[1] == "1. Which system uses digits 0-9 and A-F?", out
    assert out[2:6] == ["a. Binary", "b. Decimal", "c. Octal", "d. Hexadecimal"], out
    assert out[6] == "2. What is the base of the binary number system?" and out[7] == "a. 2", out
    assert "Answer key:" in out[-3] and out[-2:] == ["1. d", "2. a"], out
    print("  a quiz keeps its items, options and key apart OK")

    steps = ("Energizer: Light Switch Binary Relay. Direction: 1. Divide the class into two groups. "
             "2. Give each group a set of flashcards with a '0' on one side and a '1' on the other. "
             "3. Call out a number and let each group show it in binary. 4. The first correct group earns a point.")
    out = ai_limits.clean_value(steps, "textarea", **LIMITS).split("\n")
    assert out[0] == "Energizer: Light Switch Binary Relay. Direction:", out
    assert [l[:3] for l in out[1:]] == ["1. ", "2. ", "3. ", "4. "], out
    assert out[-1].endswith("earns a point."), "no step cut off"
    print("  steps in one sentence become a numbered list, none cut OK")

    # Bullets and spacing: one marker per line, no blank lines, no doubled markers.
    messy = "• - Prayer (1 min)\n\n\n•  Greetings (1 min)\n* Attendance (1 min)"
    assert ai_limits.clean_value(messy, "list", **LIMITS) == "Prayer (1 min)\nGreetings (1 min)\nAttendance (1 min)"
    assert ai_limits.clean_value("1. 1. Recall the tools\n2. 2) Measure", "list", **LIMITS) == \
        "1. Recall the tools\n2. Measure"
    # Plain prose is untouched by the splitting.
    prose = "Number systems represent quantities. The base sets the digits (Darslab, n.d.)."
    assert ai_limits.clean_value(prose, "textarea", **LIMITS) == prose
    print("  bullets and spacing tidy OK")
    print("layout cleanup OK")


if __name__ == "__main__":
    main()
