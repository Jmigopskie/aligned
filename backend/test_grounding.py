"""Self-check for services/grounding.py against a real DepEd Budget of Work.

Curriculum fields must come out as the guide's own wording (a paraphrase is
snapped back, a clipped line restored, an invented line removed), and a
reference survives only with a link that opens and isn't on a private network.

Run it directly: `venv/Scripts/python test_grounding.py`. Offline: the one
network call is stubbed.
"""
import os
import re
import sys
from types import SimpleNamespace as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import grounding

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = open(os.path.join(HERE, "builtin", "course_guides", "bow-g7-tle-ict.txt"), encoding="utf-8").read()

CONTENT = ("Demonstrate an understanding of ICT sectors, as well as the potential career and business "
           "opportunities these sectors offer in relation to their chosen career in the future.")
PERFORMANCE = "The learners convert number systems in practical scenarios."
COMPETENCY = "Discuss the emerging trends and issues in ICT."

content = F(field_key="content_standard", label="Content Standard")
competency = F(field_key="lc", label="Learning Competencies")
objectives = F(field_key="obj", label="Learning Objectives")
refs = F(field_key="refs", label="References")
procedure = F(field_key="proc", label="Procedure")

assert grounding.is_verbatim_field(content) and grounding.is_verbatim_field(objectives)
assert grounding.is_reference_field(refs) and not grounding.is_verbatim_field(procedure)

values = {
    # Paraphrased and run into the performance standard as one paragraph.
    "content_standard": "Demonstrates understanding of the ICT sectors and the career and business "
                        "opportunities they offer for their future career. Learners convert number systems "
                        "in practical scenarios.",
    # Clipped by a word limit, plus a competency the guide doesn't have.
    "lc": "Discuss the emerging trends and issues\nDesign a mobile game using Python and Unity engine",
    "obj": ["At the end of the lesson, the learners are expected to:\nDiscuss the emerging trends and issues in ICT.", ""],
    "proc": "Anything goes here",
}
out = grounding.snap_to_guide(values, [content, competency, objectives, procedure], GUIDE)
assert out["content_standard"].split("\n") == [CONTENT, PERFORMANCE], out["content_standard"]
assert out["lc"] == COMPETENCY, out["lc"]
assert out["obj"][0] == "At the end of the lesson, the learners are expected to:\n" + COMPETENCY, out["obj"]
assert out["obj"][1] == ""
assert out["proc"] == "Anything goes here", "only curriculum fields are touched"
# No guide: nothing to copy from, so values are left alone.
assert grounding.snap_to_guide(values, [competency], "") == values

# Page headers that land mid-sentence don't end up in a copied statement.
assert "Page 1 of 9" not in grounding.tidy_guide(GUIDE)

# APA citation of the guide, with the year read from the document.
cite = grounding.guide_citation("[G7] TLE: ICT, Three-Term Budget of Work",
                                "https://drive.google.com/file/d/1DFM7HaUXCJEgJGoc_rvk9H1M7cGnv17y/view", GUIDE)
assert cite == ("Department of Education. (2026). [G7] TLE: ICT, Three-Term Budget of Work [PDF]. "
                "https://drive.google.com/file/d/1DFM7HaUXCJEgJGoc_rvk9H1M7cGnv17y/view"), cite
assert "(2023)" in grounding.guide_citation("MATATAG EPP/TLE Curriculum Guide",
                                            "https://www.deped.gov.ph/wp-content/uploads/MATATAG-EPP_TLE-CG-2023-Grades-4-10-1.pdf")
assert grounding.guide_citation("Uploaded guide", None) == ""

# Private, loopback and non-http addresses are never fetched.
for bad in ("http://127.0.0.1:5000/api/me", "http://10.0.0.5/", "http://localhost/", "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/"):
    assert not grounding._public_host(bad), bad

# References: only lines whose link opens, guide citation first, no duplicate.
grounding.link_works = lambda url: "good" in url
raw = "\n".join([
    "Department of Education. (2026). Same guide. https://drive.google.com/file/d/1DFM7HaUXCJEgJGoc_rvk9H1M7cGnv17y/view",
    "Cisco. (2020). Networking basics. Cisco Networking Academy. https://good.example.org/networking",
    "Made Up. (2021). Fake book. https://dead.example.org/x",
    "Some Textbook (2019) with no link",
])
kept = grounding.keep_working_links({"refs": raw, "proc": "x"}, [refs, procedure], cite)
assert kept["refs"].split("\n") == [
    cite, "Cisco. (2020). Networking basics. Cisco Networking Academy. https://good.example.org/networking",
], kept["refs"]
assert kept["proc"] == "x"

