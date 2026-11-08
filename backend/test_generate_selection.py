"""Self-check that generation writes only the fields it was asked for.

Building Proficiency always writes the quick fields and offers the
thinking-heavy ones as a checklist, so a request now carries the exact set to
generate. Two things must hold: nothing outside that set is written, and the
"couldn't be generated" report counts only the requested fields — warning a
teacher about a Flow they deliberately kept for themselves would train them to
ignore the warning entirely.

The provider is never called: ai_service._call is replaced with a stub, so this
runs with no API key and no network.

Run it directly: `venv/Scripts/python test_generate_selection.py`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service


class Field:
    def __init__(self, field_key, label, field_type="textarea", ai_hint=None):
        self.field_key = field_key
        self.label = label
        self.field_type = field_type
        self.ai_hint = ai_hint


FIELDS = [
    Field("teacher", "Designed by Teacher/s", "text"),
    Field("sessions", "No. of Sessions", "text"),
    Field("objectives", "Learning Objectives", "list"),
    Field("flow", "Flow"),
    Field("assessment", "Formative Assessment"),
]


def stub_answers(answers, seen_keys):
    """Replace the provider with a stub that answers from `answers` and records
    which keys it was asked for."""
    def fake_call(system_instruction, parts, label):
        asked = [f.field_key for f in FIELDS if f"- {f.field_key} (" in " ".join(parts)]
        seen_keys.extend(asked)
        return {k: answers.get(k, "") for k in asked}

    ai_service._call = fake_call


def run(include_keys):
    seen = []
    answers = {k: f"content for {k}" for k in ["teacher", "sessions", "flow", "assessment"]}
    # An objectives field is only complete with at least three objectives.
    answers["objectives"] = "Identify the parts\nExplain their use\nValue careful work"
    stub_answers(answers, seen)
    events = list(ai_service.generate_full_streaming(
        {"topic": "Spreadsheets"}, FIELDS, course_guide_text="", include_keys=include_keys))
    final = [e for e in events if e["type"] == "complete"][-1]
    return final, seen


def check_subset_only():
    final, seen = run(["teacher", "sessions", "objectives"])
    assert set(final["values"]) == {"teacher", "sessions", "objectives"}, final["values"]
    assert "flow" not in seen, seen
    assert "assessment" not in seen, seen
    print("  subset only OK")


def check_missing_counts_requested_only():
    """A field left out of the request is not missing — it was never asked for."""
    seen = []
    # Everything answers except "objectives", which comes back empty.
    stub_answers({"teacher": "T", "sessions": "2", "objectives": "", "flow": "F"}, seen)
    events = list(ai_service.generate_full_streaming(
        {"topic": "X"}, FIELDS, course_guide_text="",
        include_keys=["teacher", "sessions", "objectives"]))
    final = [e for e in events if e["type"] == "complete"][-1]
    # flow and assessment were not requested, so they must not be reported.
    assert "flow" not in final["missing"], final["missing"]
    assert "assessment" not in final["missing"], final["missing"]
    # objectives was requested and came back empty, so it must be reported.
    assert "objectives" in final["missing"], final["missing"]
    assert "Learning Objectives" in final["missing_labels"], final["missing_labels"]
    print("  missing accounting OK")


def check_absent_means_everything():
    """No include_keys at all keeps the old behaviour: generate the lot."""
    final, seen = run(None)
    assert set(final["values"]) == {"teacher", "sessions", "objectives", "flow", "assessment"}, final["values"]
    assert final["missing"] == [], final["missing"]
    print("  absent means everything OK")


def check_unknown_keys_ignored():
    final, seen = run(["teacher", "not_a_field"])
    assert set(final["values"]) == {"teacher"}, final["values"]
    assert "not_a_field" not in final["missing"], final["missing"]
    print("  unknown keys ignored OK")


def check_empty_selection():
    """An empty list means generate nothing, and must not raise."""
    final, seen = run([])
    assert final["values"] == {}, final["values"]
    assert final["missing"] == [], final["missing"]
    print("  empty selection OK")


def check_select_fields_helper():
    picked = ai_service.select_fields(FIELDS, ["flow", "teacher"])
    # Document order is preserved, not the order of include_keys.
    assert [f.field_key for f in picked] == ["teacher", "flow"], [f.field_key for f in picked]
    assert len(ai_service.select_fields(FIELDS, None)) == len(FIELDS)
    print("  select_fields OK")


def check_standards_only_from_a_guide():
    """Standards and competencies are copied from a Budget of Work or
    Curriculum Guide or left blank: with no guide they are never asked of the
    model, and the page is told why they are blank. With one, they are the
    guide's own words."""
    fields = FIELDS + [Field("cs", "Content Standard"), Field("lc", "Learning Competency")]
    guide = ("Content Standard The learners demonstrate an understanding of basic spreadsheet "
             "formulas and functions. Learning Competency 1. create simple formulas to compute totals and averages.")
    seen = []

    def fake_call(system_instruction, parts, label):
        asked = [f.field_key for f in fields if f"- {f.field_key} (" in " ".join(parts)]
        seen.extend(asked)
        made = {"cs": "demonstrate understanding of spreadsheet formulas and functions",
                "lc": "create simple formulas to compute totals and averages",
                "objectives": "Identify the parts\nExplain their use\nValue careful work"}
        return {k: made.get(k, f"content for {k}") for k in asked}

    ai_service._call = fake_call
    final = [e for e in ai_service.generate_full_streaming({"topic": "Spreadsheets"}, fields, course_guide_text="")
             if e["type"] == "complete"][-1]
    assert "cs" not in seen and "lc" not in seen, seen
    assert not final["values"].get("cs") and not final["values"].get("lc"), final["values"]
    assert final["needs_guide"] == ["cs", "lc"] and "cs" not in final["missing"], final
    assert final["values"].get("objectives"), final["values"]  # objectives are still written
    assert "cs" not in ai_service.generate_full({"topic": "Spreadsheets"}, fields, course_guide_text="")

    final = [e for e in ai_service.generate_full_streaming({"topic": "Spreadsheets"}, fields,
                                                           course_guide_text=[("BoW", guide)])
             if e["type"] == "complete"][-1]
    assert final["needs_guide"] == [], final
    assert final["values"]["cs"] == "The learners demonstrate an understanding of basic spreadsheet formulas and functions.", final["values"]
    assert final["values"]["lc"] == "create simple formulas to compute totals and averages.", final["values"]
    print("  standards only from a guide OK")


