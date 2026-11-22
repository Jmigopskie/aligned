"""Self-check for the Word export's font (user report 2026-11-22: "when
exporting in docx, the font changes"). A value written into a blank that has
no runs (a label | empty-cell row) used to get a bare run, which falls back to
the document default font and size instead of the format's. Now it takes the
blank's own paragraph-mark formatting, and any font or size still missing from
the nearest text before it (the label), without the label's bold.

Run it directly: `python test_export_font.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

from services import docx_service  # noqa: E402


def font_of(run):
    rpr = run._r.find(qn("w:rPr"))
    rf = rpr.find(qn("w:rFonts")) if rpr is not None else None
    sz = rpr.find(qn("w:sz")) if rpr is not None else None
    bold = rpr.find(qn("w:b")) if rpr is not None else None
    return (rf.get(qn("w:ascii")) if rf is not None else None,
            sz.get(qn("w:val")) if sz is not None else None,
            bold is not None and bold.get(qn("w:val")) not in ("0", "false"))


def template():
    """A label | blank row like the DLP's: the label run is Arial Narrow 12pt
    bold; the blank cell has only a paragraph mark set to Arial Narrow."""
    doc = Document()
    row = doc.add_table(rows=1, cols=2).rows[0]
    label = row.cells[0].paragraphs[0].add_run("School: ")
    label.font.name, label.bold = "Arial Narrow", True
    label.font.size = docx_service.Pt(12)
    blank = row.cells[1].paragraphs[0]._p
    ppr = blank.get_or_add_pPr()
    mark = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "Arial Narrow")
    fonts.set(qn("w:hAnsi"), "Arial Narrow")
    mark.append(fonts)
    ppr.append(mark)
    return doc, row.cells[1].paragraphs[0]


def main():
    doc, blank = template()
    docx_service._set_paragraph_text(doc, blank._p, "Rizal High School")
    assert font_of(blank.runs[0]) == ("Arial Narrow", "24", False), font_of(blank.runs[0])
    print("  a plain value takes the blank's font and the label's size, not its bold OK")

    doc, blank = template()
    lines = docx_service.parse_rich_value("<b>Rizal</b> High School")
    docx_service._set_paragraph_rich(doc, blank._p, lines[0])
    fonts = [font_of(r)[:2] for r in blank.runs]
    assert fonts == [("Arial Narrow", "24"), ("Arial Narrow", "24")], fonts
    assert blank.runs[0].bold and not blank.runs[1].bold
    print("  a formatted value keeps its own bold, in the format's font OK")

    # A blank with nothing to go by at all still writes (document default).
    doc = Document()
    p = doc.add_paragraph()
    docx_service._set_paragraph_text(doc, p._p, "plain")
    assert p.text == "plain"
    print("export font OK")


if __name__ == "__main__":
    main()