# APA 7 only: mechanical slips are fixed, a line missing author/year/title goes.
assert grounding.to_apa("Smith, J. (2020). Networking basics. Retrieved from https://good.example.org/net.") == \
    "Smith, J. (2020). Networking basics. https://good.example.org/net"
assert grounding.to_apa("Department of Education. (n.d.). K to 12 curriculum guide. https://good.example.org/k12")
assert grounding.to_apa("Cruz, J. A. (2023, March 5). Emerging trends in ICT. Rappler. https://good.example.org/x")
for not_apa in ("Networking basics https://good.example.org/net", "https://good.example.org/net",
                "Some Textbook (2019). Learning ICT."):
    assert grounding.to_apa(not_apa) == "", not_apa
kept = grounding.keep_working_links({"refs": "Networking basics https://good.example.org/net"}, [refs], cite)
assert kept["refs"] == cite, "a working link that isn't an APA reference is still dropped"
assert grounding.keep_working_links({"refs": ["https://dead.example.org"]}, [refs], cite)["refs"] == [cite]
# Weekly: the guide is cited once, on the first day, not repeated every day.
weekly = grounding.keep_working_links({"refs": ["", "", ""]}, [refs], cite)["refs"]
assert weekly == [cite, "", ""], weekly

# Session logistics: only what the teacher entered survives; an invented
# school, date or time is blanked. "Time Allotment" is lesson length, not one.
school = F(field_key="school", label="School")
date = F(field_key="date", label="Date")
grade_section = F(field_key="gs", label="Grade and Section")
allot = F(field_key="ta", label="Time Allotment")
assert grounding.is_logistics_field(school) and grounding.is_logistics_field(date)
assert not grounding.is_logistics_field(allot) and not grounding.is_logistics_field(competency)
ctx = {"teacher_name": "John Mark V. Aguirre", "grade_level": "Grade 7", "section": "Campos", "topic": "ICT"}
got = grounding.keep_given_logistics(
    {"school": "Philippine National High School", "date": "October 15, 2026",
     "gs": "Grade 7 - Campos", "ta": "60 minutes", "lc": COMPETENCY},
    [school, date, grade_section, allot, competency], ctx)
assert got == {"school": "", "date": "", "gs": "Grade 7 - Campos", "ta": "60 minutes", "lc": COMPETENCY}, got

# Objectives are unpacked from the competency (DO 016), never snapped: matching
# them once swapped an objective for a look-alike Budget of Work activity line.
objs = "At the end of the lesson, the learners are expected to:\n1. identify traits of successful ICT entrepreneurs\n2. explain one trait"
assert grounding.snap_to_guide({"o": objs}, [F(field_key="o", label="Learning Objectives")], GUIDE)["o"] == objs
# In a combined field only the competency line is held to the guide's wording.
combined = "Discuss the emerging trends and issues\n1. list two trends\n2. explain one issue\n3. value safe use"
got = grounding.snap_to_guide({"c": combined}, [F(field_key="c", label="Learning Competencies / Objectives")], GUIDE)["c"]
assert got.split("\n") == [COMPETENCY, "1. list two trends", "2. explain one issue", "3. value safe use"], got

# Objectives leave the server un-numbered under a plain lead-in, so the page
# bullets them (ILAW's own hint asks for numbers; the teacher wants bullets).
from services import ai_service as _ais  # noqa: E402
lo = F(field_key="lo", label="Learning Objectives", field_type="weekly", ai_hint="numbered", parts_list=["Mon"])
got = _ais._unnumber_objectives({"lo": ["At the end of the lesson, the learners are expected to:\n1. identify a\n2) explain b\n3. value c"]}, [lo])
assert got["lo"] == ["At the end of the lesson, the learners are expected to:\nidentify a\nexplain b\nvalue c"], got
assert _ais._unnumber_objectives({"x": "1. step"}, [F(field_key="x", label="Procedure", field_type="list", ai_hint=None)])["x"] == "1. step"

