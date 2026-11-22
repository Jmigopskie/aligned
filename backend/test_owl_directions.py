"""Self-check for Alan's Guided chat (Batch 1): a general request gets two
directions to choose from, a chosen direction (or a specific request) gets the
complete part, and a locked part never gets ready-made content.

No provider or network: ai_service._call is stubbed.
Run it directly: `python test_owl_directions.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea", locked=False):
        self.field_key, self.label, self.field_type = field_key, label, field_type
        self.ai_hint, self.locked = None, locked


MOTIVATION = Field("motivation", "Motivation")
CTX = {"topic": "Measuring tools", "main_topic": "Kitchen tools"}
WRITTEN = {"objectives": "identify the parts of a measuring tape\nmeasure lengths accurately",
           "evaluation": "Multiple-choice quiz:\n1. What ..."}

prompts = []


def stub(reply):
    def call(system, parts, label):
        prompts.append(system + "\n" + "\n".join(parts))
        return reply
    return call


def direction(label):
    return {"type": "direction", "label": label, "text": f"Focus on {label.lower()}.", "why": "Fits the objectives."}


def main():
    real = ai_service._call
    try:
        # --- general_gives_two_directions ---
        ai_service._call = stub({"reply": "Pick a direction.", "choices": [
            direction("Recall game"), direction("Hands-on race"), direction("Story starter"),
            {"type": "use", "label": "Ready game", "text": "A whole game", "why": "x"},
            {"type": "ask", "label": "What materials?", "text": "What materials?"}]})
        out = ai_service.owl_chat(CTX, MOTIVATION, WRITTEN, "", [], "Help me with this part")
        kinds = [c["type"] for c in out["choices"]]
        assert kinds.count("direction") == 2 and "use" not in kinds, out
        assert out["choices"][0]["why"] and out["choices"][0]["text"], out
        assert "exactly 2 directions" in prompts[-1] and "identify the parts of a measuring tape" in prompts[-1]
        print("  a general request gets two directions OK")

        # --- direction_gives_complete_part ---
        game = "Title: Tape Hunt\n" + "\n".join(f"{n}. Question {n}? Answer: {n} cm" for n in range(1, 400))
        assert len(game) > 6000
        ai_service._call = stub({"reply": "Here is the complete activity.", "choices": [
            {"type": "use", "label": "Tape Hunt", "text": game, "why": "Recall first."},
            direction("Something else"),
            {"type": "ask", "label": "Make it shorter?", "text": "Make it shorter?"}]})
        out = ai_service.owl_chat(CTX, MOTIVATION, WRITTEN, "", [], "Go with: Recall game",
                                  direction={"label": "Recall game", "text": "Focus on recall game."})
        use = [c for c in out["choices"] if c["type"] == "use"]
        assert len(use) == 1 and use[0]["text"] == game[:8000], len(use[0]["text"]) if use else out
        assert not [c for c in out["choices"] if c["type"] == "direction"], out
        assert "Recall game" in prompts[-1] and "complete" in prompts[-1], prompts[-1][-600:]
        print("  a chosen direction gets the complete part OK")

        # --- specific_request_answered ---
        ai_service._call = stub({"reply": "Here it is.", "choices": [
            {"type": "use", "label": "Bit Hunt", "text": "Directions...\n1. Q? A", "why": "As asked."}]})
        out = ai_service.owl_chat(CTX, MOTIVATION, WRITTEN, "", [],
                                  "Give me the directions and questions for a game called Bit Hunt")
        assert [c["type"] for c in out["choices"]] == ["use"], out
        print("  a specific request is answered in full OK")

        # --- locked_direction_coaches ---
        ai_service._call = stub({"reply": "Think about it.", "choices": [
            {"type": "use", "label": "Done for you", "text": "Complete content", "why": "x"},
            {"type": "ask", "label": "What should it check?", "text": "What should it check?"}]})
        out = ai_service.owl_chat(CTX, Field("evaluation", "Evaluation", locked=True), WRITTEN, "", [], "Go with: Quiz",
                                  direction={"label": "Quiz", "text": "A quiz."})
        assert "use" not in [c["type"] for c in out["choices"]], out
        print("  a locked part only gets coaching OK")
    finally:
        ai_service._call = real
    print("owl directions OK")


if __name__ == "__main__":
    main()
