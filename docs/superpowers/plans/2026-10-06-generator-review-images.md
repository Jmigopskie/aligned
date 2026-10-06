# Field Review Popup, Sticky Deletes, Toolbar, Images and Alan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let teachers choose, in a popup, which fields the AI writes. Make deletes in the format builder stick, including images. Enlarge the document toolbar. Add Word-style image upload and formatting. Put Alan on the loaders.

**Architecture:** The backend gets one small image store (`services/image_store.py`), one blueprint (`routes/image_routes.py`) and picture support in `services/docx_service.py`, covering rendering, builder edits and rich-value export. The frontend shares one image module in `js/doc-toolbar.js`, used by both `format-builder.js` and `generator.js`. The field review popup is purely frontend and reuses the existing `include_keys` API.

**Tech Stack:** Flask 3, python-docx 1.1.2, Pillow 12, vanilla JS, a single `css/style.css`. Self-check test scripts are run with `backend/venv/Scripts/python <file>.py`, which is the repo's style. There is no pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-generator-review-images-design.md`

## Global Constraints

- Upload limit is **5 MB**. Accepted formats are **PNG, JPEG, GIF and WebP**, checked by opening the file with Pillow. GIF and WebP are re-encoded to PNG, because python-docx cannot embed WebP.
- Image ids are `uuid4().hex` (32 lowercase hex). Every lookup validates against `^[0-9a-f]{32}$`.
- Image width is one property, `data-width-pct`, an integer from 10 to 100 (presets are 25/50/75/100). There are no width classes. This simplifies the spec's `img-w-*` row while keeping the same behaviour.
- Image classes are a closed vocabulary: `lp-img`, `img-align-{left|center|right}`, `img-wrap-{inline|left|right}`, `img-border`. Captions use `span.lp-img-cap`.
- Figure markup uses `<span>` and never `<figure>`. A `<figure>` inside a `<p>` makes the HTML parser close the `<p>`, which would tear images out of their `data-anchor-index` line.
- **Deviation from the spec:** there is no `images` DB table. Files are named by id under `uploads/images/`, and reads are allowed for any logged-in user, so an owner column would have nothing to enforce.
- User-facing name: **Alan** ("Ask Alan", "Alan is writing your plan…"). File names and JS identifiers containing `owl` stay as they are.
- Alan is never the chat's open/close control.
- No emoji icons. Use SVGs from `js/icons.js`.
- After the frontend changes, bump every `?v=2026-09-24c` asset query to `?v=2026-10-06a`.
- Commit after each task to `master` with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not stage `frontend/announcements.html` or `frontend/dashboard.html` changes that are not yours. Use `git add -p` or name paths explicitly.

## Review Focus