# A numbered list's lead-in line is not numbered as item 1.
from services import ai_limits as _lim  # noqa: E402
num = _lim.clean_value("At the end of the lesson, the learners are expected to:\n1. identify\n2. explain\n3. value",
                       "list", max_items=8, max_item_words=40, max_sentences=6, max_prose_words=140)
assert num.split("\n") == ["At the end of the lesson, the learners are expected to:", "1. identify", "2. explain",
                           "3. value"], num

# Completeness, checked after every batch: every weekly day filled, and at
# least three objectives (four lines when the field also holds the competency).
from services import ai_service as _ai  # noqa: E402
wk = F(field_key="flow", label="Flow", field_type="weekly", parts_list=["Mon", "Tue"], ai_hint=None)
assert not _ai._field_complete(wk, ["Did things.", ""])
assert _ai._field_complete(wk, ["Did things.", "Did more."])
objf = F(field_key="lo", label="Learning Objectives", field_type="textarea", ai_hint=None)
assert not _ai._field_complete(objf, "At the end of the lesson, the learners are expected to:\n1. Identify\n2. Explain")
assert _ai._field_complete(objf, "At the end of the lesson, the learners are expected to:\n1. Identify\n2. Explain\n3. Value")
combo = F(field_key="lco", label="Learning Competencies / Objectives", field_type="textarea", ai_hint=None)
assert not _ai._field_complete(combo, "Discuss X.\n1. a\n2. b")
assert _ai._field_complete(combo, "Discuss X.\n1. a\n2. b\n3. c")
integ = F(field_key="i", label="Opportunities for Integration and Contextualization", field_type="text", ai_hint=None)
assert _ai._incomplete({"i": "N/A"}, [integ]) == [], "integration may honestly be N/A"

# The curriculum guide: its numbered competency is copied without the number,
# and its run-on content standard comes out as its own statement.
os.environ.setdefault("DATABASE_URL", "sqlite://")
from services import ai_service  # noqa: E402

CG = open(os.path.join(HERE, "builtin", "course_guides", "matatag-epp-tle-cg-grades-4-10.txt"),
          encoding="utf-8").read()
assert len(CG) > 200000, "the full guide ships, not the old 20,000-character cut"
assert grounding.snap_text("Perform food preservation with safety precautions.", CG) == \
    "perform food preservation with precautions"
assert grounding.snap_text("Demonstrates understanding of food preservation and processing", CG) == \
    "demonstrate an understanding of the food preservation and food processing"

# Topic search: only the section that teaches the topic is sent, with its
# standards, rather than the guide read from its first page.
excerpt = re.sub(r"\s+", " ", ai_service.guide_excerpt(CG, {"topic": "Food preservation"}))
assert "Republic of the Philippines" not in excerpt, excerpt[:200]
for statement in ("demonstrate an understanding of the food preservation and food processing",
                  "perform food preservation with precautions",
                  "The learners preserve and sell products with safety precautions."):
    assert statement in excerpt, statement
assert len(excerpt) < 9000, len(excerpt)
bow = re.sub(r"\s+", " ", ai_service.guide_excerpt(GUIDE, {"topic": "Emerging trends and issues in ICT"}))
assert COMPETENCY in bow and PERFORMANCE in bow and len(bow) < len(grounding.tidy_guide(GUIDE))

# Budget of Work + Curriculum Guide picked together: each is searched for the
# topic on its own share and labelled, and the verbatim check sees both.
excerpt, full = ai_service._guide_inputs(
    [("[G6] TLE: ICT, Three-Term Budget of Work", GUIDE), ("MATATAG EPP/TLE Curriculum Guide", CG)],
    {"topic": "Food preservation"})
assert "[From: [G6] TLE: ICT, Three-Term Budget of Work]" in excerpt and "[From: MATATAG EPP/TLE Curriculum Guide]" in excerpt
assert len(excerpt) <= ai_service.GUIDE_BUDGET + 200, len(excerpt)
assert "perform food preservation with precautions" in re.sub(r"\s+", " ", excerpt)
assert grounding.snap_text("Discuss the emerging trends and issues in ICT", full) == COMPETENCY
assert grounding.snap_text("perform food preservation with precautions", full) == "perform food preservation with precautions"
# One guide as plain text still works the way it always did.
assert ai_service._guide_inputs(GUIDE, {"topic": "Emerging trends"})[1] == GUIDE
assert ai_service._guide_inputs([], {}) == ("", "")

print("grounding OK")
