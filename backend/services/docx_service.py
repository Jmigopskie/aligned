import copy
import html as html_lib
import html.parser as _html_parser
import logging
import os
import re
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph

from config import Config
from services import docx_layout

_log = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^[IVXLCDM]{1,6}\.\s")
_SIGNATURE_RE = re.compile(r"^(prepared|checked|noted)\s+by\b", re.IGNORECASE)
_STOPWORDS = {"the", "a", "an", "of", "for", "by", "and", "or", "to", "in", "on"}
_PREAMBLE_MATCH_WINDOW = 1
_LABEL_MAX_CHARS = 100
# "Label: instructions..." in one paragraph. The label may wrap over lines in a
# narrow cell ("Opportunities for\nintegration and\ncontextualization:").
_LONG_LABEL_RE = re.compile(r"^\s*([^:]{2,90}?)\s*:\s*\S", re.S)

def export_lesson_plan(plan, fmt) -> str:
    template_path = resolve_template_path(fmt)
    if template_path:
        try:
            return _export_from_template(plan, fmt, template_path)
        except Exception:
            _log.exception(
                "Template-based export failed for format %s (%s); falling back to a "
                "generic, unstyled document.",
                getattr(fmt, "id", "?"), getattr(fmt, "name", "?"),
            )

    return _export_generic(plan, fmt)

_ALIGN_FROM_STR = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_HEADING_STYLE_BY_LEVEL = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}
_LIST_STYLE_BY_TYPE = {"bullet": "List Bullet", "number": "List Number"}

# The closed set of run-level styles the document toolbar offers, and the Word
# property each one becomes. The toolbar, the field sanitizer and this table are
# deliberately the same fixed vocabulary: a teacher can only apply formatting
# that survives export, rather than styling something on screen and losing it in
# the .docx. Extend all three together or not at all.
_FONT_SIZE_BY_CLASS = {
    "fs-sm": Pt(9),
    "fs-md": Pt(11),
    "fs-lg": Pt(14),
    "fs-xl": Pt(18),
}

_FONT_COLOR_BY_CLASS = {
    "fc-default": RGBColor(0x16, 0x23, 0x1E),
    "fc-red": RGBColor(0xAB, 0x35, 0x24),
    "fc-amber": RGBColor(0xB8, 0x84, 0x2E),
    "fc-green": RGBColor(0x1C, 0x5C, 0x4E),
    "fc-blue": RGBColor(0x1D, 0x4E, 0xD8),
}

# Word's highlight is a fixed enum rather than a free colour, which is why the
# toolbar offers exactly these three plus "none".
_HIGHLIGHT_BY_CLASS = {
    "hl-none": None,
    "hl-yellow": WD_COLOR_INDEX.YELLOW,
    "hl-green": WD_COLOR_INDEX.BRIGHT_GREEN,
    "hl-cyan": WD_COLOR_INDEX.TURQUOISE,
}

# Every class name the toolbar may send, for the route that validates an edit
# before it reaches the document.
FONT_SIZE_CLASSES = tuple(_FONT_SIZE_BY_CLASS)
FONT_COLOR_CLASSES = tuple(_FONT_COLOR_BY_CLASS)
HIGHLIGHT_CLASSES = tuple(_HIGHLIGHT_BY_CLASS)


def _apply_run_style_classes(run, size_cls=None, color_cls=None, highlight_cls=None):
    """Apply the fixed-vocabulary classes to one Word run. An unknown class is
    ignored rather than raising, so a stale page sending an old name degrades to
    plain text instead of failing the whole export."""
    if size_cls in _FONT_SIZE_BY_CLASS:
        run.font.size = _FONT_SIZE_BY_CLASS[size_cls]
    if color_cls in _FONT_COLOR_BY_CLASS:
        run.font.color.rgb = _FONT_COLOR_BY_CLASS[color_cls]
    if highlight_cls in _HIGHLIGHT_BY_CLASS:
        run.font.highlight_color = _HIGHLIGHT_BY_CLASS[highlight_cls]

def apply_content_edits(template_path, edits):
    """Apply a batch of paragraph-level edits — text changes, bold/italic/
    underline/alignment, heading level, list style, or outright deletion —
    directly to the .docx at template_path and save it back to disk.

    This is what makes a deletion actually stick: the document view always
    renders straight from this file, so a paragraph removed here is gone
    from every future render, not just hidden in the browser.

    Each edit is {"anchor_index": int, "action": "delete" | "format", ...}.
    anchor_index addresses the same flat position _iter_items() (and so
    render_template_html()'s / render_reference_html()'s data-anchor-index)
    uses, so the caller can target exactly the paragraph the teacher selected
    in the live canvas.

    Deleting a paragraph shifts every later position in the document's flat
    item order down by one. This function doesn't touch a format's fields at
    all — the caller (format_routes.edit_format_content) re-detects them
    from scratch against the edited file afterward, since fields are always
    an automatic read of the current document, never manually curated.

    Returns (deletions, applied): the sorted list of deleted indices, and how
    many edits were actually applied.
    """
    doc = Document(template_path)
    items = _iter_items(doc)

    deletions = sorted({
        e["anchor_index"] for e in edits
        if e.get("action") == "delete" and isinstance(e.get("anchor_index"), int)
        and 0 <= e["anchor_index"] < len(items)
    })

    applied = 0
    for edit in edits:
        idx = edit.get("anchor_index")
        if not isinstance(idx, int) or not (0 <= idx < len(items)):
            continue
        item = items[idx]
        el = item["el"]
        action = edit.get("action")

        if action == "delete":
            cell = item["cell"]
            if cell is not None and len(cell.paragraphs) <= 1:
                # Word requires at least one paragraph per cell — clear it
                # rather than removing the only paragraph the cell has.
                _set_paragraph_text(doc, el, "")
            else:
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
            applied += 1
        elif action == "format":
            _apply_paragraph_edit(doc, el, edit)
            applied += 1

    doc.save(template_path)
    return deletions, applied

