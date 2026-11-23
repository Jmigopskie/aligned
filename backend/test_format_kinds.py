"""Self-check for reading every school's format (user, 2026-11-24): the part
that teaches the topic and the references part are found whatever the
format calls them; Guided builds on the parts already written; a Guided
plan is laid out like Alan's without changing a word.

Labels are the live formats' own (2026-11-24). No provider or network.
Run it directly: `python test_format_kinds.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_limits, ai_service, grounding  # noqa: E402


class Field:
    def __init__(self, label, i=0, field_type="textarea"):
        self.label, self.field_type, self.sort_order = label, field_type, i
        self.field_key = label.lower().replace(" ", "_").replace("'", "")
        self.ai_hint, self.locked, self.parts_list, self.role = None, False, [], None


def fmt(*labels):
    return [Field(label, i) for i, label in enumerate(labels)]


FORMATS = {
    "TUP": (fmt("Lesson Objectives", "References", "Motivation", "Introduction", "Lesson Proper", "Application",
                "Generalization", "Evaluation"), "Lesson Proper", "References"),
    "4A's": (fmt("Learning Competencies and Objectives", "REFERENCES", "Review", "Activity", "Analysis",
                 "Abstraction", "Application", "Assessment", "Assignment"), "Abstraction", "REFERENCES"),
    "SNHS DLP": (fmt("Specific Learning Objectives", "Textbook pages", "Other Learning Resources", "Discussion",
                     "Developing mastery (leads to Formative Assessment 3)",
                     "Making generalizations and abstractions about the lesson", "Evaluating learning", "Remarks"),
                 "Discussion", "Other Learning Resources"),
    "ILAW": (fmt("References", "Learning Objectives", "Learning Experience", "Pre-Lesson", "Flow",
                 "Learning Resources", "Formative Assessment", "Reflections"), "Flow", "References"),
    "PAL3": (fmt("Learning Objectives", "Learning Resources", "Pre-Lesson", "Learning Experience",
                 "Formative Assessment"), "Learning Experience", "Learning Resources"),
    "Old TUP": (fmt("Objectives", "References", "Procedure", "Mechanics", "Evaluation"), "Procedure", "References"),
}


def main():
    for name, (fields, lesson, refs) in FORMATS.items():
        view = grounding.competency_view(fields)
        teach = [f.label for f in view if grounding.is_lesson_proper_field(f)]
        listed = [f.label for f in view if grounding.is_reference_field(f)]
        assert teach == [lesson], (name, teach)
        assert listed == [refs], (name, listed)
        kinds = grounding.field_kinds(fields)
        assert kinds[next(f.field_key for f in fields if f.label == lesson)] == "lesson_proper", (name, kinds)
    # The shipped 4A's has no references part; its materials list is not one.
    shipped = fmt("Learning Competencies and Objectives",
                  "List of Learning Resources for Development and Engagement Activities", "Abstraction")
    assert grounding.field_kinds(shipped) == {"abstraction": "lesson_proper"}, grounding.field_kinds(shipped)
    # A 4A's Abstraction is the lesson; next to a lesson proper it only sums it up.
    four_a = grounding.competency_view(FORMATS["4A's"][0])
    abstraction = next(f for f in four_a if f.label == "Abstraction")
    assert "the lesson itself" in ai_service._part_meaning(abstraction).lower()
    assert "draw out" in ai_service._part_meaning(Field("Abstraction")).lower()
    # ILAW's Flow keeps its steps, with the lesson inside, from the references.
    flow = next(f for f in grounding.competency_view(FORMATS["ILAW"][0]) if f.label == "Flow")
    directive = ai_service._grounding_directive(flow, {"topic": "Tools"})
    assert "keep its steps" in directive and "online references" in directive, directive
    print("  lesson proper and references found in every live format OK")

    # Guided builds on what is written, by part name, the lesson proper marked.
    view = grounding.competency_view(FORMATS["4A's"][0])
    written = ai_service._written_by_label(
        {"references": "Kids. (2025). Tools. https://k.org/t", "abstraction": "A ruler measures length.",
         "assessment": ""}, view, next(f for f in view if f.label == "Assessment"))
    assert written == {"REFERENCES (the references)": "Kids. (2025). Tools. https://k.org/t",
                       "Abstraction (the lesson proper)": "A ruler measures length."}, written
    prompts = []
    real = ai_service._call
    ai_service._call = lambda system, parts, label: prompts.append("\n".join(parts)) or {"reply": "ok", "choices": []}
    try:
        ai_service.owl_chat({"topic": "Tools"}, next(f for f in view if f.label == "Assessment"),
                            {"abstraction": "A ruler measures length."}, "", [], "Help", fields=view)
        assert "Abstraction (the lesson proper)" in prompts[-1] and "checks only" in prompts[-1], prompts[-1][-900:]
        ai_service.check_coherence({"topic": "Tools"}, view, {"abstraction": "x", "assessment": "y"})
        assert 'the lesson proper is the part "Abstraction"' in prompts[-1]
    finally:
        ai_service._call = real
    print("  Guided builds on the parts written; the check knows the lesson proper OK")

    # Laid out like Alan's, not a word changed.
    assert ai_limits.tidy_layout("**Steps:** 1. Open the case 2. Remove the screws 3. Lift the cover") == \
        "Steps:\n1. Open the case\n2. Remove the screws\n3. Lift the cover"
    assert ai_limits.tidy_layout("- Safety\n\n* Accuracy\n• • Care   and  patience") == \
        "• Safety\n• Accuracy\n• Care and patience"
    quiz = ai_limits.tidy_layout("Which tool measures length? a. ruler b. scale c. clock d. cup\n"
                                 "Answer key: 1. a\nCriteria | Excellent | Good | Fair")
    assert quiz.split("\n")[:3] == ["1. Which tool measures length?", "a. ruler", "b. scale"], quiz
    assert "Criteria | Excellent | Good | Fair" in quiz.split("\n"), quiz
    long_text = "A sentence that a student wrote. " * 80
    assert ai_limits.tidy_layout(long_text) == long_text.strip(), "words were cut"
    assert ai_limits.tidy_layout(["- a", "b  c"]) == ["• a", "b c"]
    print("  a Guided plan tidied without changing its words OK")
    print("format kinds OK")


if __name__ == "__main__":
    main()