1. **A paragraph holding both text and a picture gets a text edit.** `_set_paragraph_text` writes into `runs[0]`, and python-docx's `run.text =` deletes a drawing in that run, so the image silently disappears. Pinned in Task 3: `check_text_edit_keeps_picture`.
2. **A line merged away with Backspace at the start of a line.** The browser removes the second `<p>` and moves its text into the first. That must become `delete(second)` plus a text edit on the first, not "nothing changed". Pinned in Task 6, browser step.
3. **A rich value whose image file is gone** (deleted upload, or a plan copied between servers). The export must still succeed and skip the picture. Pinned in Task 4: `check_missing_image_is_skipped`.
4. **A renamed non-image or an oversized upload.** It must be rejected with a clear 400 and nothing written to disk. Pinned in Task 1.
5. **Every field set to "Keep static".** Generate must be disabled with a hint, never sending an empty `include_keys` list (the server would treat an empty list as "generate nothing", which wastes a request). Pinned in Task 8, browser step.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/services/image_store.py` (new) | Where images live; `image_path(id)` and `save_image(bytes)`. No Flask routes. |
| `backend/routes/image_routes.py` (new) | `POST /api/images`, `GET /api/images/<id>` |
| `backend/app.py` | register `image_bp` |
| `backend/services/docx_service.py` | render pictures to HTML; `_place_picture`, floating/border/caption helpers; `remove_images` / `image_format` / `insert_image` edits; rich-value image lines; drawing-safe text setters |
| `backend/routes/format_routes.py` | sanitize the new edit shapes |
| `backend/test_images.py` (new), `test_doc_edits.py`, `test_rich_export.py` | self-checks |
| `frontend/js/doc-toolbar.js` | toolbar markup (+Image), shared image module: `docImageMarkup`, `readDocImage`, `hydrateDocImages`, `initDocImageTools`, `initDocImageInsert` |
| `frontend/js/api.js` | `Api.uploadImage`, `docImageUrl`; "Alan" copy in OwlGuide |
| `frontend/js/format-builder.js` | native-delete capture, save-flush, builder image edits |
| `frontend/js/generator.js` | image insertion in fields, sanitizer, review modal, Alan loader, copy |
| `frontend/generator.html` | review modal, loader card, remove inline checklist, copy |
| `frontend/css/style.css` | toolbar sizing (merge duplicate rule), image styles, image bar, review modal, static fields, Alan loaders |
| `frontend/img/owl/alan-loading.png` (new) | cropped image 10 |
| all `frontend/*.html` | loader image, asset version |

---

### Task 1: Image upload API

**Files:**
- Create: `backend/services/image_store.py`
- Create: `backend/routes/image_routes.py`
- Modify: `backend/app.py` (blueprint registration, next to the other `register_blueprint` calls, around line 219)
- Test: `backend/test_images.py`

**Interfaces:**
- Produces: `image_store.image_path(image_id: str) -> str | None`, `image_store.save_image(data: bytes) -> dict` (`{"id", "width_px", "height_px"}`, raises `ValueError(message)`), `image_store.MAX_IMAGE_BYTES`. HTTP: `POST /api/images` → `{"status":"ok","id","url","width_px","height_px"}`; `GET /api/images/<id>` → the file.

- [ ] **Step 1: Write the failing test**

`backend/test_images.py`:

```python
"""Self-check for image upload.

Teachers insert pictures into formats and plans. What must hold: a real image
is stored and served back, anything that is not an image (whatever its name
says) or is too big is refused before it reaches disk, WebP comes back as PNG
because Word export can't embed WebP, and only a logged-in user can read one.

Run it directly: `venv/Scripts/python test_images.py`.
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from PIL import Image

from app import create_app
from extensions import db
from models.user import User
from services import image_store


def png_bytes(fmt="PNG", size=(40, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def main():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        u = User(full_name="Img", email="img@example.test", role="teacher")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        uid = u.id

    anon = app.test_client()
    res = anon.post("/api/images", data={"file": (io.BytesIO(png_bytes()), "a.png")})
    assert res.status_code == 401, res.status_code

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post("/api/images", data={"file": (io.BytesIO(png_bytes()), "a.png")})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert len(body["id"]) == 32 and body["width_px"] == 40 and body["height_px"] == 20
    assert body["url"] == f"/api/images/{body['id']}"
    got = client.get(body["url"])
    assert got.status_code == 200 and got.data == png_bytes()
    assert anon.get(body["url"]).status_code == 401
    print("  png round trip OK")

    res = client.post("/api/images", data={"file": (io.BytesIO(b"not an image at all"), "evil.png")})
    assert res.status_code == 400, res.status_code
    big = b"\0" * (image_store.MAX_IMAGE_BYTES + 1)
    res = client.post("/api/images", data={"file": (io.BytesIO(big), "big.png")})
    assert res.status_code == 400, res.status_code
    with app.app_context():
        stored = os.listdir(os.path.join(app.config["UPLOAD_FOLDER"], "images"))
    assert len(stored) == 1, stored  # only the one good PNG
    print("  rejects junk and oversize OK")

    res = client.post("/api/images", data={"file": (io.BytesIO(png_bytes("WEBP")), "a.webp")})
    assert res.status_code == 200, res.get_json()
    with app.app_context():
        path = image_store.image_path(res.get_json()["id"])
    assert path.endswith(".png"), path
    print("  webp re-encoded to png OK")

    with app.app_context():
        assert image_store.image_path("../../etc/passwd") is None
        assert image_store.image_path("0" * 32) is None
    assert client.get("/api/images/" + "0" * 32).status_code == 404
    print("  lookups are safe OK")


if __name__ == "__main__":
    main()
    print("test_images: all OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && venv/Scripts/python test_images.py`
Expected: `ImportError` / `cannot import name 'image_store'`.

- [ ] **Step 3: Implement**

`backend/services/image_store.py`:

```python
"""Uploaded pictures for formats and plans.

Files are named by a random id under uploads/images/, so the id is the only
handle anyone ever holds. Every lookup checks the id's exact shape first,
which is what stops a crafted id from walking out of the folder.
"""
import io
import os
import re
import uuid

from flask import current_app
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACCEPTED = {"PNG", "JPEG", "GIF", "WEBP"}
# python-docx embeds PNG and JPEG but not WebP, so anything else is re-encoded
# to PNG on the way in rather than failing later at export.
_KEEP_AS = {"PNG": "png", "JPEG": "jpg"}


def images_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "images")
    os.makedirs(path, exist_ok=True)
    return path


def image_path(image_id):
    if not isinstance(image_id, str) or not _ID_RE.match(image_id):
        return None
    for ext in ("png", "jpg"):
        path = os.path.join(images_dir(), f"{image_id}.{ext}")
        if os.path.isfile(path):
            return path
    return None


def save_image(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Images must be 5 MB or smaller.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        img = None
    if img is None or img.format not in _ACCEPTED:
        raise ValueError("That file isn't an image AlignED can use. Use PNG, JPG, GIF or WebP.")

    image_id = uuid.uuid4().hex
    ext = _KEEP_AS.get(img.format)
    if ext:
        with open(os.path.join(images_dir(), f"{image_id}.{ext}"), "wb") as fh:
            fh.write(data)
    else:
        img.convert("RGBA").save(os.path.join(images_dir(), f"{image_id}.png"), "PNG")
    return {"id": image_id, "width_px": img.width, "height_px": img.height}
```

`backend/routes/image_routes.py`:

```python
from flask import Blueprint, jsonify, request, send_file

from routes.auth_routes import login_required
from services import image_store

image_bp = Blueprint("images", __name__)


@image_bp.post("/images")
@login_required
def upload_image():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "message": "Choose an image to upload."}), 400
    # One byte over the limit is enough to know it's too big, without reading
    # an arbitrarily large body into memory.
    data = file.read(image_store.MAX_IMAGE_BYTES + 1)
    try:
        saved = image_store.save_image(data)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok", "url": f"/api/images/{saved['id']}", **saved})


# Any logged-in user: a public plan or format shows its pictures to everyone
# who can open it, and the id is unguessable.
@image_bp.get("/images/<image_id>")
@login_required
def get_image(image_id):
    path = image_store.image_path(image_id)
    if not path:
        return jsonify({"status": "error", "message": "Image not found."}), 404
    return send_file(path, max_age=86400)
```

`backend/app.py`: import `from routes.image_routes import image_bp`, next to the other blueprint imports, and add `app.register_blueprint(image_bp, url_prefix="/api")` after `notification_bp`.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && venv/Scripts/python test_images.py`
Expected: four `OK` lines, then `test_images: all OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/image_store.py backend/routes/image_routes.py backend/app.py backend/test_images.py
git commit -m "Add image upload: validated with Pillow, stored by random id

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Show a document's pictures in the canvas

**Files:**
- Modify: `backend/services/docx_service.py`. Add imports. Change `_render_runs_html` (around line 500) and `_render_html_paragraph` (around line 520). Add the helpers `_text_width_emu`, `_paragraph_drawings`, `_owning_run`, `_drawing_figure_html`.
- Test: `backend/test_doc_edits.py`, adding `check_pictures_render`.

**Interfaces:**
- Produces (used by Tasks 3 and 6):
  - `_paragraph_drawings(p_el) -> list[w:drawing el]`, in document order, skipping `mc:Fallback` copies.
  - `_text_width_emu(doc) -> int`.
  - `_owning_run(node) -> w:r el`.
  - The HTML contract for an existing picture: `<span class="lp-img img-align-X img-wrap-Y[ img-border]" data-docx-image="N" data-width-pct="P" contenteditable="false"><img src="data:..." alt=""></span>`, where `N` is the drawing's index within its paragraph.

- [ ] **Step 1: Write the failing test**

Add a helper and a check to `backend/test_doc_edits.py`, and call the check from the file's `__main__` block next to the others:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && venv/Scripts/python test_doc_edits.py`
Expected: `AssertionError` at `'class="lp-img' in html`.

- [ ] **Step 3: Implement**

In `docx_service.py`, add these imports: `import base64`, `from docx.shared import Emu, Inches, Pt, RGBColor` (extending the existing `docx.shared` import), `from docx.oxml import OxmlElement, parse_xml`, and `from docx.oxml.ns import nsdecls, qn`.

Add these helpers above `_run_html`:

```python
def _in_fallback(node):
    # A drawing wrapped in mc:AlternateContent appears twice (Choice and
    # Fallback); only the Choice copy is the real picture.
    parent = node.getparent()
    while parent is not None:
        if parent.tag.endswith("}Fallback"):
            return True
        parent = parent.getparent()
    return False


def _paragraph_drawings(p_el):
    return [d for d in p_el.iter(qn("w:drawing")) if not _in_fallback(d)]


def _owning_run(node):
    while node is not None and node.tag != qn("w:r"):
        node = node.getparent()
    return node


def _run_has_drawing(run):
    return any(True for _ in run._r.iter(qn("w:drawing")))


def _text_width_emu(doc):
    sec = doc.sections[-1]
    try:
        return int(sec.page_width - sec.left_margin - sec.right_margin)
    except TypeError:
        return int(Inches(6))


_ALIGN_NAME = {WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right"}


def _drawing_figure_html(para, drawing, n):
    blip = next(drawing.iter(qn("a:blip")), None)
    rid = blip.get(qn("r:embed")) if blip is not None else None
    part = para.part.related_parts.get(rid) if rid else None
    if part is None:
        return ""
    extent = next(drawing.iter(qn("wp:extent")), None)
    cx = int(extent.get("cx")) if extent is not None else 0
    pct = max(10, min(100, round(cx * 100 / _text_width_emu(para.part.document)))) if cx else 50

    anchor = drawing.find(qn("wp:anchor"))
    if anchor is not None:
        side = next(anchor.iter(qn("wp:align")), None)
        wrap = "right" if side is not None and side.text == "right" else "left"
    else:
        wrap = "inline"
    try:
        align = _ALIGN_NAME.get(para.alignment, "left")
    except Exception:
        align = "left"
    border = " img-border" if next(drawing.iter(qn("a:ln")), None) is not None else ""

    src = f"data:{part.content_type};base64,{base64.b64encode(part.blob).decode('ascii')}"
    return (
        f'<span class="lp-img img-align-{align} img-wrap-{wrap}{border}" data-docx-image="{n}" '
        f'data-width-pct="{pct}" contenteditable="false"><img src="{src}" alt=""></span>'
    )
```

Replace the body of `_render_runs_html` so it also emits pictures, numbered per paragraph:

```python
    out = []
    drawings = _paragraph_drawings(para._p)
    for item in para.iter_inner_content():
        if isinstance(item, Hyperlink):
            inner = "".join(_run_html(r) for r in item.runs)
            if not inner:
                continue
            href = _html_escape(item.address or "")
            out.append(f'<a href="{href}" target="_blank" rel="noopener">{inner}</a>' if href else inner)
        else:
            out.append(_run_html(item))
            for d in item._r.iter(qn("w:drawing")):
                if d in drawings:
                    out.append(_drawing_figure_html(para, d, drawings.index(d)))
    return "".join(out)
```

In `_render_html_paragraph`, replace the `inner = ...` line so that a picture-only paragraph keeps its picture:

```python
    inner = _render_runs_html(para)
    if not text.strip() and "lp-img" not in inner:
        inner = "&nbsp;"
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && venv/Scripts/python test_doc_edits.py`, then `venv/Scripts/python test_rich_export.py`.
Expected: all checks OK, including `pictures render OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/docx_service.py backend/test_doc_edits.py
git commit -m "Render a format's pictures in the document canvas

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Builder picture edits in the .docx (remove, format, insert) and drawing-safe text edits

**Files:**
- Modify: `backend/services/docx_service.py`, in `apply_content_edits`, `_apply_paragraph_edit`, `_set_paragraph_text` and `_set_paragraph_rich` (run filtering only). Add new helpers.
- Modify: `backend/routes/format_routes.py`, in `_EDIT_ACTIONS` and `_sanitize_content_edits`.
- Test: `backend/test_doc_edits.py`

**Interfaces:**
- Consumes: Task 1 `image_store.image_path`. Task 2 `_paragraph_drawings`, `_owning_run`, `_text_width_emu`, `_run_has_drawing`.
- Produces:
  - `_place_picture(doc, para_el, source, spec, replace_drawing=None) -> None`, where `source` is a path or stream, and `spec` is `{"width_pct": int, "align": str, "wrap": str, "border": bool}`.
  - `_insert_caption_after(doc, para_el, text, align) -> None`.
  - Edit shapes:
    - `{"anchor_index", "action": "format", "remove_images": [int], "image_format": [{"n", "width_pct", "align", "wrap", "border", "caption"}]}`
    - `{"anchor_index", "action": "insert_image", "image_id", "width_pct", "align", "wrap", "border", "caption"}`

- [ ] **Step 1: Write the failing tests**

Add to `backend/test_doc_edits.py` (wire them into `__main__`):

```python
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


def drawings_in(doc):
    return [d for d in doc.element.body.iter(qn("w:drawing"))]


def check_text_edit_keeps_picture():
    doc = Document()
    p = doc.add_paragraph()
    p.add_run().add_picture(png_stream(), width=Inches(2))
    p.add_run("Caption-ish text")
    items = docx_service._iter_items(doc)
    docx_service.apply_doc_edits(doc, items, [{"anchor_index": 0, "text": "Renamed"}])
    assert len(drawings_in(doc)) == 1, "a text edit must not delete the picture"
    assert doc.paragraphs[0].text == "Renamed"
    print("  text edit keeps picture OK")


def check_picture_edits():
    path = doc_with_picture()
    docx_service.apply_content_edits(path, [
        {"anchor_index": 1, "action": "format", "image_format": [
            {"n": 0, "width_pct": 25, "align": "center", "wrap": "right", "border": True, "caption": "Fig 1"}]},
    ])
    doc = Document(path)
    (d,) = drawings_in(doc)
    assert d.find(qn("wp:anchor")) is not None, "wrap right makes it floating"
    assert next(d.iter(qn("wp:align"))).text == "right"
    assert next(d.iter(qn("a:ln")), None) is not None, "border"
    cx = int(next(d.iter(qn("wp:extent"))).get("cx"))
    assert abs(cx - docx_service._text_width_emu(doc) * 0.25) < 2, cx
    assert doc.paragraphs[1].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert doc.paragraphs[2].text == "Fig 1" and doc.paragraphs[2].runs[0].italic
    print("  image_format OK")

    docx_service.apply_content_edits(path, [{"anchor_index": 1, "action": "format", "remove_images": [0]}])
    assert drawings_in(Document(path)) == [], "removed picture stays removed"
    print("  remove_images OK")


def check_insert_image():
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=tempfile.mkdtemp())
    with app.app_context():
        from services import image_store
        saved = image_store.save_image(png_stream().getvalue())
        path = doc_with_picture()
        docx_service.apply_content_edits(path, [
            {"anchor_index": 0, "action": "insert_image", "image_id": saved["id"],
             "width_pct": 50, "align": "left", "wrap": "inline", "border": False, "caption": ""},
            {"anchor_index": 2, "action": "insert_image", "image_id": "f" * 32,  # no such file
             "width_pct": 50, "align": "left", "wrap": "inline", "border": False, "caption": ""},
        ])
        doc = Document(path)
        assert len(drawings_in(doc)) == 2, "original + the inserted one; the missing file is skipped"
        assert doc.paragraphs[0].text == "Header line"
        assert docx_service._paragraph_drawings(doc.paragraphs[1]._p), "inserted right after line 0"
    print("  insert_image OK")
```

Also add to the format-route sanitizer check, as a new function in the same file:

```python
def check_sanitizer_image_edits():
    from routes.format_routes import _sanitize_content_edits
    out = _sanitize_content_edits([
        {"anchor_index": 1, "action": "format", "remove_images": [0, "x", -1],
         "image_format": [{"n": 0, "width_pct": 999, "align": "diagonal", "wrap": "left", "border": 1, "caption": "c" * 999}]},
        {"anchor_index": 2, "action": "insert_image", "image_id": "../etc", "width_pct": 50},
        {"anchor_index": 2, "action": "insert_image", "image_id": "a" * 32, "width_pct": 5},
    ])
    assert out[0]["remove_images"] == [0]
    f = out[0]["image_format"][0]
    assert f == {"n": 0, "width_pct": 100, "align": "left", "wrap": "left", "border": True, "caption": "c" * 300}, f
    assert len(out) == 2 and out[1]["image_id"] == "a" * 32 and out[1]["width_pct"] == 10
    print("  sanitizer image edits OK")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && venv/Scripts/python test_doc_edits.py`
Expected: FAIL at `check_text_edit_keeps_picture` ("a text edit must not delete the picture").

- [ ] **Step 3: Implement the drawing-safe text setters**

In `_set_paragraph_text`, filter the runs first:

```python
    para = Paragraph(para_el, doc)
    # run.text = ... clears the whole run, drawing included, so a run carrying
    # a picture is never used as the text carrier.
    runs = [r for r in para.runs if not _run_has_drawing(r)]
```

Make the same change in `_set_paragraph_rich`: `existing = [r for r in para.runs if not _run_has_drawing(r)]`.

- [ ] **Step 4: Implement the picture helpers** (in `docx_service.py`, below `_text_width_emu`)

```python
_ALIGN_FROM_NAME = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}


def _make_floating(run_el, side):
    """Turn an inline picture into one text wraps around (Word's Square wrap),
    held to the left or right of the column."""
    inline = next(run_el.iter(qn("wp:inline")), None)
    if inline is None:
        return
    extent = inline.find(qn("wp:extent"))
    anchor = parse_xml(
        f'<wp:anchor {nsdecls("wp")} distT="0" distB="0" distL="114300" distR="114300" simplePos="0" '
        'relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="column"><wp:align>{side}</wp:align></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{extent.get("cx")}" cy="{extent.get("cy")}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapSquare wrapText="bothSides"/></wp:anchor>'
    )
    anchor.append(inline.find(qn("wp:docPr")))
    anchor.append(parse_xml(f'<wp:cNvGraphicFramePr {nsdecls("wp")}/>'))
    anchor.append(inline.find(qn("a:graphic")))
    inline.getparent().replace(inline, anchor)


def _add_picture_border(run_el):
    sppr = next(run_el.iter(qn("pic:spPr")), None)
    if sppr is None:
        return
    for old in sppr.findall(qn("a:ln")):
        sppr.remove(old)
    sppr.append(parse_xml(f'<a:ln {nsdecls("a")} w="9525"><a:solidFill><a:srgbClr val="404040"/></a:solidFill></a:ln>'))


def _place_picture(doc, para_el, source, spec, replace_drawing=None):
    para = Paragraph(para_el, doc)
    run = para.add_run()
    run.add_picture(source, width=Emu(int(_text_width_emu(doc) * spec["width_pct"] / 100)))
    if replace_drawing is not None:
        old = _owning_run(replace_drawing)
        old.addprevious(run._r)  # lxml moves the element
        old.getparent().remove(old)
    para.alignment = _ALIGN_FROM_NAME.get(spec.get("align"), WD_ALIGN_PARAGRAPH.LEFT)
    if spec.get("wrap") in ("left", "right"):
        _make_floating(run._r, spec["wrap"])
    if spec.get("border"):
        _add_picture_border(run._r)


def _insert_caption_after(doc, para_el, text, align):
    new_p = OxmlElement("w:p")
    para_el.addnext(new_p)
    para = Paragraph(new_p, doc)
    run = para.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    para.alignment = _ALIGN_FROM_NAME.get(align, WD_ALIGN_PARAGRAPH.LEFT)
    return new_p


def _drawing_blob(doc, drawing):
    blip = next(drawing.iter(qn("a:blip")), None)
    rid = blip.get(qn("r:embed")) if blip is not None else None
    part = doc.part.related_parts.get(rid) if rid else None
    return io.BytesIO(part.blob) if part is not None else None
```

Add `import io` at the top. Note: `_drawing_blob` uses `doc.part`, which holds the body's images. That is the scope of this change, since header images are out of scope.

- [ ] **Step 5: Wire the edits into `apply_content_edits`**

Inside `apply_content_edits`, before the main `for edit in edits:` loop, add an insert pass. It runs first so that an insert after a line that is also being deleted still lands:

```python
    from services import image_store  # local: docx_service must import without an app

    for edit in edits:
        if edit.get("action") != "insert_image":
            continue
        idx = edit.get("anchor_index")
        if not isinstance(idx, int) or not (0 <= idx < len(items)):
            continue
        path = image_store.image_path(edit.get("image_id"))
        if not path:
            continue  # the upload is gone; skip it rather than fail the save
        new_p = OxmlElement("w:p")
        items[idx]["el"].addnext(new_p)
        _place_picture(doc, new_p, path, edit)
        if edit.get("caption"):
            _insert_caption_after(doc, new_p, edit["caption"], edit.get("align"))
        applied += 1
```

Move `applied = 0` above this pass. In the existing loop, change `elif action == "format":` to pass `doc`. Picture handling lives in `_apply_paragraph_edit` so plan edits can never reach it: plans call `apply_doc_edits`, whose edits never carry these keys. At the **start** of `_apply_paragraph_edit`, add:

```python
    if "image_format" in edit or "remove_images" in edit:
        drawings = _paragraph_drawings(el)  # indices are against the original order
        for spec in edit.get("image_format") or []:
            if 0 <= spec["n"] < len(drawings):
                blob = _drawing_blob(doc, drawings[spec["n"]])
                if blob is not None:
                    _place_picture(doc, el, blob, spec, replace_drawing=drawings[spec["n"]])
                    if spec.get("caption"):
                        _insert_caption_after(doc, el, spec["caption"], spec.get("align"))
        for n in edit.get("remove_images") or []:
            if 0 <= n < len(drawings):
                run = _owning_run(drawings[n])
                if run is not None and run.getparent() is not None:
                    run.getparent().remove(run)
```

The `drawings[n]` reference stays valid after a replace, because `_place_picture` removes the *old* run. Removing an index that was also reformatted is a no-op, since its run already has no parent. The frontend never sends both for the same `n`.

- [ ] **Step 6: Sanitize the new edit shapes** (`format_routes.py`)

```python
_EDIT_ACTIONS = {"delete", "format", "insert_image"}
_IMG_ALIGNS = {"left", "center", "right"}
_IMG_WRAPS = {"inline", "left", "right"}
_IMG_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _image_spec(raw):
    try:
        pct = int(raw.get("width_pct", 50))
    except (TypeError, ValueError):
        pct = 50
    caption = raw.get("caption") if isinstance(raw.get("caption"), str) else ""
    return {
        "width_pct": max(10, min(100, pct)),
        "align": raw.get("align") if raw.get("align") in _IMG_ALIGNS else "left",
        "wrap": raw.get("wrap") if raw.get("wrap") in _IMG_WRAPS else "inline",
        "border": bool(raw.get("border")),
        "caption": caption.strip()[:300],
    }
```

Add `import re` if it is missing. In `_sanitize_content_edits`, after `edit = {...}`, add:

```python
        if action == "insert_image":
            if not isinstance(e.get("image_id"), str) or not _IMG_ID_RE.match(e["image_id"]):
                continue
            edit.update(_image_spec(e), image_id=e["image_id"])
```

Inside the `if action == "format":` block, add:

```python
            if isinstance(e.get("remove_images"), list):
                edit["remove_images"] = [n for n in e["remove_images"] if isinstance(n, int) and not isinstance(n, bool) and n >= 0]
            if isinstance(e.get("image_format"), list):
                specs = []
                for raw in e["image_format"]:
                    if isinstance(raw, dict) and isinstance(raw.get("n"), int) and raw["n"] >= 0:
                        specs.append({"n": raw["n"], **_image_spec(raw)})
                edit["image_format"] = specs
```

- [ ] **Step 7: Run all backend checks**

Run: `cd backend && venv/Scripts/python test_doc_edits.py && venv/Scripts/python test_rich_export.py && venv/Scripts/python test_field_roles.py`
Expected: every check prints OK.

- [ ] **Step 8: Commit**

```bash
git add backend/services/docx_service.py backend/routes/format_routes.py backend/test_doc_edits.py
git commit -m "Let the format builder remove, restyle and insert pictures; text edits keep pictures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Pictures in a plan's rich field values export to Word

**Files:**
- Modify: `backend/services/docx_service.py`, in `_RichLineParser`, `parse_rich_value` and `_set_paragraph_rich`.
- Test: `backend/test_rich_export.py`

**Interfaces:**
- Consumes: the generator's markup from Task 7, `<span class="lp-img img-align-X img-wrap-Y[ img-border]" data-img-id="ID" data-width-pct="P"><img ...><span class="lp-img-cap">caption</span></span>`. Also Task 3's `_place_picture` and Task 1's `image_store.image_path`.
- Produces: line dicts `{"runs": [], "list": None, "image": {"id", "width_pct", "align", "wrap", "border"}}`, plus a caption line whose `"align"` key is set.

- [ ] **Step 1: Write the failing tests** (add to `test_rich_export.py` and call them from its main)

```python
import io
import tempfile
from PIL import Image
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from app import create_app  # set DATABASE_URL=sqlite:// at the top of the file if not already


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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/Scripts/python test_rich_export.py`
Expected: FAIL in `check_image_lines_parse` (the texts lack the empty image line).

- [ ] **Step 3: Implement the parser**

In `_RichLineParser.__init__`, add `self.image = None` and `self.in_caption = False`. Change `innermost()` to read `frame.get(key)`. In `handle_starttag`'s `span` branch, before the existing push:

```python
            a = dict(attrs)
            if "lp-img" in classes and self.image is None:
                try:
                    pct = max(10, min(100, int(a.get("data-width-pct") or 50)))
                except ValueError:
                    pct = 50
                pick = lambda prefix, allowed, default: next(
                    (c[len(prefix):] for c in classes if c.startswith(prefix) and c[len(prefix):] in allowed), default)
                self.image = {
                    "id": a.get("data-img-id") or "",
                    "width_pct": pct,
                    "align": pick("img-align-", ("left", "center", "right"), "left"),
                    "wrap": pick("img-wrap-", ("inline", "left", "right"), "inline"),
                    "border": "img-border" in classes,
                    "caption": [],
                }
                self.span_stack.append({"img": True})
                return
            if "lp-img-cap" in classes and self.image is not None:
                self.in_caption = True
                self.span_stack.append({"cap": True})
                return
```

In `handle_endtag`, replace the `span` branch:

```python
        elif tag == "span" and self.span_stack:
            frame = self.span_stack.pop()
            if frame.get("cap"):
                self.in_caption = False
            elif frame.get("img"):
                img, self.image = self.image, None
                caption = img.pop("caption")
                if self.lines[-1]["runs"]:
                    self._new_line()
                self.lines[-1]["image"] = img
                if caption:
                    self._new_line()
                    self.lines[-1]["runs"] = caption
                    self.lines[-1]["align"] = img["align"]
                self._new_line()
```

At the top of `handle_data`, after the empty check, add:

```python
        if self.image is not None:
            if self.in_caption:
                self.image["caption"].append({"text": data, "bold": bool(self.bold), "italic": True,
                                              "underline": bool(self.underline), "size": "fs-sm",
                                              "color": None, "highlight": None})
            return
```

In `parse_rich_value`, keep image lines: `lines = [l for l in parser.lines if l.get("image") or any(r["text"].strip() for r in l["runs"])]`.

At the top of `_set_paragraph_rich`:

```python
    if line.get("image"):
        from services import image_store
        para = Paragraph(para_el, doc)
        for r in para.runs:
            if not _run_has_drawing(r):
                r.text = ""
        path = image_store.image_path(line["image"]["id"])
        if path:
            _place_picture(doc, para_el, path, line["image"])
        return
```

At the end of `_set_paragraph_rich`, add:

```python
    if line.get("align"):
        Paragraph(para_el, doc).alignment = _ALIGN_FROM_NAME.get(line["align"])
```

- [ ] **Step 4: Run all backend checks**

Run: `cd backend && for t in test_rich_export test_doc_edits test_images test_lesson_plan_drafts test_generate_selection; do venv/Scripts/python $t.py || break; done`
Expected: all OK.

- [ ] **Step 5: Commit**

```bash
git add backend/services/docx_service.py backend/test_rich_export.py
git commit -m "Export pictures in a plan's styled fields with size, alignment, wrap, border and caption

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Shared image module and the toolbar Image button

**Files:**
- Modify: `frontend/js/doc-toolbar.js`
- Modify: `frontend/js/api.js` (add `uploadImage` to `Api` next to `scanFormat`, and a `docImageUrl` helper)
- Modify: `frontend/css/style.css` (image styles and image bar)

**Interfaces:**
- Produces, as globals used by Tasks 6 and 7:
  - `Api.uploadImage(file) -> Promise<{id, url, width_px, height_px}>`
  - `docImageUrl(id) -> string`
  - `docImageMarkup({ id, widthPct = 50, align = "center", wrap = "inline", border = false, caption = "" }) -> string`
  - `readDocImage(fig) -> { width_pct, align, wrap, border, caption }`
  - `hydrateDocImages(rootEl) -> void` (sets each figure's CSS width from `data-width-pct`, and `src` for `data-img-id` figures)
  - `initDocImageTools({ rootEl, selectable(fig) -> bool, onChange(fig), onDelete(fig) }) -> { deselect() }`
  - `initDocImageInsert({ toolbarEl, beforePick() -> bool, onUploaded(result) })`
  - Toolbar markup gains `<button data-image-insert>` and `<input type="file" data-image-input hidden>`.

- [ ] **Step 1: api.js**

Next to `scanFormat` in `Api`:

```js
  uploadImage: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/images", { method: "POST", body: form });
  },
```

Below `API_URL`:

```js
// Built from the id, never taken from stored markup, so a saved plan can't point
// an <img> anywhere else.
function docImageUrl(id) {
  return `${API_URL}/api/images/${encodeURIComponent(id)}`;
}
```

(Confirm `apiFetch` returns parsed JSON. Check how `scanFormat` consumes it and match that.)

- [ ] **Step 2: Toolbar markup**

In `renderDocToolbar`, insert a group before the zoom group:

```js
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-image-insert="1" data-icon="image" title="Insert image" aria-label="Insert image"></button>
      <input type="file" data-image-input accept="image/png,image/jpeg,image/gif,image/webp" hidden />
    </div>
```

Also add `aria-label` equal to `title` on every existing icon-only button in the toolbar markup. Today they only have `title`, which screen readers don't reliably announce.

- [ ] **Step 3: The shared image module** (append to `doc-toolbar.js`)

```js
// ---------------------------------------------------------------------------
// Images: one markup, one image bar, used by the builder and the generator.
// The vocabulary is closed for the same reason the font sizes are: the Word
// export reproduces exactly these properties and nothing else.
// ---------------------------------------------------------------------------

const DOC_IMG_ALIGNS = ["left", "center", "right"];
const DOC_IMG_WRAPS = ["inline", "left", "right"];

function docImageMarkup({ id, widthPct = 50, align = "center", wrap = "inline", border = false, caption = "" }) {
  const cap = caption ? `<span class="lp-img-cap" contenteditable="true">${escapeHtml(caption)}</span>` : "";
  return `<span class="lp-img img-align-${align} img-wrap-${wrap}${border ? " img-border" : ""}" data-img-id="${escapeHtml(id)}" data-width-pct="${widthPct}" contenteditable="false"><img src="${docImageUrl(id)}" alt="">${cap}</span>`;
}

function docImgClassValue(fig, prefix, allowed, fallback) {
  const cls = Array.from(fig.classList).find((c) => c.startsWith(prefix));
  const val = cls ? cls.slice(prefix.length) : fallback;
  return allowed.includes(val) ? val : fallback;
}

function readDocImage(fig) {
  const cap = fig.querySelector(".lp-img-cap");
  return {
    width_pct: Math.max(10, Math.min(100, parseInt(fig.dataset.widthPct, 10) || 50)),
    align: docImgClassValue(fig, "img-align-", DOC_IMG_ALIGNS, "left"),
    wrap: docImgClassValue(fig, "img-wrap-", DOC_IMG_WRAPS, "inline"),
    border: fig.classList.contains("img-border"),
    caption: cap ? cap.textContent.trim() : "",
  };
}

function hydrateDocImages(rootEl) {
  rootEl.querySelectorAll(".lp-img").forEach((fig) => {
    fig.style.width = `${readDocImage(fig).width_pct}%`;
    const img = fig.querySelector("img");
    if (fig.dataset.imgId && img) img.src = docImageUrl(fig.dataset.imgId);
  });
}

function setDocImgClass(fig, prefix, value) {
  Array.from(fig.classList).filter((c) => c.startsWith(prefix)).forEach((c) => fig.classList.remove(c));
  fig.classList.add(prefix + value);
}

function initDocImageTools({ rootEl, selectable = () => true, onChange, onDelete }) {
  const bar = document.createElement("div");
  bar.className = "doc-img-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Image options");
  bar.hidden = true;
  const btn = (act, val, label, html) =>
    `<button type="button" class="doc-img-btn" data-act="${act}" data-val="${val}" aria-label="${label}" title="${label}">${html}</button>`;
  bar.innerHTML = [
    btn("w", 25, "Small", "S"), btn("w", 50, "Medium", "M"), btn("w", 75, "Large", "L"), btn("w", 100, "Full width", "Full"),
    '<span class="doc-img-sep"></span>',
    btn("align", "left", "Align left", Icons.alignLeft), btn("align", "center", "Align centre", Icons.alignCenter), btn("align", "right", "Align right", Icons.alignRight),
    '<span class="doc-img-sep"></span>',
    btn("wrap", "inline", "In line with text", "Inline"), btn("wrap", "left", "Wrap text, image left", "Wrap L"), btn("wrap", "right", "Wrap text, image right", "Wrap R"),
    '<span class="doc-img-sep"></span>',
    btn("border", "", "Border", "Border"), btn("caption", "", "Caption", "Caption"),
    btn("delete", "", "Delete image", Icons.trash),
  ].join("");
  document.body.appendChild(bar);

  let selected = null;

  function place() {
    if (!selected) return;
    const r = selected.getBoundingClientRect();
    bar.style.top = `${window.scrollY + r.top - bar.offsetHeight - 8}px`;
    bar.style.left = `${window.scrollX + Math.max(8, r.left)}px`;
  }

  function syncBar() {
    const s = readDocImage(selected);
    bar.querySelectorAll("[data-act]").forEach((b) => {
      const { act, val } = b.dataset;
      const on = (act === "w" && Number(val) === s.width_pct) || (act === "align" && val === s.align)
        || (act === "wrap" && val === s.wrap) || (act === "border" && s.border) || (act === "caption" && !!selected.querySelector(".lp-img-cap"));
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function select(fig) {
    deselect();
    selected = fig;
    fig.classList.add("lp-img-selected");
    const handle = document.createElement("span");
    handle.className = "lp-img-handle";
    handle.setAttribute("aria-hidden", "true");
    fig.appendChild(handle);
    bar.hidden = false;
    syncBar();
    place();
  }

  function deselect() {
    if (!selected) return;
    selected.classList.remove("lp-img-selected");
    selected.querySelectorAll(".lp-img-handle").forEach((h) => h.remove());
    selected = null;
    bar.hidden = true;
  }

  function changed() {
    hydrateDocImages(selected.parentElement || rootEl);
    syncBar();
    place();
    onChange(selected);
  }

  rootEl.addEventListener("click", (e) => {
    const fig = e.target.closest(".lp-img");
    if (fig && rootEl.contains(fig) && selectable(fig)) {
      if (e.target.closest(".lp-img-cap")) return; // typing a caption, not selecting
      select(fig);
    } else if (!bar.contains(e.target)) {
      deselect();
    }
  });

  bar.addEventListener("mousedown", (e) => e.preventDefault());
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b || !selected) return;
    const { act, val } = b.dataset;
    if (act === "w") selected.dataset.widthPct = val;
    else if (act === "align") setDocImgClass(selected, "img-align-", val);
    else if (act === "wrap") setDocImgClass(selected, "img-wrap-", val);
    else if (act === "border") selected.classList.toggle("img-border");
    else if (act === "caption") {
      const cap = selected.querySelector(".lp-img-cap");
      if (cap) cap.remove();
      else {
        const c = document.createElement("span");
        c.className = "lp-img-cap";
        c.contentEditable = "true";
        c.textContent = "Caption";
        selected.insertBefore(c, selected.querySelector(".lp-img-handle"));
        c.focus();
        document.getSelection().selectAllChildren(c);
      }
    } else if (act === "delete") {
      const fig = selected;
      deselect();
      onDelete(fig);
      return;
    }
    changed();
  });

  // Corner drag: width as a share of the line the picture sits in, so the
  // number means the same thing in the canvas and in the exported document.
  rootEl.addEventListener("pointerdown", (e) => {
    if (!e.target.classList.contains("lp-img-handle") || !selected) return;
    e.preventDefault();
    const fig = selected;
    const box = (fig.parentElement || rootEl).getBoundingClientRect();
    const left = fig.getBoundingClientRect().left;
    const move = (ev) => {
      const pct = Math.round(((ev.clientX - left) / box.width) * 100);
      fig.dataset.widthPct = String(Math.max(10, Math.min(100, pct)));
      fig.style.width = `${fig.dataset.widthPct}%`;
      place();
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      changed();
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  });

  document.addEventListener("keydown", (e) => {
    if (!selected) return;
    if (e.key === "Escape") deselect();
    else if ((e.key === "Delete" || e.key === "Backspace") && !e.target.closest(".lp-img-cap")) {
      e.preventDefault();
      const fig = selected;
      deselect();
      onDelete(fig);
    }
  });
  window.addEventListener("scroll", place, true);
  window.addEventListener("resize", place);

  return { deselect };
}

function initDocImageInsert({ toolbarEl, beforePick, onUploaded }) {
  const button = toolbarEl.querySelector("[data-image-insert]");
  const input = toolbarEl.querySelector("[data-image-input]");
  if (!button || !input) return;
  button.addEventListener("mousedown", (e) => e.preventDefault());
  button.addEventListener("click", () => {
    if (beforePick && !beforePick()) return;
    input.value = "";
    input.click();
  });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      showToast("Images must be 5 MB or smaller.", true);
      return;
    }
    button.disabled = true;
    try {
      onUploaded(await Api.uploadImage(file));
    } catch (err) {
      showToast(err.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
```

(`escapeHtml` and `showToast` already exist globally in `api.js`. Confirm with `grep -n "function escapeHtml\|function showToast" frontend/js/api.js`.)

- [ ] **Step 4: CSS** (append to `style.css`, near the doc-editor block)

```css
/* ---- Pictures inside the document canvas ---- */
.lp-img { display: block; position: relative; max-width: 100%; margin: 8px 0; line-height: 0; }
.lp-img img { width: 100%; height: auto; display: block; }
.lp-img.img-align-center { margin-left: auto; margin-right: auto; }
.lp-img.img-align-right { margin-left: auto; }
.lp-img.img-wrap-left { float: left; margin: 4px 16px 8px 0; }
.lp-img.img-wrap-right { float: right; margin: 4px 0 8px 16px; }
.lp-img.img-border img { outline: 1px solid #404040; }
.lp-img-cap { display: block; line-height: 1.4; font-size: 0.82em; font-style: italic; padding-top: 4px; text-align: inherit; }
.lp-img.img-align-center .lp-img-cap { text-align: center; }
.lp-img.img-align-right .lp-img-cap { text-align: right; }
.lp-img-selected { outline: 2px solid var(--primary); outline-offset: 2px; cursor: default; }
.lp-img-handle { position: absolute; right: -7px; bottom: -7px; width: 14px; height: 14px; border-radius: 3px; background: var(--primary); border: 2px solid var(--surface); cursor: nwse-resize; touch-action: none; }

.doc-img-bar { position: absolute; z-index: 60; display: flex; flex-wrap: wrap; align-items: center; gap: 2px; padding: 4px; max-width: min(560px, calc(100vw - 16px)); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); box-shadow: 0 6px 20px rgba(0,0,0,.12); }
.doc-img-btn { min-width: 36px; height: 36px; padding: 0 8px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text-heading); font-size: 13px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.doc-img-btn svg { width: 18px; height: 18px; }
.doc-img-btn:hover { background: var(--bg); }
.doc-img-btn[aria-pressed="true"] { border-color: var(--primary); color: var(--primary); background: var(--bg); }
.doc-img-btn[data-act="delete"] { color: var(--danger); }
.doc-img-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
.doc-img-sep { width: 1px; align-self: stretch; margin: 4px; background: var(--border); }
```

- [ ] **Step 5: Smoke check**

Load the format builder in a browser (Task 11 starts the server). Check that the toolbar renders with an Image button and that the console shows no errors. The behaviour is verified in Tasks 6 and 7.

- [ ] **Step 6: Commit**

```bash
git add frontend/js/doc-toolbar.js frontend/js/api.js frontend/css/style.css
git commit -m "Shared image tools: insert button, image bar with size, align, wrap, border, caption

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Format builder: deletes stick, Save keeps pending edits, pictures editable

