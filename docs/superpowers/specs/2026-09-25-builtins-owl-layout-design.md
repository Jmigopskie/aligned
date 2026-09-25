# Built-in formats, official DepEd guides, owl chat launcher, and a layout pass

Date: 2026-09-25
Status: approved, ready for implementation planning

## Why

Four requests, taken together because they all touch the "make a lesson plan" path:

1. **No ready-made formats.** A new teacher lands on an empty format picker. The
   five school formats in `backend/uploads/` (4A's, DLP, ILAW, PAL3 SDLP, SNHS
   DLP) should be available to everyone out of the box, and nobody should be
   able to edit or delete them.
2. **The owl chat covers the owl.** `.owl-chat` (z-index 45) and `.owl-guide`
   (z-index 40) are both pinned bottom-right, and `showOwlChat(true)` calls
   `OwlGuide.hide()`. The chat also opens by default on desktop, and on a phone
   the owl is `display: none`, so there is nothing to reopen it from except the
   chat's own header strip.
3. **The course guide library starts empty.** Teachers have to find and upload
   DepEd's documents themselves. The two real DepEd documents already uploaded
   (`3_G7_TLE__ICT.pdf`, `1_G9___G10_TLE__ICT_-_Computer_Programming.pdf`) are
   DepEd's **Three-Term Budget of Work** (BOW), "Last updated April 7, 2026",
   which is what schools teach from now.
4. **Several pages feel cramped or unfinished.** Needs an audit, then fixes.

## Decisions taken

Confirmed with the user before this spec was written:

- Built-in files live in a **tracked** `backend/builtin/` directory, because
  `backend/uploads/` is gitignored and would never reach the VPS.
- Built-in format fields are **detected once** with the existing PDF-to-DOCX and
  `_suggest_fields` flow, reviewed by hand, and **frozen** into a committed
  `formats.json`. Startup seeding reads the file and never calls the AI.
- Guide scope is **ICT and Computer Programming only**. No Home Economics,
  Agri-Fishery Arts, Industrial Arts or other TLE components are sourced or
  listed as missing. The generator's subject list stays at its two values,
  `ICT` and `CP (ComProg)`.
- BOW documents are preferred sources, since schools follow them now. The
  official MATATAG EPP/TLE Curriculum Guide is included alongside.
- The chat's open or collapsed choice is kept in **sessionStorage**. The prompt
  said "localStorage for the session", but localStorage would make one "open"
  click permanent and break "Guided always starts minimized". sessionStorage
  survives reloads in the tab and resets on a new visit.

## 1. Backend: built-ins

### Files

```
backend/builtin/
  formats/
    formats.json            # manifest, fields frozen from one-off AI detection
    4as-lesson-plan.pdf     # the five originals, renamed to slugs
    4as-lesson-plan.docx    # converted, fillable template (anchor_index targets)
    ...
  course_guides/
    guides.json             # manifest
    SOURCES.md              # every file's source URL and retrieval date
    *.pdf
```

`formats.json` entry:

```json
{
  "key": "4as-lesson-plan",
  "name": "4A's Lesson Plan",
  "description": "Activity, Analysis, Abstraction, Application.",
  "source": "4as-lesson-plan.pdf",
  "template": "4as-lesson-plan.docx",
  "fields": [{"field_key": "...", "label": "...", "field_type": "textarea",
              "anchor_index": 12, "is_required": true, "role": null}]
}
```

`guides.json` entry:

```json
{
  "key": "bow-g7-tle-ict",
  "title": "[G7] TLE: ICT, Three-Term Budget of Work",
  "subject": "ICT",
  "doc_type": "budget_of_work",
  "grade_band": "7-8",
  "grades": "7",
  "curriculum": "MATATAG",
  "file": "bow-g7-tle-ict.pdf",
  "source_url": "https://...",
  "retrieved_at": "2026-09-25"
}
```

