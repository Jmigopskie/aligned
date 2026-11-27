"""Self-check: an admin's field context ("What goes here") makes a part the app
doesn't know by name read as the standard part it describes, while known
labels read exactly as before. Run: `python test_field_context.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import ai_service, field_roles, grounding


class F:
    def __init__(self, label, hint=None, key="f1", field_type="textarea"):
        self.label, self.ai_hint, self.field_key, self.field_type = label, hint, key, field_type
        self.role = None


def main():
    # Unknown words, described by the admin.
    quiz = F("Self-Check", "A short quiz learners answer to check their understanding.")
    teach = F("Lesson Development", "Teach the new topic: definitions, key terms and examples.")
    aims = F("Kahon A", "What learners should be able to do at the end of the lesson.")
    home = F("Kahon B", "Something learners do at home to extend the lesson.")
    assert field_roles.role_for(quiz) == "heavy"
    assert "evaluation" in field_roles.part_text(quiz)
    assert grounding.is_lesson_proper_field(teach)
    assert ai_service._is_objective_field(aims)
    assert "assignment" in field_roles.part_text(home)

    # Known labels: the context never changes what they are.
    assert field_roles.part_text(F("Teacher", "The lesson's evaluation teacher")) == "f1 teacher"
    assert field_roles.part_text(F("Pre-Lesson", "Routine, then a review")) == "f1 pre-lesson"
    # No context, or context naming no part: unchanged.
    assert field_roles.part_text(F("Kahon C")) == "f1 kahon c"
    assert field_roles.role_for(F("Kahon C", "Write anything.")) == "easy"

    # The prompt carries both the part's name and the admin's words.
    block = ai_service._schema_block([quiz])
    assert '"Self-Check"' in block and "check their understanding" in block, block
    print("field context OK")


if __name__ == "__main__":
    main()
