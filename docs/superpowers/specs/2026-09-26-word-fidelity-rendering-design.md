# Document view that looks like the file in Word

Date: 2026-09-26
Status: design approved in conversation, spec awaiting review

## Why

The document a teacher sees in the app (the generator's live document, the format
builder canvas and the two plan previews) is HTML drawn from the format's .docx by
`docx_service.render_template_html` / `render_reference_html`. It looks noticeably
different from the same file opened in Word. The user's target is their own ILAW
plan, `backend/uploads/T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx`: viewed in the app
it must look like it does in Word or any other document viewer.

Side-by-side renders (LibreOffice vs app) of that file and the five built-ins showed:

1. **Page size ignored.** Every document is squeezed into a 760px portrait sheet.
   ILAW is 13 x 8.5 in landscape, so cells wrap into tall slivers ("Sectio / n").
2. **Pictures dropped.** Logos (`w:drawing`) never render.
3. **Fonts and sizes ignored.** The app font replaces the file's (Arial, Arial
   Narrow, Times, Bookman); sizes are rounded; document defaults and styles are
   never read.
4. **Spacing invented.** A flat 8px paragraph gap, 1.55 line height and 7x10px cell
   padding replace the file's spacing, indents and cell margins, roughly doubling
   the page height.
5. **Tables approximated.** Cell widths, row heights and vertical alignment are
   ignored; a grey fallback grid is drawn where Word draws nothing; every value
   cell gets an app tint; table-style borders (Table Grid) are not read.
6. **Numbering lost.** Numbered and bulleted lists render without their markers.
7. **Headings guessed.** An app heuristic adds bold and margin Word doesn't have.

## Decisions (confirmed with the user)

- **Approach A**: teach our own renderer Word's layout properties. No third-party
  renderer (docx-preview), no server-side LibreOffice (the VPS has 2 GB RAM, one
  CPU and no LibreOffice).
- **Continuous real page**: one sheet at the file's true width, margins and
  orientation; no page breaks.
- **Phones**: the same page, fitted to the screen width; zoom (buttons or pinch)
  enlarges it and the panel scrolls both ways.
- **Renderer only.** The built-in ILAW keeps its PDF-converted template. Its junk
  font names (`Type3 (8 0 R)`) are shown as Arial, the font of the source PDF.

## Success criteria

- The user's T1W7 sample, uploaded as a format, looks like its Word rendering in
  the app: 936pt-wide landscape page, both logos at the top of the title cell,
  Arial / Arial Narrow at the file's sizes, grey label cells, centred and
  bottom-aligned cells, numbered objectives, the same column widths and borders.
- Each of the five built-ins matches its own file's rendering the same way.
- Fields, weekly day cells, anchors, detection and export behave exactly as today;
  all existing backend tests pass.
- Known ceiling: browsers measure text a hair differently from Word, so a line can
  wrap one word earlier or later.

## Design

### 1. Page and zoom

- The renderer reads the document's last section (`w:sectPr`): `pgSz` and `pgMar`.
  `.lp-doc` gets inline `width` and `padding` in points. Built-ins have zero
  margins and render edge to edge, as in Word.
- Every emitted length is in points (twips / 20, half-points / 2, EMU / 12700), so
  100% zoom is the true physical size, like Word at 100%.
- One continuous sheet: page breaks and section breaks draw nothing.
- Zoom moves from `transform: scale` to CSS `zoom`, so scroll size, caret and
  selection stay correct and the `margin-bottom` compensation is removed.
- New default **Fit**: scale = min(1, available width of the wrap / page width),
  recomputed on resize. The readout shows it ("Fit 68%"). − and + step along the
  existing ladder from the current scale; Reset returns to Fit; the saved per-page
  choice is kept (a saved step still wins over Fit).
- Applies to all four views: generator live document, format builder canvas,
  generator plan preview, plan list preview. The two previews have no toolbar and
  get Fit only, from one shared helper.

### 2. Text