**Files:**
- Modify: `frontend/js/format-builder.js`

**Interfaces:**
- Consumes: Task 5's `initDocImageTools`, `initDocImageInsert`, `readDocImage`, `hydrateDocImages`, `docImageMarkup`; the Task 3 edit shapes; the Task 2 markup (`data-docx-image`).

- [ ] **Step 1: Picture-blind line text**

A picture's caption must not count as the line's text. Add this helper, and use it in `extractAnchorState` instead of `el.textContent`:

```js
function lineTextWithoutImages(el) {
  const clone = el.cloneNode(true);
  clone.querySelectorAll(".lp-img").forEach((f) => f.remove());
  return clone.textContent;
}
```

In `extractAnchorState`, use `text: normalizeAnchorText(lineTextWithoutImages(el)),`.

- [ ] **Step 2: Snapshot pictures; capture native deletes and picture edits**

Add the state `let imageSnapshot = {}; // "anchor:n" -> readDocImage(fig)`. In `snapshotContentState()`, reset it and fill it:

```js
  imageSnapshot = {};
  docBuilderCanvas.querySelectorAll("[data-anchor-index] .lp-img[data-docx-image]").forEach((fig) => {
    const idx = fig.closest("[data-anchor-index]").dataset.anchorIndex;
    imageSnapshot[`${idx}:${fig.dataset.docxImage}`] = readDocImage(fig);
  });
```

