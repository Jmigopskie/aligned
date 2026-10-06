"""Self-check for whole-document editing.

A teacher edits the lesson plan the way they would edit a Word file: the labels,
headings and table text, not only the AI's field slots. Those edits are stored
per plan against the position they belong to (the same anchor_index the format
builder already uses) and replayed onto a fresh copy of the reference file at
export, so the exported .docx keeps the original fonts and table layout while
carrying the teacher's wording.

What matters here: the edits round-trip through the plan, an autosave that omits
them does not wipe them, and the applier actually changes the document without
disturbing anything it was not asked to change.

Run it directly: `venv/Scripts/python test_doc_edits.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document

from app import create_app
from extensions import db
from models.user import User
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from services import docx_service

import io
import tempfile
from PIL import Image
from docx.shared import Inches


def png_stream(color=(30, 90, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), color).save(buf, "PNG")
    buf.seek(0)
    return buf


def doc_with_picture():
    """A document whose second line is a picture, saved to disk, since the
    canvas renderer reads a path just as the builder does."""
    doc = Document()
    doc.add_paragraph("Header line")
    doc.add_paragraph().add_run().add_picture(png_stream(), width=Inches(3))
    doc.add_paragraph("After the picture")
    path = os.path.join(tempfile.mkdtemp(), "pic.docx")
    doc.save(path)
    return path


def check_pictures_render():
    html = docx_service.render_reference_html(doc_with_picture())["html"]
    assert 'class="lp-img' in html, html[:400]
    assert 'data-docx-image="0"' in html
    assert "data:image/png;base64," in html
    # 3in of a 6in text column (Letter, 1in margins)
    assert 'data-width-pct="50"' in html, html
    # The picture stays inside its own anchored line.
    assert 'data-anchor-index="1"><span class="lp-img' in html.replace("\n", "")
    print("  pictures render OK")


def check_applier():
    """The core: replay edits onto a document by position."""
    doc = Document()
    doc.add_paragraph("Name of Lesson")
    doc.add_paragraph("Learning Area/s")
    doc.add_paragraph("Untouched line")
    items = docx_service._iter_items(doc)

    docx_service.apply_doc_edits(doc, items, [
        {"anchor_index": 0, "text": "Title of Lesson"},
        {"anchor_index": 1, "text": "Subject Area", "bold": True},
    ])

    texts = [p.text for p in doc.paragraphs]
    assert texts[0] == "Title of Lesson", texts
    assert texts[1] == "Subject Area", texts
    # Nothing asked about line 2, so line 2 is exactly as it was.
    assert texts[2] == "Untouched line", texts
    assert doc.paragraphs[1].runs[0].bold is True
    print("  applier OK")


def check_applier_is_defensive():
    """Junk must not break an export: a teacher's plan still has to come out."""
    doc = Document()
    doc.add_paragraph("Only line")
    items = docx_service._iter_items(doc)

    docx_service.apply_doc_edits(doc, items, [
        {"anchor_index": 99, "text": "out of range"},   # position no longer exists
        {"anchor_index": "x", "text": "not a number"},
        {"text": "no anchor at all"},
        "not even a dict",
        {"anchor_index": 0, "text": "Applied"},          # the valid one still lands
    ])
    assert [p.text for p in doc.paragraphs] == ["Applied"], [p.text for p in doc.paragraphs]

    # None and an empty list are both no-ops rather than errors.
    docx_service.apply_doc_edits(doc, items, None)
    docx_service.apply_doc_edits(doc, items, [])
    assert [p.text for p in doc.paragraphs] == ["Applied"]
    print("  defensive OK")


def check_round_trip():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        u = User(full_name="Doc Edits", email="doc.edits@example.test", role="teacher")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        uid = u.id

        fmt = LessonPlanFormat(owner_id=uid, name="DLP")
        db.session.add(fmt)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = uid

        edits = [{"anchor_index": 3, "text": "Renamed by the teacher", "bold": True}]
        res = client.post("/api/lesson-plans", json={
            "format_id": fmt.id, "title": "Doc edit plan", "doc_edits": edits,
        })
        assert res.status_code == 201, res.status_code
        plan = res.get_json()["lesson_plan"]
        assert plan["doc_edits"] == edits, plan["doc_edits"]
        pid = plan["id"]

        # An autosave carrying only field values must not wipe the body edits.
        res = client.patch(f"/api/lesson-plans/{pid}", json={"field_values": {"a": "b"}})
        assert res.get_json()["lesson_plan"]["doc_edits"] == edits, "autosave wiped the document edits"

        # Sending them explicitly replaces them; an empty list clears them.
        res = client.patch(f"/api/lesson-plans/{pid}", json={"doc_edits": [{"anchor_index": 1, "text": "Second"}]})
        assert len(res.get_json()["lesson_plan"]["doc_edits"]) == 1
        res = client.patch(f"/api/lesson-plans/{pid}", json={"doc_edits": []})
        assert res.get_json()["lesson_plan"]["doc_edits"] == []

        # A plan saved before this existed reads as [], never None.
        legacy = LessonPlan(user_id=uid, format_id=fmt.id, title="Legacy")
        db.session.add(legacy)
        db.session.commit()
        assert legacy.to_dict()["doc_edits"] == [], legacy.to_dict()["doc_edits"]

        # Junk in the column degrades rather than raising.
        legacy.doc_edits = "not json"
        db.session.commit()
        assert legacy.to_dict()["doc_edits"] == []
    print("  round trip OK")


check_applier()
check_applier_is_defensive()
check_round_trip()
check_pictures_render()
print("doc edits OK")
