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


def check_tables():
    doc = Document()
    grid = doc.add_table(rows=2, cols=2)
    grid.style = doc.styles["Table Grid"]
    grid.cell(0, 0).text = "A"
    tc_pr = grid.cell(1, 1)._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml('<w:tcMar %s><w:top w:w="100" w:type="dxa"/></w:tcMar>' % nsdecls("w")))
    tc_pr.append(parse_xml('<w:vAlign %s w:val="center"/>' % nsdecls("w")))
    grid.rows[0]._tr.get_or_add_trPr().append(
        parse_xml('<w:trHeight %s w:val="400" w:hRule="exact"/>' % nsdecls("w")))
    plain = doc.add_table(rows=1, cols=1)
    plain.cell(0, 0).text = "B"
    converted = doc.add_table(rows=1, cols=1)
    converted.cell(0, 0).text = "C"
    # PDF-converted files write colours with a "#" and sizes as "8.0".
    converted.cell(0, 0)._tc.get_or_add_tcPr().append(parse_xml(
        '<w:tcBorders %s><w:top w:val="single" w:sz="8.0" w:color="#1F4E79"/></w:tcBorders>' % nsdecls("w")))
    # Converted files write indents like "730.0"; still read, not dropped.
    plain._tbl.tblPr.append(parse_xml('<w:tblInd %s w:w="730.0" w:type="dxa"/>' % nsdecls("w")))
    html = _render(doc)
    tables = re.findall(r"<table.*?</table>", html, re.S)
    cells = re.findall(r'<td class="lp-td" style="([^"]*)"', tables[0])

    # Table Grid: outer borders on the table's edge, insideH/insideV between.
    assert "border-top:0.5pt solid #000000" in cells[0] and "border-right:0.5pt solid #000000" in cells[0], cells[0]
    # Word's default cell margins (Normal Table: 0.075in left and right).
    assert "padding:0pt 5.4pt 0pt 5.4pt" in cells[0], cells[0]
    # An exact row height is a minimum on screen, so typing can grow the row.
    assert '<tr style="height:20pt">' in tables[0], tables[0][:300]
    assert "padding:5pt 5.4pt 0pt 5.4pt" in cells[-1] and "vertical-align:middle" in cells[-1], cells[-1]
    assert re.search(r'<col style="width:[0-9.]+pt">', tables[0]), tables[0][:300]
    # No border in the file: none drawn (no fallback grid).
    plain_cell = re.search(r'<td class="lp-td" style="([^"]*)"', tables[1]).group(1)
    assert "border-top:none" in plain_cell and "border-left:none" in plain_cell, plain_cell
    assert "margin-left:36.5pt" in tables[1], tables[1][:300]
    converted_cell = re.search(r'<td class="lp-td" style="([^"]*)"', tables[2]).group(1)
    assert "border-top:1pt solid #1F4E79" in converted_cell, converted_cell
    print("  tables OK")


def check_lists():
    doc = Document()
    numbering = doc.part.numbering_part.element
    numbering.append(parse_xml(
        '<w:abstractNum %s w:abstractNumId="90">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%%1."/>'
        '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>'
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%%2."/>'
        '<w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>' % nsdecls("w")))
    numbering.append(parse_xml(
        '<w:abstractNum %s w:abstractNumId="91"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:numFmt w:val="bullet"/><w:lvlText w:val=""/></w:lvl></w:abstractNum>' % nsdecls("w")))
    numbering.append(parse_xml('<w:num %s w:numId="90"><w:abstractNumId w:val="90"/></w:num>' % nsdecls("w")))
    numbering.append(parse_xml('<w:num %s w:numId="91"><w:abstractNumId w:val="91"/></w:num>' % nsdecls("w")))

    def listed(text, num_id, ilvl=0):
        p = doc.add_paragraph(text)
        p._p.get_or_add_pPr().append(parse_xml(
            '<w:numPr %s><w:ilvl w:val="%d"/><w:numId w:val="%s"/></w:numPr>' % (nsdecls("w"), ilvl, num_id)))

    for text, ilvl in (("one", 0), ("sub a", 1), ("sub b", 1), ("two", 0), ("sub again", 1)):
        listed(text, "90", ilvl)
    listed("dot", "91")
    html = _render(doc)

    # A bullet with no hanging indent keeps a space for Word's tab after it.
    assert re.findall(r'data-marker="([^"]*)"', html) == ["1.", "a.", "b.", "2.", "a.", "• "], \
        re.findall(r'data-marker="([^"]*)"', html)
    # The marker hangs in the indent and is not text in the paragraph, so an
    # editor reading the paragraph back never saves "1." into the document.
    first = re.search(r'<p class="lp-p" style="([^"]*)" data-marker="1\."[^>]*>(.*?)</p>', html)
    assert first and "--lp-marker-w:18pt" in first.group(1) and "text-indent:-18pt" in first.group(1), html[:800]
    assert not re.sub(r"<[^>]+>", "", first.group(2)).startswith("1."), first.group(2)
    print("  lists OK")


