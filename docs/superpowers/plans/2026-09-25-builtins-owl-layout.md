# Built-ins, Owl Launcher and Layout Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship locked built-in lesson plan formats and official DepEd guides in the UI, make the owl the always-visible launcher for the Guided chat, and fix the layout problems the audit found on every page.

**Architecture:** Tasks 1 to 3 (backend, fixtures, guides) are already committed. The rest is frontend only: vanilla HTML/JS pages, one stylesheet, and the shared `api.js` loaded by every page. Shared fixes go into `api.js` and `style.css` once, so every page gets them without per-page code.

**Tech Stack:** Flask + SQLAlchemy backend (done), vanilla ES2017 browser JS with no build step, one `frontend/css/style.css`, icons as inline SVG strings in `frontend/js/icons.js`.

**Spec:** `docs/superpowers/specs/2026-09-25-builtins-owl-layout-design.md`

## Global Constraints

- All CSS in `frontend/css/style.css`, using the `:root` tokens. No CSS framework, no new dependency.
- Every element ID referenced by `frontend/js/*.js` stays. Check with the ID diff in Task 8.
- Icons: SVG from `frontend/js/icons.js` only. No emoji, no text glyphs (`+`, `&hellip;`, `✓`, `⟳`) standing in for icons.
- UI copy contains no em dashes.
- No single-sided accent borders on cards, panels or banners.
- At 390px: 16px side gutter, no horizontal page scroll, 44px minimum touch targets.
- Bump the asset query string on every page (`?v=2026-09-24c` becomes `?v=2026-09-25a`).
- Backend self-checks: `bash $CLAUDE_JOB_DIR/tmp/runtests.sh` (runs every `backend/test_*.py` with the main venv) must stay all OK.

## Audit results (drives Tasks 4 and 7)

Two independent passes (design review, detector plus browser measurement) over 19 page views at 1440px and 390px. Design health 26/40.

| Page | Verdict | Reasons | Fix (task) |
|---|---|---|---|
| dashboard | cramped, broken at 390 | Table titles wrap one letter per line; hero 320px tall; `&hellip;` menu glyph | T4 tables, T7 hero cap, T4 glyphs |
| lesson-plan | unfinished | Text "+" glyphs, em dash in intro, CTA between title and intro on phone, 140px empty tile | T5 redesign |
| lesson-plan-list | crowded, broken at 390 | Letter-per-line titles, pills wrap ("Dra/ft"), actions off screen, five unlabelled icon buttons | T4 tables, T4 pills, T4 titles on icon buttons |
| generator-setup | fine | Em dash in topic placeholder, placeholder truncated at 390 | T7 copy |
| generator-generate | unfinished | Empty state has nothing to click; `✓ … ⟳` glyphs | T7 empty-state CTA, T4 glyphs |
| format-builder | fine | Em dashes in intro | T4 copy sweep |
| course-guides | fine, rebuilt | Inline heading styles, "+" glyph | T6 redesign |
| my-classes | fine | Inline `max-width:420px`, inconsistent gaps | T7 |
| announcements | crowded, broken at 390 | Letter-per-line, pill goes vertical | T4 tables |
| settings | unfinished | `.hint` outside `.field` renders at 16px, 25 inline styles, brand subtitle differs | T4 hint, T7 settings |
| teacher-dashboard | unfinished | Empty table shows headers above "No lesson plans yet" | T7 |
| sections | fine | CTA between title and intro on phone | T4 header |
| submissions | fine | Inline filter row wraps 1 + 2 | T4 filter bar |
| teacher-announcements | crowded, broken at 390 | Letter-per-line, edit actions hidden | T4 tables |
| admin-dashboard | fine | Header buttons wrap above the intro | T4 header |
| admin-users | crowded, broken at 390 | Emails break mid-word, pills vertical, actions hidden, input and select heights differ | T4 tables, T4 control height |
| admin-sections | crowded | Names break, columns clipped, intro unbounded | T4 tables, T4 header |
| admin-documents | crowded | Letter-per-line, UPDATED clipped | T4 tables |
| admin-announcements | crowded, broken at 390 | Letter-per-line, actions hidden, em dashes | T4 tables, T4 copy |