`subject` is `ICT` or `CP (ComProg)`, matching the generator's option values
exactly. `doc_type` is `budget_of_work` or `curriculum_guide`. `grade_band` is
`4-6`, `7-8`, `9-10` or `SHS`.

### Columns

Added with `_add_column` in `app.py`, never a bare ALTER:

- `lesson_plan_formats`: `is_builtin BOOLEAN NOT NULL DEFAULT 0`,
  `builtin_key VARCHAR(64)`, `description VARCHAR(255)`.
- `course_guides`: `is_builtin BOOLEAN NOT NULL DEFAULT 0`,
  `builtin_key VARCHAR(64)`, `doc_type VARCHAR(20)`, `grade_band VARCHAR(8)`,
  `grades VARCHAR(20)`, `curriculum VARCHAR(20)`, `source_url VARCHAR(500)`,
  `retrieved_at DATE`.

### Seeding

New module `backend/services/builtins.py` with `seed_builtins(app)`, called in
`create_app()` after the migrations and `_ensure_default_admin`.

- Idempotent, keyed on `builtin_key`. Missing rows are inserted; existing
  built-in rows have their name, description, metadata and fields refreshed
  from the manifest when they differ. Rows that are not built-in are never read
  or written.
- Owner and uploader is the bootstrap admin (both FKs are NOT NULL).
- Formats point `source_file_path` and `template_docx_path` at the files in
  `backend/builtin/formats/`, as absolute paths resolved at seed time, so the
  existing `docx_service.resolve_*` helpers work unchanged. `is_public = True`.
- Guides run `text_extract.extract_text` once on insert and store `file_hash`.
- Three gunicorn workers boot at once. Each insert is committed on its own;
  an `IntegrityError` on the unique `builtin_key` (created as a unique index by
  the seeder, tolerant of "already exists") is rolled back and skipped.
- A missing file or bad manifest entry is logged and skipped. It never stops
  the app from booting.

### Locking

`format_routes._reject_if_builtin(fmt)` returns a 403, "Built-in formats are
read-only.", and is the first check in `update_format`, `delete_format`,
`edit_format_content` and `set_field_roles`. Course guides have no edit or
delete routes, so the upload route's hash dedupe is the only interaction: an
upload identical to a built-in returns the built-in row.

### Serialisation and search

- `LessonPlanFormat.to_dict` adds `is_builtin`, `description`, `field_count`,
  and `thumbnail` (a relative `img/formats/<key>.webp` path, built-ins only).
- `CourseGuide.to_dict` adds `is_builtin`, `doc_type`, `grade_band`, `grades`,
  `curriculum`, `source_url`, `retrieved_at`, `has_file`.
- `GET /course-guides` accepts `subject`, `q`, `grade_band`, `doc_type`,
  orders `is_builtin DESC, created_at DESC`, and raises the limit to 50.
- New `GET /course-guides/<id>/file` streams the file inline, login required.
- `GET /formats/<id>/source` accepts `?inline=1` to open the PDF in a tab
  instead of downloading it.

### Thumbnails

Page 1 of each built-in format rendered once with PyMuPDF (already installed
as a pdf2docx dependency) to `frontend/img/formats/<key>.webp`, 480px wide.

## 2. Lesson Plan page

Title "Create Lesson Plan". Order:

1. Header with the title, subtitle and "New format" button (plus icon).
2. "Continue where you left off", unchanged.
3. Search, always visible.
4. **Ready-to-use formats**: a card per built-in with thumbnail, a "Built-in"
   badge with a lock icon, name, description, "N fields", a primary
   "Use this format" and a secondary "View original". No edit or delete menu.
5. **My formats**: the teacher's own formats with the existing menu, then the
   "New format" tile. Empty state invites them to add one.
6. **Shared by other teachers**: other teachers' public formats, shown only
   when there are any.

Search filters all three sections; a section with no matches is hidden.

## 3. Course Guides page

