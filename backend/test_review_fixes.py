"""Self-check for the fixes from the image branch's final review.

Each check names the failure it pins down: a crafted .docx running script in the
canvas, a picture copied into every line of a field, a plan's stray picture
keys crashing export, a tiny file that decodes to gigabytes, a Word-only (EMF)
logo breaking the whole save, and a picture lost when its line is merged into
the one above.

Run it directly: `venv/Scripts/python test_review_fixes.py`.
"""
import io
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from PIL import Image
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches

from app import create_app
from services import docx_service, image_store


def png_stream():
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), (30, 90, 200)).save(buf, "PNG")
    buf.seek(0)
    return buf


def drawings(el):
    return list(el.iter(qn("w:drawing")))


def doc_with_picture(content_type=None):
    doc = Document()
    doc.add_paragraph("Header line")
    doc.add_paragraph().add_run().add_picture(png_stream(), width=Inches(3))
    path = os.path.join(tempfile.mkdtemp(), "pic.docx")
    doc.save(path)
    if content_type:
        # Rewrite the package's declared type for .png, as a hostile or
        # unusual producer might.
        src = path + ".src"
        os.replace(path, src)
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b'ContentType="image/png"', f'ContentType="{content_type}"'.encode())
                zout.writestr(item, data)
    return path


def check_content_type_cannot_inject():
    html = docx_service.render_reference_html(doc_with_picture('image/png&quot; onerror=&quot;alert(1)'))["html"]
    assert "onerror" not in html, html[:300]
    print("  hostile content type OK")


def check_unembeddable_picture_is_not_editable():
    html = docx_service.render_reference_html(doc_with_picture("image/x-emf"))["html"]
    assert "data-docx-image" not in html, "an EMF picture must not be offered for restyling"
    print("  EMF not editable OK")


def check_picture_not_copied_into_every_line(app):
    with app.app_context():
        saved = image_store.save_image(png_stream().getvalue())
        html = (f'<span class="lp-img img-align-left img-wrap-inline" data-img-id="{saved["id"]}" '
                f'data-width-pct="50"></span>first<br>second')
        lines = docx_service.parse_rich_value(html)
        doc = Document()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        docx_service._fill_paragraphs_rich(doc, cell.paragraphs, lines)
        assert len(drawings(cell._tc)) == 1, f"{len(drawings(cell._tc))} pictures; the field has one"
        assert [p.text for p in cell.paragraphs] == ["", "first", "second"], [p.text for p in cell.paragraphs]
    print("  picture not copied into following lines OK")


def check_block_region_template_picture_not_copied():
    doc = Document()
    anchor = doc.add_paragraph("Flow:")
    old = doc.add_paragraph("old text")
    old.add_run().add_picture(png_stream(), width=Inches(1))
    boundary = doc.add_paragraph("Next label:")
    lines = docx_service.parse_rich_value("one<br>two")
    docx_service._replace_block_region_rich(doc, anchor._p, boundary._p, lines)
    assert drawings(doc.element.body) == [], "the replaced region's old picture must not repeat into new lines"
    assert [p.text for p in doc.paragraphs] == ["Flow:", "one", "two", "Next label:"], [p.text for p in doc.paragraphs]
    print("  block region template picture not copied OK")


def check_plan_doc_edits_ignore_picture_keys():
    doc = Document()
    doc.add_paragraph().add_run().add_picture(png_stream(), width=Inches(1))
    items = docx_service._iter_items(doc)
    docx_service.apply_doc_edits(doc, items, [
        {"anchor_index": 0, "image_format": [{"n": 0}]},
        {"anchor_index": 0, "image_format": [{"n": "a"}], "remove_images": [0]},
    ])
    assert len(drawings(doc.element.body)) == 1, "a plan's edits never change the template's pictures"
    print("  plan doc_edits ignore picture keys OK")


def check_decompression_bomb_rejected(app):
    buf = io.BytesIO()
    Image.new("1", (8000, 8000)).save(buf, "PNG")  # tiny file, 64M pixels
    with app.app_context():
        before = len(os.listdir(image_store.images_dir()))
        try:
            image_store.save_image(buf.getvalue())
        except ValueError:
            pass
        else:
            raise AssertionError("an 8000x8000 image must be refused before decoding")
        assert len(os.listdir(image_store.images_dir())) == before, "nothing written"
    print("  decompression bomb rejected OK")


def check_merge_keeps_picture():
    path = doc_with_picture()
    # Line 1 (the picture's line) was merged into line 0 with Backspace.
    docx_service.apply_content_edits(path, [
        {"anchor_index": 1, "action": "delete", "move_images_to": 0},
    ])
    doc = Document(path)
    assert len(drawings(doc.paragraphs[0]._p)) == 1, "the picture moved to the line it was merged into"
    assert len(doc.paragraphs) == 1, [p.text for p in doc.paragraphs]

    from routes.format_routes import _sanitize_content_edits
    out = _sanitize_content_edits([
        {"anchor_index": 1, "action": "delete", "move_images_to": 0},
        {"anchor_index": 2, "action": "delete", "move_images_to": "x"},
    ])
    assert out[0]["move_images_to"] == 0 and "move_images_to" not in out[1], out
    print("  merge keeps picture OK")


if __name__ == "__main__":
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    check_content_type_cannot_inject()
    check_unembeddable_picture_is_not_editable()
    check_picture_not_copied_into_every_line(app)
    check_block_region_template_picture_not_copied()
    check_plan_doc_edits_ignore_picture_keys()
    check_decompression_bomb_rejected(app)
    check_merge_keeps_picture()
    print("review fixes OK")
