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


ON_TOPIC = "A number system is a way of writing numbers. Each number system has a base. " * 30
PAGES = {
    "https://a.edu/numbers": ON_TOPIC,
    "https://www.b.org/binary": ON_TOPIC,
    "https://www.f.gov.ph/number-systems": ON_TOPIC,
    "https://g.com/numbers": ON_TOPIC,
    "https://a.edu/other": "Number systems, briefly. " + "x " * 900,   # same site as the first, thinner
    "https://c.com/broken": "",                                          # doesn't open
    "https://d.net/thin": "number systems",                              # opens, but no real text
    "https://e.com/adobo": "Adobo is a Filipino dish of meat in vinegar. " * 40,  # not about the topic
    "https://en.wikipedia.org/wiki/Numeral_system": ON_TOPIC,            # not a source a plan cites
    "https://www.youtube.com/watch?v=1": ON_TOPIC,
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
        # Every page that passes, not two: school/government first, then .org, then the rest.
        assert urls == ["https://a.edu/numbers", "https://www.f.gov.ph/number-systems",
                        "https://www.b.org/binary", "https://g.com/numbers"], found
        # APA 7: the model's line, with the site dropped where it repeats the author.
        assert found[0] == "Kids Learn. (2025). Number systems. https://a.edu/numbers", found
        assert all(grounding.to_apa(l) == l for l in found), found
        assert len(calls) == 2 and all("Find 10" in c and "different website" in c for c in calls), calls
        assert any("DepEd" in c for c in calls)
        print("  every reliable, on-topic, readable reference, one per site OK")

        # Four is a thin set: searched again next time, not remembered.
        ai_service.find_references({"topic": "Number systems", "subject": "ICT"})
        assert len(calls) == 4, len(calls)
        # A full set is remembered for the topic.
        ai_service._FOUND_REFERENCES.clear()
        full = ai_service.find_references({"topic": "Number systems", "subject": "ICT"}, count=3)
        assert ai_service.find_references({"topic": "Number systems", "subject": "ICT"}) == full and len(calls) == 6
        print("  only a full set is cached OK")

        # The rules on their own.
        assert grounding.is_unreliable_site("https://m.facebook.com/x") and grounding.is_unreliable_site("https://youtu.be/x")
        assert not grounding.is_unreliable_site("https://www.deped.gov.ph/x")
        assert [grounding.source_rank(u) for u in ("https://deped.gov.ph/a", "https://up.edu.ph/a",
                                                   "https://unesco.org/a", "https://khan.com/a")] == [0, 0, 1, 2]
        assert grounding.topic_terms("What is a Number Systems?") == ["number", "system"]
        assert grounding.to_apa("W3Schools. (n.d.). HTML images. W3Schools. https://w3schools.com/a") == \
            "W3Schools. (n.d.). HTML images. https://w3schools.com/a"
        assert grounding.to_apa("Cruz, J. (2024). Binary. Kids Learn. https://k.org/b") == \
            "Cruz, J. (2024). Binary. Kids Learn. https://k.org/b"
        print("  reliability, topic and APA rules OK")

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

    # --- The search sends the reasoning setting the writing calls use ---
    sent = []
    real_post, real_flag = ai_service.requests.post, ai_service.Config.OPENROUTER_REASONING

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}", "annotations": []}}]}

    try:
        ai_service.requests.post = lambda url, **kw: sent.append(kw["json"]) or Reply()
        for flag in (True, False):
            ai_service.Config.OPENROUTER_REASONING = flag
            ai_service._web_search_post("system", "prompt")
        assert "reasoning" not in sent[0] and sent[1]["reasoning"] == {"enabled": False}, sent
    finally:
        ai_service.requests.post, ai_service.Config.OPENROUTER_REASONING = real_post, real_flag
    print("  search follows OPENROUTER_REASONING OK")

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
