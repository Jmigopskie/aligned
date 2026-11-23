"""Self-check for Building Proficiency's speed and built-in coherence (user
reports 2026-11-23/24: about 5 minutes per plan, the coherence check still
found things to change, and the plan must be written top to bottom):
- the reference search runs beside the first batches, not before them;
- batches are written one after another, each told everything above it; the
  references are in before the lesson proper, which is a batch of its own;
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
prompts = {}


def fake_call(system, parts, label):
    calls.append(label)
    prompts[label] = "\n".join(parts)
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
    real_check = ai_service.check_coherence
    try:
        ai_service._call, ai_service.find_references = fake_call, fake_refs
        ai_service.reference_material = lambda lines, context: "Rulers measure length."
        start = time.time()
        events = list(ai_service.generate_full_streaming(
            {"topic": "Measuring tools"}, FIELDS, course_guide_text="", include_keys=[f.field_key for f in FIELDS]))
        took = time.time() - start
        writes = [c for c in calls if c.startswith("Building Proficiency")]
        # Top to bottom, one batch after another (user, 2026-11-24): the
        # lesson proper is a batch of its own, so what follows it is written
        # from it; the search runs beside the batches before it.
        assert writes == sorted(writes, key=lambda c: int(c.split()[-1].split("/")[0])), writes
        assert len(writes) == 6, writes
        assert "- references (" not in prompts["Building Proficiency 4/6"].split("Now fill ONLY")[1], \
            "the verified references are never asked of the model again"
        done = [e["section"] for e in events if e["type"] == "section_done"]
        assert done[:4] == ["Objectives – Analysis", "Online references", "Lesson Proper",
                            "Abstraction – Evaluation"], done
        assert done.count("Online references") == 1, done   # the model's own list never replaces it
        lp_prompt = prompts["Building Proficiency 2/6"]
        assert "Kids Learn" in lp_prompt and "Rulers measure length." in lp_prompt
        assert "Written Lesson Proper." in prompts["Building Proficiency 3/6"]   # the assessment sees it
        serial = SEARCH_DELAY + (len(writes) + 1) * CALL_DELAY
        assert took < serial, f"{took:.2f}s: the search didn't run beside the first batch"
        print(f"  top to bottom, references before the lesson proper, {took:.2f}s OK")

        final = events[-1]
        assert final["type"] == "complete" and not final["missing"], final
        values = final["values"]
        assert values["evaluation"].startswith("1. Which tool measures length?") and "a. ruler" in values["evaluation"], values["evaluation"]
        assert values.get("content_standard", "") != "Invented standard"
        assert "not_requested" not in values
        assert any(e.get("section") == "Coherence check" for e in events if e["type"] == "section_done")
        assert "Kids Learn" in values["references"], values["references"]
        print("  coherence fixes applied to the parts written, not standards OK")

        # Server run 2026-11-24: the pass pasted "Add a performance task ..." over
        # a 5-item quiz. An instruction, or a quiz fix without its key, is never applied.
        quiz_ctx = {"topic": "Flowers", "assessment_type": "5-item multiple-choice quiz"}
        evaluation = next(f for f in FIELDS if f.field_key == "evaluation")
        for fix in ("Add a performance task evaluation: 'Assemble a diagram.'", "Performance task: draw a flower."):
            ai_service.check_coherence = lambda *a, fix=fix: {"issues": [{"part_key": "evaluation", "fix": fix}]}
            assert ai_service._apply_coherence(quiz_ctx, [evaluation], {}, {}, "", "") == {}, fix
        ai_service.check_coherence = real_check
        objectives = next(f for f in FIELDS if f.field_key == "objectives")
        assert "a quiz can check" in ai_service._grounding_directive(objectives, quiz_ctx)
        assert "quiz can check" not in ai_service._grounding_directive(objectives, {"topic": "Flowers"})
        print("  the teacher's quiz stays a quiz; objectives fit it OK")

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
        ai_service.check_coherence = real_check
    print("fast coherent build OK")


if __name__ == "__main__":
    main()