def check_owl_options_explained():
    """Alan's options carry a line on why they fit; follow-up questions don't."""
    out = ai_service._clean_owl_reply({"reply": "Two ways in.", "choices": [
        {"type": "use", "label": "A video hook", "text": "Show a 1-minute clip.", "why": "It gets attention fast."},
        {"type": "ask", "label": "Any shorter?", "text": "Any shorter?", "why": "ignored"},
        {"type": "use", "label": "A question", "text": "Ask what they know."},
    ]})
    use, ask, bare = out["choices"]
    assert use["why"] == "It gets attention fast." and "why" not in ask and "why" not in bare, out
    print("  owl options explained OK")


def check_one_statement_and_sample():
    """A standard or competency is ONE statement even when the model copies
    two; a sample plan shapes the prompt but is never lesson details, never a
    source for the school or the standards."""
    from services import grounding
    guide = ("Content Standard The learners demonstrate an understanding of spreadsheet formulas. "
             "The learners demonstrate an understanding of charts and graphs.")
    cs = Field("cs", "Content Standard")
    two = "The learners demonstrate an understanding of spreadsheet formulas.\nThe learners demonstrate an understanding of charts and graphs."
    got = grounding.snap_to_guide({"cs": two}, [cs], guide)["cs"]
    assert got == "The learners demonstrate an understanding of spreadsheet formulas.", got

    ctx = {"topic": "Formulas", "sample_plan": "SAMPLE PLAN Rizal High School Motivation: a picture puzzle"}
    block = ai_service._lesson_block(ctx, "", "")
    assert "--- SAMPLE ---" in block and "SAMPLE PLAN Rizal" in block.split("--- SAMPLE ---")[1], block
    assert "Rizal" not in ai_service._context_block(ctx), ai_service._context_block(ctx)
    school = Field("school", "School", "text")
    kept = grounding.keep_given_logistics({"school": "Rizal High School"}, [school], ctx)
    assert kept["school"] == "", kept
    print("  one statement, sample plan OK")


