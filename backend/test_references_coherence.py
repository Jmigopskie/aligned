"""Self-check for the testers' round on Guided (TUP):
- references: several, each from a different website, only pages that really
  open with text; the search's own results fill in when the model lists one;
  a topic's references are found once (cached);
- the references search runs beside Alan's reply, not after it;
- objectives, lesson proper and evaluation are told to line up.

No provider or network: the web search, page reader and model are stubbed.
Run it directly: `python test_references_coherence.py`.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service, grounding  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea"):
        self.field_key, self.label, self.field_type = field_key, label, field_type
        self.ai_hint, self.locked = None, False


PAGES = {
    "https://a.edu/numbers": "x" * 2000,
    "https://www.b.org/binary": "y" * 2000,
    "https://a.edu/other": "z" * 2000,   # same site as the first
    "https://c.com/broken": "",          # doesn't open
    "https://d.net/thin": "short",       # opens, but no real text
}


def main():
    real = (ai_service.PROVIDER, ai_service._web_search_post, grounding.page_text, ai_service._call)
    calls = []
    try:
        ai_service.PROVIDER = "openrouter"
        ai_service._FOUND_REFERENCES.clear()

        def search(system, prompt):
            calls.append(prompt)
            listed = '{"references": ["Kids Learn. (2025). Number systems. Kids Learn. https://a.edu/numbers"]}'
            return listed, {u: f"{u.rsplit('/', 1)[1].title()} explained - Site {i}" for i, u in enumerate(PAGES)}

        ai_service._web_search_post = search
        grounding.page_text = lambda url: PAGES.get(url, "")
        found = ai_service.find_references({"topic": "Number systems", "subject": "ICT"})
        urls = [grounding.reference_urls([l])[0] for l in found]
        assert urls == ["https://a.edu/numbers", "https://www.b.org/binary"], found
        assert found[0].startswith("Kids Learn.") and grounding.to_apa(found[1]) == found[1], found
        assert "different website" in calls[0] and "Find 8" in calls[0]
        # Found once per topic.
        assert ai_service.find_references({"topic": "Number systems", "subject": "ICT"}) == found and len(calls) == 1
        print("  several readable references, one per site OK")

        # --- The references search runs beside the reply ---
        ai_service._FOUND_REFERENCES.clear()
        overlap = {}

        def slow_search(system, prompt):
            overlap["search"] = threading.current_thread().name
            time.sleep(0.6)
            return search(system, prompt)

        def slow_call(system, parts, label):
            time.sleep(0.6)
            return {"reply": "Here are references.", "choices": []}

        ai_service._web_search_post, ai_service._call = slow_search, slow_call
        start = time.time()
        answer = ai_service.owl_chat({"topic": "Number systems"}, Field("references", "References", "list"),
                                     {}, "", [], "Find references")
        took = time.time() - start
        assert took < 1.1, f"search and reply ran one after the other ({took:.2f}s)"
        assert answer["choices"] and answer["choices"][0]["label"] == "Online references", answer
        print(f"  references search beside the reply OK ({took:.2f}s)")
    finally:
        ai_service.PROVIDER, ai_service._web_search_post, grounding.page_text, ai_service._call = real

    # --- Objectives, lesson and evaluation line up ---
    ctx = {"topic": "Number systems"}
    lesson = ai_service._grounding_directive(Field("lesson_proper", "Lesson Proper"), ctx)
    evaluation = ai_service._grounding_directive(Field("evaluation", "V. Evaluation"), ctx)
    objectives = ai_service._field_directive(Field("objectives", "Lesson Objectives", "list"))
    assert "every learning objective already written" in lesson, lesson
    assert "checks one of the learning objectives" in evaluation and "lesson proper taught" in evaluation, evaluation
    assert "the evaluation can check" in objectives, objectives
    mastery = ai_service._grounding_directive(Field("mastery", "Developing mastery (leads to Formative Assessment 3)"), ctx)
    assert "learning objectives" not in mastery
    print("  objectives, lesson and evaluation aligned OK")
    print("references and coherence OK")


if __name__ == "__main__":
    main()
