"""Self-check: the lesson proper is the lesson itself (headings, definitions,
terms, examples, as on slides), taught from the references' pages.

- Building Proficiency finds the references before writing, reads their pages
  into the prompt, and lists the same references afterwards (one search).
- Guided's chat about the lesson proper reads the references the student
  listed, or tells them to add some first.
- The written lesson keeps its headings and bullets and isn't cut to 8 lines.

No provider or network is used: ai_service._call, find_references and the
page reader are stubbed. Run it directly: `python test_lesson_proper.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service, grounding  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea", ai_hint=None):
        self.field_key = field_key
        self.label = label
        self.field_type = field_type
        self.ai_hint = ai_hint
        self.locked = False


LESSON = Field("lesson_proper", "Lesson Proper")
REFS = Field("references", "References", "list")
GEN = Field("generalization", "Generalization")
REF_LINE = "Kids Learn. (2025). Number systems. Kids Learn. https://example.org/number-systems"
PAGE = ("A number system is an organized way of writing numbers using digits and rules. "
        "Binary has 2 digits, 0 and 1, so its base is 2. Decimal has 10 digits, 0 to 9.")
TAUGHT = "\n".join(["What is a Number System?", "• A number system is an organized way of writing numbers.",
                    "It is defined by:", "1. Digits: the symbols it uses", "2. Base: how many digits it uses",
                    "3. Place value: a digit's value by its position", "Examples:",
                    "• Decimal has 10 digits (0-9), so its base is 10.", "• Binary has 2 digits (0 and 1), so its base is 2.",
                    "What is Binary?", "• Base 2."])


def main():
    context = {"topic": "Number systems", "main_topic": "Number systems"}

    # --- Which parts are the lesson, and what they are asked for ---
    assert grounding.is_lesson_proper_field(LESSON) and grounding.is_lesson_proper_field(Field("discussion", "Discussion"))
    assert not grounding.is_lesson_proper_field(GEN) and not grounding.is_lesson_proper_field(Field("abstraction", "Abstraction"))
    directive = ai_service._grounding_directive(LESSON, context)
    assert "What is a Number System?" in directive and "references' content" in directive, directive
    assert "references" not in ai_service._grounding_directive(GEN, context)
    assert grounding.reference_urls([REF_LINE, REF_LINE + ".", "no link"]) == ["https://example.org/number-systems"]
    # Private addresses are never read.
    assert grounding.page_text("http://127.0.0.1/") == "" and grounding.page_text("http://169.254.169.254/") == ""
    print("  lesson proper asks for the lesson OK")

    # --- The lesson keeps its shape and length; other parts keep the ceiling ---
    out = ai_service._trim({"lesson_proper": TAUGHT, "generalization": "\n".join(f"Point {n}" for n in range(12))},
                           [LESSON, GEN], context=context)
    assert out["lesson_proper"] == TAUGHT, out["lesson_proper"]
    assert len(out["generalization"].split("\n")) == ai_service._MAX_LIST_ITEMS
    print("  lesson kept whole OK")

    # --- Building Proficiency: references found first, their pages read, one search ---
    searches, prompts = [], []
    real = (ai_service.find_references, grounding.page_text, ai_service._call)
    try:
        ai_service.find_references = lambda ctx, count=4: searches.append(1) or [REF_LINE]
        grounding.page_text = lambda url: PAGE if url == "https://example.org/number-systems" else ""

        def fake_call(system, parts, label):
            prompts.append(" ".join(parts))
            return {"lesson_proper": TAUGHT, "references": "", "generalization": "Number systems use digits and a base."}

        ai_service._call = fake_call
        values = ai_service.generate_full(context, [REFS, LESSON, GEN])
        assert len(searches) == 1, searches
        assert PAGE in prompts[0] and REF_LINE in prompts[0], prompts[0][-800:]
        assert values["lesson_proper"] == TAUGHT and REF_LINE in values["references"], values
        print("  building proficiency teaches from the references OK")

        # --- Guided: the student's own references, or a nudge to add them ---
        prompts.clear()
        ai_service._call = lambda system, parts, label: prompts.append(" ".join(parts)) or {
            "reply": "Here is a draft from your references.",
            "choices": [{"type": "use", "label": "Lesson", "text": TAUGHT + "\n" + "• more\n" * 200, "why": "From your references."}]}
        answer = ai_service.owl_chat(context, LESSON, {"references": f"• {REF_LINE}"}, "", [], "Help me write the lesson")
        assert PAGE in prompts[0] and REF_LINE in prompts[0], prompts[0][-600:]
        assert len(answer["choices"][0]["text"]) > 1500, "the whole lesson comes through"
        prompts.clear()
        ai_service.owl_chat(context, LESSON, {"references": ""}, "", [], "Help me write the lesson")
        assert "not listed any online references" in prompts[0]
        prompts.clear()
        ai_service.owl_chat(context, GEN, {"references": f"• {REF_LINE}"}, "", [], "Help")
        assert PAGE not in prompts[0], "only the lesson proper reads the pages"
        print("  guided chat uses the student's references OK")
    finally:
        ai_service.find_references, grounding.page_text, ai_service._call = real
    print("lesson proper OK")


if __name__ == "__main__":
    main()
