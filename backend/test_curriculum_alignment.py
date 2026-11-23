"""Self-check for aligning the plan to the selected curriculum (user,
2026-11-24): the section for the topic is found; a topic the document doesn't
name goes under its main topic or its closest section (an AI picks the
closest competency only when no words match, once per lesson); the learners'
grade picks that grade's section; every prompt says who the class is and how
long the session runs. No provider or network.

Run it directly: `python test_curriculum_alignment.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service  # noqa: E402

FILLER = "General notes about the school year and classroom routines. " * 40
GUIDE = (
    "GRADE 7\nContent Standard\nThe learner demonstrates understanding of measuring tools.\n"
    "Learning Competency\nUse measuring tools such as the ruler and the tape measure in carpentry.\n" + FILLER +
    "GRADE 8\nContent Standard\nThe learner demonstrates understanding of measuring tools and precision.\n"
    "Learning Competency\nUse measuring tools such as calipers for precise carpentry work.\n" + FILLER +
    "GRADE 8\nContent Standard\nThe learner demonstrates understanding of plant reproduction.\n"
    "Learning Competency\nDescribe the reproductive organs of flowering plants and their functions.\n" + FILLER
)


def main():
    calls = []
    real = ai_service._call

    def pick(system, parts, label):
        calls.append(label)
        lines = parts[0].split("Lines of the curriculum document:\n")[1].split("\n")
        hit = next(l for l in lines if "reproductive organs" in l)
        return {"index": int(hit.split(".")[0])}

    ai_service._call = pick
    try:
        excerpt, how = ai_service._guide_match(GUIDE, {"topic": "Measuring tools", "grade_level": "Grade 8"}, 1500)
        assert how == "exact" and "calipers" in excerpt and "tape measure" not in excerpt, (how, excerpt[:300])
        excerpt, how = ai_service._guide_match(GUIDE, {"topic": "Measuring tools", "grade_level": "Grade 7"}, 1500)
        assert "tape measure" in excerpt, excerpt[:300]
        print("  the learners' grade picks that grade's section OK")

        excerpt, how = ai_service._guide_match(GUIDE, {"topic": "Squares and levels", "main_topic": "Measuring tools",
                                                       "grade_level": "Grade 8"}, 1500)
        assert how == "main" and "calipers" in excerpt, how
        excerpt, how = ai_service._guide_match(GUIDE, {"topic": "Precision cutting", "grade_level": "Grade 8"}, 1500)
        assert how == "closest" and "precis" in excerpt.lower(), (how, excerpt[:200])
        assert not calls, "words matched, so no AI was asked"
        # No word in common: the AI picks the closest competency, once.
        ctx = {"topic": "Pollination by bees", "grade_level": "Grade 8"}
        excerpt, how = ai_service._guide_match(GUIDE, ctx, 1500)
        assert how == "closest" and "reproductive organs" in excerpt, (how, excerpt[:200])
        ai_service._guide_match(GUIDE, ctx, 1500)
        assert calls == ["Closest competency"], calls
        # Reference pages never ask the AI.
        ai_service.guide_excerpt(GUIDE, {"topic": "Volcano eruptions"}, 1500)
        assert calls == ["Closest competency"], calls
        print("  main topic, closest words, then the AI's closest competency (cached) OK")

        excerpt, _ = ai_service._guide_inputs([("BoW", GUIDE)], ctx)
        assert "closest matching section" in excerpt and "Align the lesson" in excerpt, excerpt[:300]
    finally:
        ai_service._call = real
        ai_service._CLOSEST.clear()

    block = ai_service._lesson_block({"topic": "Tools", "grade_level": "Grade 7", "duration_minutes": 50}, "Guide")
    assert "Grade 7 learners" in block and "50 minutes" in block and "ALIGNED" in block, block
    college = ai_service._learners_directive({"level_type": "College", "year": "2nd Year", "program": "BSIT"})
    assert "2nd Year BSIT college students" in college, college
    print("  every prompt says who the class is and how long it runs OK")
    print("curriculum alignment OK")


if __name__ == "__main__":
    main()