At the end of `renderDocCanvas`, call `hydrateDocImages(docBuilderCanvas)`.

Rewrite `buildContentEdits()`:

```js
function buildContentEdits() {
  const edits = [];
  const present = new Set();
  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => present.add(parseInt(el.dataset.anchorIndex, 10)));

  // A line removed with Backspace/Delete is simply gone from the canvas; it has
  // to be sent as a delete or the next render brings it straight back. Worked
  // out fresh on every call, so undoing the Backspace un-deletes it too.
  const deletes = new Set(markedDeletes);
  Object.keys(contentSnapshot).forEach((key) => {
    const idx = parseInt(key, 10);
    if (!present.has(idx)) deletes.add(idx);
  });
  deletes.forEach((idx) => edits.push({ anchor_index: idx, action: "delete" }));

  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    if (deletes.has(idx)) return;
    const before = contentSnapshot[idx];
    if (!before) return;
    const now = extractAnchorState(el);
    const patch = {};
    if (now.text !== before.text) patch.text = now.text;
    if (now.bold !== before.bold) patch.bold = now.bold;
    if (now.italic !== before.italic) patch.italic = now.italic;
    if (now.underline !== before.underline) patch.underline = now.underline;
    if (now.align !== before.align) patch.align = now.align;
    if (headingEdits[idx] !== undefined) patch.heading = headingEdits[idx];
    if (listEdits[idx] !== undefined) patch.list = listEdits[idx];
    if (sizeEdits[idx]) patch.size = sizeEdits[idx];
    if (colorEdits[idx]) patch.color = colorEdits[idx];
    if (highlightEdits[idx]) patch.highlight = highlightEdits[idx];

    // Existing pictures in this line: removed, or restyled.
    const removed = [];
    const restyled = [];
    Object.keys(imageSnapshot).filter((k) => k.startsWith(`${idx}:`)).forEach((k) => {
      const n = parseInt(k.split(":")[1], 10);
      const fig = el.querySelector(`.lp-img[data-docx-image="${n}"]`);
      if (!fig) { removed.push(n); return; }
      const now = readDocImage(fig);
      if (JSON.stringify(now) !== JSON.stringify(imageSnapshot[k])) restyled.push({ n, ...now });
    });
    if (removed.length) patch.remove_images = removed;
    if (restyled.length) patch.image_format = restyled;

    if (Object.keys(patch).length) edits.push({ anchor_index: idx, action: "format", ...patch });

    // New pictures the teacher inserted into this line go in right after it.
    el.querySelectorAll(".lp-img[data-img-id]").forEach((fig) => {
      edits.push({ anchor_index: idx, action: "insert_image", image_id: fig.dataset.imgId, ...readDocImage(fig) });
    });
  });

  return edits;
}
```