def apply_doc_edits(doc, items, edits):
    """Replay a plan's own document edits onto an open document, in place.

    apply_content_edits() is the format builder's equivalent, and it saves the
    template back to disk because the builder is editing the format itself. A
    plan must never do that: its edits belong to one teacher's copy, not to the
    shared format every other teacher generates from. So this takes a document
    already in memory, changes it, and saves nothing.

    Every entry is validated rather than trusted. An edit pointing at a position
    that no longer exists, or carrying a non-numeric anchor, is skipped: the
    reference file can be re-uploaded and re-detected after these were recorded,
    and losing one stale line is far better than failing a teacher's export.
    """
    if not edits:
        return 0

    applied = 0
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        idx = edit.get("anchor_index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            continue
        if not (0 <= idx < len(items)):
            continue
        _apply_paragraph_edit(doc, items[idx]["el"], edit)
        applied += 1
    return applied


def _apply_paragraph_edit(doc, el, edit):
    if "text" in edit:
        _set_paragraph_text(doc, el, edit["text"])

    para = Paragraph(el, doc)

    if "align" in edit:
        para.alignment = _ALIGN_FROM_STR.get(edit["align"])

    if "heading" in edit:
        level = edit["heading"] or 0
        style_name = _HEADING_STYLE_BY_LEVEL.get(level, "Normal")
        if _has_style(doc, style_name):
            try:
                para.style = doc.styles[style_name]
            except Exception:
                pass

    if "list" in edit:
        style_name = _LIST_STYLE_BY_TYPE.get(edit["list"])
        if style_name and _has_style(doc, style_name):
            try:
                para.style = doc.styles[style_name]
            except Exception:
                pass
        elif edit["list"] is None and para.style is not None and para.style.name in _LIST_STYLE_BY_TYPE.values():
            if _has_style(doc, "Normal"):
                try:
                    para.style = doc.styles["Normal"]
                except Exception:
                    pass

    run_keys = ("bold", "italic", "underline", "size", "color", "highlight")
    if any(k in edit for k in run_keys):
        runs = para.runs
        if not runs and para.text:
            # _set_paragraph_text() above guarantees at least one run
            # whenever there's text to carry the formatting on.
            runs = para.runs
        for run in runs:
            if "bold" in edit:
                run.bold = edit["bold"]
            if "italic" in edit:
                run.italic = edit["italic"]
            if "underline" in edit:
                run.underline = edit["underline"]
            # The builder's toolbar applies these to a whole line, matching how
            # it already treats bold, so they are set on every run of it.
            _apply_run_style_classes(run, edit.get("size"), edit.get("color"), edit.get("highlight"))

def render_template_html(fmt):
    """Render this format's real reference .docx as HTML that mirrors its actual
    tables and headers, with an editable slot placed at every field whose
    position is already known in the document.

    Each field is located directly by its stored anchor_index — the exact
    paragraph/cell position the teacher clicked to define it in the format
    builder — falling back to keyword matching only for older fields saved
    before anchor_index existed. Either way the position comes from the real
    document structure, never from an AI redrawing the template, so the editor
    can never show a field, table, or section that doesn't genuinely exist in
    the source file — anything on the format with no resolvable anchor is
    reported back in "unmatched_fields" instead of being faked in the HTML.

    Returns None if there's no usable template file for this format (e.g. the
    format was created without a reference file). Otherwise:
    {
      "html": "<div class='lp-doc'>...</div>",
      "matched_fields": [field_key, ...],   # got a real slot in the document
      "unmatched_fields": [field_key, ...], # no position for these could be
                                             # resolved in the reference file
    }
    """
    template_path = resolve_template_path(fmt)
    if not template_path:
        return None

    doc = Document(template_path)
    fields_sorted = sorted(fmt.fields, key=lambda f: f.sort_order)
    items = _iter_items(doc)
    anchors = _locate_anchors(doc, items, fields_sorted)

    if not anchors:
        return {
            "html": "",
            "matched_fields": [],
            "unmatched_fields": [f.field_key for f in fields_sorted],
        }

    weekly_keys = {f.field_key for f in fields_sorted if f.field_type == "weekly"}
    slots, cell_value_targets = _plan_html_slots(doc, items, anchors, weekly_keys)
    html = _render_doc_body_html(doc, items, slots, cell_value_targets)

    return {
        "html": html,
        "matched_fields": sorted(anchors.keys()),
        "unmatched_fields": [f.field_key for f in fields_sorted if f.field_key not in anchors],
    }

def render_reference_html(source_path):
    """Render a bare reference .docx as HTML for the format builder's live
    document editor, before any fields exist yet. Every paragraph is tagged
    with a stable data-anchor-index (the same position _iter_items() would
    assign it), so a field can be defined at that exact spot — either by the
    teacher clicking it directly, or by AI suggestion (candidate_label_lines /
    ai_service.suggest_field_anchors) pointing at one of these same indices.
    Either way the field is pinned to a position that genuinely exists in the
    file; nothing about the document's structure is ever invented.

    Returns {"html": "..."} , or None if the file can't be opened as a Word
    document at all (e.g. a scanned/image-only PDF that converted to an empty
    .docx).
    """
    try:
        doc = Document(source_path)
    except Exception:
        return None

    items = _iter_items(doc)
    html = _render_doc_body_html(doc, items, slots={}, cell_value_targets={})
    if not html.strip() or not items:
        return None
    return {"html": html}

def candidate_label_lines(source_path):
    """Every label-like line in the reference document, as [{"index", "text"}, ...]
    in document order — the same indices render_reference_html() tags each
    element with. This is the list an AI is allowed to choose fields from
    (ai_service.suggest_field_anchors): it can only ever point at one of these
    real positions, never invent a label that isn't actually in the file.

    A line counts as label-like either by _looks_like_label() (a heading, a
    signature line, or text ending in a colon — tuned for free-flowing
    paragraphs) or, for a table cell, by having a genuinely empty sibling
    cell in its row. That second check matters: a plain grid layout like
    "Grade Level | ____" or "____ | Subject" carries no colon or heading
    markup at all, so relying on _looks_like_label() alone would silently
    skip almost every field in that kind of template.

    Returns None if the file can't be opened as a Word document.
    """
    try:
        doc = Document(source_path)
    except Exception:
        return None

    items = _iter_items(doc)
    header = _day_header(doc)
    lines = []
    for idx, item in enumerate(items):
        text = _element_text(doc, item["el"])
        if not text:
            continue

        # A table cell's second and later lines are typically explanatory
        # help text under the real label (very common in DepEd-style
        # templates — e.g. a "Flow:" cell followed by several sentences of
        # instructions), not a second field. Only the cell's first non-blank
        # line is ever eligible, so one cell yields at most one candidate.
        if item["cell"] is not None and not _is_first_textual_line_in_cell(doc, items, idx):
            continue

        # A line that starts mid-sentence is the tail of text cut at a page
        # break when a PDF was converted ("guidance or support throughout each
        # session."), never a label. A weekday is a column header.
        if text[:1].islower() or text.lower() in _WEEKDAY_NAMES:
            continue

        # DepEd templates often put the label and its instructions in one
        # paragraph ("Flow: Describe the activities that you can implement...").
        # Too long to be a label as a whole, but the part before the colon is.
        if len(text) > _LABEL_MAX_CHARS:
            match = _LONG_LABEL_RE.match(text)
            label = " ".join(match.group(1).split()) if match else ""
            if not label or len(label) > 60:
                continue
            text = label + ":"

        cells = _weekly_cells(item) if item["cell"] is not None else []
        # A table label whose next cell already holds text, with no blank of
        # its own beside, under or inside it, is either answered in the
        # template ("School: | EMMANUEL ... IHS") or a heading over the real
        # fields ("Learning Competency and Curriculum Standards:"). As a field
        # it would only steal a neighbour's blank cell.
        if (item["cell"] is not None and not cells and _next_cell_has_text(item)
                and not _blank_lines_after_in_cell(item)):
            continue

        if _looks_like_label(text) or _has_fillable_slot(doc, items, idx):
            entry = {"index": idx, "text": text}
            if item["cell"] is not None:
                entry["blank_cells"] = len(cells)
                if len(cells) >= 2:
                    entry["parts"] = weekly_part_labels(doc, cells, header)
            lines.append(entry)

    return lines

def _next_cell_has_text(item):
    """Whether the cell right after this one in its row already holds text."""
    row_cells, col_idx, cell = item["row_cells"], item["col_idx"], item["cell"]
    if not row_cells or col_idx is None:
        return False
    for other in row_cells[col_idx + 1:]:
        if other._tc is cell._tc:
            continue  # the same merged cell repeated by python-docx
        return bool(other.text.strip())
    return False


def _blank_lines_after_in_cell(item):
    """Whether the label's own cell has blank lines under it to write into."""
    paragraphs = item["cell"].paragraphs
    pos = next((i for i, p in enumerate(paragraphs) if p._p is item["el"]), None)
    return pos is not None and any(not p.text.strip() for p in paragraphs[pos + 1:])


def _is_first_textual_line_in_cell(doc, items, idx):
    cell = items[idx]["cell"]
    for j in range(idx - 1, -1, -1):
        other = items[j]
        if other["cell"] is not cell:
            return True
        if _element_text(doc, other["el"]):
            return False
    return True

def _render_block_children(doc, parent_el, slots, cell_value_targets, index_by_el_id, layout):
    """Render the paragraph/table children of any container element, in
    document order. Used for both the document body and a table cell's
    contents — a table nested inside another table's cell (a common way to
    build a bordered sub-layout) is otherwise invisible: _iter_items()
    already recurses into it for anchoring purposes, so without this same
    recursion here the HTML view would silently omit real content that
    fields can still be anchored to."""
    parts = []
    for child in parent_el:
        if child.tag == qn("w:p"):
            parts.append(_render_html_paragraph(doc, child, slots, index_by_el_id, layout))
        elif child.tag == qn("w:tbl"):
            parts.append(_render_html_table(doc, Table(child, doc), slots, cell_value_targets, index_by_el_id, layout))
        # w:tcPr / w:sectPr and anything else is layout metadata, not content.
    return "".join(parts)

def _render_doc_body_html(doc, items, slots, cell_value_targets):
    # One Layout per render: it resolves Word's styles once, and its list
    # counters advance as paragraphs are drawn in document order.
    layout = docx_layout.Layout(doc)
    index_by_el_id = {id(item["el"]): idx for idx, item in enumerate(items)}
    body_html = _render_block_children(doc, doc.element.body, slots, cell_value_targets, index_by_el_id, layout)
    page_css, page_width = layout.page()
    return f'<div class="lp-doc" style="{page_css}" data-page-width="{page_width:g}">' + body_html + "</div>"

def _plan_html_slots(doc, items, anchors, weekly_keys=frozenset()):
    """Decide, for each matched field, where its editable value slot goes in the
    HTML — mirroring the same priority order the real .docx fill uses (an empty
    sibling cell in the same row, then appending within the same cell, then
    inline-after-colon, then a new block right after the label) so the editor
    lines up with what the real export will actually do.

    Returns:
      slots: {id(anchor_paragraph_el): (field_key, "inline" | "same_cell" | "block")}
      cell_value_targets: {id(cell._tc): (field_key, part)} -- cells that
        themselves ARE the value slot for a field labeled earlier in the same
        row; part is the day index of a weekly field, None otherwise.
    """
    slots = {}
    cell_value_targets = {}
    claimed_cells = set()

    # Document order, not field/sort order — when two labels in the same row
    # could both claim one blank cell, the one whose label actually comes
    # first in the document should win it.
    for field_key, idx in sorted(anchors.items(), key=lambda kv: kv[1]):
        item = items[idx]
        anchor_el = item["el"]
        cell = item["cell"]
        row_cells = item["row_cells"]
        col_idx = item["col_idx"]

        if field_key in weekly_keys:
            day_cells = [c for c in _weekly_cells(item) if id(c[0]) not in claimed_cells]
            if day_cells:
                for part, (tc, _start, _span) in enumerate(day_cells):
                    cell_value_targets[id(tc)] = (field_key, part)
                    claimed_cells.add(id(tc))
                continue

        if cell is not None and row_cells and col_idx is not None:
            sibling = _find_empty_sibling_cell(row_cells, cell, col_idx, claimed_cells)
            if sibling is not None:
                cell_value_targets[id(sibling._tc)] = (field_key, None)
                claimed_cells.add(id(sibling._tc))
                continue

        if cell is not None:
            slots[id(anchor_el)] = (field_key, "same_cell")
        else:
            has_colon = ":" in _element_text(doc, anchor_el)
            slots[id(anchor_el)] = (field_key, "inline") if has_colon else (field_key, "block")

    return slots, cell_value_targets

def _html_escape(text):
    # quote=True (the default) also escapes " and ' — needed because this is
    # used both for plain text content and for the hyperlink href attribute
    # value in _render_runs_html(); a docx hyperlink address containing a "
    # would otherwise be able to break out of href="..." and inject markup.
    return html_lib.escape(text or "")

def _run_html(run, layout, p_el):
    pictures = layout.pictures(run._r)
    text = run.text
    if not text:
        return pictures
    style = layout.run_css(run._r, p_el)
    escaped = _html_escape(text)
    return pictures + (f'<span style="{style}">{escaped}</span>' if style else escaped)

def _render_runs_html(para, layout):
    """Render each run as its own span so mixed formatting within one
    paragraph (e.g. a bold label followed by a plain colon) survives in the
    HTML instead of being collapsed to a single paragraph-wide guess.

    Walks iter_inner_content() rather than .runs directly — a paragraph's
    hyperlinked text lives in a nested <w:hyperlink> and doesn't show up in
    .runs at all, so relying on .runs alone would silently drop it even
    though para.text (used for anchor/heading detection) does include it.
    """
    p_el = para._p
    out = []
    for item in para.iter_inner_content():
        if isinstance(item, Hyperlink):
            inner = "".join(_run_html(r, layout, p_el) for r in item.runs)
            if not inner:
                continue
            href = _html_escape(item.address or "")
            out.append(f'<a href="{href}" target="_blank" rel="noopener">{inner}</a>' if href else inner)
        else:
            out.append(_run_html(item, layout, p_el))
    return "".join(out)

def _render_html_paragraph(doc, p_el, slots, index_by_el_id, layout):
    para = Paragraph(p_el, doc)
    text = para.text
    classes = "lp-p lp-candidate" if _looks_like_label(text) else "lp-p"

    # Everything visual comes from the file (docx_layout). A list number is an
    # attribute drawn by CSS ::before, never text in the paragraph: both editors
    # read a paragraph's text back from the page, and a marker in it would be
    # saved into the document as typed text.
    style, marker = layout.paragraph(p_el)
    marker_attr = ""
    if marker:
        marker_attr = f' data-marker="{_html_escape(marker["text"])}"'
        if marker["width"]:
            width = f"--lp-marker-w:{marker['width']:g}pt"
            style = f"{style};{width}" if style else width
    style_attr = f' style="{style}"' if style else ""

    inner = _render_runs_html(para, layout)
    if "<img" not in inner and not text.strip():
        inner = "&nbsp;"

    anchor_attr = ""
    if index_by_el_id is not None:
        idx = index_by_el_id.get(id(p_el))
        if idx is not None:
            anchor_attr = f' data-anchor-index="{idx}"'

    open_tag = f'<p class="{classes}"{style_attr}{marker_attr}{anchor_attr}>'
    slot = slots.get(id(p_el))
    if not slot:
        return f"{open_tag}{inner}</p>"

    field_key, kind = slot
    if kind == "inline":
        return (
            f'{open_tag}{inner} '
            f'<span class="lp-field lp-field-inline" data-field-key="{field_key}" '
            f'contenteditable="true"></span></p>'
        )

    # "block" or "same_cell" — label paragraph stays read-only, the value gets
    # its own editable block right after it (inside the same cell, if any),
    # in the style Word would give text typed there.
    slot_css = layout.slot_css(p_el)
    slot_style = f' style="{slot_css}"' if slot_css else ""
    return (
        f'{open_tag}{inner}</p>'
        f'<div class="lp-field lp-field-block" data-field-key="{field_key}"{slot_style} '
        f'contenteditable="true"></div>'
    )

def _tc_pr(tc):
    return tc.find(qn("w:tcPr"))

def _cell_grid_span(tc):
    tcPr = _tc_pr(tc)
    if tcPr is None:
        return 1
    span_el = tcPr.find(qn("w:gridSpan"))
    if span_el is None:
        return 1
    try:
        return max(1, int(span_el.get(qn("w:val"))))
    except (TypeError, ValueError):
        return 1

def _render_html_cell(doc, cell, slots, cell_value_targets, cell_css, colspan, rowspan, index_by_el_id, layout):
    style_attr = f' style="{cell_css}"' if cell_css else ""
    span_attr = (f' colspan="{colspan}"' if colspan > 1 else "") + (f' rowspan="{rowspan}"' if rowspan > 1 else "")

    target = cell_value_targets.get(id(cell._tc))
    if target:
        # This cell IS the (originally empty) value slot for a label earlier in
        # the same row — replace its near-empty content with one editable slot
        # instead of rendering its blank paragraphs. A weekly field's day cells
        # each carry which part (day) they hold. The slot takes the style Word
        # gives text typed into this cell.
        field_key, part = target
        part_attr = f' data-part="{part}"' if part is not None else ""
        first_p = cell._tc.find(qn("w:p"))
        slot_css = layout.slot_css(first_p) if first_p is not None else ""
        slot_style = f' style="{slot_css}"' if slot_css else ""
        return (
            f'<td class="lp-td lp-td-value"{span_attr}{style_attr}>'
            f'<div class="lp-field lp-field-cell" data-field-key="{field_key}"{part_attr}{slot_style} '
            f'contenteditable="true"></div></td>'
        )

    inner = _render_block_children(doc, cell._tc, slots, cell_value_targets, index_by_el_id, layout)
    return f'<td class="lp-td"{span_attr}{style_attr}>{inner or "&nbsp;"}</td>'

def _vmerge_rowspans(rows_cells):
    """Map (row_idx, col_idx) -> rowspan for every cell that starts a vertical
    merge, and the set of (row_idx, col_idx) positions that are continuations
    of one and must be omitted from the HTML entirely — otherwise a real
    merged cell would render as several stacked duplicate ones.

    python-docx's `row.cells` already resolves a vertically merged region to
    the *same* `_Cell`/tc object on every row it spans (exactly like it does
    for a horizontal span within one row), so a merge is detected here by
    identical cell identity repeating down a column rather than by reading
    `w:vMerge` directly — that XML flag isn't reachable through `row.cells`,
    it's already been resolved away by the time we see it.
    """
    origin_rowspan = {}
    skip = set()
    n_cols = max((len(rc) for rc in rows_cells), default=0)

    for col_idx in range(n_cols):
        row_idx = 0
        while row_idx < len(rows_cells):
            row_cells = rows_cells[row_idx]
            if col_idx >= len(row_cells):
                row_idx += 1
                continue
            tc = row_cells[col_idx]._tc
            span = 1
            next_row = row_idx + 1
            while next_row < len(rows_cells):
                nr_cells = rows_cells[next_row]
                if col_idx >= len(nr_cells) or nr_cells[col_idx]._tc is not tc:
                    break
                span += 1
                next_row += 1
            if span > 1:
                origin_rowspan[(row_idx, col_idx)] = span
                for skip_row in range(row_idx + 1, row_idx + span):
                    skip.add((skip_row, col_idx))
            row_idx += span

    return origin_rowspan, skip

def _render_html_table(doc, table, slots, cell_value_targets, index_by_el_id, layout):
    tbl_el = table._tbl
    table_css, grid = layout.table(tbl_el)
    rows = list(table.rows)
    rows_cells = [row.cells for row in rows]
    origin_rowspan, vmerge_skip = _vmerge_rowspans(rows_cells)
    n_rows = len(rows_cells)
    n_cols = len(grid) or max((len(rc) for rc in rows_cells), default=0)

    rows_html = []
    for row_idx, (row, row_cells) in enumerate(zip(rows, rows_cells)):
        seen_tc_ids = set()
        cells_html = []
        for col_idx, cell in enumerate(row_cells):
            if (row_idx, col_idx) in vmerge_skip:
                continue
            tc_id = id(cell._tc)
            if tc_id in seen_tc_ids:
                # Horizontally merged cell — python-docx returns the same
                # underlying cell once per spanned column; only render it once.
                continue
            seen_tc_ids.add(tc_id)
            colspan = _cell_grid_span(cell._tc)
            rowspan = origin_rowspan.get((row_idx, col_idx), 1)
            cell_css = layout.cell(cell._tc, tbl_el, top=row_idx == 0, bottom=row_idx + rowspan >= n_rows,
                                   left=col_idx == 0, right=col_idx + colspan >= n_cols)
            cells_html.append(_render_html_cell(
                doc, cell, slots, cell_value_targets, cell_css, colspan, rowspan, index_by_el_id, layout
            ))
        row_css = layout.row(row._tr)
        row_attr = f' style="{row_css}"' if row_css else ""
        rows_html.append(f"<tr{row_attr}>{''.join(cells_html)}</tr>")

    colgroup = ""
    if grid:
        colgroup = "<colgroup>" + "".join(f'<col style="width:{round(w, 2):g}pt">' for w in grid) + "</colgroup>"
    style_attr = f' style="{table_css}"' if table_css else ""
    return f'<table class="lp-table"{style_attr}>{colgroup}{"".join(rows_html)}</table>'

def resolve_source_path(fmt):
    raw = (fmt.source_file_path or "").strip()
    if not raw:
        return None
    if os.path.isfile(raw):
        return raw
    filename = raw.replace("\\", "/").rsplit("/", 1)[-1]
    candidate = os.path.join(Config.UPLOAD_FOLDER, filename)
    return candidate if os.path.isfile(candidate) else None

def _template_cache_dir():
    path = os.path.join(Config.UPLOAD_FOLDER, "template_docx_cache")
    os.makedirs(path, exist_ok=True)
    return path

def resolve_template_path(fmt):
    """Return a .docx path usable as a fillable export template for this
    format: the original reference file when it's already a Word document,
    or an auto-converted copy when the reference file is a PDF (e.g. a
    lesson-plan format exported/scanned as PDF). The converted copy is
    generated once and cached on the format so repeat exports reuse it
    instead of preserving its tables, fonts and layout every export."""
    source_path = resolve_source_path(fmt)
    if not source_path:
        return None

    if source_path.lower().endswith((".docx", ".dotx")):
        return source_path

    if source_path.lower().endswith(".pdf"):
        cached = (fmt.template_docx_path or "").strip()
        if cached and os.path.isfile(cached):
            return cached

        try:
            converted_path = _convert_pdf_to_docx(source_path, fmt.id)
        except Exception:
            _log.exception(
                "Couldn't convert PDF reference file to an editable template for "
                "format %s (%s); this export will fall back to a generic document.",
                getattr(fmt, "id", "?"), getattr(fmt, "name", "?"),
            )
            return None

        fmt.template_docx_path = converted_path
        try:
            from extensions import db
            db.session.commit()
        except Exception:
            _log.exception("Couldn't save the converted template path for format %s", fmt.id)
        return converted_path

    return None

def convert_pdf_to_docx(pdf_path, out_path) -> str:
    """Turn a PDF reference format into an editable .docx with the same
    tables/labels, so the normal template-filling logic below (and the format
    builder's live document editor) can treat it exactly like a Word-sourced
    format instead of a plain PDF."""
    from pdf2docx import Converter

    cv = Converter(pdf_path)
    try:
        cv.convert(out_path)
    finally:
        cv.close()
    return out_path

def _convert_pdf_to_docx(pdf_path, format_id) -> str:
    out_path = os.path.join(_template_cache_dir(), f"format_{format_id}_template.docx")
    return convert_pdf_to_docx(pdf_path, out_path)

def _iter_items(doc):
    """Flat list of every paragraph in the document, in document order, including
    paragraphs nested inside table cells (at any depth). Table-based layouts are
    how almost every real lesson-plan template is built, so anchor-finding and
    filling must be able to see into cells, not just the top-level body.

    Each item also carries its table context (the cell it lives in, and that
    cell's row siblings) so fill logic can target the right place — the same
    cell, the next cell in the row, and so on — without having to rediscover
    the table structure later.

    A merged cell (horizontal gridSpan or vertical vMerge) is returned by
    python-docx's row.cells once per spanned column/row — the same underlying
    cell object repeating. Without deduping that here, a wide merged label
    cell (common for a long instruction like "Flow:" spanning two columns)
    would have every one of its paragraphs walked and appended twice, each
    duplicate becoming its own spurious field candidate downstream.
    """
    items = []
    seen_tc_ids = set()

    def walk(parent_el, cell, row_cells, col_idx):
        for child in parent_el:
            if child.tag == qn("w:p"):
                items.append({
                    "el": child,
                    "cell": cell,
                    "row_cells": row_cells,
                    "col_idx": col_idx,
                })
            elif child.tag == qn("w:tbl"):
                table = Table(child, doc)
                for row in table.rows:
                    cells = row.cells
                    for c_idx, c in enumerate(cells):
                        tc_id = id(c._tc)
                        if tc_id in seen_tc_ids:
                            continue
                        seen_tc_ids.add(tc_id)
                        walk(c._tc, c, cells, c_idx)

    walk(doc.element.body, None, None, None)
    return items

def _cell_is_empty(cell):
    return not any(p.text.strip() for p in cell.paragraphs)

def _has_fillable_slot(doc, items, idx):
    """True if the item at this position has a real, nearby place for a
    value to go, by any of the heuristics the actual fill logic (further
    below) uses: an empty sibling cell in the same row, blank lines later in
    the same cell, or a blank paragraph immediately following it. Lets
    candidate_label_lines() recognize a table-cell label even when it has no
    colon or heading markup at all — the common "Grade Level | ____" grid
    layout — by checking for the blank a person would actually write into,
    the same way the fill logic itself locates one."""
    item = items[idx]
    cell, row_cells, col_idx = item["cell"], item["row_cells"], item["col_idx"]

    if cell is not None and row_cells and col_idx is not None:
        if _find_empty_sibling_cell(row_cells, cell, col_idx) is not None:
            return True

    # A merged header label whose blank answer cells are in the row below.
    if cell is not None and _weekly_cells(item):
        return True

    if cell is not None:
        cell_paragraphs = cell.paragraphs
        anchor_pos = next((i for i, p in enumerate(cell_paragraphs) if p._p is item["el"]), None)
        if anchor_pos is not None and any(not p.text.strip() for p in cell_paragraphs[anchor_pos + 1:]):
            return True

    next_idx = idx + 1
    if next_idx < len(items) and items[next_idx]["cell"] is cell:
        if not _element_text(doc, items[next_idx]["el"]):
            return True

    return False

def _find_empty_sibling_cell(row_cells, cell, col_idx, claimed=None):
    """Find the blank value cell for a label cell in the same table row.
    Most templates put the label immediately left of its blank, but some put
    the label on the right with the blank cell(s) before it — so this checks
    rightward first (the more common layout) and falls back to searching
    leftward rather than assuming a fixed direction.

    `claimed` is the set of cell ids already handed to another field in this
    same fill/render pass — skipping those (rather than just checking
    emptiness) stops two labels in the same row from racing for one blank
    cell, where the loser would otherwise fall through and get its value
    stuffed into its own label cell instead."""
    claimed = claimed or ()
    for c_idx in range(col_idx + 1, len(row_cells)):
        candidate = row_cells[c_idx]
        if candidate is cell or id(candidate._tc) in claimed:
            continue
        if _cell_is_empty(candidate):
            return candidate
    for c_idx in range(col_idx - 1, -1, -1):
        candidate = row_cells[c_idx]
        if candidate is cell or id(candidate._tc) in claimed:
            continue
        if _cell_is_empty(candidate):
            return candidate
    return None

# ---- Weekly fields: one answer per day, each in its own cell ----
# A weekly lesson plan (ILAW) answers most rows once per day, under a
# MONDAY..FRIDAY header, so one field has several blank cells rather than one.

_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _tc_text(tc):
    return "".join(t.text or "" for t in tc.iter(qn("w:t"))).strip()


def _row_grid(tr):
    """[(tc, start_col, span), ...] for one table row, in grid columns, so cells
    in different rows (or tables built on the same grid) can be lined up."""
    col = 0
    trpr = tr.find(qn("w:trPr"))
    if trpr is not None:
        before = trpr.find(qn("w:gridBefore"))
        if before is not None:
            col = int(before.get(qn("w:val")) or 0)
    out = []
    for tc in tr.findall(qn("w:tc")):
        span = _cell_grid_span(tc)
        out.append((tc, col, span))
        col += span
    return out


def _table_grid_width(tbl):
    return len(tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol")))


def _day_header(doc):
    """The document's day header: ({grid_col: "Monday", ...}, table grid width)
    from the first table row naming at least three weekdays, or (None, None)."""
    for tbl in doc.element.body.iter(qn("w:tbl")):
        for tr in tbl.findall(qn("w:tr")):
            labels = {}
            for tc, start, _span in _row_grid(tr):
                text = _tc_text(tc).lower()
                if text in _WEEKDAY_NAMES:
                    labels[start] = text.capitalize()
            if len(labels) >= 3:
                return labels, _table_grid_width(tbl)
    return None, None


def _weekly_cells(item):
    """Where a weekly field's parts go, left to right, as [(tc, start_col, span)]:
    the run of blank cells right after the label in its own row or, when the
    label is the last cell of a merged header row ("Performance Standards:"
    spanning the week), the blank cells directly under it in the next row."""
    cell = item.get("cell")
    if cell is None:
        return []
    label_tc = cell._tc
    tr = label_tc.getparent()
    if tr is None or tr.tag != qn("w:tr"):
        return []
    grid = _row_grid(tr)
    pos = next((i for i, g in enumerate(grid) if g[0] is label_tc), None)
    if pos is None:
        return []

    beside = []
    for tc, start, span in grid[pos + 1:]:
        if _tc_text(tc):
            break
        beside.append((tc, start, span))
    if beside or pos + 1 < len(grid):
        return beside

    _tc, label_start, label_span = grid[pos]
    below_tr = tr.getnext()
    while below_tr is not None and below_tr.tag != qn("w:tr"):
        below_tr = below_tr.getnext()
    if below_tr is None:
        return []
    below = [(tc, start, span) for tc, start, span in _row_grid(below_tr)
             if start >= label_start and start + span <= label_start + label_span]
    if len(below) >= 2 and all(not _tc_text(tc) for tc, _s, _sp in below):
        return below
    return []


def weekly_part_labels(doc, cells, header=None):
    """A name for each weekly part: the day(s) above its column in the day
    header when the document has one ("Monday", or "Monday to Tuesday" for a
    cell spanning two days), otherwise "Column 1", "Column 2"..."""
    labels, width = header if header is not None else _day_header(doc)
    fallback = [f"Column {i}" for i in range(1, len(cells) + 1)]
    if not labels or not cells:
        return fallback
    tbl = cells[0][0].getparent().getparent()
    if tbl is not None and _table_grid_width(tbl) == width:
        names = []
        for _tc, start, span in cells:
            covered = [labels[c] for c in range(start, start + span) if c in labels]
            if not covered:
                return fallback
            names.append(covered[0] if len(covered) == 1 else f"{covered[0]} to {covered[-1]}")
        return names
    ordered = [labels[c] for c in sorted(labels)]
    return ordered if len(ordered) == len(cells) else fallback


def _weekly_parts(value, count):
    """A weekly value as exactly `count` strings. Older saves or a model that
    answered with one string still land, in the first part."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        value = []
    parts = ["" if v is None else str(v) for v in value][:count]
    return parts + [""] * (count - len(parts))


def _fill_weekly(doc, items, idx, value, rich, claimed_cells):
    """Write each part of a weekly value into its own cell, leaving a part with
    nothing in it blank rather than borrowing another day's text."""
    cells = [c for c in _weekly_cells(items[idx]) if id(c[0]) not in claimed_cells]
    parts = _weekly_parts(value, len(cells))
    rich_parts = list(rich) if isinstance(rich, (list, tuple)) else []
    for i, (tc, _start, _span) in enumerate(cells):
        claimed_cells.add(id(tc))
        paragraphs = [Paragraph(p, None) for p in tc.findall(qn("w:p"))]
        rich_html = rich_parts[i] if i < len(rich_parts) else ""
        if rich_html:
            _fill_paragraphs_rich(doc, paragraphs, parse_rich_value(rich_html))
        elif parts[i].strip():
            _fill_paragraphs(doc, paragraphs, parts[i])

def _fill_paragraphs(doc, paragraphs, value):
    """Write value's lines into an existing run of (assumed blank) paragraphs,
    cloning the last one for any extra lines the value needs."""
    lines = _value_lines(value)
    els = [p._p for p in paragraphs]
    template_el = els[0]

    for i, line in enumerate(lines):
        if i < len(els):
            _set_paragraph_text(doc, els[i], line)
        else:
            new_el = copy.deepcopy(template_el)
            _set_paragraph_text(doc, new_el, line)
            els[-1].addnext(new_el)
            els.append(new_el)

def _append_in_cell(doc, anchor_el, value):
    """Last resort within a table cell: add new lines right after the label,
    cloning the label paragraph's formatting so the cell's look (borders,
    shading, font) is preserved instead of falling back to a plain paragraph."""
    lines = _value_lines(value)
    template_el = anchor_el
    insert_after = anchor_el
    for line in lines:
        new_el = copy.deepcopy(template_el)
        _set_paragraph_text(doc, new_el, line)
        insert_after.addnext(new_el)
        insert_after = new_el

def _fill_cell_value(doc, items, idx, value, claimed_cells=None):
    """Fill a field whose label anchor lives inside a table cell. Tries, in
    order: an empty cell later in the same row (the common label|value table
    layout), extra blank lines left in the same cell under the label, and
    finally appending new lines after the label without disturbing the table.

    `claimed_cells` tracks value cells already used by another field in this
    same export, so two labels never fight over the same blank — see
    _find_empty_sibling_cell."""
    if claimed_cells is None:
        claimed_cells = set()
    item = items[idx]
    anchor_el = item["el"]
    cell = item["cell"]
    row_cells = item["row_cells"]
    col_idx = item["col_idx"]

    if row_cells and col_idx is not None:
        sibling = _find_empty_sibling_cell(row_cells, cell, col_idx, claimed_cells)
        if sibling is not None:
            _fill_paragraphs(doc, sibling.paragraphs, value)
            claimed_cells.add(id(sibling._tc))
            return

    cell_paragraphs = cell.paragraphs
    anchor_pos = next((i for i, p in enumerate(cell_paragraphs) if p._p is anchor_el), None)
    if anchor_pos is not None:
        blanks = [p for p in cell_paragraphs[anchor_pos + 1:] if not p.text.strip()]
        if blanks:
            _fill_paragraphs(doc, blanks, value)
            return

    _append_in_cell(doc, anchor_el, value)

# ---- Rich-text values: a field the teacher styled directly in the live
# document editor (generator.js) is saved as sanitized HTML — a small subset
# (b/strong, i/em, u, ul/ol/li, br) — instead of a plain string. These mirror
# the plain fill functions above exactly, but write real bold/italic/
# underline runs and List Bullet/List Number paragraphs instead of flattening
# everything to plain text. ----

class _RichLineParser(_html_parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = [{"runs": [], "list": None}]
        self.list_stack = []
        self.bold = 0
        self.italic = 0
        self.underline = 0
        # Nested <span class="fs-lg fc-red hl-yellow"> wrappers. A stack rather
        # than a single value, so an inner span overrides an outer one and the
        # outer one comes back when the inner closes. Every <span> is pushed,
        # including one carrying no recognised class, so the pops stay aligned
        # with the opens.
        self.span_stack = []

    def _new_line(self, list_type=None):
        self.lines.append({"runs": [], "list": list_type})

    def handle_starttag(self, tag, attrs):
        if tag in ("b", "strong"):
            self.bold += 1
        elif tag in ("i", "em"):
            self.italic += 1
        elif tag == "u":
            self.underline += 1
        elif tag == "br":
            self._new_line()
        elif tag == "ul":
            self.list_stack.append("bullet")
        elif tag == "ol":
            self.list_stack.append("number")
        elif tag == "li":
            list_type = self.list_stack[-1] if self.list_stack else "bullet"
            if self.lines[-1]["runs"]:
                self._new_line(list_type)
            else:
                self.lines[-1]["list"] = list_type
        elif tag == "span":
            classes = set((dict(attrs).get("class") or "").split())
            self.span_stack.append({
                "size": next((c for c in classes if c in _FONT_SIZE_BY_CLASS), None),
                "color": next((c for c in classes if c in _FONT_COLOR_BY_CLASS), None),
                "highlight": next((c for c in classes if c in _HIGHLIGHT_BY_CLASS), None),
            })

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("i", "em"):
            self.italic = max(0, self.italic - 1)
        elif tag == "u":
            self.underline = max(0, self.underline - 1)
        elif tag in ("ul", "ol") and self.list_stack:
            self.list_stack.pop()
        elif tag == "span" and self.span_stack:
            self.span_stack.pop()

    def handle_data(self, data):
        if not data:
            return
        def innermost(key):
            for frame in reversed(self.span_stack):
                if frame[key]:
                    return frame[key]
            return None

        self.lines[-1]["runs"].append({
            "text": data,
            "bold": bool(self.bold),
            "italic": bool(self.italic),
            "underline": bool(self.underline),
            "size": innermost("size"),
            "color": innermost("color"),
            "highlight": innermost("highlight"),
        })

def parse_rich_value(html_str):
    """Parse a field's sanitized rich-text HTML into
    [{"runs": [{"text","bold","italic","underline"}, ...], "list": None|"bullet"|"number"}, ...],
    dropping any line left with no actual text (a stray <br>/<li>)."""
    parser = _RichLineParser()
    parser.feed(html_str or "")
    lines = [l for l in parser.lines if any(r["text"].strip() for r in l["runs"])]
    if not lines:
        lines = [{"runs": [{"text": "-", "bold": False, "italic": False, "underline": False,
                            "size": None, "color": None, "highlight": None}], "list": None}]
    return lines

def _apply_run_marks(run, r):
    run.bold = bool(r["bold"])
    run.italic = bool(r["italic"])
    run.underline = bool(r["underline"])
    # The size/colour/highlight a teacher picked in the document toolbar. Read
    # with .get() because a value stored before these existed has no such key.
    _apply_run_style_classes(run, r.get("size"), r.get("color"), r.get("highlight"))

def _set_paragraph_rich(doc, para_el, line, template_run=None):
    """Like _set_paragraph_text, but writes one line's runs (each with its
    own bold/italic/underline) into the paragraph instead of one plain
    string, and applies a bullet/numbered list style when the line came from
    an <li>."""
    para = Paragraph(para_el, doc)
    existing = list(para.runs)
    runs = line["runs"] or [{"text": "", "bold": False, "italic": False, "underline": False,
                             "size": None, "color": None, "highlight": None}]

    for i, r in enumerate(runs):
        if i < len(existing):
            run = existing[i]
            run.text = r["text"]
        else:
            run = para.add_run(r["text"])
            if template_run is not None:
                _copy_run_style(template_run, run)
        _apply_run_marks(run, r)

    for extra in existing[len(runs):]:
        extra.text = ""

    if line["list"]:
        style_name = _LIST_STYLE_BY_TYPE.get(line["list"])
        if style_name and _has_style(doc, style_name):
            try:
                para.style = doc.styles[style_name]
            except Exception:
                pass

def _fill_paragraphs_rich(doc, paragraphs, lines):
    els = [p._p for p in paragraphs]
    template_el = els[0]
    template_run = Paragraph(template_el, doc).runs[0] if Paragraph(template_el, doc).runs else None

    for i, line in enumerate(lines):
        if i < len(els):
            _set_paragraph_rich(doc, els[i], line, template_run)
        else:
            new_el = copy.deepcopy(template_el)
            _set_paragraph_rich(doc, new_el, line, template_run)
            els[-1].addnext(new_el)
            els.append(new_el)

def _append_in_cell_rich(doc, anchor_el, lines):
    template_run = Paragraph(anchor_el, doc).runs[0] if Paragraph(anchor_el, doc).runs else None
    insert_after = anchor_el
    for line in lines:
        new_el = copy.deepcopy(anchor_el)
        _set_paragraph_rich(doc, new_el, line, template_run)
        insert_after.addnext(new_el)
        insert_after = new_el

def _fill_cell_value_rich(doc, items, idx, lines, claimed_cells=None):
    if claimed_cells is None:
        claimed_cells = set()
    item = items[idx]
    anchor_el = item["el"]
    cell = item["cell"]
    row_cells = item["row_cells"]
    col_idx = item["col_idx"]

    if row_cells and col_idx is not None:
        sibling = _find_empty_sibling_cell(row_cells, cell, col_idx, claimed_cells)
        if sibling is not None:
            _fill_paragraphs_rich(doc, sibling.paragraphs, lines)
            claimed_cells.add(id(sibling._tc))
            return

    cell_paragraphs = cell.paragraphs
    anchor_pos = next((i for i, p in enumerate(cell_paragraphs) if p._p is anchor_el), None)
    if anchor_pos is not None:
        blanks = [p for p in cell_paragraphs[anchor_pos + 1:] if not p.text.strip()]
        if blanks:
            _fill_paragraphs_rich(doc, blanks, lines)
            return

    _append_in_cell_rich(doc, anchor_el, lines)

def _replace_block_region_rich(doc, anchor_el, boundary_el, lines):
    region_els = []
    sib = anchor_el.getnext()
    while sib is not None and sib is not boundary_el:
        region_els.append(sib)
        sib = sib.getnext()

    template_el = next(
        (el for el in region_els if el.tag == qn("w:p") and _element_text(doc, el)),
        None,
    )
    template_run = None
    if template_el is not None:
        p = Paragraph(template_el, doc)
        template_run = p.runs[0] if p.runs else None

    new_els = []
    for line in lines:
        if template_el is not None:
            new_el = copy.deepcopy(template_el)
        else:
            para = doc.add_paragraph()
            new_el = para._p
            new_el.getparent().remove(new_el)
        _set_paragraph_rich(doc, new_el, line, template_run)
        new_els.append(new_el)

    insert_after = anchor_el
    for new_el in new_els:
        insert_after.addnext(new_el)
        insert_after = new_el

    for el in region_els:
        el.getparent().remove(el)

def _export_from_template(plan, fmt, template_path) -> str:
    doc = Document(template_path)
    values = plan.get_values()
    rich_values = plan.get_rich_values()
    fields_sorted = sorted(fmt.fields, key=lambda f: f.sort_order)

    items = _iter_items(doc)

    anchors = _locate_anchors(doc, items, fields_sorted)
    if not anchors:
        raise ValueError("No field labels from this format could be found in the reference file.")

    # After _locate_anchors, deliberately. Anchors resolve by stored position
    # first but fall back to matching a field's label text, and these edits can
    # rewrite exactly that text, so resolving first keeps a renamed label from
    # orphaning its own field. Before the fill, so the values land in the
    # document the teacher actually edited.
    apply_doc_edits(doc, items, plan.get_doc_edits())

    # Weekly fields always fill their own day cells, never an inline blank.
    consumed = _fill_labeled_blanks(
        doc, items, [f for f in fields_sorted if f.field_type != "weekly"], anchors, values)

    other_anchor_els = {
        id(items[anchors[f.field_key]]["el"])
        for f in fields_sorted
        if f.field_key in anchors
    }

    remaining = [f for f in fields_sorted if f.field_key in anchors and f.field_key not in consumed]

    # Cell-anchored fields are filled in document order with a shared claimed
    # set, so two labels in the same row never race for one blank value cell
    # (see _find_empty_sibling_cell). Block-region fields keep the original
    # bottom-up order — safe here since each mutates a disjoint stretch of
    # paragraphs identified by direct element references, not by re-deriving
    # positions from anchors after an earlier mutation.
    cell_fields = sorted(
        (f for f in remaining if items[anchors[f.field_key]]["cell"] is not None),
        key=lambda f: anchors[f.field_key],
    )
    claimed_cells = set()
    for field in cell_fields:
        idx = anchors[field.field_key]
        rich_html = rich_values.get(field.field_key)
        if field.field_type == "weekly" and _weekly_cells(items[idx]):
            _fill_weekly(doc, items, idx, values.get(field.field_key), rich_html, claimed_cells)
            continue
        if isinstance(rich_html, list):
            rich_html = "<br>".join(part for part in rich_html if part)
        if rich_html:
            _fill_cell_value_rich(doc, items, idx, parse_rich_value(rich_html), claimed_cells)
        else:
            value = values.get(field.field_key, "")
            _fill_cell_value(doc, items, idx, value, claimed_cells)

    block_fields = sorted(
        (f for f in remaining if items[anchors[f.field_key]]["cell"] is None),
        key=lambda f: anchors[f.field_key],
        reverse=True,
    )
    for field in block_fields:
        idx = anchors[field.field_key]
        item = items[idx]
        boundary_el = _next_boundary(doc, item["el"], other_anchor_els - {id(item["el"])})
        rich_html = rich_values.get(field.field_key)
        if rich_html:
            _replace_block_region_rich(doc, item["el"], boundary_el, parse_rich_value(rich_html))
        else:
            value = values.get(field.field_key, "")
            _replace_block_region(doc, item["el"], boundary_el, value)

    unmatched = [f for f in fields_sorted if f.field_key not in anchors]
    if unmatched:
        heading_style = _sample_style(doc, heading=True)
        body_style = _sample_style(doc, heading=False)
        current_section = None
        for field in unmatched:
            if field.section_group != current_section:
                current_section = field.section_group
                if current_section:
                    _add_styled_heading(doc, current_section, heading_style)
            _add_styled_label(doc, field.label, body_style)
            _add_field_value(doc, field, values.get(field.field_key, ""), body_style)

    return _save(doc, plan)

def _element_text(doc, el):
    if el.tag == qn("w:p"):
        return Paragraph(el, doc).text.strip()
    if el.tag == qn("w:tbl"):
        table = Table(el, doc)
        return " ".join(
            cell.text.strip() for row in table.rows for cell in row.cells if cell.text.strip()
        )
    return ""

def _keywords(label):
    words = re.findall(r"[a-zA-Z]+", (label or "").lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]

def _locate_field_anchors(doc, items, fields, used=None):
    anchors = {}
    used = set() if used is None else used
    for field in fields:
        kws = _keywords(field.label)
        if not kws:
            continue
        for idx, item in enumerate(items):
            if idx in used:
                continue
            text = _element_text(doc, item["el"])
            if not text or len(text) > _LABEL_MAX_CHARS:
                continue
            if all(kw in text.lower() for kw in kws):
                anchors[field.field_key] = idx
                used.add(idx)
                break
    return anchors

def _locate_anchors(doc, items, fields):
    """Resolve each field to its position (index into `items`) in the real
    document. A field defined through the document editor carries an
    anchor_index recorded when the teacher clicked its exact spot in the
    reference file — that's used directly and is unambiguous. Only fields
    saved before anchor_index existed fall back to keyword matching against
    their label text."""
    anchors = {}
    used = set()
    needs_keyword_search = []

    for field in fields:
        idx = getattr(field, "anchor_index", None)
        if idx is not None and 0 <= idx < len(items) and idx not in used:
            anchors[field.field_key] = idx
            used.add(idx)
        else:
            needs_keyword_search.append(field)

    if needs_keyword_search:
        anchors.update(_locate_field_anchors(doc, items, needs_keyword_search, used))

    return anchors

def _looks_like_label(text):
    if not text or len(text) > _LABEL_MAX_CHARS:
        return False
    if _HEADING_RE.match(text) or _SIGNATURE_RE.match(text):
        return True
    return text.rstrip().endswith(":")

def _copy_run_style(source_run, target_run):
    src_rpr = source_run._r.find(qn("w:rPr"))
    if src_rpr is None:
        return
    target_r = target_run._r
    existing = target_r.find(qn("w:rPr"))
    if existing is not None:
        target_r.remove(existing)
    target_r.insert(0, copy.deepcopy(src_rpr))

def _fill_inline_value(doc, para_el, value):
    para = Paragraph(para_el, doc)
    runs = para.runs
    if not runs:
        return False
    full_text = para.text
    colon_pos = full_text.find(":")
    if colon_pos == -1:
        return False
    keep_len = colon_pos + 1

    consumed = 0
    split_run_index = None
    for i, run in enumerate(runs):
        run_len = len(run.text)
        if consumed + run_len < keep_len:
            consumed += run_len
            continue
        split_run_index = i
        break

    if split_run_index is None:
        new_run = para.add_run(f" {value}")
        _copy_run_style(runs[-1], new_run)
        return True

    split_run = runs[split_run_index]
    local_cut = keep_len - consumed
    split_run.text = split_run.text[:local_cut] + f" {value}"
    for extra in runs[split_run_index + 1:]:
        extra.text = ""
    return True

def _fill_labeled_blanks(doc, items, fields, anchors, values):
    consumed = set()

    for field in fields:
        if field.field_key not in anchors:
            continue
        value = values.get(field.field_key)
        if value in (None, "", []):
            continue

        idx = anchors[field.field_key]
        anchor_item = items[idx]
        anchor_el = anchor_item["el"]

        filled_any = False
        target = None
        for window_idx in range(idx, min(idx + 1 + _PREAMBLE_MATCH_WINDOW, len(items))):
            window_item = items[window_idx]
            # Never let the "blank on the next line" search wander out of the
            # anchor's own context — e.g. from a body paragraph into the first
            # cell of a table that happens to follow it, or across a cell
            # boundary into a neighboring cell.
            if window_item["cell"] is not anchor_item["cell"]:
                break
            para = Paragraph(window_item["el"], doc)
            # An underlined run only counts as a fillable blank when its own
            # text is actually blank (nothing, spaces, or underscores) — a
            # label styled with underline for emphasis (common in DepEd
            # templates) has underlined runs too, but they're the label text
            # itself, not a blank to overwrite.
            underlined = [r for r in para.runs if r.underline and not re.sub(r"[_\s]", "", r.text)]
            if underlined:
                target = underlined
                break
            if window_idx != idx:
                break

        if target:
            target[0].text = str(value)
            for extra in target[1:]:
                extra.text = ""
            filled_any = True
        elif (
            anchor_item["cell"] is None
            # A table-cell label (even one ending in a colon, like "Flow:")
            # always prefers its dedicated value cell over inline-after-colon
            # filling — see _fill_cell_value below — so the answer lands in
            # the blank cell next to it instead of being crammed into the
            # same cell as the label.
            and not isinstance(value, list)
            and "\n" not in str(value).strip()
            and _fill_inline_value(doc, anchor_el, value)
        ):
            filled_any = True

        if filled_any:
            consumed.add(field.field_key)

    return consumed

def _next_boundary(doc, anchor_el, other_anchor_ids):
    sib = anchor_el.getnext()
    while sib is not None:
        if sib.tag == qn("w:sectPr"):
            return sib
        if sib.tag == qn("w:tbl"):
            # A table is always a hard boundary: never treat it as part of a
            # field's "blank region" to be cleared, or it gets deleted along
            # with the blank paragraphs around it.
            return sib
        if id(sib) in other_anchor_ids:
            return sib
        if sib.tag == qn("w:p"):
            text = _element_text(doc, sib)
            if _looks_like_label(text):
                return sib
        sib = sib.getnext()
    return None

def _value_lines(value):
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items or ["-"]
    text = str(value).strip() if value is not None else ""
    if not text:
        return ["-"]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines or ["-"]

def _set_paragraph_text(doc, para_el, text):
    para = Paragraph(para_el, doc)
    runs = para.runs
    if runs:
        runs[0].text = text
        for extra in runs[1:]:
            extra.text = ""
    else:
        para.add_run(text)

def _build_lines_from_template(doc, template_el, lines):
    built = []
    for line in lines:
        new_el = copy.deepcopy(template_el)
        _set_paragraph_text(doc, new_el, line)
        built.append(new_el)
    return built

def _build_lines_from_style(doc, style, lines):
    built = []
    for line in lines:
        para = doc.add_paragraph()
        run = para.add_run(line)
        _apply_style(run, style, bold_override=False)
        el = para._p
        el.getparent().remove(el)
        built.append(el)
    return built

def _replace_block_region(doc, anchor_el, boundary_el, value):
    region_els = []
    sib = anchor_el.getnext()
    while sib is not None and sib is not boundary_el:
        region_els.append(sib)
        sib = sib.getnext()

    template_el = next(
        (el for el in region_els if el.tag == qn("w:p") and _element_text(doc, el)),
        None,
    )

    lines = _value_lines(value)
    if template_el is not None:
        new_els = _build_lines_from_template(doc, template_el, lines)
    else:
        new_els = _build_lines_from_style(doc, _sample_style(doc, heading=False), lines)

    insert_after = anchor_el
    for new_el in new_els:
        insert_after.addnext(new_el)
        insert_after = new_el

    for el in region_els:
        el.getparent().remove(el)

def _sample_style(doc, heading):
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text or not para.runs:
            continue
        run = para.runs[0]
        is_heading_like = bool(_HEADING_RE.match(text)) or bool(run.bold and len(text) < 60)
        if is_heading_like != heading:
            continue
        try:
            size = run.font.size
        except Exception:
            size = None
        try:
            color = run.font.color.rgb if run.font.color and run.font.color.type else None
        except Exception:
            color = None
        return {
            "name": run.font.name,
            "size": size,
            "bold": run.bold if run.bold is not None else heading,
            "color": color,
        }
    return {"name": None, "size": None, "bold": heading, "color": None}

def _apply_style(run, style, bold_override=None):
    run.bold = style.get("bold", False) if bold_override is None else bold_override
    if style.get("name"):
        run.font.name = style["name"]
    if style.get("size"):
        try:
            run.font.size = style["size"]
        except Exception:
            pass
    if style.get("color"):
        try:
            run.font.color.rgb = style["color"]
        except Exception:
            pass

def _add_styled_heading(doc, text, style):
    para = doc.add_paragraph()
    run = para.add_run(text)
    _apply_style(run, style, bold_override=True)
    return para

def _add_styled_label(doc, text, style):
    para = doc.add_paragraph()
    run = para.add_run(text)
    _apply_style(run, style, bold_override=True)
    return para

def _has_style(doc, name):
    try:
        doc.styles[name]
        return True
    except KeyError:
        return False

def _add_field_value(doc, field, value, style):
    bullet_style = "List Bullet" if _has_style(doc, "List Bullet") else None

    def _line(text, bullet=False):
        para = doc.add_paragraph(style=bullet_style if bullet else None)
        run = para.add_run(text)
        _apply_style(run, style, bold_override=False)
        return para

    # A weekly value, outside its day cells, reads as one labelled line per day.
    if field.field_type == "weekly" and isinstance(value, list):
        names = field.parts_list or []
        written = False
        for i, part in enumerate(value):
            text = " ".join(str(part or "").split())
            if text:
                name = names[i] if i < len(names) else f"Part {i + 1}"
                _line(f"{name}: {text}")
                written = True
        if not written:
            _line("-")
        return

    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        if not items:
            _line("-")
            return
        for item in items:
            _line(item, bullet=True)
        return

    text = str(value).strip() if value is not None else ""
    if not text:
        _line("-")
        return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        _line("-")
        return

    if field.field_type in ("list", "table") and len(lines) > 1:
        for line in lines:
            _line(line.lstrip("-• \t"), bullet=True)
    else:
        for line in lines:
            _line(line)

def _export_generic(plan, fmt) -> str:
    doc = Document()
    doc.add_heading(plan.title or fmt.name, level=0)

    meta = doc.add_paragraph()
    meta.add_run(
        f"Subject: {plan.subject or '-'}    "
        f"Grade Level: {plan.grade_level or '-'}    "
        f"Quarter: {plan.quarter or '-'}    "
        f"Date: {plan.date or '-'}"
    ).italic = True

    values = plan.get_values()
    fields_sorted = sorted(fmt.fields, key=lambda f: f.sort_order)
    default_style = {"name": None, "size": None, "bold": False, "color": None}

    current_section = None
    for field in fields_sorted:
        if field.section_group != current_section:
            current_section = field.section_group
            if current_section:
                doc.add_heading(current_section, level=1)

        doc.add_heading(field.label, level=2)
        _add_field_value(doc, field, values.get(field.field_key, ""), default_style)

    return _save(doc, plan)

def _save(doc, plan) -> str:
    os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
    filename = f"lesson_plan_{plan.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.docx"
    path = os.path.join(Config.GENERATED_FOLDER, filename)
    doc.save(path)
    return path
