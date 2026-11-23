"""Self-check for the export's spacing (user report 2026-11-24: tables and
text ran to the top and bottom of the paper, and the Word file didn't look
like the preview):
- a page has at least 0.75" at its top and bottom, in Word and the preview;
- every answer gets the same spacing: 3pt above its first line and below its
  last, none between, 1.15 lines, no list numbering or bold carried over
  from a label, flush left in a table cell; the preview's slot the same;
- "• • item" prints with one bullet;
- the teacher's own edited document text is not touched.

Run it directly: `python test_export_layout.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Inches  # noqa: E402

from services import docx_layout, docx_service  # noqa: E402


def spacing(p_el):
    sp = p_el.pPr.find(qn("w:spacing"))
    return {k.split("}")[1]: v for k, v in sp.attrib.items()}


def main():
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Inches(0)
    row = doc.add_table(rows=1, cols=2).rows[0]
    label = row.cells[0].paragraphs[0]
    label.add_run("Objectives").bold = True
    blank = row.cells[1].paragraphs[0]._p
    ppr = blank.get_or_add_pPr()
    sp, ind, num = OxmlElement("w:spacing"), OxmlElement("w:ind"), OxmlElement("w:numPr")
    sp.set(qn("w:before"), "896")        # a PDF conversion's leftovers
    sp.set(qn("w:line"), "187")
    ind.set(qn("w:left"), "464")
    ppr.append(num)
    ppr.append(sp)
    ppr.append(ind)
    edited = doc.add_paragraph("A heading the teacher reworded")._p

    docx_service._fill_paragraphs(doc, row.cells[1].paragraphs, "• • identify tools\n• measure lengths\n• value care")
    docx_service._apply_paragraph_edit(doc, edited, {"text": "Reworded heading"})
    docx_service.tidy_value_paragraphs(doc)
    docx_service.ensure_page_margins(doc)

    cell = row.cells[1].paragraphs
    assert [p.text for p in cell] == ["• identify tools", "• measure lengths", "• value care"], [p.text for p in cell]
    assert spacing(cell[0]._p) == {"before": "60", "after": "0", "line": "276", "lineRule": "auto"}, spacing(cell[0]._p)
    assert spacing(cell[1]._p)["before"] == "0" and spacing(cell[1]._p)["after"] == "0"
    assert spacing(cell[2]._p)["after"] == "60"
    assert cell[0]._p.pPr.find(qn("w:numPr")) is None and cell[0]._p.pPr.find(qn("w:ind")) is None
    # Schema order: spacing before ind/jc/rPr, or Word ignores it.
    tags = [c.tag.split("}")[1] for c in cell[0]._p.pPr]
    assert tags.index("spacing") == len(tags) - 1 or all(
        t not in ("ind", "jc", "rPr") for t in tags[:tags.index("spacing")]), tags
    assert edited.pPr is None or edited.pPr.find(qn("w:spacing")) is None, "the teacher's own text was re-spaced"
    assert all(s.top_margin >= Inches(0.75) - 1 and s.bottom_margin >= Inches(0.75) - 1 for s in doc.sections)
    print("  answers spaced alike, flush in cells, one bullet; margins at least 0.75in OK")

    # The preview draws the same: the page's margins and the slot's spacing.
    layout = docx_layout.Layout(doc)
    page_css, _ = layout.page()
    assert "padding:54pt" in page_css.replace(" ", "")[:40] or "padding:54pt" in page_css, page_css
    slot = layout.slot_css(blank)
    assert "padding-top:3pt" in slot and "padding-bottom:3pt" in slot and "line-height" in slot, slot
    assert "margin-left" not in slot, slot   # flush in a cell, like the export
    print("  preview page and answer slot match the export OK")
    print("export layout OK")


if __name__ == "__main__":
    main()