Rename today's `deletedAnchors` to `markedDeletes` throughout the file: the declaration, `snapshotContentState()` and the Delete-line button handler. It now holds only the lines marked with the toolbar's Delete button. Lines missing from the canvas are recomputed on every call, so undo works.

- [ ] **Step 3: Wire the image tools and insertion**

Inside the `if (docToolbar) {` block, add:

```js
  initDocImageTools({
    rootEl: docBuilderCanvas,
    onChange: () => updateSaveContentButton(),
    onDelete: (fig) => { fig.remove(); updateSaveContentButton(); },
  });

  initDocImageInsert({
    toolbarEl: docToolbar,
    beforePick: () => {
      if (getSelectedAnchorEls().length) return true;
      showToast("Click into the line the picture should follow, then choose Insert image.", true);
      return false;
    },
    onUploaded: (res) => {
      const anchor = getSelectedAnchorEls().pop() || lastFocusedAnchor;
      if (!anchor) return;
      anchor.insertAdjacentHTML("beforeend", docImageMarkup({ id: res.id }));
      hydrateDocImages(anchor);
      updateSaveContentButton();
    },
  });
```

The file dialog steals the selection, so remember the last anchor. Declare `let lastFocusedAnchor = null;` near the state. In the existing `mouseup` and `keyup` listeners on `docBuilderCanvas`, add: `lastFocusedAnchor = getSelectedAnchorEls().pop() || lastFocusedAnchor;`.