Cross-page, measured: `.badge` text 2.93:1 contrast; table headers 11px; `.row-action-btn` 32px, `.row-menu-btn` 30x24, `.btn-sm` 31px, checkboxes 15px, banner close 20x22; `a.btn-primary:hover` text at 1:1 (`a:hover` beats `.btn-primary`); an emoji and em dash in `.lp-field.step-locked:empty::before`; `.auth-divider` 2.54:1; 107 inline `style=""` attributes.

## Review Focus

1. A teacher with no formats of their own and no shared ones: Lesson Plan page must still show the five built-ins, a clear "My formats" empty state, and no "Shared" section. Pinned in Task 5 Step 4.
2. Searching formats with a query that matches nothing in one section: that section hides; if nothing matches anywhere, one "No matching formats" message shows. Pinned in Task 5 Step 4.
3. Opening Guided mode on a 390px phone: owl visible, chat collapsed, tapping the owl opens a sheet above it that never overlaps it. Pinned in Task 8 owl check.
4. A table row whose title is one long unbroken string (an email or pasted URL) at 390px: wraps inside its card, no page overflow. Pinned in Task 9 Step 3.
5. A course guide search on the Course Guides page with a grade band that has no official guides and no uploads: an empty state that names the filter and offers to clear it. Pinned in Task 6 Step 3.

---

### Task 4: Shared layout foundation

**Files:**
- Modify: `frontend/css/style.css` (tokens, `.page-header`, `.page-subtitle`, `.data-table`, `.badge`, `.status-pill`, `.btn-sm`, `.row-action-btn`, `.row-menu-btn`, `.hint`, `.lp-field.step-locked:empty::before`, `a.btn` hover, `.auth-divider`; new `.table-scroll`, `.filter-bar`, `.page-actions`)
- Modify: `frontend/js/api.js` (new `labelTableCells()` wired once on load)
- Modify: `frontend/js/icons.js` (add `plus`, `moreHorizontal`, `lock`, `shieldCheck`, `externalLink`, `check`, `refresh` if missing)
- Modify: every `frontend/*.html` with a table wrapper or page header (replace `<div style="overflow-x:auto;">` with `<div class="table-scroll">`; move the intro paragraph into the header block)
- Modify: `frontend/js/dashboard.js`, `lesson-plan-list.js`, `generator.js` and any file emitting `&hellip;`, `+` or status glyphs as icons

**Interfaces:**
- Produces: CSS classes `.page-header` (grid: `.page-heading` block with `h1` + `.page-subtitle`, then `.page-actions`), `.table-scroll`, `.filter-bar`; tokens `--space-1..8` (4, 8, 12, 16, 20, 24, 32, 40px) and `--text-xs/sm/base/md/lg/xl` (12, 13, 14, 16, 20, 24px); global `labelTableCells(root = document)` in `api.js` that copies each `thead th` text onto the matching `td` as `data-label`.

- [ ] **Step 1: Tokens.** Add the spacing and type tokens to `:root`. Use them in every rule this plan touches; leave untouched rules alone.
- [ ] **Step 2: Phone tables become cards.** In `api.js`:

```js
// Lets a table read as stacked cards at phone width: each cell carries its
// column's header as data-label, which the CSS prints beside the value. Rows
// are rendered by each page's own script, so this watches for them instead
// of every page calling it.
function labelTableCells(root = document) {
  root.querySelectorAll("table.data-table").forEach((table) => {
    const heads = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent.trim());
    table.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).forEach((td, i) => {
        if (td.colSpan > 1) td.classList.add("cell-full");
        else if (heads[i] && !td.hasAttribute("data-label")) td.setAttribute("data-label", heads[i]);
      });
    });
  });
}
new MutationObserver(() => labelTableCells()).observe(document.documentElement, { childList: true, subtree: true });
```