- Filter bar: text search, grade-band chips (All, 4 to 6, 7 to 8, 9 to 10,
  SHS), subject toggle (All, ICT, Computer Programming), type select (All,
  Budget of Work, Curriculum Guide).
- Results grouped **Official DepEd** then **Shared by teachers**. Built-in
  cards carry an "Official DepEd" badge with a shield icon, doc type, grades,
  curriculum label, retrieved date and an "Open" link.
- Upload panel unchanged.

In the generator, the course guide search also sends the chosen grade band,
derived from the grade level select, so built-ins for that grade come first.

## 4. Owl as the chat launcher

- `OwlGuide.dock({ onToggle })` and `OwlGuide.undock()` in `api.js`. Docked:
  no auto-hide, a click that is not a drag calls `onToggle` instead of passing
  through, `role="button"`, `aria-controls="owl-chat"`, `aria-expanded`,
  Enter and Space toggle. Drag and arrow-key nudging still work.
- `showOwlChat(true)` docks the owl instead of hiding it; leaving Guided
  undocks it.
- Owl z-index 46, chat 45. The chat is placed from the owl's rect: to the left
  of the owl with a 12px gap, bottom-aligned, when there is room for the chat's
  minimum width; otherwise as a full-width sheet above the owl with 16px
  gutters. Recomputed on owl move, window resize and chat resize.
- Docked owl is 96px wide on desktop and 64px at 640px and below, where it is
  visible only while docked. Speech bubbles stay hidden on phones.
- Collapsed means the panel is hidden and only the owl shows. Guided always
  starts collapsed. The header "Hide" button collapses. A new owl reply while
  collapsed shows an unread dot on the owl.
- The choice is stored under sessionStorage `owlChatOpen`.
- Scripted lines still show in the owl's bubble while collapsed; suppressed
  while the chat is open.
- `.owl-chat-open` room on `.dash-main` includes the owl's width.

## 5. Layout audit and redesign

1. Before screenshots of every page at 1440px and 390px into
   `docs/superpowers/screenshots/2026-09-25/before/`.
2. Audit each with `/impeccable` critique and the `/ui-ux-pro-max`
   guidelines. The results table (page, verdict, reasons, fix) is recorded in
   the implementation plan, since it drives those tasks.
3. Fix shared problems first, then each flagged page.
4. After screenshots into `after/`, and an `/impeccable` finish review.

Constraints: all CSS in `style.css` with existing tokens, Space Grotesk
headings, no framework; every element ID used by `js/*.js` kept (checked by
diffing the ID lists); SVG icons from `icons.js` only; no em dashes in UI copy;
no single-sided accent borders; 16px gutter and no horizontal scroll at 390px;
44px touch targets; asset version bumped.

## Existing uploads that are not curriculum guides

Reported, not deleted:

- `uploads/course_guides/1_DEPED_SDLP_FORMAT.docx.pdf`: a filled-in 4A's
  semi-detailed lesson plan (TUP Cavite, TLE CSS).
- `uploads/course_guides/1_HTML_EVENT_HANDLING_DLP.pdf`: a filled-in Grade 10
  TLE ICT detailed lesson plan (Salawag NHS).

## Scraping cleanup

Guides are located with the browser and downloaded with plain `curl` into the
job's scratch directory. No scraping script, temporary file or dependency is
added to the repository. `requirements.txt` is unchanged.

## Testing

`backend/test_builtins.py`, standalone like the others:

- seeding twice gives the same rows; a changed manifest updates a built-in
- a user's own format and user-uploaded guides are untouched by seeding
- 403 on all four mutating format routes for a built-in, even for the admin
  who owns it; a teacher's own format still edits
- every user sees built-ins in `GET /formats`
- guide search puts built-ins first and filters by grade band and doc type
- `GET /course-guides/<id>/file` serves the file

Frontend behaviour is verified in the browser at 1440px and 390px.
