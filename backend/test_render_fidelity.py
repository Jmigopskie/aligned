"""Self-check for the document view's fidelity to Word.

The document a teacher sees is HTML drawn from the format's .docx. It has to
look like the file does in Word: the page's true size, the file's fonts and
spacing, Word's table borders and cell margins, list numbers, and pictures.
Each check builds a small .docx holding just the property under test and reads
the rendered HTML back.

Run it directly: `venv/Scripts/python test_render_fidelity.py`.
"""
import io
import os
import re
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt

from services import docx_service

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads",
                      "T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx")


def _save(doc):
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


def _render(doc):
    path = _save(doc)
    try:
        return docx_service.render_reference_html(path)["html"]
    finally:
        os.remove(path)


def _p_style(html, text):
    """The style attribute of the paragraph whose first text is `text`."""
    match = re.search(r'<p class="lp-p[^"]*" style="([^"]*)"[^>]*>(?:<span[^>]*>)?' + re.escape(text), html)
    assert match, (text, html[:600])
    return match.group(1)


def check_page():
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(13), Inches(8.5)
    section.left_margin = section.right_margin = Inches(0.5)
    section.top_margin = section.bottom_margin = Inches(0.5)
    doc.add_paragraph("x")
    html = _render(doc)
    assert html.startswith('<div class="lp-doc" style="width:936pt;padding:36pt 36pt 36pt 36pt;'), html[:200]
    assert 'data-page-width="936"' in html
    print("  page OK")


def check_text_cascade():
    doc = Document()
    doc.styles["Normal"].font.name = "Arial Narrow"
    doc.styles["Normal"].font.size = Pt(9)
    p = doc.add_paragraph()
    p.add_run("plain")
    big = p.add_run("big")
    big.font.size = Pt(14)
    big.bold = True
    doc.add_paragraph().add_run("junk").font.name = "Type3 (8 0 R)"
    spaced = doc.add_paragraph("spaced").paragraph_format
    spaced.space_before, spaced.space_after = Pt(6), Pt(3)
    spaced.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spaced.line_spacing = Pt(14)
    hanging = doc.add_paragraph("hanging").paragraph_format
    hanging.left_indent, hanging.first_line_indent = Pt(36), Pt(-18)
    html = _render(doc)

    # Style (Normal) under direct formatting, fonts and sizes exact.
    assert "<span style=\"font-family:'Arial Narrow',sans-serif;font-size:9pt\">plain</span>" in html, html
    assert "font-size:14pt;font-weight:700\">big</span>" in html, html
    # A converted file's unnamed PDF font shows as the source PDFs' Arial.
    assert "<span style=\"font-family:'Arial',sans-serif;font-size:9pt\">junk</span>" in html, html
    style = _p_style(html, "spaced")
    assert "margin-top:6pt;margin-bottom:3pt" in style and "line-height:14pt" in style, style
    style = _p_style(html, "hanging")
    assert "margin-left:36pt" in style and "text-indent:-18pt" in style, style
    # No invented typography: the old heading heuristic's classes are gone.
    assert "lp-heading" not in html and "lp-bold" not in html
    print("  text cascade OK")


def main():
    check_page()
    check_text_cascade()
    print("render fidelity OK")


if __name__ == "__main__":
    main()