CSS: `.data-table td` uses `overflow-wrap: break-word`. At `max-width: 640px`: `thead` visually hidden; `tr` is a bordered card (`display: grid; gap: var(--space-2); padding: var(--space-3) var(--space-4)`); `td` is `display: flex; justify-content: space-between; gap: var(--space-3); padding: 0; border: 0`; `td[data-label]::before { content: attr(data-label); }` in 12px uppercase body colour; the first cell spans full width, bold, no label; `.bulk-cell` cells sit top-left; the actions cell (`td:last-child` containing buttons) is full width with actions left-aligned; `.cell-full` spans full width with no label.
- [ ] **Step 3: One page header.** `.page-header` becomes a two-column grid: heading block (h1 plus `.page-subtitle` at `--text-sm`, max 640px, margin 6px top) and `.page-actions` (flex, wraps). At 640px and below, one column, actions after the subtitle. Delete the negative margin on `.page-subtitle` and every inline `style="margin-bottom:..."` on `h1.dash-page-title` and the intro `p`. Apply to every page in scope.
- [ ] **Step 4: Filter bar.** `.filter-bar { display:flex; flex-wrap:wrap; gap: var(--space-3); align-items:flex-end; margin-bottom: var(--space-5); }` with `.filter-bar .field { margin:0; flex: 1 1 180px; max-width: 280px; }` and one control height (`--control-h: 44px`) shared by `input`, `select` and `.btn`. Replace the five inline filter rows (admin-users, submissions, lesson-plan-list, admin-sections, admin-documents).
- [ ] **Step 5: Contrast and size fixes.** `.badge` colour `#7A5516` on `--accent-tint` (>= 4.5:1), 12px. Table `th` 12px. `.status-pill`, `.badge`: `white-space: nowrap`. `a.btn-primary:hover { color:#fff }` (and `.btn-secondary` equivalent). `.auth-divider` colour `var(--text-body)`. `.hint` global (not only under `.field`). Locked field placeholder: `content: "Locked. Finish the current field first."`, colour `var(--text-body)`, lock drawn with a mask of the `lock` SVG via a `background` data URI on `::before`, no emoji.
- [ ] **Step 6: Touch targets.** At `max-width: 640px`: `.row-action-btn`, `.row-menu-btn`, `.btn-sm`, `.icon-btn`, `.announcement-banner-close`, `.password-toggle-btn` min 44x44 (pad with `::after { inset:-6px }` where the visual size must stay); checkboxes 20px with a 44px label hit area.
- [ ] **Step 7: Glyph icons and copy.** Replace text `+` in CTAs with `Icons.plus`, `&hellip;` menus with `Icons.moreHorizontal`, status glyphs in `generator.js` with SVG. Give every icon-only button a `title` and `aria-label`. Replace em dashes in all UI strings (HTML and JS) with a comma, colon or full stop as the sentence needs. Verify: `grep -rn "—" frontend/*.html frontend/js/*.js` shows only comments.
- [ ] **Step 8: Check and commit.** Run the ID diff (Task 9 Step 1) and the 390px overflow check on every table page. Commit: "Shared layout pass: phone tables as cards, one page header, contrast and touch targets".

### Task 5: Lesson Plan page with built-in formats

**Files:**
- Modify: `frontend/lesson-plan.html`, `frontend/js/lesson-plan.js`, `frontend/css/style.css`

**Interfaces:**
- Consumes: `GET /api/formats` rows with `is_builtin`, `description`, `field_count`, `thumbnail`, `owner_id`, `is_public`; `Api.formatSourceUrl(id)` (append `?inline=1` for built-ins).
- Produces: sections `#builtin-section` (`#builtin-grid`), `#mine-section` (`#mine-grid`, `#mine-empty`), `#shared-section` (`#shared-grid`). Existing IDs kept: `new-format-btn`, `error-box`, `drafts-strip`, `drafts-list`, `format-search-row`, `format-search`, `loading-state`, `empty-state`.

