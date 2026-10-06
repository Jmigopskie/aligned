"""Self-check that the document toolbar's formatting survives Word export.

The toolbar lets a teacher set font size, text colour and highlight as well as
bold/italic/underline. Those are stored as a fixed vocabulary of span classes,
and this pins down that each one becomes a real Word run property rather than
being quietly dropped somewhere between the browser and the .docx. Formatting
that looks applied on screen and vanishes on export is worse than not offering
it at all, which is what this guards.

Run it directly: `venv/Scripts/python test_rich_export.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt

from services import docx_service


def runs_of(html):
    """Write one field's rich HTML into a real paragraph and hand back its runs,
    which is exactly what export does for a styled field."""
    doc = Document()
    para = doc.add_paragraph("placeholder")
    lines = docx_service.parse_rich_value(html)
    docx_service._set_paragraph_rich(doc, para._p, lines[0])
    return [r for r in para.runs if r.text]


def check_marks_still_work():
    runs = runs_of("<b>bold</b> <i>it</i> <u>un</u>")
    by_text = {r.text.strip(): r for r in runs}
    assert by_text["bold"].bold is True
    assert by_text["it"].italic is True
    assert by_text["un"].underline is True
    print("  bold/italic/underline OK")


def check_size():
    runs = runs_of('<span class="fs-xl">big</span> plain')
    big = next(r for r in runs if r.text.strip() == "big")
    plain = next(r for r in runs if "plain" in r.text)
    assert big.font.size == Pt(18), big.font.size
    # The unstyled run must be left alone rather than forced to a size, so it
    # keeps inheriting the template's own font.
    assert plain.font.size is None, plain.font.size

    for cls, pt in [("fs-sm", 9), ("fs-md", 11), ("fs-lg", 14), ("fs-xl", 18)]:
        run = runs_of(f'<span class="{cls}">x</span>')[0]
        assert run.font.size == Pt(pt), (cls, run.font.size)
    print("  font size OK")


def check_color():
    run = runs_of('<span class="fc-red">danger</span>')[0]
    assert str(run.font.color.rgb) == "AB3524", run.font.color.rgb

    run = runs_of('<span class="fc-blue">link</span>')[0]
    assert str(run.font.color.rgb) == "1D4ED8", run.font.color.rgb

    # Every colour the toolbar offers maps to something real.
    for cls in docx_service.FONT_COLOR_CLASSES:
        run = runs_of(f'<span class="{cls}">x</span>')[0]
        assert run.font.color.rgb is not None, cls
    print("  text colour OK")


def check_highlight():
    run = runs_of('<span class="hl-yellow">note</span>')[0]
    assert run.font.highlight_color == WD_COLOR_INDEX.YELLOW, run.font.highlight_color

    run = runs_of('<span class="hl-cyan">note</span>')[0]
    assert run.font.highlight_color == WD_COLOR_INDEX.TURQUOISE, run.font.highlight_color

    # "None" clears rather than setting a colour.
    run = runs_of('<span class="hl-none">note</span>')[0]
    assert run.font.highlight_color is None, run.font.highlight_color
    print("  highlight OK")


def check_combined_and_nested():
    # Several properties on one run, alongside a mark.
    runs = runs_of('<b><span class="fs-lg fc-green hl-yellow">all at once</span></b>')
    run = runs[0]
    assert run.bold is True
    assert run.font.size == Pt(14)
    assert str(run.font.color.rgb) == "1C5C4E"
    assert run.font.highlight_color == WD_COLOR_INDEX.YELLOW
    print("  combined marks OK")

    # An inner span overrides an outer one, and the outer resumes after it.
    runs = runs_of('<span class="fc-blue">out <span class="fc-red">in</span> out2</span>')
    colors = [str(r.font.color.rgb) for r in runs]
    assert colors == ["1D4ED8", "AB3524", "1D4ED8"], colors
    print("  nested spans OK")


def check_unknown_class_is_ignored():
    # A class outside the vocabulary must not raise and must not style anything:
    # a page left open across a deploy could still send an old name.
    runs = runs_of('<span class="fc-chartreuse fs-enormous">odd</span>')
    assert runs[0].text == "odd"
    assert runs[0].font.size is None
    assert runs[0].font.color.rgb is None
    print("  unknown classes ignored OK")


def check_lists_still_work():
    lines = docx_service.parse_rich_value("<ul><li>one</li><li>two</li></ul>")
    assert [l["list"] for l in lines] == ["bullet", "bullet"], lines
    assert [l["runs"][0]["text"] for l in lines] == ["one", "two"]

    lines = docx_service.parse_rich_value("<ol><li>first</li></ol>")
    assert lines[0]["list"] == "number", lines
    print("  lists OK")


def check_plain_text_unchanged():
    # A field with no styling at all still round-trips as one plain run, so
    # nothing about the ordinary case changed.
    lines = docx_service.parse_rich_value("just text")
    assert len(lines) == 1 and len(lines[0]["runs"]) == 1
    run = lines[0]["runs"][0]
    assert run["text"] == "just text"
    assert (run["size"], run["color"], run["highlight"]) == (None, None, None)
    print("  plain text OK")


import io
import tempfile
from PIL import Image
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from app import create_app


def fig(image_id, cls="img-align-center img-wrap-inline", pct=50, caption=""):
    cap = f'<span class="lp-img-cap">{caption}</span>' if caption else ""
    return (f'Before<span class="lp-img {cls}" data-img-id="{image_id}" data-width-pct="{pct}">'
            f'<img src="/api/images/{image_id}" alt="">{cap}</span>After')


def check_image_lines_parse():
    lines = docx_service.parse_rich_value(fig("a" * 32, "img-align-right img-wrap-left img-border", 30, "Fig <b>1</b>"))
    texts = ["".join(r["text"] for r in l["runs"]) for l in lines]
    assert texts == ["Before", "", "Fig 1", "After"], texts
    assert lines[1]["image"] == {"id": "a" * 32, "width_pct": 30, "align": "right", "wrap": "left", "border": True}
    assert lines[2]["align"] == "right" and lines[2]["runs"][0]["italic"]
    print("  image lines parse OK")


def check_image_exports():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        from services import image_store
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), (0, 0, 0)).save(buf, "PNG")
        saved = image_store.save_image(buf.getvalue())
        lines = docx_service.parse_rich_value(fig(saved["id"], "img-align-center img-wrap-right img-border", 40))
        doc = Document()
        para = doc.add_paragraph("placeholder")
        docx_service._set_paragraph_rich(doc, para._p, lines[1])
        d = next(para._p.iter(qn("w:drawing")))
        assert d.find(qn("wp:anchor")) is not None
        assert next(d.iter(qn("a:ln")), None) is not None
        assert para.alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert para.text == "", "placeholder text replaced by the picture"
    print("  image exports OK")


def check_missing_image_is_skipped():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        lines = docx_service.parse_rich_value(fig("b" * 32))
        doc = Document()
        para = doc.add_paragraph("placeholder")
        docx_service._set_paragraph_rich(doc, para._p, lines[1])  # must not raise
        assert next(para._p.iter(qn("w:drawing")), None) is None
    print("  missing image skipped OK")


check_marks_still_work()
check_size()
check_color()
check_highlight()
check_combined_and_nested()
check_unknown_class_is_ignored()
check_lists_still_work()
check_plain_text_unchanged()
check_image_lines_parse()
check_image_exports()
check_missing_image_is_skipped()
print("rich export OK")