def _png():
    """A valid one-pixel PNG, built here so the test carries no binary file."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _make_floating(r_el, x_emu=12700, relative="column"):
    """Turn an inline picture into a square-wrapped one, x_emu from `relative`."""
    inline = r_el.find(".//" + qn("wp:inline"))
    anchor = parse_xml(
        '<wp:anchor %s distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="1" '
        'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="%s"><wp:posOffset>%d</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        '</wp:anchor>' % (nsdecls("wp"), relative, x_emu))
    for child in list(inline):
        anchor.append(child)
        if child.tag == qn("wp:extent"):
            anchor.append(parse_xml('<wp:wrapSquare %s wrapText="bothSides"/>' % nsdecls("wp")))
    inline.getparent().replace(inline, anchor)


def check_pictures():
    doc = Document()
    doc.add_picture(io.BytesIO(_png()), width=Pt(40), height=Pt(20))
    floating = doc.add_paragraph("Text that wraps beside the picture.").add_run()
    floating.add_picture(io.BytesIO(_png()), width=Pt(30), height=Pt(30))
    _make_floating(floating._r)
    broken = doc.add_paragraph().add_run()
    broken.add_picture(io.BytesIO(_png()), width=Pt(10), height=Pt(10))
    broken._r.find(".//" + qn("a:blip")).set(qn("r:embed"), "rIdMissing")
    html = _render(doc)
    styles = re.findall(r'<img src="data:image/png;base64,[A-Za-z0-9+/=]+" alt="" style="([^"]*)">', html)
    # The unreadable picture is left out and the page still renders.
    assert len(styles) == 2, styles
    assert styles[0].startswith("width:40pt;height:20pt"), styles
    assert "float:left" in styles[1] and "margin-left:1pt" in styles[1] and "margin-right:9pt" in styles[1], styles

    # Two logos floated in an otherwise empty line of a table cell (the
    # teacher's ILAW title cell): Word places each at its own offset, side by
    # side, and the next line's text flows below them.
    doc = Document()
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    holder = cell.paragraphs[0]
    for x_emu, relative in ((577390, "leftMargin"), (-35560, "column")):
        run = holder.add_run()
        run.add_picture(io.BytesIO(_png()), width=Pt(47), height=Pt(47))
        _make_floating(run._r, x_emu, relative)
    cell.add_paragraph("LESSON PLAN (ILAW)")
    html = _render(doc)
    styles = re.findall(r'<img src="data:image/png;base64,[A-Za-z0-9+/=]+" alt="" style="([^"]*)">', html)
    assert "position:absolute" in styles[0] and "left:45.46pt" in styles[0], styles
    assert "position:absolute" in styles[1] and "left:-2.8pt" in styles[1], styles
    holder_style = re.search(r'<p class="lp-p" style="([^"]*)"[^>]*><img', html).group(1)
    assert "min-height:47pt" in holder_style, holder_style
    print("  pictures OK")


def check_slot_takes_the_cell_style():
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "School:"
    table.cell(0, 1).paragraphs[0]._p.get_or_add_pPr().append(parse_xml(
        '<w:rPr %s><w:rFonts w:ascii="Century Gothic" w:hAnsi="Century Gothic"/><w:sz w:val="20"/></w:rPr>'
        % nsdecls("w")))
    path = _save(doc)
    try:
        doc = Document(path)
        items = docx_service._iter_items(doc)
        idx = next(i for i, it in enumerate(items) if docx_service._element_text(doc, it["el"]) == "School:")
        slots, targets = docx_service._plan_html_slots(doc, items, {"school": idx})
        html = docx_service._render_doc_body_html(doc, items, slots, targets)
    finally:
        os.remove(path)
    # Typed text looks the way Word (and the export) will set it in that cell.
    assert re.search(r'data-field-key="school" style="font-family:\'Century Gothic\',sans-serif;font-size:10pt',
                     html), html
    print("  field slot takes the cell's style OK")


def check_hostile_file():
    """A format's .docx is uploaded by one teacher and viewed by others: no
    value in it may break out of an attribute, inject CSS, run a link as
    script, or blow the page up."""
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run("font")
    run._r.get_or_add_rPr().append(parse_xml(
        '<w:rFonts %s w:ascii="X&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"/>' % nsdecls("w")))
    run = p.add_run("colour")
    run._r.get_or_add_rPr().append(parse_xml(
        '<w:color %s w:val="000&quot; onmouseover=&quot;alert(2)"/>' % nsdecls("w")))
    run = p.add_run("shade")
    run._r.get_or_add_rPr().append(parse_xml(
        '<w:shd %s w:val="clear" w:fill="fff;background:url(//evil/x)"/>' % nsdecls("w")))
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "cell"
    cell._tc.get_or_add_tcPr().append(parse_xml(
        '<w:tcBorders %s><w:top w:val="single" w:sz="4" w:color="000&quot;&gt;&lt;b"/></w:tcBorders>'
        % nsdecls("w")))
    cell._tc.get_or_add_tcPr().append(parse_xml(
        '<w:shd %s w:val="clear" w:fill="abc&quot; onclick=&quot;x"/>' % nsdecls("w")))
    link_p = doc.add_paragraph()
    r_id = doc.part.relate_to("javascript:alert(3)",
                              "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                              is_external=True)
    link_p._p.append(parse_xml('<w:hyperlink %s r:id="%s"><w:r><w:t>click</w:t></w:r></w:hyperlink>'
                               % (nsdecls("w", "r"), r_id)))
    numbering = doc.part.numbering_part.element
    numbering.append(parse_xml(
        '<w:abstractNum %s w:abstractNumId="95"><w:lvl w:ilvl="0"><w:start w:val="2000000000"/>'
        '<w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%%1."/></w:lvl></w:abstractNum>' % nsdecls("w")))
    numbering.append(parse_xml('<w:num %s w:numId="95"><w:abstractNumId w:val="95"/></w:num>' % nsdecls("w")))
    for _ in range(3):
        doc.add_paragraph("item")._p.get_or_add_pPr().append(parse_xml(
            '<w:numPr %s><w:ilvl w:val="0"/><w:numId w:val="95"/></w:numPr>' % nsdecls("w")))
    html = _render(doc)
    # Neutralised text may remain ("Ximg srcx onerroralert1" as a font name);
    # what must never appear is a working attribute, tag, CSS url or script link.
    for bad in ("onerror=", "onmouseover=", "onclick=", "<img src=x", "url(", "javascript:", "<b"):
        assert bad not in html, (bad, html[:1500])
    assert len(html) < 20000, len(html)
    print("  hostile file OK")


def check_teacher_sample():
    """The teacher's own ILAW plan: the look the user asked for."""
    if not os.path.isfile(SAMPLE):
        print("  teacher sample not in backend/uploads; skipped")
        return
    html = docx_service.render_reference_html(SAMPLE)["html"]
    assert 'data-page-width="936"' in html
    assert len(re.findall(r"<img ", html)) == 2, "both logos"
    assert "'Arial Narrow'" in html
    # Its numbered list has no hanging indent, so the marker keeps its tab's space.
    assert re.search(r'data-marker="1\. ?"', html), "numbered list"
    assert html.count('data-marker="•"') > 10, "bullets"
    print("  teacher sample OK")


def main():
    check_page()
    check_text_cascade()
    check_tables()
    check_lists()
    check_pictures()
    check_slot_takes_the_cell_style()
    check_hostile_file()
    check_teacher_sample()
    print("render fidelity OK")


if __name__ == "__main__":
    main()
