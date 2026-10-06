"""Self-check for where pictures land in the format's .docx.

Three cases from the image branch's review: two pictures inserted after the
same line keep the order they were added in; restyling a picture that shares
its line with text moves the picture onto its own line instead of realigning
the text; and a text edit on a line whose text sits in the same run as its
picture (some non-Word producers do this) replaces the text and keeps the
picture.

Run it directly: `venv/Scripts/python test_picture_lines.py`.
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from PIL import Image
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from app import create_app
from services import docx_service, image_store


def png(color):
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), color).save(buf, "PNG")
    return buf.getvalue()


def save(doc):
    path = os.path.join(tempfile.mkdtemp(), "f.docx")
    doc.save(path)
    return path


def has_picture(p):
    return next(p._p.iter(qn("w:drawing")), None) is not None


def check_inserts_keep_order(app):
    with app.app_context():
        a = image_store.save_image(png((255, 0, 0)))["id"]
        b = image_store.save_image(png((0, 0, 255)))["id"]
        doc = Document()
        doc.add_paragraph("Line")
        doc.add_paragraph("Next")
        path = save(doc)
        spec = {"width_pct": 30, "align": "left", "wrap": "inline", "border": False}
        docx_service.apply_content_edits(path, [
            {"anchor_index": 0, "action": "insert_image", "image_id": a, **spec, "caption": "first"},
            {"anchor_index": 0, "action": "insert_image", "image_id": b, **spec, "caption": ""},
        ])
        out = Document(path)
        texts = [p.text for p in out.paragraphs]
        pics = [has_picture(p) for p in out.paragraphs]
        # Line, picture A, its caption, picture B, Next.
        assert texts == ["Line", "", "first", "", "Next"], texts
        assert pics == [False, True, False, True, False], pics
        blob_a = out.part.related_parts[next(out.paragraphs[1]._p.iter(qn("a:blip"))).get(qn("r:embed"))].blob
        assert blob_a == png((255, 0, 0)), "the first picture added is the first in the document"
    print("  inserts keep their order OK")


def check_restyle_moves_picture_off_a_text_line():
    doc = Document()
    p = doc.add_paragraph("Name of school")
    p.add_run().add_picture(io.BytesIO(png((0, 128, 0))), width=Inches(1))
    doc.add_paragraph("After")
    path = save(doc)
    docx_service.apply_content_edits(path, [{"anchor_index": 0, "action": "format", "image_format": [
        {"n": 0, "width_pct": 40, "align": "center", "wrap": "inline", "border": False, "caption": ""}]}])
    out = Document(path)
    assert [x.text for x in out.paragraphs] == ["Name of school", "", "After"], [x.text for x in out.paragraphs]
    assert out.paragraphs[0].alignment in (None, WD_ALIGN_PARAGRAPH.LEFT), "the text line keeps its alignment"
    assert not has_picture(out.paragraphs[0]) and has_picture(out.paragraphs[1])
    assert out.paragraphs[1].alignment == WD_ALIGN_PARAGRAPH.CENTER
    print("  restyle moves picture off a text line OK")


def check_restyle_in_place_when_line_is_only_a_picture():
    doc = Document()
    doc.add_paragraph().add_run().add_picture(io.BytesIO(png((0, 0, 0))), width=Inches(1))
    path = save(doc)
    docx_service.apply_content_edits(path, [{"anchor_index": 0, "action": "format", "image_format": [
        {"n": 0, "width_pct": 40, "align": "right", "wrap": "inline", "border": False, "caption": ""}]}])
    out = Document(path)
    assert len(out.paragraphs) == 1 and has_picture(out.paragraphs[0])
    assert out.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    print("  restyle in place on a picture-only line OK")


def check_text_in_the_picture_run_is_replaced():
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run()
    run.add_picture(io.BytesIO(png((9, 9, 9))), width=Inches(1))
    t = OxmlElement("w:t")
    t.text = "hello"
    run._r.append(t)  # text and picture in one run, as some producers write it
    items = docx_service._iter_items(doc)
    docx_service.apply_doc_edits(doc, items, [{"anchor_index": 0, "text": "new"}])
    assert doc.paragraphs[0].text == "new", doc.paragraphs[0].text
    assert has_picture(doc.paragraphs[0])
    print("  text in the picture's run replaced OK")


if __name__ == "__main__":
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    check_inserts_keep_order(app)
    check_restyle_moves_picture_off_a_text_line()
    check_restyle_in_place_when_line_is_only_a_picture()
    check_text_in_the_picture_run_is_replaced()
    print("picture lines OK")