- [ ] **Step 4: Save keeps pending edits**

Pull the body of the `docSaveContentBtn` click handler into a function, and make the handler call it:

```js
// Applies the canvas edits. Returns false when there was something to save and
// it didn't happen (the teacher cancelled, or the request failed), so callers
// can stop instead of quietly leaving work behind.
async function flushContentEdits() {
  const edits = buildContentEdits();
  if (!edits.length) return true;
  const deleteCount = edits.filter((e) => e.action === "delete").length;
  const warning = deleteCount
    ? `This permanently deletes ${deleteCount} line${deleteCount === 1 ? "" : "s"} from the document. This can't be undone. Continue?`
    : "Save these changes into the document? This can't be undone.";
  if (!confirm(warning)) return false;
  setButtonLoading(docSaveContentBtn, true, "Saving");
  try {
    if (editingFormatId) {
      await Api.editFormatContent(editingFormatId, edits);
      renderDocCanvas((await Api.getFormatTemplateHtml(editingFormatId)).html);
      showToast("Document updated — fields refreshed automatically.");
    } else {
      renderDocCanvas((await Api.editScannedContent(sourceTempToken, edits)).preview_html);
      showToast("Document updated.");
    }
    return true;
  } catch (err) {
    showError(err.message);
    return false;
  } finally {
    setButtonLoading(docSaveContentBtn, false);
  }
}
```

`docSaveContentBtn.addEventListener("click", flushContentEdits);`

In `createFormatBtn`'s handler, right after the name check, add:

```js
  if (isDocBased && !(await flushContentEdits())) return;
```

(`isDocBased` is computed one line later today. Move its declaration above this line.)

- [ ] **Step 5: Browser verification**

Use the running app (Task 11, Step 1) and the ILAW format, or upload `backend/uploads/T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx` as a new format:
1. The two logo pictures are visible in the canvas.
2. Click a logo, press Delete, click **Save changes to document**, and confirm. After the re-render the logo is gone.
3. Put the caret at the start of a line and press Backspace to merge it into the line above. Then click the **main Save button** (not "Save changes to document"). Reopen the format, and the merge has stuck.
4. Insert a picture after a line. Set it to L, centre, wrap right, border and caption "Test", then save. Download the source (the existing download endpoint) and open it in Word. The picture is floating right with a border, and the caption is italic below.
5. Undo a Backspace deletion before saving. The status reads "no unsaved changes" for that line, not "1 unsaved".

- [ ] **Step 6: Commit**

```bash
git add frontend/js/format-builder.js
git commit -m "Format builder: Backspace deletes and picture edits stick; Save keeps pending edits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Generator: students insert pictures while editing a field

**Files:**
- Modify: `frontend/js/generator.js`, in `sanitizeRichValueHtml` (around line 1299), `paintRestoredValues` (around line 1905) and `wireLiveDocToolbar` (around line 1510).

**Interfaces:**
- Consumes: Task 5's module, and Task 4's markup contract.

- [ ] **Step 1: Sanitizer keeps pictures**

In `sanitizeRichValueHtml`, before the generic `SPAN` branch, add:

```js
    } else if (tag === "SPAN" && child.classList.contains("lp-img")) {
      // Only uploaded pictures (an id of the exact shape the server issues);
      // the format's own pictures belong to the template, not to this field.
      const id = child.dataset.imgId || "";
      if (!/^[0-9a-f]{32}$/.test(id)) return;
      const s = readDocImage(child);
      const cap = child.querySelector(".lp-img-cap");
      const capHtml = cap && cap.textContent.trim() ? `<span class="lp-img-cap">${sanitizeRichValueHtml(cap)}</span>` : "";
      out += `<span class="lp-img img-align-${s.align} img-wrap-${s.wrap}${s.border ? " img-border" : ""}" data-img-id="${id}" data-width-pct="${s.width_pct}" contenteditable="false"><img src="${docImageUrl(id)}" alt="">${capHtml}</span>`;
```

Restructure the `if/else if` chain so this branch comes before `tag === "SPAN"`. Because the branch handles `lp-img-handle` by skipping it (it only rebuilds from the data), the handle is never stored. The stored caption loses `contenteditable`, and `paintRestoredValues` restores it in the next step.

- [ ] **Step 2: Repaint pictures**

In `paintRestoredValues`, after `el.innerHTML = rich;`, add:

```js
        hydrateDocImages(el);
        el.querySelectorAll(".lp-img-cap").forEach((c) => { c.contentEditable = "true"; });
```

- [ ] **Step 3: Wire the tools**

At the end of `wireLiveDocToolbar()`, add:

```js
  const fieldOf = (fig) => fig.closest("[data-field-key]");
  initDocImageTools({
    rootEl: liveDocWrap,
    // The format's own pictures are part of the template; only pictures a
    // student put into a field are theirs to change.
    selectable: (fig) => !!fig.dataset.imgId && !!fieldOf(fig),
    onChange: (fig) => { const f = fieldOf(fig); if (f) { syncFieldFromEl(f); markDirty(); } },
    onDelete: (fig) => { const f = fieldOf(fig); fig.remove(); if (f) { syncFieldFromEl(f); markDirty(); } },
  });

  let imageTargetRange = null;
  initDocImageInsert({
    toolbarEl: liveDocToolbar,
    beforePick: () => {
      const el = activeFieldEl();
      if (!el) {
        showToast("Click into a field first, then choose Insert image.", true);
        return false;
      }
      const sel = window.getSelection();
      imageTargetRange = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
      return true;
    },
    onUploaded: (res) => {
      const range = imageTargetRange;
      if (!range) return;
      const node = range.startContainer;
      const field = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement).closest("[data-field-key]");
      if (!field) return;
      const tpl = document.createElement("template");
      tpl.innerHTML = docImageMarkup({ id: res.id });
      range.collapse(false);
      range.insertNode(tpl.content.firstChild);
      hydrateDocImages(field);
      syncFieldFromEl(field);
      markDirty();
    },
  });
```


- [ ] **Step 4: Browser verification**

1. Generate or open a plan. Click into a field, insert a picture, and set it to M, right, wrap left, border and caption "Diagram".
2. Reload the page. The draft restore shows the picture with the same settings, and the caption is still editable.
3. Click a format logo in the generator document. No image bar appears.
4. Save, then **Export as Word** and open the file. The picture sits in that field's place, floating left, with a border and the italic caption.
5. Inspect `fieldRichValues` in the console. It contains no `lp-img-handle` and no `style=`.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/generator.js
git commit -m "Generator: insert and format pictures inside a field while editing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Field review popup before generating

**Files:**
- Modify: `frontend/generator.html`. Remove the `#generate-scope` block (lines ~214–220). Add the modal after `#preview-overlay`.
- Modify: `frontend/js/generator.js`. Replace `renderGenerateScope` and `selectedGenerateKeys` and their storage. Change the `generateFullBtn` handler to open the modal. Update `reportGenerationOutcome`'s wording. Add static marks.
- Modify: `frontend/css/style.css`. Add the modal list, the segmented toggle and the field highlights, and delete the `.generate-scope*` rules.

**Interfaces:**
- Produces: `staticKeys: Set<string>`, `selectedGenerateKeys() -> string[]` (every field not in `staticKeys`, in document order), `paintStaticMarks()`.

- [ ] **Step 1: Markup** (`generator.html`, after `#preview-overlay`)

```html
  <div class="modal-overlay" id="gen-review-overlay" hidden>
    <div class="modal-dialog gen-review-dialog" role="dialog" aria-modal="true" aria-labelledby="gen-review-title">
      <div class="modal-header">
        <h2 id="gen-review-title">Which fields should Alan write?</h2>
        <button type="button" class="modal-close" id="gen-review-close" aria-label="Close">&times;</button>
      </div>
      <div class="modal-body">
        <p class="text-sm mt-0">Fields set to <strong>Keep static</strong> are left exactly as they are. Alan won't write in them, and you can still type in them yourself. They're highlighted in your document behind this window.</p>
        <div class="gen-review-bulk">
          <button type="button" class="link-btn" data-review-all="gen">Generate all</button>
          <button type="button" class="link-btn" data-review-all="static">Keep all static</button>
        </div>
        <div id="gen-review-list"></div>
      </div>
      <div class="modal-footer gen-review-footer">
        <span class="text-sm" id="gen-review-hint"></span>
        <button type="button" class="btn btn-secondary" id="gen-review-cancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="gen-review-confirm">Generate</button>
      </div>
    </div>
  </div>
```

Check how `#preview-overlay` is opened and closed in `generator.js`, and how `.modal-footer` / `.link-btn` exist in `style.css`. Reuse whatever is there, and add `.modal-footer` / `.link-btn` styles only if they are missing.

- [ ] **Step 2: State and storage** (replace the `SCOPE_PREFIX` block through `selectedGenerateKeys`)

