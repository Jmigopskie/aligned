"""Self-check for the fixes from Batch 1's final review:
- a regenerate gives Alan the parts that stay, so the new ones fit them;
- a locked part with a chosen direction is coached, not told to write;
- the coherence verdict follows the model's own flag and matches parts by label;
- the coherence check and the regenerate context are size-capped;
- Word XML children stay in schema order (font size before language; table
  borders before tblLook);
- a regenerate the student walks away from (tab closed) is refunded.

No provider or network. Run it directly: `python test_batch1_review_fixes.py`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

from services import ai_service, docx_service  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea", locked=False):
        self.field_key, self.label, self.field_type = field_key, label, field_type
        self.ai_hint, self.locked, self.parts_list = None, locked, []


prompts = []


def stub(reply):
    def call(system, parts, label):
        prompts.append(system + "\n" + "\n".join(parts))
        return reply
    return call


def check_regenerate_context():
    real = ai_service._call
    try:
        ai_service._call = stub({"evaluation": "1. Which part ...?"})
        fields = [Field("objectives", "Objectives", "list"), Field("evaluation", "Evaluation")]
        written = {"objectives": "identify the parts of a measuring tape"}
        ai_service.generate_full({"topic": "Tape"}, fields, include_keys=["evaluation"], written=written)
        assert "identify the parts of a measuring tape" in prompts[-1] and "stay as they are" in prompts[-1], prompts[-1][-500:]
        prompts.clear()
        events = list(ai_service.generate_full_streaming({"topic": "Tape"}, fields, include_keys=["evaluation"],
                                                         written=written))
        assert events[-1]["type"] == "complete" and all("identify the parts of a measuring tape" in p for p in prompts), prompts
        assert "objectives" not in events[-1]["values"], "the parts that stay are context, not output"
        # Capped: one huge part can't flood the prompt.
        block = ai_service._written_block({"a": "x" * 50000, "b": ["y" * 50000]})
        assert len(block) < ai_service._WRITTEN_BUDGET + 500, len(block)
    finally:
        ai_service._call = real
    print("  regenerate sees the parts that stay OK")


def check_locked_direction():
    real = ai_service._call
    try:
        ai_service._call = stub({"reply": "Think about what to check.", "choices": []})
        ai_service.owl_chat({"topic": "Tape"}, Field("evaluation", "Evaluation", locked=True), {}, "", [],
                            "Go with: Quiz", direction={"label": "Quiz", "text": "A short quiz."})
        assert "Write the complete part" not in prompts[-1], prompts[-1][-600:]
        assert "Quiz" in prompts[-1] and "coach" in prompts[-1].lower(), prompts[-1][-600:]
    finally:
        ai_service._call = real
    print("  a locked part with a direction is coached OK")


def check_coherence_verdict():
    real = ai_service._call
    fields = [Field("objectives", "Objectives", "list"), Field("evaluation", "V. Evaluation")]
    values = {"objectives": "identify", "evaluation": "1. Q?"}
    try:
        # The model names the part by its label instead of its key.
        ai_service._call = stub({"coherent": False, "summary": "Objective 1 isn't assessed.", "issues": [
            {"part_key": "V. Evaluation", "problem": "Nothing checks it.", "fix": "Add an item."}]})
        out = ai_service.check_coherence({}, fields, values, "full")
        assert [i["part_key"] for i in out["issues"]] == ["evaluation"] and out["coherent"] is False, out
        # The model says it doesn't line up but names no part we know: not "coherent".
        ai_service._call = stub({"coherent": False, "summary": "They drift.", "issues": [
            {"part_key": "made_up", "problem": "x", "fix": "y"}]})
        assert ai_service.check_coherence({}, fields, values, "full")["coherent"] is False
        # Capped: a huge plan is cut before it reaches the model.
        ai_service._call = stub({"coherent": True, "summary": "ok", "issues": []})
        ai_service.check_coherence({}, fields, {"objectives": "z" * 200000, "evaluation": "q"}, "full")
        assert len(prompts[-1]) < 60000, len(prompts[-1])
    finally:
        ai_service._call = real
    print("  coherence verdict and size cap OK")


def check_xml_order():
    doc = Document()
    row = doc.add_table(rows=1, cols=2).rows[0]
    label = row.cells[0].paragraphs[0].add_run("School: ")
    label.font.size = docx_service.Pt(12)
    blank = row.cells[1].paragraphs[0]._p
    mark = OxmlElement("w:rPr")
    for tag, attrs in (("w:rFonts", {"w:ascii": "Arial"}), ("w:lang", {"w:val": "en-US"})):
        el = OxmlElement(tag)
        for k, v in attrs.items():
            el.set(qn(k), v)
        mark.append(el)
    blank.get_or_add_pPr().append(mark)
    docx_service._set_paragraph_text(doc, blank, "Rizal")
    tags = [c.tag.split("}")[1] for c in blank.find(qn("w:r")).find(qn("w:rPr"))]
    assert tags.index("sz") < tags.index("lang") and tags[0] == "rFonts", tags

    doc = Document()
    for line in ("A | B | C", "x | y | z"):
        doc.add_paragraph(line)
    docx_service.pipe_rows_to_tables(doc)
    tbl_pr = doc.tables[0]._tbl.tblPr
    children = [c.tag.split("}")[1] for c in tbl_pr]
    if "tblLook" in children:
        assert children[-1] == "tblLook" and children.index("tblBorders") < children.index("tblLook"), children
    print("  Word XML in schema order OK")


def check_refund_on_disconnect():
    from app import create_app
    from extensions import db
    from models.format import FormatField, LessonPlanFormat
    from models.points import Build
    from models.section import Section, SectionMembership
    from models.user import User
    from datetime import datetime

    def slow_stream(context, fields, course_guide_text="", include_keys=None, course_guide_citation="", written=None):
        yield {"type": "section_start", "section": "x", "index": 1, "total": 1}
        yield {"type": "section_done", "section": "x", "index": 1, "total": 1, "values": {"motivation": "A game."}}
        yield {"type": "complete", "values": {"motivation": "A game."}, "missing": [], "missing_labels": []}

    app = create_app()
    app.config.update(TESTING=True)
    real = ai_service.generate_full_streaming
    with app.app_context():
        tina = User(full_name="Tina", email="tina.fix@example.test", role="teacher")
        ana = User(full_name="Ana", email="ana.fix@example.test", role="student", points=20)
        for u in (tina, ana):
            u.set_password("password123")
        db.session.add_all([tina, ana])
        db.session.commit()
        sec = Section(teacher_id=tina.id, name="7-B", join_code="FIX001")
        db.session.add(sec)
        db.session.commit()
        db.session.add(SectionMembership(section_id=sec.id, student_id=ana.id))
        fmt = LessonPlanFormat(name="Plain", owner_id=tina.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add(FormatField(format_id=fmt.id, field_key="motivation", label="Motivation"))
        db.session.add(Build(student_id=ana.id, run_key="fix-run", points=30, completed_at=datetime.utcnow()))
        db.session.commit()
        ana_id, fid = ana.id, fmt.id
        try:
            ai_service.generate_full_streaming = slow_stream
            client = app.test_client()
            with client.session_transaction() as s:
                s["user_id"] = ana_id
            res = client.post("/api/generate/full-stream", buffered=False, json={
                "format_id": fid, "include_keys": ["motivation"], "context": {"topic": "x"}, "run_key": "fix-run",
                "written_values": {"objectives": "identify"}})
            assert res.status_code == 200
            stream = iter(res.response)
            next(stream)          # the first event arrives ...
            res.close()           # ... and the student closes the tab
            db.session.expire_all()
            assert db.session.get(User, ana_id).points == 20, db.session.get(User, ana_id).points
        finally:
            ai_service.generate_full_streaming = real
    print("  a regenerate walked away from is refunded OK")


def main():
    check_regenerate_context()
    check_locked_direction()
    check_coherence_verdict()
    check_xml_order()
    check_refund_on_disconnect()
    print("batch 1 review fixes OK")


if __name__ == "__main__":
    main()
