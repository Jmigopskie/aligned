"""Self-check for Building Proficiency's speed and built-in coherence (user
report 2026-11-23: about 5 minutes per plan, and the coherence check still
found things to change in a plan Alan wrote):
- the reference search runs beside the writing, not before it;
- after the first batch, the other batches are written at the same time;
- one coherence pass at the end applies its fixes to the parts being written
  (never to standards copied from the guide, references, or parts not asked for).

No provider or network: ai_service._call and find_references are stubbed with
fixed delays. Run it directly: `python test_fast_coherent_build.py`.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service  # noqa: E402


class Field:
    def __init__(self, key, label, field_type="textarea"):
        self.field_key, self.label, self.field_type = key, label, field_type
        self.ai_hint, self.locked, self.parts_list, self.role = None, False, [], None
        self.sort_order = 0


LABELS = ["Objectives", "Motivation", "Activity", "Analysis", "Lesson Proper", "Abstraction", "Application",
          "Generalization", "Evaluation", "Assignment", "Remarks", "Reflection Notes", "References",
          "Content Standard", "Materials", "Values Integration", "Review", "Closure", "Practice", "Extension"]
FIELDS = [Field(l.lower().replace(" ", "_"), l, "list" if l == "Objectives" else "textarea") for l in LABELS]
CALL_DELAY, SEARCH_DELAY = 0.4, 1.2
calls = []


def fake_call(system, parts, label):
    calls.append(label)
    time.sleep(CALL_DELAY)
    if system == ai_service._COHERENCE_SYSTEM:
        return {"coherent": False, "summary": "The evaluation misses objective 2.", "issues": [
            {"part_key": "evaluation", "problem": "Objective 2 isn't checked.", "fix": "1. Which tool measures length?\na. ruler\nb. scale\nc. thermometer\nd. clock"},
            {"part_key": "content_standard", "problem": "x", "fix": "Invented standard"},
            {"part_key": "not_requested", "problem": "x", "fix": "y"}]}
    values = {f.field_key: f"Written {f.label}." for f in FIELDS}
    values["objectives"] = "identify measuring tools\nmeasure lengths accurately\nvalue careful work"
    return values


def fake_refs(context, count=10):
    time.sleep(SEARCH_DELAY)
    return ["Kids Learn. (2025). Measuring tools. https://example.org/tools"]


def main():
    real = (ai_service._call, ai_service.find_references, ai_service.reference_material)
    try:
        ai_service._call, ai_service.find_references = fake_call, fake_refs
        ai_service.reference_material = lambda lines, context: "Rulers measure length."
        start = time.time()
        events = list(ai_service.generate_full_streaming(
            {"topic": "Measuring tools"}, FIELDS, course_guide_text="", include_keys=[f.field_key for f in FIELDS]))
        took = time.time() - start
        batches = -(-len(FIELDS) // ai_service._STREAM_CHUNK_SIZE)
        old = SEARCH_DELAY + batches * CALL_DELAY
        assert took < old * 0.75, f"{took:.2f}s, the old one-after-another flow takes about {old:.2f}s"
        print(f"  {took:.2f}s instead of about {old:.2f}s OK")

        final = events[-1]
        assert final["type"] == "complete" and not final["missing"], final
        values = final["values"]
        assert values["evaluation"].startswith("1. Which tool measures length?") and "a. ruler" in values["evaluation"], values["evaluation"]
        assert values.get("content_standard", "") != "Invented standard"
        assert "not_requested" not in values
        assert any(e.get("section") == "Coherence check" for e in events if e["type"] == "section_done")
        assert "Kids Learn" in values["references"], values["references"]
        print("  coherence fixes applied to the parts written, not standards OK")

        # A regenerate of one part: only that part is written and fixed.
        calls.clear()
        events = list(ai_service.generate_full_streaming(
            {"topic": "Measuring tools"}, FIELDS, include_keys=["motivation"],
            written={"objectives": "identify tools"}))
        assert set(events[-1]["values"]) == {"motivation"}, events[-1]["values"]
        print("  a regenerate only touches its parts OK")

        # The references part is never asked for again: its model-written
        # links are dropped and the verified ones fill it at the end.
        calls.clear()
        list(ai_service.generate_full_streaming({"topic": "Tools"}, FIELDS, include_keys=[f.field_key for f in FIELDS]))
        assert not [c for c in calls if "filling gaps" in c], calls
        print("  no wasted retries on references OK")
    finally:
        ai_service._call, ai_service.find_references, ai_service.reference_material = real
    print("fast coherent build OK")


if __name__ == "__main__":
    main()
