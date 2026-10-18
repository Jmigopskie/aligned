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
assert grounding.keep_working_links({"refs": ["https://dead.example.org"]}, [refs], cite)["refs"] == [cite]

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

print("grounding OK")