def check_competency_view_and_three_objectives():
    """SNHS has "Learning Competencies/ Objectives" AND "Specific Learning
    Objectives": the first holds the competency alone (testers found the
    objectives under it too). A lesson has exactly three objectives."""
    from services import grounding
    combined = Field("learning_competencies_objectives", "Learning Competencies/ Objectives")
    specific = Field("specific_learning_objectives", "Specific Learning Objectives")
    view = grounding.competency_view([combined, specific])
    lc, obj = view
    assert lc.field_key == combined.field_key and lc.label == "Learning Competencies", lc.label
    assert grounding.is_copy_only_field(lc) and not ai_service._is_objective_field(lc)
    assert ai_service._is_objective_field(obj) and obj is specific
    assert "exactly ONE statement" in ai_service._field_directive(lc)
    # A format whose only objectives field is the combined one keeps it combined.
    alone = grounding.competency_view([combined])[0]
    assert alone is combined and ai_service._is_objective_field(alone)

    four = "At the end of the lesson, the learners are expected to:\n1. identify parts\n2. explain uses\n3. value care\n4. assemble a PC"
    got = ai_service._unnumber_objectives({"o": four}, [Field("o", "Learning Objectives")])["o"]
    assert got.split("\n") == ["At the end of the lesson, the learners are expected to:", "identify parts",
                               "explain uses", "value care"], got
    both = "Discuss ICT trends.\nAt the end of the lesson, the learners are expected to:\na\nb\nc\nd"
    got = ai_service._unnumber_objectives({alone.field_key: both}, [alone])[alone.field_key]
    assert got.split("\n") == ["Discuss ICT trends.", "At the end of the lesson, the learners are expected to:",
                               "a", "b", "c"], got
    # The TUP SDLP prints the lead-in itself (its hint says so): not written twice.
    tup = Field("lesson_objectives", "Lesson Objectives",
                ai_hint="Only the objectives: the template already prints 'At the end of the lesson, the students should be able to:'")
    assert "expected to:" not in ai_service._field_directive(tup), ai_service._field_directive(tup)
    got = ai_service._unnumber_objectives({"lesson_objectives": four}, [tup])["lesson_objectives"]
    assert got.split("\n") == ["identify parts", "explain uses", "value care"], got
    print("  competency view, three objectives OK")


def check_web_references():
    """References come from a web search: a line is kept only if its URL was
    in the search results, it is APA, and the link opens. Search trouble means
    no references, never a failed plan."""
    from services import grounding
    real = "https://www.w3schools.com/html/html_images.asp"
    answer = json.dumps({"references": [
        f"W3Schools. (n.d.). HTML images. W3Schools. {real}",
        "Made Up. (2024). A page. Nowhere. https://invented.example/page",  # not a search result
        "no apa here https://www.w3schools.com/html/",                      # not APA
    ]})
    calls = []
    real_post, real_provider, real_works = ai_service._web_search_post, ai_service.PROVIDER, grounding.page_text
    # Search results by URL and title; the second is the same site, so only one is kept.
    cited = {real: "HTML Images - W3Schools", "https://www.w3schools.com/html": "HTML Tutorial - W3Schools"}
    ai_service._web_search_post = lambda system, prompt: (calls.append(prompt), (answer, cited))[1]
    ai_service.PROVIDER = "openrouter"
    grounding.page_text = lambda url: "page text " * 200 if url in cited else ""
    ai_service._FOUND_REFERENCES.clear()
    try:
        found = ai_service.find_references({"topic": "HTML images", "subject": "ICT"})
        assert found == [f"W3Schools. (n.d.). HTML images. W3Schools. {real}"], found
        assert "HTML images" in calls[0]
        refs = Field("references", "References")
        merged = ai_service._with_web_references({"references": "DepEd. (2023). CG. https://deped.gov.ph/cg.pdf"},
                                                 [refs, Field("flow", "Flow")], {"topic": "HTML images"})
        assert merged["references"].split("\n")[0].startswith("DepEd."), merged
        assert merged["references"].split("\n")[1].startswith("W3Schools."), merged
        assert ai_service._with_web_references({}, [Field("flow", "Flow")], {"topic": "x"}) == {}

        def boom(system, prompt):
            raise RuntimeError("search down")
        ai_service._web_search_post = boom
        assert ai_service.find_references({"topic": "HTML tables"}) == []
    finally:
        ai_service._web_search_post, ai_service.PROVIDER, grounding.page_text = real_post, real_provider, real_works
        ai_service._FOUND_REFERENCES.clear()
    print("  web references OK")


