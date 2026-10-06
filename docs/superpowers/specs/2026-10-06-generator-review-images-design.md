# Field review popup, sticky deletes, bigger toolbar, images, and Alan

Date: 2026-10-06
Status: approved in conversation, awaiting written-spec review

## Why

Reported together by the user:

1. **The generator writes into fields it shouldn't.** Only thinking-heavy
   fields have a checklist (inline on the page); every easy field (Designed by,
   Declaration of AI use, References, ...) is always written.
2. **Deletes in the format builder come back after saving, especially images.**
3. **The document toolbar is too small.**
4. **The owl should be Alan, and Alan should be on the loading screens**, using
   image 10 of `img/Alan_GuidedMode-CharacterUpdated.zip`.
5. (Added during design) **Teachers want to upload images and format them like
   in Word.**

## Decisions taken

Confirmed with the user before this spec was written:

- The pre-generate choice is per field: **Generate** or **Keep static**. A static
  field is never written by the AI and keeps whatever it already holds (template
  text, the teacher's own text, or blank). It stays editable by hand.
- The choice is made in a **popup modal**, not inline, while the live document
  highlights each field.
- Alan (image 10) goes on **both** loaders: the page-transition loader on every
  page and the "generating your plan" state.
- Image upload exists in **both** the format builder (becomes part of the
  format) and the generator, where it is **manual only**: a student inserts an
  image while editing a plan. The AI never inserts images.
- Image formatting: **resize, align, text wrap, caption and border**.

## 1. Field review popup

### Behaviour

`Generate full plan` opens a modal, `#gen-review-overlay`, instead of
generating straight away:

- Title: "Which fields should Alan write?"
- Every field of the format, in document order, in two groups: *Quick fields*
  (role `easy`) and *Needs real thinking* (role `heavy`). A group with no
  fields is not shown.
- Each row: the field label and a two-way segmented toggle, **Generate** /
  **Keep static** (radio buttons styled as a segmented control, so keyboard
  and screen-reader behaviour comes for free).
- "Generate all" and "Keep all static" links at the top.
- A field that already has content shows a small "has content" note, since
  generating it would overwrite that content.
- Footer: `Cancel` and `Generate N fields` (disabled when N = 0, with the
  existing "tick at least one field" wording as its hint).

While the modal is open, the live document behind it marks every field slot
(`[data-field-key]`):

- `.lp-field-review-gen`: teal outline.
- `.lp-field-review-static`: grey hatched fill with a "static" corner tag.

Hovering or focusing a modal row scrolls that slot into view and pulses it
(`.lp-field-review-pulse`, one short animation, none under
`prefers-reduced-motion`). Closing the modal removes the review classes.

### Generation and memory

`Generate N fields` closes the modal and generates exactly the kept set, using
the existing `include_keys` API. **No backend change.** `selectedGenerateKeys()`
reads from the modal state instead of the inline checklist.

The choice is remembered per format in localStorage under a new key,
`alignedGenScope:v2:<formatId>`, holding the list of static keys. When there is
no v2 entry, the v1 entry (excluded heavy keys) seeds it, so a teacher's earlier
choices carry over. Fields new to the format default to **Generate**, matching
today's behaviour.

### After generation

Static fields that are still empty keep the hatched `static` look, so the
teacher can see what is theirs to write. `reportGenerationOutcome()` already
separates "you chose to write these" from "couldn't generate"; its wording
changes from "unticked" to "kept static".

### Removed

The inline `#generate-scope` block in `generator.html` and its CSS.

## 2. Deletes that come back (format builder)

Root causes, found in `format-builder.js` / `docx_service.py`:

1. **Native deletes aren't sent.** `buildContentEdits()` iterates the anchors
   still in the DOM. A line removed with Backspace or Delete is no longer there,
   so no edit is produced, and the server re-render brings it back.
2. **Images are never rendered.** `_run_html()` returns `""` for a run with no
   text, so pictures are invisible in the canvas and cannot be selected.
   Clearing their paragraph's text leaves the `w:drawing` in the file.
3. **`Save changes` drops pending canvas edits.** The format-save button never
   applies edits that are still waiting behind `Save edits`.

Fixes:

1. `buildContentEdits()` also emits `{anchor_index, action: "delete"}` for every
   index in `contentSnapshot` that is no longer present in the canvas.
2. The renderer emits each drawing as an `<img>` (see §4.3), so it can be seen,
   selected, formatted and deleted. Deletion sends a `remove_images` edit.
3. `createFormatBtn` first applies pending edits (`buildContentEdits()`
   non-empty → `editFormatContent` / `editScannedContent`), then saves the
   format. The existing confirm dialog for destructive edits still shows.

## 3. Toolbar

Both screens use `renderDocToolbar()` from `doc-toolbar.js`, so the fix is CSS
plus the new image button.

- `.doc-tool-btn`: 40px min-width and height, 20px icons, 14px label text.
- Toolbar selects (heading, size): 40px height, 14px font.
- Controls grouped with thin dividers (text style | marks | colour | lists |
  alignment | image | view), wrapping cleanly on narrow screens.
- The toolbar stays sticky at the top of its stage, including in fullscreen.
- `style.css` has two `.doc-toolbar` rules (around lines 2746 and 3052). They
  are merged into one so the sizing is not fought over.

Exact spacing is set during implementation with the `ui-ux-pro-max:ui-styling`
skill.

## 4. Images

### 4.1 Upload API

`POST /api/images` (multipart, field `file`), logged-in users only.

- Accepts PNG, JPEG, GIF and WebP up to 5 MB. Validated by opening with Pillow,
  not by trusting the extension or MIME type. Anything else returns 400.
- Stored at `uploads/images/<uuid>.<ext>`. New table `images(id uuid, owner_id,
  filename, width_px, height_px, created_at)`, created through the existing
  `db.create_all()` / `_add_column` setup.
- Returns `{id, url: "/api/images/<id>", width_px, height_px}`.

`GET /api/images/<id>` serves the file to any logged-in user. Plans and formats
can be public, so the image must be readable by anyone who can read them. Ids
are unguessable UUIDs.

### 4.2 The image vocabulary

One fixed vocabulary, shared by the canvas, the sanitizers and the exporter, in
the same way as the font-size classes:

| Property | Classes | Word |
|---|---|---|
| Width | `img-w-sm` (25%), `img-w-md` (50%), `img-w-lg` (75%), `img-w-full` (100% of the text column), or a free width from drag-resizing stored as `data-width-pct` (10–100) | picture width as a share of the section's text width |
| Align | `img-align-left`, `img-align-center`, `img-align-right` | paragraph alignment |
| Wrap | `img-wrap-inline` (default), `img-wrap-left`, `img-wrap-right` | inline picture, or a floating `wp:anchor` with `wrapSquare`, positioned left or right |
| Border | `img-border` | thin picture outline (`a:ln` in the picture's `spPr`, 0.75pt, dark grey) |
| Caption | a `<figcaption>` inside `<figure class="lp-img">` | italic small paragraph directly below |

Markup:

```html
<figure class="lp-img img-w-md img-align-center img-wrap-inline" data-img-id="<uuid>" contenteditable="false">
  <img src="/api/images/<uuid>" alt="">
  <figcaption contenteditable="true">Optional caption</figcaption>
</figure>
```

### 4.3 Format builder

- **Rendering existing pictures:** `_render_runs_html()` emits, for a run
  containing a `w:drawing`, a `<figure class="lp-img ..." data-docx-image="<n>">`
  with the image embedded as a data URI (read from the related image part).
  `n` is the drawing's index within its paragraph. The width class is derived
  from `wp:extent` against the section's text width; a floating anchor maps to
  its wrap side.
- **Edits**, all validated by `_sanitize_content_edits()`:
  - `{anchor_index, action: "format", remove_images: [n, ...]}`
  - `{anchor_index, action: "format", image_format: {n, width, align, wrap, border, caption}}`
  - `{anchor_index, action: "insert_image", image_id, width, align, wrap, border, caption}`
    inserts a new paragraph holding the picture after that line (and a caption
    paragraph if one is given).
- These are applied in `apply_content_edits()`. Inserts are applied after
  deletes and formats, from the highest anchor to the lowest, so indices stay
  valid. Fields are re-detected afterwards, as today.

### 4.4 Generator (manual only)

- The image button is enabled only while the caret is inside a field slot. A
  picture can only live in a field's rich value. Non-field lines of a plan are
  edited through `doc_edits`, which are text and format only.
- `sanitizeRichValueHtml()` keeps `figure.lp-img` with only the vocabulary
  classes, `data-img-id` (UUID-shaped), `data-width-pct` (integer 10–100), the
  inner `<img>` with `src` rebuilt from the id (never trusted from the DOM), and
  `<figcaption>` text with the existing inline marks.
- `_RichLineParser` turns a figure into its own line
  `{"image": {...}, "runs": [], "list": None}`, plus a caption line.
  `parse_rich_value()` keeps image lines even though they have no text.
  `_set_paragraph_rich()` writes an image line with `run.add_picture()`, then
  applies alignment, wrap, border and caption.
- The backend sanitizer for rich values gets the same allow-list. An image id
  is only exported if the file exists, so a missing image is skipped rather
  than failing the export.

### 4.5 Image bar (frontend)

Shared in `doc-toolbar.js` so both screens behave the same:

- Clicking a figure selects it (`.lp-img-selected`) and shows a floating bar
  above it with: S / M / L / Full, align left / center / right, wrap inline /
  left / right, border toggle, caption toggle, and delete.
- Corner handle drag-resize, keeping the aspect ratio, sets `data-width-pct`.
- Delete or Backspace on a selected figure removes it. In the builder this
  records a `remove_images` edit for an existing picture, or simply drops a
  pending insert.
- Every control is a real `<button>` with an `aria-label`. The bar closes on
  Escape or a click outside the figure.

## 5. Alan

- Extract `Alan_GuidedMode-10.png` from
  `img/Alan_GuidedMode-CharacterUpdated.zip`, crop away the empty canvas,
  scale it to about 512px tall, and save it as
  `frontend/img/owl/alan-loading.png`.
- **Page loader:** every page's `.page-transition` uses `alan-loading.png` at
  about 120px, keeps the bob animation (removed under `prefers-reduced-motion`),
  and says "Loading…".
- **Generation loader:** while a full plan is generated, a centred card in the
  generate panel shows Alan, "Alan is writing your plan…", and the existing
  per-section progress list. It replaces the bare progress list.
- **Name:** user-facing "the owl" / "Ask the owl" becomes "Alan" / "Ask Alan"
  (chat header, placeholders, step-mode copy, guide tooltips, toasts).
  File names and code identifiers stay as they are.
- Alan is never the chat's open/close control (an existing rule).
- Presentation is checked against the `taste-skill:brandkit` skill during
  implementation.

Bump the `?v=` asset version on every page touched.

## Testing

| Check | What it pins down |
|---|---|
| `test_images.py` (new) | Upload accepts a real PNG and rejects a renamed `.txt` and a file over 5 MB; GET serves it; an anonymous request is refused |
| `test_doc_edits.py` (extended) | `remove_images` strips the drawing from the saved .docx; `insert_image` adds a picture after the right line with the requested width, alignment, wrap, border and caption; `image_format` resizes an existing picture |
| `test_rich_export.py` (extended) | A rich value containing a figure exports a picture with each option; a figure whose image file is missing is skipped |
| Browser pass | Backspace-deleted lines and deleted images stay deleted after `Save edits` and after `Save changes`; the review modal highlights fields and the static ones stay blank after generation; toolbar buttons are 40px; Alan shows on both loaders; image bar works with the keyboard |

## Out of scope

- Images in Word headers and footers (the user's live format has none).
- Removing a field from a format or plan (static covers the need).
- AI-inserted images.
- Cropping or rotating images.