- [ ] **Step 1: Markup.** Title "Create Lesson Plan", subtitle "Start from a ready-made school format, or use one of your own.", `+ New format` button with `Icons.plus`. Drafts strip unchanged. Search always visible. Three `<section>`s, each with an `h2` (`.section-title`) and a one-line description.
- [ ] **Step 2: Built-in card.** `.format-card.is-builtin`: thumbnail (`<img loading="lazy" width="480" height="679">` in a 4:3 cropped frame showing the top of page 1), "Built-in" badge with `Icons.lock`, name, description, meta "`N` fields", primary "Use this format" (to `generator.html?format_id=`), secondary "View original" (opens `formatSourceUrl(id) + "?inline=1"` in a new tab). No menu.
- [ ] **Step 3: Own and shared cards.** Keep the existing card and menu (menu button uses `Icons.moreHorizontal`). "New format" tile uses `Icons.plus` and is 96px tall at 390px.
- [ ] **Step 4: Render and search.** Split `formats` into built-in, mine (`owner_id === currentUser.id && !is_builtin`), shared (rest). Search filters all three; a section with no match hides (mine keeps its empty state only when there is no query); when nothing matches anywhere, show `#empty-state` "No matching formats". Verify in the browser: student with no own formats sees five built-ins, the mine empty state, no shared section; query "zzz" shows only the empty state; query "dlp" shows DLP and SNHS DLP.
- [ ] **Step 5: Commit.** "Lesson Plan page: ready-to-use formats first, then yours and shared ones".

### Task 6: Course Guides page and generator guide search

**Files:**
- Modify: `frontend/course-guides.html`, `frontend/js/course-guides.js`, `frontend/js/api.js` (`Api.searchCourseGuides(params)`), `frontend/js/generator.js` (guide search call), `frontend/css/style.css`

**Interfaces:**
- Consumes: `GET /api/course-guides?subject&q&grade_band&doc_type&prefer_grade_band`, rows with `is_builtin, doc_type, grade_band, grades, curriculum, retrieved_at, source_url`; `GET /api/course-guides/<id>/file`.
- Produces: `Api.searchCourseGuides(params)` where `params` is a string (legacy subject) or an object of the query keys above; `Api.courseGuideFileUrl(id)`.

- [ ] **Step 1: Filter bar.** Text search (`#subject-input` kept), grade chips (`#grade-chips`, buttons with `aria-pressed`: All, 4 to 6, 7 to 8, 9 to 10, SHS), subject segmented control (`#subject-filter`: All, ICT, Computer Programming mapping to `ICT` and `CP (ComProg)`), type select (`#type-filter`). Any change re-runs the search (debounced 250ms for text).
- [ ] **Step 2: Results.** Two groups, "Official DepEd" (`#official-grid`) and "Shared by teachers" (`#results-grid`, kept). Official card: `Icons.shieldCheck` "Official DepEd" badge, title, doc type label ("Budget of Work" or "Curriculum Guide"), "Grade 7" or "Grades 9 to 10", curriculum, "Retrieved 25 Sep 2026", "Open" link to the file URL (new tab). Teacher card as today, plus "Open".
- [ ] **Step 3: Empty states.** With filters set and no results: "No guides match these filters" plus a "Clear filters" button that resets all controls. With no filters and no results: current copy.
- [ ] **Step 4: Generator.** In the course guide search in `generator.js`, send `{subject, prefer_grade_band}` where the band comes from `#ctx-k12-grade` (4 to 6 to "4-6", 7 to 8 to "7-8", 9 to 10 to "9-10", 11 to 12 to "SHS"; college or unset sends none). Mark official results with the same badge.
- [ ] **Step 5: Verify and commit.** Browser: chips filter, "Computer Programming" shows only the CP BOW, "Open" loads the PDF, generator with Grade 9 lists the 9 to 10 guides first. Commit: "Course guides: official DepEd guides first, with grade, subject and type filters".

### Task 7: Per-page fixes from the audit

**Files:** `dashboard.html`, `generator.html`, `js/generator.js`, `my-classes.html`, `settings.html`, `js/dashboard.js`, `admin-sections.html`, all pages' `.brand-sub`, `frontend/css/style.css`