```js
// Which fields Alan must leave alone ("static"), remembered per format so a
// teacher who always writes their own Flow says so once. v1 stored only the
// heavy fields a teacher unticked; it seeds v2 so those choices carry over.
const SCOPE_V1 = "alignedGenScope:v1:";
const SCOPE_V2 = "alignedGenScope:v2:";
let staticKeys = new Set();

function loadStaticKeys() {
  try {
    const raw = localStorage.getItem(SCOPE_V2 + fmt.id) || localStorage.getItem(SCOPE_V1 + fmt.id);
    staticKeys = new Set(raw ? JSON.parse(raw) : []);
  } catch (err) {
    staticKeys = new Set();
  }
  const known = new Set((fmt.fields || []).map((f) => f.field_key));
  staticKeys.forEach((k) => { if (!known.has(k)) staticKeys.delete(k); });
}

function saveStaticKeys() {
  try {
    localStorage.setItem(SCOPE_V2 + fmt.id, JSON.stringify([...staticKeys]));
  } catch (err) {
    /* private mode or quota: the choice just won't persist */
  }
}

function selectedGenerateKeys() {
  return fieldsInDocumentOrder().map((f) => f.field_key).filter((k) => !staticKeys.has(k));
}

// Empty static fields keep a hatched "static" look after the popup closes, so
// the teacher can see which blanks are theirs to write.
function paintStaticMarks() {
  liveDocWrap.querySelectorAll("[data-field-key]").forEach((el) => {
    el.classList.toggle("lp-field-static", staticKeys.has(el.dataset.fieldKey));
  });
}
```

At the call site that used `renderGenerateScope()` (around line 2727), call `loadStaticKeys(); paintStaticMarks();` instead. Remove the `generateScope*` element constants (lines ~105–107).

- [ ] **Step 3: The popup**

```js
const reviewOverlay = document.getElementById("gen-review-overlay");
const reviewList = document.getElementById("gen-review-list");
const reviewConfirm = document.getElementById("gen-review-confirm");
const reviewHint = document.getElementById("gen-review-hint");

function reviewRowMarkup(f) {
  const key = escapeHtml(f.field_key);
  const isStatic = staticKeys.has(f.field_key);
  const filled = isFieldComplete(f.field_key) ? '<span class="gen-review-note">has content</span>' : "";
  return `
    <div class="gen-review-row" data-review-key="${key}">
      <span class="gen-review-label">${escapeHtml(f.label || f.field_key)}${filled}</span>
      <div class="seg" role="radiogroup" aria-label="${escapeHtml(f.label || f.field_key)}">
        <label><input type="radio" name="rv-${key}" value="gen" ${isStatic ? "" : "checked"}><span>Generate</span></label>
        <label><input type="radio" name="rv-${key}" value="static" ${isStatic ? "checked" : ""}><span>Keep static</span></label>
      </div>
    </div>`;
}

function renderReviewList() {
  const fields = fieldsInDocumentOrder();
  const groups = [
    ["Quick fields", fields.filter((f) => f.role !== "heavy")],
    ["Needs real thinking", fields.filter((f) => f.role === "heavy")],
  ].filter(([, list]) => list.length);
  reviewList.innerHTML = groups
    .map(([title, list]) => `<fieldset class="gen-review-group"><legend>${title}</legend>${list.map(reviewRowMarkup).join("")}</fieldset>`)
    .join("");
  syncReview();
}

function syncReview() {
  const n = selectedGenerateKeys().length;
  reviewConfirm.disabled = n === 0;
  reviewConfirm.textContent = n ? `Generate ${n} field${n === 1 ? "" : "s"}` : "Generate";
  reviewHint.textContent = n ? "" : "Set at least one field to Generate, or fill the plan in yourself.";
  liveDocWrap.querySelectorAll("[data-field-key]").forEach((el) => {
    const isStatic = staticKeys.has(el.dataset.fieldKey);
    el.classList.toggle("lp-field-review-gen", !isStatic);
    el.classList.toggle("lp-field-review-static", isStatic);
  });
}

reviewList.addEventListener("change", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (!row) return;
  if (e.target.value === "static") staticKeys.add(row.dataset.reviewKey);
  else staticKeys.delete(row.dataset.reviewKey);
  saveStaticKeys();
  syncReview();
});

// Pointing at a row shows where that field is in the document behind.
function pulseField(key) {
  const el = liveDocWrap.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("lp-field-review-pulse");
  void el.offsetWidth;
  el.classList.add("lp-field-review-pulse");
}
reviewList.addEventListener("mouseover", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (row && row.dataset.reviewKey !== reviewList.dataset.lastPulse) {
    reviewList.dataset.lastPulse = row.dataset.reviewKey;
    pulseField(row.dataset.reviewKey);
  }
});
reviewList.addEventListener("focusin", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (row) pulseField(row.dataset.reviewKey);
});

document.querySelectorAll("[data-review-all]").forEach((btn) => {
  btn.addEventListener("click", () => {
    staticKeys = btn.dataset.reviewAll === "static" ? new Set(fieldsInDocumentOrder().map((f) => f.field_key)) : new Set();
    saveStaticKeys();
    renderReviewList();
  });
});

let reviewReturnFocus = null;
function openReview() {
  reviewReturnFocus = document.activeElement;
  renderReviewList();
  reviewOverlay.hidden = false;
  reviewOverlay.querySelector("input, button").focus();
}

function closeReview() {
  reviewOverlay.hidden = true;
  liveDocWrap.querySelectorAll(".lp-field-review-gen, .lp-field-review-static, .lp-field-review-pulse")
    .forEach((el) => el.classList.remove("lp-field-review-gen", "lp-field-review-static", "lp-field-review-pulse"));
  paintStaticMarks();
  if (reviewReturnFocus) reviewReturnFocus.focus();
}

document.getElementById("gen-review-close").addEventListener("click", closeReview);
document.getElementById("gen-review-cancel").addEventListener("click", closeReview);
reviewOverlay.addEventListener("keydown", (e) => { if (e.key === "Escape") closeReview(); });
reviewConfirm.addEventListener("click", () => {
  closeReview();
  runFullGeneration();
});
```

The overlay must **not** cover the document fully. The highlights are the point. Give `.gen-review-dialog` a right-docked layout on wide screens (see the CSS), so the document stays visible on the left.

- [ ] **Step 4: The Generate button opens the popup**

Rename the current `generateFullBtn` click handler's function body to `async function runFullGeneration() { ... }`. Keep its gate check, the `selectedGenerateKeys().length` check and everything else as they are. Then:

```js
generateFullBtn.addEventListener("click", () => {
  if (!updateGate()) {
    showError("Fill in the cooperating teacher, subject, and course guide first.");
    return;
  }
  openReview();
});
```

In `reportGenerationOutcome`, change the "kept off my list" sentence to: `` `${list} ${n === 1 ? "is" : "are"} still blank because you kept ${n === 1 ? "it" : "them"} static. Fill ${n === 1 ? "it" : "them"} in whenever you are ready.` `` (where `n = yoursLabels.length`). Also call `paintStaticMarks()` at the end of it.

- [ ] **Step 5: CSS** (append; delete the old `.generate-scope*` rules)

```css
/* ---- Pre-generate field review ---- */
.gen-review-dialog { max-width: 520px; }
@media (min-width: 1100px) {
  #gen-review-overlay { justify-content: flex-end; background: rgba(0,0,0,.18); }
  .gen-review-dialog { height: calc(100vh - 32px); margin: 16px; display: flex; flex-direction: column; }
  .gen-review-dialog .modal-body { flex: 1; overflow: auto; }
}
.gen-review-bulk { display: flex; gap: 16px; margin: 4px 0 12px; }
.gen-review-group { border: 0; padding: 0; margin: 0 0 16px; }
.gen-review-group legend { font-weight: 700; font-size: 13px; color: var(--text-heading); margin-bottom: 6px; }
.gen-review-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.gen-review-label { font-size: 14px; color: var(--text-heading); }
.gen-review-note { margin-left: 8px; font-size: 11.5px; color: var(--text-body); font-style: italic; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; flex-shrink: 0; }
.seg label { cursor: pointer; }
.seg input { position: absolute; opacity: 0; pointer-events: none; }
.seg span { display: inline-block; padding: 8px 12px; font-size: 13px; font-weight: 600; color: var(--text-body); min-height: 36px; line-height: 20px; }
.seg input:checked + span { background: var(--primary); color: #fff; }
.seg input[value="static"]:checked + span { background: var(--text-body); }
.seg input:focus-visible + span { outline: 2px solid var(--primary); outline-offset: -2px; }
.gen-review-footer { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.gen-review-footer #gen-review-hint { margin-right: auto; }

.lp-field-review-gen { outline: 2px solid var(--primary); outline-offset: 2px; }
.lp-field-review-static,
.lp-field-static:not(.lp-filled) {
  background: repeating-linear-gradient(135deg, transparent 0 6px, rgba(100,116,139,.12) 6px 12px);
  outline: 1px dashed #94A3B8; outline-offset: 2px; position: relative;
}
.lp-field-review-static::after,
.lp-field-static:not(.lp-filled)::after {
  content: "static"; position: absolute; top: -9px; right: 4px; font-size: 10px; font-weight: 700;
  padding: 0 4px; border-radius: 3px; background: #64748B; color: #fff; line-height: 16px;
}
.lp-field-review-pulse { animation: review-pulse .9s ease-out 1; }
@keyframes review-pulse { 0% { box-shadow: 0 0 0 0 rgba(28,92,78,.45); } 100% { box-shadow: 0 0 0 12px rgba(28,92,78,0); } }
@media (prefers-reduced-motion: reduce) { .lp-field-review-pulse { animation: none; } }
```

- [ ] **Step 6: Browser verification**

1. Click **Generate full plan**. The popup lists every field in two groups, and the document behind shows teal outlines.
2. Set "Designed by Teacher/s" and "Declaration of AI use" to **Keep static**. Their slots turn hatched and tagged "static" behind the popup. Hovering a row scrolls to and pulses that field.
3. Click **Keep all static**. The confirm button is disabled and the hint shows. Click **Generate all**, and it is enabled again.
4. Confirm. Generation runs. The two static fields stay blank and hatched, every other field fills in, and Alan's message says they were kept static.
5. Reload the page and reopen the popup. The two fields are still static.
6. Press Escape to close the popup. Focus returns to the Generate button, and the review outlines are gone.

