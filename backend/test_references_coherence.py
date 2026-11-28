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


def own_page(n, words="number system"):
    """An on-topic page with text of its own (identical text reads as a copy)."""
    return " ".join(f"Page {n} line {i}: a {words} sample {i * 7 + n} uses base {i + n * 3}." for i in range(80))


PAGES = {
    "https://a.edu/numbers": own_page(1),
    "https://www.b.org/binary": own_page(2),
    "https://www.f.gov.ph/number-systems": own_page(3),
    "https://g.com/numbers": own_page(4),
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

        def search(prompt):
            calls.append(prompt)
            return {u: f"{u.rsplit('/', 1)[1].title()} explained" for u in PAGES}

        def read(url):
            # What a page says about itself, as page_text records it while reading.
            grounding._META[url] = {"https://a.edu/numbers": {"author": "Juan Dela Cruz", "date": "2025-03-04T08:00",
                                                              "site": "Kids Learn"},
                                    "https://www.b.org/binary": {"author": "", "date": "", "site": "B Org"}
                                    }.get(url, {})
            return PAGES.get(url, "")

        ai_service._web_search_post = search
        grounding.page_text = read
        found = ai_service.find_references({"topic": "Number systems", "subject": "ICT"})
        urls = [grounding.reference_urls([l])[0] for l in found]
        # Every page that passes, not two: school/government first, then .org, then the rest.
        assert urls == ["https://a.edu/numbers", "https://www.f.gov.ph/number-systems",
                        "https://www.b.org/binary", "https://g.com/numbers"], found
        # APA 7 from the page itself: author (surname first), date, title, site.
        assert found[0] == "Dela Cruz, J. (2025, March 4). Numbers explained. Kids Learn. https://a.edu/numbers", found
        # No author: the site is the author and isn't repeated; no date: n.d.
        assert found[2] == "B Org. (n.d.). Binary explained. https://www.b.org/binary", found
        assert found[1] == "f.gov.ph. (n.d.). Number-Systems explained. https://www.f.gov.ph/number-systems", found
        # A page title's trailing site name, only when it is the site's.
        assert ai_service._split_site("Parts of a Flower – Gardening Solutions", "gardeningsolutions.ifas.ufl.edu") \
            == ("Parts of a Flower", "Gardening Solutions")
        assert ai_service._split_site("TLE 7 - 8 - Carpentry - Module 5", "pdfcoffee.com")[1] == ""
        assert ai_service._split_site("Biology 2e | OpenStax") == ("Biology 2e", "OpenStax")
        assert all(grounding.to_apa(l) == l for l in found), found
        assert len(calls) == 2 and all("Find 10" in c and "different website" in c for c in calls), calls
        assert any("DepEd" in c for c in calls)
        print("  every reliable, on-topic, readable reference, one per site OK")

        # Three or more are remembered for the topic...
        assert ai_service.find_references({"topic": "Number systems", "subject": "ICT"}) == found and len(calls) == 2
        # ...a thin set is searched again next time.
        ai_service._FOUND_REFERENCES.clear()
        grounding.page_text = lambda url: ON_TOPIC if url == "https://a.edu/numbers" else ""
        assert len(ai_service.find_references({"topic": "Number systems", "subject": "ICT"})) == 1
        ai_service.find_references({"topic": "Number systems", "subject": "ICT"})
        assert len(calls) == 6, len(calls)
        grounding.page_text = lambda url: PAGES.get(url, "")

        # --- At most five, the most on-topic first, no repeated titles (user, 2026-11-28) ---
        ai_service._FOUND_REFERENCES.clear()
        pages = {f"https://s{n}.com/binary": own_page(n, "binary number system") for n in range(12)}
        pages["https://copy.org/binary"] = pages["https://s0.com/binary"]     # the same page on another site
        pages["https://deped.gov.ph/numbers"] = own_page(50)                   # 2 of the topic's 3 terms
        ai_service._web_search_post = lambda prompt: {u: "Binary number systems" for u in pages}
        grounding.page_text = lambda url: pages.get(url, "")
        found = ai_service.find_references({"topic": "Binary number systems"})
        urls = [grounding.reference_urls([l])[0] for l in found]
        assert len(found) == ai_service._WEB_REFERENCES == 5, found
        assert not {"https://copy.org/binary", "https://s0.com/binary"} <= set(urls), "a copied page isn't cited twice"
        assert "https://deped.gov.ph/numbers" not in urls, "a page covering the whole topic beats a .gov covering part"
        ai_service._web_search_post = search
        grounding.page_text = lambda url: PAGES.get(url, "")
        print("  five references at most, on-topic first, no repeats OK")
        ai_service._FOUND_REFERENCES.clear()
        print("  only a set of 3+ is cached OK")

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

        def slow_search(prompt):
            overlap["search"] = threading.current_thread().name
            time.sleep(0.6)
            return search(prompt)

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

    # --- The search asks for results only (a written reply took 5+ minutes) ---
    sent = []
    real_post = ai_service.requests.post

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}", "annotations": [
                {"type": "url_citation", "url_citation": {"url": "https://a.edu/x/", "title": "X"}}]}}]}

    try:
        ai_service.requests.post = lambda url, **kw: sent.append(kw["json"]) or Reply()
        assert ai_service._web_search_post("prompt") == {"https://a.edu/x": "X"}
        assert sent[0]["max_tokens"] <= 32 and "reasoning" not in sent[0], sent
        assert sent[0]["plugins"][0]["id"] == "web"
    finally:
        ai_service.requests.post = real_post
    print("  search asks for results only, with a capped reply OK")

    # --- A page's own author and date, read from its HTML ---
    meta = grounding._meta_of('<html><meta name="author" content="Maria  Santos"><meta property="og:site_name" '
                              'content="Science Hub"><script type="application/ld+json">{"datePublished": '
                              '"2023-11-02"}</script></html>')
    assert meta == {"author": "Maria Santos", "date": "2023-11-02", "site": "Science Hub"}, meta
    assert grounding.apa_author("Maria Santos") == "Santos, M."
    assert grounding.apa_author("Department of Education") == "Department of Education"
    assert grounding.apa_author("Mary Ann de los Santos") == "de los Santos, M. A."
    assert grounding.apa_date("2023-11-02T10:00:00Z") == "2023, November 2"
    assert grounding.apa_date("Posted 2019") == "2019" and grounding.apa_date("") == "n.d."
    print("  APA author and date from the page OK")

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