- **Style cascade**, resolved on the server in Word's order: `docDefaults` →
  table style (`tblStyle` pPr/rPr, for text inside that table) → paragraph style
  and its `basedOn` chain → character style (`rStyle`) and its chain → direct
  formatting. Theme fonts (`minorHAnsi`, `majorHAnsi`) and theme colours resolve
  from `word/theme/theme1.xml`.
- **Runs** become inline CSS:
  - `font-family`: the resolved name plus a generic fallback (serif for Times,
    Cambria, Georgia, Bookman, Garamond, Book Antiqua; sans-serif otherwise).
    Names starting with `Type3` or empty after conversion map to Arial.
  - `font-size` in exact points (10.5pt stays 10.5pt).
  - bold, italic, underline (single/double/dotted/dashed/wavy), strike, caps,
    small caps, superscript/subscript (`vertAlign`).
  - colour (including `themeColor`), highlight (Word's full 16-colour palette),
    run shading.
- **Paragraphs** become inline CSS:
  - `margin-top` / `margin-bottom` from `spacing before/after`; with
    `contextualSpacing`, the gap between two paragraphs of the same style is 0.
  - line spacing: `lineRule="auto"` → unitless `line-height` = (line / 240) × the
    font's single-line factor (1.15 by default, 1.22 for Calibri/Aptos);
    `exact` → `line-height: Npt`; `atLeast` → `line-height: max(Npt, <auto>)`.
  - `ind`: left/right → margins, `firstLine` → `text-indent`, `hanging` →
    negative `text-indent` with matching left margin.
  - alignment (`jc`, as today).
- **Breaks and tabs**: `w:br` → `<br>`; page breaks are skipped; `w:tab` → an
  inline gap to the next 0.5 in default stop (custom tab stops are ignored;
  `ponytail:` note in code).
- **Numbering**: `numPr` (direct or from the paragraph style) resolves through
  `numbering.xml` (`num` → `abstractNum`, `lvlOverride`/`startOverride`). A counter
  per list and level produces the marker from `lvlText` and `numFmt`: decimal,
  lowerLetter, upperLetter, lowerRoman, upperRoman, bullet; any other format falls
  back to decimal. Deeper levels reset when a shallower one advances. Symbol /
  Wingdings private-use bullets map to the Unicode glyph they draw (`` •,
  `` ▪, `` ➢, `` ❖, `` ✓, `o` stays o). The marker is an
  inline-block span sized to the hanging indent, styled like the paragraph's
  first run.
- **App styling removed**: `.lp-doc` no longer sets font, size, line height,
  colour, padding or paragraph margins; the `lp-heading` / `lp-bold` heuristic is
  dropped from the markup. Classes the JS uses stay (`lp-p`, `lp-candidate`,
  `data-anchor-index`, `lp-field*`). Field tints stay: they show where to type.

### 3. Tables and pictures

- **Geometry**: column widths from `tblGrid` in points (not percentages); table
  width from `tblW` (`dxa` → pt, `pct` → %, `auto` → grid sum); `tblInd` and table
  `jc` (centre/right); `table-layout: fixed` when `tblLayout` is fixed or all
  widths are known.
- **Cell padding** from cell margins: table style `tblCellMar` → table
  `tblCellMar` → cell `tcMar` (`start`/`end` treated as `left`/`right`). Word's
  default is 5.4pt left and right, 0 top and bottom.
- **Borders**, Word's model: table-style `tblBorders` → table `tblBorders` → cell
  `tcBorders`. A cell on the table's edge takes `top/left/bottom/right`; an
  interior edge takes `insideH` / `insideV`. `none`/`nil` or nothing specified
  draws no border (the grey fallback grid is removed). Widths are exact
  (`sz` eighths of a point); single, double, dashed, dotted.
- **Shading**: cell `shd` fill (including `themeFill`) and table-style shading.
  The app's tint on every value cell is removed.
- **Rows**: `trHeight` becomes a minimum height for both `atLeast` and `exact`, so
  an exact row starts at the file's height and grows while a teacher types.
- **Cells**: `vAlign` top/center/bottom → `vertical-align`. Merges (`gridSpan`,
  `vMerge`) and nested tables work as today.
- **Pictures**:
  - inline (`wp:inline`) → `<img>` as a data URI at its `extent` size in points.
  - floating (`wp:anchor`): `wrapSquare`/`wrapTight`/`wrapThrough` → CSS float
    (left unless positioned right) with the `posOffset` as a margin, so text
    wraps around it and two logos sit side by side; `wrapTopAndBottom` → block;
    `wrapNone` or `behindDoc` → absolutely positioned in its paragraph.
  - EMF/WMF or any image that can't be read is skipped; the page still renders.
- **Hyperlinks** take the file's Hyperlink character style.

### 4. Structure, errors, testing

- **New module `backend/services/docx_layout.py`**: `Layout(doc)` is built once per
  render and caches styles, theme, numbering and images. Its methods return CSS
  strings or small HTML fragments: `page_css()`, `paragraph_css(p, table)`,
  `run_css(run, p, table)`, `list_marker(p)`, `table_css(tbl)`,
  `col_widths_pt(tbl)`, `cell_css(tc, row_idx, col_idx, n_rows, n_cols, tbl)`,
  `row_css(tr)`, `picture_html(run)`, `slot_css(p)`.
- `docx_service`'s `_render_*` functions call it and keep their HTML contract
  (`lp-doc`, `lp-table`, `lp-td`, `lp-td-value`, `lp-p`, `lp-candidate`,
  `data-anchor-index`, `lp-field*`, `data-field-key`, `data-part`). Slot planning,
  anchors, weekly cells, detection and export are not touched. The old helpers it
  replaces (`_run_style_css`, `_paragraph_html_classes` styling,
  `_border_side_css`, `_table_default_borders`, `_cell_border_style`,
  `_cell_shading_css`, `_table_col_widths_pct`) are deleted.
- **Typed text**: an empty value cell's slot gets `slot_css`, the style of that
  cell's first paragraph and its paragraph-mark run properties (what Word gives
  new text there). `.lp-doc` gets the document-default font and size inline, so
  inline slots inherit the file's text style.