- [ ] **Step 1:** `.hero-banner` min-height 200px (160px at 640px and below), hero buttons one row with wrap gap `--space-2`.
- [ ] **Step 2:** Generate tab empty state gets a primary "Go to Setup" button that switches to the Setup tab via the existing tab button (`[data-tab="setup"]`).
- [ ] **Step 3:** Teacher dashboard: when the recent-plans table is empty, hide its `thead` and render `.empty-state` with a CTA to Submissions.
- [ ] **Step 4:** Settings: move inline heading and margin styles into `.panel-title` (16px, Space Grotesk) and spacing classes; `#banner-preview` gets no `src` attribute until set.
- [ ] **Step 5:** My Classes: join card uses `.panel.form-narrow`; remove inline styles.
- [ ] **Step 6:** `.brand-sub` reads "TLE-ICT Lesson Plan Maker" on every page.
- [ ] **Step 7:** Topic placeholder: "e.g. Cell formulas" with the explanation moved to a `.hint`.
- [ ] **Step 8: Commit.** "Per-page layout fixes from the audit".

### Task 8: Owl as the chat launcher (spec section 4)

**Files:** `frontend/js/api.js` (`OwlGuide.dock`, `OwlGuide.undock`, `OwlGuide.setUnread`), `frontend/js/generator.js` (`showOwlChat`, `setOwlChatCollapsed`, placement), `frontend/css/style.css` (`.owl-guide.is-docked`, `.owl-chat` placement, `.owl-unread`)

**Interfaces:**
- Produces: `OwlGuide.dock({ onToggle })`, `OwlGuide.undock()`, `OwlGuide.setExpanded(bool)`, `OwlGuide.setUnread(bool)`, `OwlGuide.rect()` returning the owl image's `DOMRect` or null; `OwlGuide.onMove(fn)` called after every drag or nudge.

- [ ] **Step 1:** Docked state: no auto-hide, `.is-docked` class (owl 96px, 64px at 640px and below, visible on phones only when docked), bubble still shows scripted lines but hides while `setExpanded(true)`. Owl image gets `role="button"`, `tabindex="0"`, `aria-controls="owl-chat"`, `aria-expanded`, `aria-label="Chat with the owl"`; click without drag and Enter or Space call `onToggle`.
- [ ] **Step 2:** `generator.js`: `showOwlChat(true)` docks and applies the stored state (`sessionStorage.owlChatOpen === "1"` opens, otherwise collapsed); remove the `max-width: 640px` auto-collapse line. `setOwlChatCollapsed(c)` hides the panel (`owlChat.hidden` stays false; `.is-collapsed` sets `display:none`), writes sessionStorage, calls `OwlGuide.setExpanded(!c)`, clears unread when opening. New owl reply while collapsed calls `setUnread(true)`. Leaving Guided calls `undock()`.
- [ ] **Step 3:** Placement function `placeChat()`: from `OwlGuide.rect()`, if `rect.left - 12 - 16 >= CHAT_W_MIN` then right edge at `innerWidth - rect.left + 12` and bottom aligned to `innerHeight - rect.bottom`, width min(stored, available); else sheet: `left:16px; right:16px; bottom: innerHeight - rect.top + 12`. Set via CSS custom properties `--chat-right`, `--chat-bottom`, `--chat-left`. Call on open, resize, owl move, chat resize. `chatMaxWidth()` uses the available width.
- [ ] **Step 4: Verify** at 1440 and 390 with Playwright: Guided opens collapsed with owl visible; clicking the owl opens the chat; `chat.right <= owl.left` (desktop) or `chat.bottom <= owl.top` (phone); drag owl 200px left, chat follows; reload keeps it open; Hide collapses. Commit: "Owl opens the Guided chat and is never covered by it".

### Task 9: Verification and report

- [ ] **Step 1: ID diff.** For every page, `grep -o 'id="[^"]*"'` before (`git show 0278d34:frontend/<page>`) and after; every ID referenced in `frontend/js/*.js` via `getElementById`/`querySelector('#…')` must still exist.
- [ ] **Step 2:** Backend suite all OK.
- [ ] **Step 3:** After screenshots at 1440 and 390 into `docs/superpowers/screenshots/2026-09-25/after/`, with the 390px overflow check.
- [ ] **Step 4:** `impeccable detect --json frontend` once; fix real findings.
- [ ] **Step 5:** Finish review of the changed pages against this plan's audit table.
- [ ] **Step 6:** Publish the report artifact (changes per task, built-in formats, guides table, cleanup confirmation, tests, before and after screenshots).