- [ ] **Step 7: Commit**

```bash
git add frontend/generator.html frontend/js/generator.js frontend/css/style.css
git commit -m "Review which fields Alan writes in a popup, with static fields highlighted in the document

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A bigger toolbar

**Files:**
- Modify: `frontend/css/style.css`. Delete the stale `.doc-toolbar` rule at around line 2746 (the space-between and border-bottom one). Its `.doc-toolbar-views` / `.doc-view-btn` siblings stay. Restyle the rules at around lines 3052–3130.

- [ ] **Step 1: Run the styling skill**

Invoke `ui-ux-pro-max:ui-styling` with a screenshot of the generator toolbar (Task 11, Step 1 has the server). Ask it to review touch-target size, grouping and density for a 40px toolbar on desktop and at 390px wide. Write down its concrete deltas, and apply them on top of Step 2 if they differ.

- [ ] **Step 2: CSS**

Delete the first `.doc-toolbar { ... justify-content: space-between ... }` rule. Change the remaining rules to:

```css
.doc-toolbar {
  position: sticky; top: 0; z-index: 20;
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 6px; padding: 8px 10px; margin-bottom: 12px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
}
.doc-toolbar-group { display: flex; align-items: center; gap: 4px; }
.doc-toolbar-sep { width: 1px; align-self: stretch; margin: 6px 4px; background: var(--border); }
.doc-tool-btn {
  min-width: 40px; height: 40px; padding: 0 10px;
  border: 1px solid transparent; border-radius: 8px; background: transparent;
  color: var(--text-heading); font-size: 15px; font-weight: 600; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
}
.doc-tool-btn svg { width: 20px; height: 20px; }
.doc-tool-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
.doc-tool-select { height: 40px; border: 1px solid var(--border); border-radius: 8px; padding: 0 10px; font-size: 14px; background: var(--surface); color: var(--text-heading); }
@media (max-width: 640px) {
  .doc-toolbar { gap: 4px; padding: 6px; }
  .doc-toolbar-sep { display: none; }
}
```

(Keep the existing `.doc-tool-btn` hover, active, danger and `.doc-toolbar-save` rules. Also check the old `.doc-tool-btn` block's remaining properties, such as `display` and `align-items` at around lines 3077–3093, and fold them into this one so there is a single `.doc-tool-btn` rule.) In fullscreen, check that `.doc-stage.is-pseudo-fullscreen` / `:fullscreen` still shows the toolbar at the top. It does, because it is `sticky` inside the stage.

- [ ] **Step 3: Browser verification**

The toolbar buttons measure 40×40 in DevTools on both the generator and the format builder. At 390px wide, the toolbar wraps without horizontal scroll. The colour menus still open below their buttons.

- [ ] **Step 4: Commit**

```bash
git add frontend/css/style.css
git commit -m "Make the document toolbar a 40px, sticky, readable bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Alan on the loaders, and Alan by name

**Files:**
- Create: `frontend/img/owl/alan-loading.png`
- Modify: every `frontend/*.html` that has `.page-transition` (the loader image and the asset version)
- Modify: `frontend/generator.html` (generation loader card, chat title)
- Modify: `frontend/js/generator.js` (`renderProgress` target, copy)
- Modify: `frontend/js/api.js` (OwlGuide copy)
- Modify: `frontend/css/style.css` (loader sizes, card)

- [ ] **Step 1: Make the asset**

```bash
cd frontend && backend_py=../backend/venv/Scripts/python
"$backend_py" - <<'EOF'
import io, zipfile
from PIL import Image
with zipfile.ZipFile("img/Alan_GuidedMode-CharacterUpdated.zip") as z:
    img = Image.open(io.BytesIO(z.read("Alan_GuidedMode-10.png"))).convert("RGBA")
# The canvas is 1920x1080 with Alan in the middle: crop to what isn't white.
bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
from PIL import ImageChops
bbox = ImageChops.difference(img, bg).getbbox()
img = img.crop(bbox)
# Pad 4% so the bob animation doesn't clip, then turn white into transparency.
pad = int(max(img.size) * 0.04)
canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (255, 255, 255, 0))
canvas.paste(img, (pad, pad))
px = canvas.load()
for y in range(canvas.height):
    for x in range(canvas.width):
        r, g, b, a = px[x, y]
        if r > 245 and g > 245 and b > 245:
            px[x, y] = (255, 255, 255, 0)
canvas.thumbnail((512, 512))
canvas.save("img/owl/alan-loading.png", optimize=True)
print(canvas.size)
EOF
```

Open `img/owl/alan-loading.png` with the Read tool and check it. Alan should be whole, with no white box around him, and his eye whites should still be there. The white-key removes only near-pure white, and the eyes are `#F5F5F5`-ish. If the eyes are punched out, switch to a flood fill from the corners: `ImageDraw.floodfill` on each corner with `thresh=10`.

- [ ] **Step 2: Run the brand check**

Invoke `taste-skill:brandkit` with the asset and the two placements (a full-page loader at about 120px, and a generation card). Ask only for presentation guidance on sizing, the motion's character, surface and type. Apply what fits the app's existing tokens. Do not introduce new brand colours or fonts.

- [ ] **Step 3: Page loader on every page**

```bash
cd frontend && grep -l 'class="page-transition"' *.html | xargs sed -i 's#<img src="img/owl/alan-idle.png" alt="" />\(\s*\)$#<img src="img/owl/alan-loading.png" alt="" />\1#'
grep -n -A1 'class="page-transition"' *.html | grep img
```

Expected: every page-transition `<img>` now points to `alan-loading.png`. The chat avatar (`class="owl-chat-avatar"`) is untouched, because it doesn't match the pattern.

In the CSS, change `.page-transition img` to `width: 120px;` and `.page-transition span` to `font-size: 14px`, and add:

```css
@media (prefers-reduced-motion: reduce) { .page-transition img { animation: none; } }
```

- [ ] **Step 4: Generation loader card**

In `generator.html`, replace `<div id="generation-progress" class="generation-progress mt-16" hidden></div>` with:

```html
<div id="generation-progress" class="gen-loader mt-16" hidden aria-live="polite">
  <img src="img/owl/alan-loading.png" alt="" class="gen-loader-owl" />
  <div class="gen-loader-body">
    <strong class="gen-loader-title">Alan is writing your plan…</strong>
    <div id="generation-progress-list" class="generation-progress"></div>
  </div>
</div>
```

In `generator.js`, `renderProgress` writes `generationProgressList.innerHTML = ...` (add `const generationProgressList = document.getElementById("generation-progress-list");`) and keeps `generationProgressEl.hidden = false`.

```css
.gen-loader { display: flex; align-items: center; gap: 20px; padding: 20px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.gen-loader-owl { width: 96px; height: auto; flex-shrink: 0; animation: page-transition-bob 1.4s ease-in-out infinite; }
.gen-loader-title { display: block; font-size: 16px; color: var(--text-heading); margin-bottom: 8px; }
@media (prefers-reduced-motion: reduce) { .gen-loader-owl { animation: none; } }
@media (max-width: 520px) { .gen-loader { flex-direction: column; text-align: center; } }
```

- [ ] **Step 5: Call him Alan**

```bash
cd frontend && grep -n -i "the owl\|ask the owl\|owl's\|owl is" *.html js/*.js | grep -v "^\s*//" 
```

For every hit that is **user-visible text**, meaning a string literal, HTML text node, `aria-label`, `placeholder` or `title`, change it to Alan: "Ask the owl" → "Ask Alan", "the owl" → "Alan", "The owl is typing" → "Alan is typing", and "the owl's" → "Alan's". Leave code comments and identifiers alone. Check the `generator.html` header `<strong>Ask the owl</strong>` and `aria-label="Chat with the owl"`, the `generator.js` step copy at `#step-controls` in the HTML, the chat-history empty message (around line 564), and the typing indicator (around line 274).

- [ ] **Step 6: Bump asset versions**

```bash
cd frontend && sed -i 's/?v=2026-09-24c/?v=2026-10-06a/g' *.html && grep -c "2026-10-06a" *.html | head -30
```

Use `git add -p` afterwards so the user's own uncommitted edits in `announcements.html` and `dashboard.html` are not swept into this commit. Stage only the loader image line and the version lines in those two files.

- [ ] **Step 7: Browser verification**

Navigating between pages shows Alan with the clipboard bobbing, at about 120px. Generating shows the card with Alan and the per-section progress. The chat header reads "Ask Alan". Grep for remaining user-visible "owl" text, which should return nothing.

- [ ] **Step 8: Commit**

```bash
git add frontend/img/owl/alan-loading.png frontend/css/style.css frontend/js/generator.js frontend/js/api.js frontend/generator.html
git add -p frontend/*.html
git commit -m "Alan on the page and generation loaders, and called Alan throughout

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: End-to-end verification

- [ ] **Step 1: Start the app**

Run in the background: `cd backend && venv/Scripts/python run.py`. Open `http://127.0.0.1:5000/` with Playwright and log in as a teacher test account. Ask the user for credentials if none are known. Generation spends the user's API credits, so run **at most one** full generation in this whole task, with most fields set to static.

- [ ] **Step 2: All backend self-checks**

```bash
cd backend && for t in test_*.py; do echo "== $t"; venv/Scripts/python "$t" || echo "FAILED: $t"; done
```

Expected: no `FAILED` lines. `test_migration_race.py` may need MySQL. If it was already skipped or failing before this branch (check with `git stash` if unsure), report it as pre-existing rather than fixing it.

- [ ] **Step 3: Re-run the browser checks** from Tasks 6, 7, 8, 9 and 10 in one pass, taking screenshots of: the review popup with highlights, an image with the image bar open, the toolbar at desktop and at 390px, and both Alan loaders.

- [ ] **Step 4: Design review**

Run `impeccable:impeccable` and `ui-ux-pro-max:design` on those screenshots (per the user's standing preference). Fix the material issues they raise, then re-screenshot.

- [ ] **Step 5: Commit any fixes**, then report to the user with what was verified and anything left.