- **Frontend**:
  - `style.css`: `.lp-doc` keeps only white background, shadow, `color:#000` and
    `box-sizing`; `.lp-td` loses its border, padding and font size; the value-cell
    tint and heading rules go; `.lp-doc-wrap` stays as the grey desk; the
    `max-width` overrides on `.lp-doc` go.
  - `doc-toolbar.js`: CSS `zoom`, Fit default, readout.
  - A shared `fitDocPage(wrapEl)` helper for the two previews.
  - Bump the `?v=` asset version.
- **Errors**: every property read is wrapped so a malformed style, numbering,
  theme or picture drops only that property. Missing `styles.xml`,
  `numbering.xml` or theme → Word's built-in defaults (Calibri 11pt, spacing after
  8pt, line 1.08). Return values of `render_template_html` and
  `render_reference_html` are unchanged.
- **Tests**: new `backend/test_render_fidelity.py`, assert-based and runnable
  directly, using small .docx files generated with python-docx:
  page size and margins; the cascade (defaults → style → direct); table-style
  inner vs outer borders; cell margins; row minimum height; `vAlign`; list
  counters ("1.", "2.", "a.", "•"); inline picture as data URI; floating picture
  as float; `Type3` → Arial. Plus checks on the T1W7 sample: page 936pt wide, two
  logos, the first objective carries "1.". The existing 13 backend tests and the
  weekly-field tests keep passing.
- **Visual check**: side-by-side images at the same scale (LibreOffice vs app at
  100%) for the five built-ins and the T1W7 sample, saved under
  `docs/superpowers/screenshots/2026-09-26/fidelity/`; generator and format
  builder checked in the browser at 1440 and 390px with Fit.
- **Deploy**: backup, then the usual archive deploy to the VPS; verify health and
  a rendered ILAW view.

## Out of scope

- Exported plans clip text in the built-ins' `exact`-height rows (seen on a real
  export). A separate export bug, raised with the user after this work.
- Pagination and page breaks; headers, footers and text boxes (none of the six
  files use them); custom tab stops; right-to-left text.