def check_assessment_type():
    """The setup's assessment choice shapes the field that assesses: a quiz of
    exactly N items with an answer key, or a performance task with a rubric.
    A practice activity that "leads to" an assessment, other fields, and a
    plan whose setup never asked get no such directive."""
    evaluation = Field("evaluating_learning", "Evaluating learning")
    quiz = ai_service._grounding_directive(evaluation, {"assessment_type": "a 3-item multiple-choice quiz"})
    assert "exactly 3 items" in quiz and "Answer key" in quiz, quiz
    task = ai_service._grounding_directive(Field("assessment", "Formative Assessment"),
                                           {"assessment_type": "a performance task with a rubric"})
    assert "performance task" in task and "Rubric:" in task and "Answer key" not in task, task
    mastery = Field("developing_mastery", "Developing mastery (leads to Formative Assessment 3)")
    assert "quiz" not in ai_service._grounding_directive(mastery, {"assessment_type": "a 3-item multiple-choice quiz"})
    assert "quiz" not in ai_service._grounding_directive(Field("flow", "Flow"), {"assessment_type": "a 3-item multiple-choice quiz"})
    # Setup never asked: no quiz or task, only the tie to the objectives.
    unasked = ai_service._grounding_directive(evaluation, {})
    assert "quiz" not in unasked and "Rubric:" not in unasked and "learning objectives" in unasked, unasked
    # 5, 10, 15 or 20 items: a two-digit count is read whole.
    twenty = {"assessment_type": "a 20-item multiple-choice quiz"}
    assert "exactly 20 items" in ai_service._grounding_directive(evaluation, twenty)
    # The quiz comes back whole, numbered and lettered; other fields keep the ceilings.
    quiz_text = "\n".join(f"{n}. Question {n}?\na. one\nb. two\nc. three\nd. four" for n in range(1, 21))
    quiz_text += "\nAnswer key:\n" + "\n".join(f"{n}. b" for n in range(1, 21))
    flow = Field("flow", "Flow")
    out = ai_service._trim({"evaluating_learning": quiz_text, "flow": "\n".join(f"Step {n}" for n in range(1, 21))},
                           [evaluation, flow], context=twenty)
    lines = out["evaluating_learning"].split("\n")
    assert len(lines) == 121 and lines[0] == "1. Question 1?" and lines[1] == "a. one", lines[:3]
    assert lines[-1] == "20. b" and "Answer key:" in lines, lines[-3:]
    assert len(out["flow"].split("\n")) == ai_service._MAX_LIST_ITEMS
    # Without a quiz in the setup, the evaluation field keeps the usual ceiling.
    plain = ai_service._trim({"evaluating_learning": quiz_text}, [evaluation], context={})
    assert len(plain["evaluating_learning"].split("\n")) == ai_service._MAX_LIST_ITEMS
    print("  assessment type OK")


check_assessment_type()
check_web_references()
check_competency_view_and_three_objectives()
check_one_statement_and_sample()
check_owl_options_explained()
check_standards_only_from_a_guide()
check_subset_only()
check_missing_counts_requested_only()
check_absent_means_everything()
check_unknown_keys_ignored()
check_empty_selection()
check_select_fields_helper()
print("generate selection OK")
