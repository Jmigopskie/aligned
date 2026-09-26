# Word-fidelity document view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The document a teacher sees in the app (generator, format builder, both plan previews) looks like the file does in Word, and the five built-in templates look like their original PDFs.

**Architecture:** A new read-only module `backend/services/docx_layout.py` resolves Word's layout (page, style cascade, numbering, table geometry, borders, cell margins, pictures) into inline CSS in points. `docx_service`'s existing `_render_*` functions call it and keep their HTML contract, so field slots, anchors, weekly cells, detection and export are untouched. The frontend stops imposing typography on `.lp-doc` and zooms with CSS `zoom` and a default "Fit". A one-off script repairs the five built-in .docx templates against their source PDFs.

**Tech Stack:** Python 3 / Flask, python-docx, lxml, PyMuPDF (already installed with pdf2docx), vanilla JS/CSS.

**Spec:** `docs/superpowers/specs/2026-09-26-word-fidelity-rendering-design.md`

## Global Constraints

- Every emitted length is in points: twips / 20, half-points / 2, EMU / 12700, formatted by `_pt()` (`936.0` → `936pt`, `5.4` → `5.4pt`).
- No new dependencies. PyMuPDF is used only by the one-off repair script and one test.
- The HTML contract stays: `lp-doc`, `lp-table`, `lp-td`, `lp-td-value`, `lp-p`, `lp-candidate`, `data-anchor-index`, `lp-field`, `lp-field-inline`, `lp-field-block`, `lp-field-cell`, `data-field-key`, `data-part` (in that attribute order after `data-field-key`).
- Keep the element IDs the JS uses. All CSS goes in `frontend/css/style.css`. No emoji icons. No em dashes in UI copy.
- Bump the asset version `?v=2026-09-26c` → `?v=2026-09-26d` in every HTML file.
- A property Layout can't read drops only that property; rendering never raises because of layout.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015CLhpZkxttCjfcSJgpVusu
  ```
- Python: `PY=C:/tle/rel-Aligned/aligned/backend/venv/Scripts/python.exe`. Run tests from `backend/` in the worktree: `cd backend && $PY test_render_fidelity.py`. Set `PYTHONIOENCODING=utf-8` when printing document text.
- Scratch files go in `C:/Users/jmj11/.claude/jobs/d7419724/tmp/fid/` (call it `$FID`).
- VPS: never overwrite `backend/.env`, always run `backup.sh` first, no SSH keys added, the password is only used on the plink/pscp command line.

## Review Focus

1. **A list marker must never be saved as document text.** The generator's `anchorText()` and the builder's `extractAnchorState()` read a paragraph's DOM text. Markers are drawn by CSS `::before` from `data-marker`, so they are not in the DOM text. Task 3 asserts the marker is not inside the paragraph's markup.
2. **Files with no numbering part, no theme, or converted junk values** (`tblInd="730.0"`, empty or `Type3` font names) must render. Task 2 tests `730.0`; Task 1 tests `Type3`; Task 7 renders all five built-ins, which have no numbering or theme parts.
3. **A picture the browser can't show** (EMF/WMF, or a broken relationship) is left out and the page still renders. Task 4 tests a broken `r:embed`.
4. **Fit inside a modal that opens hidden** (plan previews) must fit once it becomes visible, not stay at 100% of a 0-width box. Task 6 uses a ResizeObserver and checks it in the browser.
5. **Structure drift from the template repair** would unpin fields on saved plans. Task 7's script asserts the paragraph count and per-paragraph text are preserved, and `test_builtins.py` asserts the item counts and that every field still anchors to its label.

---

## File Structure

- Create `backend/services/docx_layout.py`: the `Layout` class and helpers. One responsibility: read Word layout and return CSS or `<img>` markup.
- Modify `backend/services/docx_service.py:418-809`: the `_render_*` functions call `Layout`; the old styling helpers are deleted.
- Create `backend/test_render_fidelity.py`: assert-based checks, runnable directly.
- Modify `backend/test_builtins.py`: add the anchor, structure and logo guards for the repaired templates.
- Modify `frontend/css/style.css`: the `.lp-doc` rules (around lines 2941-2993, 3090, 4577-4592).
- Modify `frontend/js/doc-toolbar.js:44-47,120,153-272`: CSS zoom with Fit.
- Modify `frontend/js/api.js`: add `docFitScale()` and `fitDocPage()`.
- Modify `frontend/js/generator.js:~2757` and `frontend/js/lesson-plan-list.js:~355`: fit the previews.
- Modify `frontend/*.html`: bump the asset version.
- Replace `backend/builtin/formats/{4as-lesson-plan,dlp,ilaw-lesson-plan,pal3-sdlp,snhs-dlp}.docx` with repaired versions.
- Scratch, not committed: `$FID/repair.py`, `$FID/evidence.py`.

---

### Task 1: Layout skeleton: page and text cascade, wired into the renderer

**Files:**
- Create: `backend/services/docx_layout.py`
- Modify: `backend/services/docx_service.py` (imports; `_render_block_children` … `_render_html_paragraph`, lines 418-629)
- Test: `backend/test_render_fidelity.py`

**Interfaces:**
- Produces: `docx_layout.Layout(doc)` with `page() -> (css: str, width_pt: float)`, `paragraph(p_el) -> (css: str, marker: dict | None)`, `run_css(r_el, p_el) -> str`, `slot_css(p_el) -> str`, `pictures(r_el) -> str` (returns `""` until Task 4). Module helpers `_pt(v) -> str`, `_num(v, default)`, `_val(el, attr="val")`, `_on(el)`, `_last(chain, tag)`, `_merged(chain, tag) -> dict`, `_font_css(name) -> str`.
- The `docx_service` render functions gain a trailing `layout` parameter: `_render_block_children(doc, parent_el, slots, cell_value_targets, index_by_el_id, layout)`, `_render_html_paragraph(doc, p_el, slots, index_by_el_id, layout)`, `_render_html_table(doc, table, slots, cell_value_targets, index_by_el_id, layout)`, `_render_html_cell(doc, cell, slots, cell_value_targets, cell_css, colspan, rowspan, index_by_el_id, layout)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/test_render_fidelity.py`:

```python
"""Self-check for the document view's fidelity to Word.

The document a teacher sees is HTML drawn from the format's .docx. It has to
look like the file does in Word: the page's true size, the file's fonts and
spacing, Word's table borders and cell margins, list numbers, and pictures.
Each check builds a small .docx holding just the property under test and reads
the rendered HTML back.

Run it directly: `venv/Scripts/python test_render_fidelity.py`.
"""
import io
import os
import re
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt

from services import docx_service

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads",
                      "T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx")


def _save(doc):
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


def _render(doc):
    path = _save(doc)
    try:
        return docx_service.render_reference_html(path)["html"]
    finally:
        os.remove(path)


def _p_style(html, text):
    """The style attribute of the paragraph whose first text is `text`."""
    match = re.search(r'<p class="lp-p[^"]*" style="([^"]*)"[^>]*>(?:<span[^>]*>)?' + re.escape(text), html)
    assert match, (text, html[:600])
    return match.group(1)


def check_page():
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(13), Inches(8.5)
    section.left_margin = section.right_margin = Inches(0.5)
    section.top_margin = section.bottom_margin = Inches(0.5)
    doc.add_paragraph("x")
    html = _render(doc)
    assert html.startswith('<div class="lp-doc" style="width:936pt;padding:36pt 36pt 36pt 36pt;'), html[:200]
    assert 'data-page-width="936"' in html
    print("  page OK")


def check_text_cascade():
    doc = Document()
    doc.styles["Normal"].font.name = "Arial Narrow"
    doc.styles["Normal"].font.size = Pt(9)
    p = doc.add_paragraph()
    p.add_run("plain")
    big = p.add_run("big")
    big.font.size = Pt(14)
    big.bold = True
    doc.add_paragraph().add_run("junk").font.name = "Type3 (8 0 R)"
    spaced = doc.add_paragraph("spaced").paragraph_format
    spaced.space_before, spaced.space_after = Pt(6), Pt(3)
    spaced.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spaced.line_spacing = Pt(14)
    hanging = doc.add_paragraph("hanging").paragraph_format
    hanging.left_indent, hanging.first_line_indent = Pt(36), Pt(-18)
    html = _render(doc)

    # Style (Normal) under direct formatting, fonts and sizes exact.
    assert "<span style=\"font-family:'Arial Narrow',sans-serif;font-size:9pt\">plain</span>" in html, html
    assert "font-size:14pt;font-weight:700\">big</span>" in html, html
    # A converted file's unnamed PDF font shows as the source PDFs' Arial.
    assert "<span style=\"font-family:'Arial',sans-serif;font-size:9pt\">junk</span>" in html, html
    style = _p_style(html, "spaced")
    assert "margin-top:6pt;margin-bottom:3pt" in style and "line-height:14pt" in style, style
    style = _p_style(html, "hanging")
    assert "margin-left:36pt" in style and "text-indent:-18pt" in style, style
    # No invented typography: the old heading heuristic's classes are gone.
    assert "lp-heading" not in html and "lp-bold" not in html
    print("  text cascade OK")


def main():
    check_page()
    check_text_cascade()
    print("render fidelity OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: FAIL on the `check_page` assertion (the current `lp-doc` has no inline style).

- [ ] **Step 3: Create `backend/services/docx_layout.py`**

```python
"""Word's own layout, as CSS for the document view.

The document a teacher sees in the app is HTML drawn from the format's .docx
(docx_service.render_template_html / render_reference_html). For it to look
like the file does in Word, every length, font and border has to come from the
file, not from the app's stylesheet. Layout reads those properties the way Word
resolves them (document defaults, then the table's style, then the paragraph
style chain, the character style chain, and direct formatting last) and hands
back inline CSS in points, so 100% zoom is the page's true size.

It only reads. A property it can't make sense of is left out and the page
still renders: a canvas that renders is worth more than one that is exact.
"""
import base64
import logging
import re

from docx.oxml.ns import qn
from lxml import etree

_log = logging.getLogger(__name__)

_EMU_PER_PT = 12700
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

_SERIF = {"times new roman", "times", "cambria", "georgia", "bookman old style", "bookman", "garamond",
          "book antiqua", "palatino linotype", "century schoolbook", "baskerville old face"}
# Word's single line spacing is a font metric; CSS takes a multiple of the font
# size. Factors for the fonts these templates use; 1.15 fits the rest.
_LINE_FACTOR = {"calibri": 1.22, "aptos": 1.2, "cambria": 1.17, "century gothic": 1.23}
_THEME_FONT = {"minorHAnsi": "minor", "minorAscii": "minor", "minorBidi": "minor", "minorEastAsia": "minor",
               "majorHAnsi": "major", "majorAscii": "major", "majorBidi": "major", "majorEastAsia": "major"}
_HIGHLIGHT = {"yellow": "#FFFF00", "green": "#00FF00", "cyan": "#00FFFF", "magenta": "#FF00FF",
              "blue": "#0000FF", "red": "#FF0000", "darkBlue": "#000080", "darkCyan": "#008080",
              "darkGreen": "#008000", "darkMagenta": "#800080", "darkRed": "#800000",
              "darkYellow": "#808000", "darkGray": "#808080", "lightGray": "#C0C0C0",
              "black": "#000000", "white": "#FFFFFF"}
_UNDERLINE_STYLE = {"double": "double", "dotted": "dotted", "dash": "dashed", "wave": "wavy"}
_ALIGN = {"center": "center", "right": "right", "end": "right", "both": "justify", "distribute": "justify"}
_OFF = {"0", "false", "off"}


def _pt(value):
    """A length in points, trimmed: 936.0 -> '936pt', 5.4 -> '5.4pt'."""
    return f"{round(value, 2):g}pt"


def _num(value, default=None):
    """Word writes whole numbers, but converted files carry values like "730.0"."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _val(el, attr="val"):
    return None if el is None else el.get(qn("w:" + attr))


def _on(el):
    """A toggle property (w:b, w:i, ...): present means on unless val says off."""
    return el is not None and (_val(el) or "true").lower() not in _OFF


def _local(el):
    return etree.QName(el).localname


def _last(chain, tag):
    """The most specific <w:tag> in a chain of pPr/rPr/tblPr elements."""
    found = None
    for el in chain:
        child = el.find(qn("w:" + tag))
        if child is not None:
            found = child
    return found


def _merged(chain, tag):
    """Attributes of every <w:tag> in the chain, later ones winning per attribute."""
    out = {}
    for el in chain:
        child = el.find(qn("w:" + tag))
        if child is not None:
            out.update({etree.QName(k).localname: v for k, v in child.attrib.items()})
    return out


def _font_css(name):
    name = (name or "").strip()
    # PDF conversion leaves names like "Type3 (8 0 R)" (or none at all) for
    # fonts the PDF drew without naming; the source PDFs set that text in Arial.
    if not name or name.startswith("Type3"):
        name = "Arial"
    generic = "serif" if name.lower() in _SERIF else "sans-serif"
    return "font-family:'%s',%s" % (name.replace("'", ""), generic)


class Layout:
    """Word's layout for one document. Build once per render: it caches the
    styles, theme and numbering, and list counters advance as paragraphs are
    laid out in document order."""

    def __init__(self, doc):
        self.doc = doc
        styles_el = doc.styles.element
        self._styles = {}
        self._default_style = {}
        for style in styles_el.findall(qn("w:style")):
            sid = style.get(qn("w:styleId"))
            self._styles[sid] = style
            if style.get(qn("w:default")) in ("1", "true"):
                self._default_style.setdefault(style.get(qn("w:type")), sid)
        defaults = styles_el.find(qn("w:docDefaults"))
        self._default_rpr = defaults.find(qn("w:rPrDefault") + "/" + qn("w:rPr")) if defaults is not None else None
        self._default_ppr = defaults.find(qn("w:pPrDefault") + "/" + qn("w:pPr")) if defaults is not None else None
        self._theme_fonts = self._read_theme_fonts()
        self._numbering = self._read_numbering()
        self._counters = {}
        self._chains = {}

    # -- document parts ------------------------------------------------------

    def _read_theme_fonts(self):
        fonts = {"minor": "Calibri", "major": "Calibri Light"}
        try:
            for rel in self.doc.part.rels.values():
                if rel.reltype.endswith("/theme"):
                    root = etree.fromstring(rel.target_part.blob)
                    for kind in ("minor", "major"):
                        latin = root.find(f".//{{{_A}}}{kind}Font/{{{_A}}}latin")
                        if latin is not None and latin.get("typeface"):
                            fonts[kind] = latin.get("typeface")
        except Exception:
            _log.debug("Theme fonts unreadable; Word's defaults apply.", exc_info=True)
        return fonts

    def _read_numbering(self):
        """{numId: ({ilvl: lvl element}, {ilvl: start override})}."""
        return {}  # Task 3

    # -- style chains --------------------------------------------------------

    def _chain(self, style_id, kind):
        """Style elements from the root of the basedOn chain down to style_id
        (or the document's default style of that kind)."""
        key = (style_id, kind)
        if key not in self._chains:
            chain, seen = [], set()
            sid = style_id if style_id in self._styles else self._default_style.get(kind)
            while sid and sid in self._styles and sid not in seen:
                seen.add(sid)
                chain.append(self._styles[sid])
                sid = _val(self._styles[sid].find(qn("w:basedOn")))
            self._chains[key] = chain[::-1]
        return self._chains[key]

    def _table_styles(self, tbl_el):
        if tbl_el is None:
            return []
        tbl_pr = tbl_el.find(qn("w:tblPr"))
        style_id = _val(tbl_pr.find(qn("w:tblStyle"))) if tbl_pr is not None else None
        return self._chain(style_id, "table")

    def _enclosing_table(self, p_el):
        return next(p_el.iterancestors(qn("w:tbl")), None)

    def _p_style_id(self, p_el):
        ppr = p_el.find(qn("w:pPr"))
        return _val(ppr.find(qn("w:pStyle"))) if ppr is not None else None

    def _ppr_chain(self, p_el):
        """pPr elements for a paragraph, least to most specific."""
        ppr = p_el.find(qn("w:pPr"))
        chain = [self._default_ppr]
        chain += [s.find(qn("w:pPr")) for s in self._table_styles(self._enclosing_table(p_el))]
        chain += [s.find(qn("w:pPr")) for s in self._chain(self._p_style_id(p_el), "paragraph")]
        level = self._list_level([el for el in chain + [ppr] if el is not None])
        if level is not None:
            chain.append(level[0].find(qn("w:pPr")))
        chain.append(ppr)
        return [el for el in chain if el is not None]

    def _rpr_chain(self, p_el, r_el=None):
        """rPr elements for a run, or with no run for the paragraph mark (what
        Word gives an empty line or newly typed text), least to most specific."""
        ppr = p_el.find(qn("w:pPr"))
        chain = [self._default_rpr]
        chain += [s.find(qn("w:rPr")) for s in self._table_styles(self._enclosing_table(p_el))]
        chain += [s.find(qn("w:rPr")) for s in self._chain(self._p_style_id(p_el), "paragraph")]
        if r_el is None:
            chain.append(ppr.find(qn("w:rPr")) if ppr is not None else None)
        else:
            rpr = r_el.find(qn("w:rPr"))
            r_style = _val(rpr.find(qn("w:rStyle"))) if rpr is not None else None
            if r_style:
                chain += [s.find(qn("w:rPr")) for s in self._chain(r_style, "character")]
            chain.append(rpr)
        return [el for el in chain if el is not None]

    def _first_run_chain(self, p_el):
        for r_el in p_el.iter(qn("w:r")):
            if "".join(t.text or "" for t in r_el.iter(qn("w:t"))).strip():
                return self._rpr_chain(p_el, r_el)
        return None

    def _list_level(self, ppr_chain):
        return None  # Task 3

    # -- text ----------------------------------------------------------------

    def _font_name(self, chain):
        name = None
        for el in chain:
            fonts = el.find(qn("w:rFonts"))
            if fonts is None:
                continue
            theme = fonts.get(qn("w:asciiTheme")) or fonts.get(qn("w:hAnsiTheme"))
            if theme in _THEME_FONT:
                name = self._theme_fonts[_THEME_FONT[theme]]
            elif fonts.get(qn("w:ascii")) is not None or fonts.get(qn("w:hAnsi")) is not None:
                name = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
        return name

    def _text_css(self, chain, marks):
        """Font and size, plus (with marks) everything else a run can carry."""
        size = _num(_val(_last(chain, "sz")), 22) / 2
        vert = _val(_last(chain, "vertAlign")) if marks else None
        if vert in ("superscript", "subscript"):
            size *= 0.65
        css = [_font_css(self._font_name(chain)), "font-size:" + _pt(size)]
        if not marks:
            return css
        if vert in ("superscript", "subscript"):
            css.append("vertical-align:" + ("super" if vert == "superscript" else "sub"))
        if _on(_last(chain, "b")):
            css.append("font-weight:700")
        if _on(_last(chain, "i")):
            css.append("font-style:italic")
        underline = _val(_last(chain, "u"))
        deco = ["underline"] if underline and underline != "none" else []
        if _on(_last(chain, "strike")) or _on(_last(chain, "dstrike")):
            deco.append("line-through")
        if deco:
            css.append("text-decoration:" + " ".join(deco))
            if underline in _UNDERLINE_STYLE:
                css.append("text-decoration-style:" + _UNDERLINE_STYLE[underline])
        if _on(_last(chain, "caps")):
            css.append("text-transform:uppercase")
        elif _on(_last(chain, "smallCaps")):
            css.append("font-variant:small-caps")
        color = _val(_last(chain, "color"))
        if color and color.lower() != "auto":
            css.append("color:#" + color)
        highlight = _HIGHLIGHT.get(_val(_last(chain, "highlight")) or "")
        fill = _val(_last(chain, "shd"), "fill")
        if highlight:
            css.append("background-color:" + highlight)
        elif fill and fill.lower() != "auto":
            css.append("background-color:#" + fill)
        if _on(_last(chain, "vanish")):
            css.append("display:none")
        return css

    def run_css(self, r_el, p_el):
        try:
            return ";".join(self._text_css(self._rpr_chain(p_el, r_el), marks=True))
        except Exception:
            _log.debug("Run layout unreadable; drawn plain.", exc_info=True)
            return ""

    def slot_css(self, p_el):
        """What Word gives text typed into this (empty) paragraph: its mark's
        font and size, and its alignment."""
        try:
            css = self._text_css(self._rpr_chain(p_el), marks=False)
            align = _ALIGN.get(_val(_last(self._ppr_chain(p_el), "jc")) or "")
            if align:
                css.append("text-align:" + align)
            return ";".join(css)
        except Exception:
            _log.debug("Slot layout unreadable; drawn plain.", exc_info=True)
            return ""

    # -- paragraphs ----------------------------------------------------------

    def paragraph(self, p_el):
        """(css, marker) for one paragraph; marker is {"text", "width"} or None.
        Call once per paragraph, in document order: list counters advance here."""
        try:
            return self._paragraph(p_el)
        except Exception:
            _log.debug("Paragraph layout unreadable; drawn plain.", exc_info=True)
            return "", None

    def _same_style(self, p_el, other):
        if other is None or other.tag != qn("w:p"):
            return False
        return (self._p_style_id(other) or self._default_style.get("paragraph")) == \
            (self._p_style_id(p_el) or self._default_style.get("paragraph"))

    def _paragraph(self, p_el):
        chain = self._ppr_chain(p_el)
        spacing = _merged(chain, "spacing")
        before = _num(spacing.get("before"), 0) / 20
        after = _num(spacing.get("after"), 0) / 20
        # "Don't add space between paragraphs of the same style."
        if _on(_last(chain, "contextualSpacing")):
            if self._same_style(p_el, p_el.getprevious()):
                before = 0
            if self._same_style(p_el, p_el.getnext()):
                after = 0
        css = ["margin-top:" + _pt(before), "margin-bottom:" + _pt(after)]

        # Word sizes a line by its text; an empty line by its paragraph mark.
        font_chain = self._first_run_chain(p_el) or self._rpr_chain(p_el)
        css += self._text_css(font_chain, marks=False)
        single = _LINE_FACTOR.get((self._font_name(font_chain) or "").lower(), 1.15)
        line = _num(spacing.get("line"))
        rule = spacing.get("lineRule", "auto")
        if line is None:
            css.append("line-height:%g" % single)
        elif rule == "exact":
            css.append("line-height:" + _pt(line / 20))
        elif rule == "atLeast":
            css.append("line-height:max(%s,%gem)" % (_pt(line / 20), single))
        else:
            css.append("line-height:%g" % round(line / 240 * single, 3))

        ind = {}
        for el in chain:
            child = el.find(qn("w:ind"))
            if child is None:
                continue
            attrs = {etree.QName(k).localname: v for k, v in child.attrib.items()}
            if "firstLine" in attrs:
                ind.pop("hanging", None)
            if "hanging" in attrs:
                ind.pop("firstLine", None)
            ind.update(attrs)
        left = _num(ind.get("left", ind.get("start")), 0) / 20
        right = _num(ind.get("right", ind.get("end")), 0) / 20
        hanging = _num(ind.get("hanging"), 0) / 20
        first = _num(ind.get("firstLine"), 0) / 20
        if left:
            css.append("margin-left:" + _pt(left))
        if right:
            css.append("margin-right:" + _pt(right))
        if hanging:
            css.append("text-indent:" + _pt(-hanging))
        elif first:
            css.append("text-indent:" + _pt(first))
        align = _ALIGN.get(_val(_last(chain, "jc")) or "")
        if align:
            css.append("text-align:" + align)
        return ";".join(css), self._marker(chain, hanging)

    def _marker(self, chain, hanging):
        return None  # Task 3

    # -- page ----------------------------------------------------------------

    def page(self):
        """(css, width in pt): the page's true width and margins, and the
        document's default text style for anything typed straight onto it."""
        width = 612.0
        css = []
        try:
            sect = self.doc.element.body.find(qn("w:sectPr"))
            size = sect.find(qn("w:pgSz")) if sect is not None else None
            margins = sect.find(qn("w:pgMar")) if sect is not None else None
            width = _num(_val(size, "w"), 12240) / 20
            sides = [abs(_num(_val(margins, side), 1440)) / 20 for side in ("top", "right", "bottom", "left")]
            css += ["width:" + _pt(width), "padding:" + " ".join(_pt(v) for v in sides)]
            chain = [el for el in [self._default_rpr] + [s.find(qn("w:rPr")) for s in self._chain(None, "paragraph")]
                     if el is not None]
            css += self._text_css(chain, marks=False)
        except Exception:
            _log.debug("Page layout unreadable; default page drawn.", exc_info=True)
        return ";".join(css), width

    # -- pictures ------------------------------------------------------------

    def pictures(self, r_el):
        return ""  # Task 4
```

- [ ] **Step 4: Wire it into `docx_service.py`**

Add the import next to `from config import Config`:

```python
from services import docx_layout
```

Replace the functions from `_render_block_children` (line 418) through `_render_html_paragraph` (ending line 629) with the versions below. Leave `_plan_html_slots` and `_html_escape` as they are, and delete `_paragraph_html_classes`, `_ALIGN_CSS`, `_paragraph_align_style`, `_HIGHLIGHT_CSS` and `_run_style_css`:

```python
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
```

(`_plan_html_slots` and `_html_escape` unchanged.)

```python
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
    slot_css = layout.slot_css(p_el)
    slot_style = f' style="{slot_css}"' if slot_css else ""
    if kind == "inline":
        return (
            f'{open_tag}{inner} '
            f'<span class="lp-field lp-field-inline" data-field-key="{field_key}" '
            f'contenteditable="true"></span></p>'
        )

    # "block" or "same_cell" — label paragraph stays read-only, the value gets
    # its own editable block right after it (inside the same cell, if any),
    # in the style Word would give text typed there.
    return (
        f'{open_tag}{inner}</p>'
        f'<div class="lp-field lp-field-block" data-field-key="{field_key}"{slot_style} '
        f'contenteditable="true"></div>'
    )
```

In `_render_html_cell` and `_render_html_table`, add the pass-through only for now (Task 2 replaces their styling). Change their signatures and inner calls:

```python
def _render_html_cell(doc, cell, slots, cell_value_targets, default_borders, colspan=1, rowspan=1, index_by_el_id=None, layout=None):
    ...
    inner = _render_block_children(doc, cell._tc, slots, cell_value_targets, index_by_el_id, layout)
```

```python
def _render_html_table(doc, table, slots, cell_value_targets, index_by_el_id=None, layout=None):
    ...
            cells_html.append(_render_html_cell(
                doc, cell, slots, cell_value_targets, default_borders, colspan, rowspan, index_by_el_id, layout
            ))
```

- [ ] **Step 5: Run the new test and the existing ones**

Run: `cd backend && $PY test_render_fidelity.py && $PY test_weekly_fields.py && $PY test_doc_edits.py`
Expected: `render fidelity OK`, `weekly fields OK`, and test_doc_edits' own OK line.

- [ ] **Step 6: Commit**

```bash
git add backend/services/docx_layout.py backend/services/docx_service.py backend/test_render_fidelity.py
git commit -m "Document view: true page size and the file's own text styles"
```
(with the trailer from Global Constraints)

---

### Task 2: Tables (geometry, borders, cell margins, shading, rows, vertical alignment)

**Files:**
- Modify: `backend/services/docx_layout.py` (add module helper `_border_css`, methods `table`, `row`, `cell`, `_tbl_pr_chain`)
- Modify: `backend/services/docx_service.py` (`_render_html_cell`, `_render_html_table`; delete `_BORDER_SIDES`, `_border_side_css`, `_borders_from_element`, `_table_default_borders`, `_cell_border_style`, `_cell_shading_css`, `_table_col_widths_pct`)
- Test: `backend/test_render_fidelity.py`

**Interfaces:**
- Consumes: `Layout`, `_pt`, `_num`, `_val`, `_last`, `_merged` from Task 1.
- Produces: `Layout.table(tbl_el) -> (css: str, grid_pt: list[float])`, `Layout.row(tr_el) -> str`, `Layout.cell(tc_el, tbl_el, top, bottom, left, right) -> str`. `_render_html_cell(doc, cell, slots, cell_value_targets, cell_css, colspan, rowspan, index_by_el_id, layout)`.

- [ ] **Step 1: Add the failing test** to `test_render_fidelity.py` (and call it from `main()` after `check_text_cascade()`):

```python
def check_tables():
    doc = Document()
    grid = doc.add_table(rows=2, cols=2)
    grid.style = doc.styles["Table Grid"]
    grid.cell(0, 0).text = "A"
    tc_pr = grid.cell(1, 1)._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml('<w:tcMar %s><w:top w:w="100" w:type="dxa"/></w:tcMar>' % nsdecls("w")))
    tc_pr.append(parse_xml('<w:vAlign %s w:val="center"/>' % nsdecls("w")))
    grid.rows[0]._tr.get_or_add_trPr().append(
        parse_xml('<w:trHeight %s w:val="400" w:hRule="exact"/>' % nsdecls("w")))
    plain = doc.add_table(rows=1, cols=1)
    plain.cell(0, 0).text = "B"
    # Converted files write indents like "730.0"; still read, not dropped.
    plain._tbl.tblPr.append(parse_xml('<w:tblInd %s w:w="730.0" w:type="dxa"/>' % nsdecls("w")))
    html = _render(doc)
    tables = re.findall(r"<table.*?</table>", html, re.S)
    cells = re.findall(r'<td class="lp-td" style="([^"]*)"', tables[0])

    # Table Grid: outer borders on the table's edge, insideH/insideV between.
    assert "border-top:0.5pt solid #000000" in cells[0] and "border-right:0.5pt solid #000000" in cells[0], cells[0]
    # Word's default cell margins (Normal Table: 0.075in left and right).
    assert "padding:0pt 5.4pt 0pt 5.4pt" in cells[0], cells[0]
    # An exact row height is a minimum on screen, so typing can grow the row.
    assert '<tr style="height:20pt">' in tables[0], tables[0][:300]
    assert "padding:5pt 5.4pt 0pt 5.4pt" in cells[-1] and "vertical-align:middle" in cells[-1], cells[-1]
    assert re.search(r'<col style="width:[0-9.]+pt">', tables[0]), tables[0][:300]
    # No border in the file: none drawn (no fallback grid).
    plain_cell = re.search(r'<td class="lp-td" style="([^"]*)"', tables[1]).group(1)
    assert "border-top:none" in plain_cell and "border-left:none" in plain_cell, plain_cell
    assert "margin-left:36.5pt" in tables[1], tables[1][:300]
    print("  tables OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: FAIL in `check_tables` (the old cells carry no padding style).

- [ ] **Step 3: Add to `docx_layout.py`**

Module level, after `_font_css`:

```python
_VALIGN = {"center": "middle", "bottom": "bottom", "top": "top"}
_BORDER_STYLE = {"double": "double", "dashed": "dashed", "dotted": "dotted", "dashSmallGap": "dashed",
                 "dotDash": "dashed", "dotDotDash": "dotted"}
_SIDE = {"start": "left", "end": "right"}


def _border_css(el):
    val = _val(el)
    if not val or val in ("none", "nil"):
        return "none"
    size = _num(_val(el, "sz"), 4) / 8  # eighths of a point
    color = (_val(el, "color") or "").strip()
    color = "#000000" if not color or color.lower() == "auto" else "#" + color
    style = _BORDER_STYLE.get(val, "solid")
    if style == "double":
        size = max(size * 3, 2.25)  # both lines and the gap between them
    return "%s %s %s" % (_pt(max(size, 0.5)), style, color)
```

Methods on `Layout`, after `page()`:

```python
    # -- tables --------------------------------------------------------------

    def _tbl_pr_chain(self, tbl_el):
        tbl_pr = tbl_el.find(qn("w:tblPr"))
        chain = [s.find(qn("w:tblPr")) for s in self._table_styles(tbl_el)] + [tbl_pr]
        return [el for el in chain if el is not None]

    def table(self, tbl_el):
        """(css, column widths in pt) for a table."""
        try:
            chain = self._tbl_pr_chain(tbl_el)
            grid = [(_num(col.get(qn("w:w")), 0) or 0) / 20
                    for col in tbl_el.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))]
            fixed = bool(grid) and all(grid)
            css = ["table-layout:fixed"] if fixed else []
            width = _merged(chain, "tblW")
            if width.get("type") == "pct":
                raw = width.get("w", "")
                pct = _num(raw.rstrip("%")) if raw.endswith("%") else _num(raw, 0) / 50
                if pct:
                    css.append("width:%g%%" % round(pct, 2))
            elif width.get("type") == "dxa" and _num(width.get("w")):
                css.append("width:" + _pt(_num(width.get("w")) / 20))
            elif fixed:
                css.append("width:" + _pt(sum(grid)))
            jc = _val(_last(chain, "jc"))
            indent = _num(_merged(chain, "tblInd").get("w"), 0) / 20
            if jc == "center":
                css.append("margin-left:auto;margin-right:auto")
            elif jc in ("right", "end"):
                css.append("margin-left:auto")
            elif indent:
                css.append("margin-left:" + _pt(indent))
            return ";".join(css), grid if fixed else []
        except Exception:
            _log.debug("Table layout unreadable; drawn plain.", exc_info=True)
            return "", []

    def row(self, tr_el):
        # An "exact" height is shown as a minimum too: on screen a row has to
        # grow while a teacher types into it.
        height = _num(_val(tr_el.find(qn("w:trPr") + "/" + qn("w:trHeight"))), 0) / 20
        return "height:" + _pt(height) if height else ""

    def cell(self, tc_el, tbl_el, top, bottom, left, right):
        """CSS for one cell. top/bottom/left/right say whether each side lies on
        the table's outer edge (Word draws tblBorders there, insideH/insideV
        between cells)."""
        try:
            chain = self._tbl_pr_chain(tbl_el)
            tc_pr = tc_el.find(qn("w:tcPr"))

            table_borders = {}
            for el in chain:
                borders = el.find(qn("w:tblBorders"))
                for side in (borders if borders is not None else []):
                    if isinstance(side.tag, str):
                        table_borders[_SIDE.get(_local(side), _local(side))] = side
            pick = {"top": "top" if top else "insideH", "bottom": "bottom" if bottom else "insideH",
                    "left": "left" if left else "insideV", "right": "right" if right else "insideV"}
            sides = {side: table_borders.get(source) for side, source in pick.items()}
            cell_borders = tc_pr.find(qn("w:tcBorders")) if tc_pr is not None else None
            for el in (cell_borders if cell_borders is not None else []):
                if isinstance(el.tag, str) and _SIDE.get(_local(el), _local(el)) in sides:
                    sides[_SIDE.get(_local(el), _local(el))] = el
            css = ["border-%s:%s" % (side, _border_css(el)) for side, el in sides.items()]

            margins = {"top": 0.0, "right": 5.4, "bottom": 0.0, "left": 5.4}
            sources = [el.find(qn("w:tblCellMar")) for el in chain]
            sources.append(tc_pr.find(qn("w:tcMar")) if tc_pr is not None else None)
            for mar in sources:
                for side in (mar if mar is not None else []):
                    if not isinstance(side.tag, str):
                        continue
                    name = _SIDE.get(_local(side), _local(side))
                    if name in margins and (side.get(qn("w:type")) or "dxa") == "dxa":
                        margins[name] = _num(side.get(qn("w:w")), 0) / 20
            css.append("padding:" + " ".join(_pt(margins[s]) for s in ("top", "right", "bottom", "left")))

            if tc_pr is not None:
                fill = _val(tc_pr.find(qn("w:shd")), "fill")
                if fill and fill.lower() != "auto":
                    css.append("background-color:#" + fill)
                valign = _VALIGN.get(_val(tc_pr.find(qn("w:vAlign"))) or "")
                if valign:
                    css.append("vertical-align:" + valign)
            return ";".join(css)
        except Exception:
            _log.debug("Cell layout unreadable; drawn plain.", exc_info=True)
            return ""
```

- [ ] **Step 4: Replace the table rendering in `docx_service.py`**

Delete `_BORDER_SIDES`, `_border_side_css`, `_borders_from_element`, `_table_default_borders`, `_cell_border_style`, `_cell_shading_css` and `_table_col_widths_pct`. Keep `_tc_pr`, `_cell_grid_span` and `_vmerge_rowspans`. Replace `_render_html_cell` and `_render_html_table`:

```python
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
```

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && $PY test_render_fidelity.py && $PY test_weekly_fields.py`
Expected: `render fidelity OK` (page, text cascade, tables) and `weekly fields OK`.

- [ ] **Step 6: Commit**: `git commit -am "Document view: Word's table widths, borders, cell margins and row heights"` (plus trailer).

---

### Task 3: List numbers and bullets

**Files:**
- Modify: `backend/services/docx_layout.py` (`_read_numbering`, `_list_level`, `_marker`, module helpers `_format_number`, `_roman`, `_BULLET_GLYPHS`)
- Test: `backend/test_render_fidelity.py`

**Interfaces:**
- Consumes: `Layout._ppr_chain`, `Layout.paragraph` from Task 1.
- Produces: the `marker` returned by `Layout.paragraph()`, `{"text": "1.", "width": 18.0}` (width in pt, 0 for none), which `_render_html_paragraph` writes as `data-marker` and `--lp-marker-w`.

- [ ] **Step 1: Add the failing test** (call it from `main()` after `check_tables()`):

```python
def check_lists():
    doc = Document()
    numbering = doc.part.numbering_part.element
    numbering.append(parse_xml(
        '<w:abstractNum %s w:abstractNumId="90">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%%1."/>'
        '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>'
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%%2."/>'
        '<w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>' % nsdecls("w")))
    numbering.append(parse_xml(
        '<w:abstractNum %s w:abstractNumId="91"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:numFmt w:val="bullet"/><w:lvlText w:val="\uf0b7"/></w:lvl></w:abstractNum>' % nsdecls("w")))
    numbering.append(parse_xml('<w:num %s w:numId="90"><w:abstractNumId w:val="90"/></w:num>' % nsdecls("w")))
    numbering.append(parse_xml('<w:num %s w:numId="91"><w:abstractNumId w:val="91"/></w:num>' % nsdecls("w")))

    def listed(text, num_id, ilvl=0):
        p = doc.add_paragraph(text)
        p._p.get_or_add_pPr().append(parse_xml(
            '<w:numPr %s><w:ilvl w:val="%d"/><w:numId w:val="%s"/></w:numPr>' % (nsdecls("w"), ilvl, num_id)))

    for text, ilvl in (("one", 0), ("sub a", 1), ("sub b", 1), ("two", 0), ("sub again", 1)):
        listed(text, "90", ilvl)
    listed("dot", "91")
    html = _render(doc)

    assert re.findall(r'data-marker="([^"]*)"', html) == ["1.", "a.", "b.", "2.", "a.", "\u2022"], \
        re.findall(r'data-marker="([^"]*)"', html)
    # The marker hangs in the indent and is not text in the paragraph, so an
    # editor reading the paragraph back never saves "1." into the document.
    first = re.search(r'<p class="lp-p" style="([^"]*)" data-marker="1\."[^>]*>(.*?)</p>', html)
    assert first and "--lp-marker-w:18pt" in first.group(1) and "text-indent:-18pt" in first.group(1), html[:800]
    assert not re.sub(r"<[^>]+>", "", first.group(2)).startswith("1."), first.group(2)
    print("  lists OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: FAIL in `check_lists` (no markers yet: `[]`).

- [ ] **Step 3: Implement in `docx_layout.py`**

Module level:

```python
# Symbol and Wingdings bullets are stored as private-use code points that only
# mean something in those fonts; this is what they draw, in Unicode.
_BULLET_GLYPHS = {"\uf0b7": "\u2022", "\uf0a7": "\u25aa", "\uf0d8": "\u27a2", "\uf076": "\u2756",
                  "\uf0fc": "\u2713", "\uf06e": "\u25a0", "\uf0a8": "\u25a1"}


def _roman(n):
    out = ""
    for value, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += symbol
            n -= value
    return out


def _format_number(n, fmt):
    if fmt in ("lowerLetter", "upperLetter"):
        letters = chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1)  # Word: a..z, aa, bb
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("lowerRoman", "upperRoman"):
        return _roman(n) if fmt == "upperRoman" else _roman(n).lower()
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt == "none":
        return ""
    return str(n)  # decimal, and any format this view doesn't draw
```

Replace the three Task 1 stubs on `Layout`:

```python
    def _read_numbering(self):
        """{numId: ({ilvl: lvl element}, {ilvl: start override})}, with each
        list instance's level overrides applied."""
        try:
            root = self.doc.part.numbering_part.element
        except Exception:
            return {}
        abstracts = {
            a.get(qn("w:abstractNumId")): {lvl.get(qn("w:ilvl")): lvl for lvl in a.findall(qn("w:lvl"))}
            for a in root.findall(qn("w:abstractNum"))
        }
        out = {}
        for num in root.findall(qn("w:num")):
            levels = dict(abstracts.get(_val(num.find(qn("w:abstractNumId"))), {}))
            starts = {}
            for override in num.findall(qn("w:lvlOverride")):
                ilvl = override.get(qn("w:ilvl"))
                lvl = override.find(qn("w:lvl"))
                if lvl is not None:
                    levels[ilvl] = lvl
                start = _num(_val(override.find(qn("w:startOverride"))))
                if start is not None:
                    starts[ilvl] = int(start)
            out[num.get(qn("w:numId"))] = (levels, starts)
        return out

    def _list_level(self, ppr_chain):
        """(lvl element, numId, ilvl, starts) when the paragraph is in a list."""
        num_id, ilvl = None, "0"
        for ppr in ppr_chain:
            num_pr = ppr.find(qn("w:numPr"))
            if num_pr is not None:
                num_id = _val(num_pr.find(qn("w:numId"))) or num_id
                ilvl = _val(num_pr.find(qn("w:ilvl"))) or ilvl
        if not num_id or num_id == "0" or num_id not in self._numbering:
            return None
        levels, starts = self._numbering[num_id]
        lvl = levels.get(ilvl)
        return None if lvl is None else (lvl, num_id, int(ilvl), starts)

    def _marker(self, chain, hanging):
        level = self._list_level(chain)
        if level is None:
            return None
        lvl, num_id, ilvl, starts = level
        # ponytail: counters are per list instance (numId); Word also continues
        # numbering across instances of one abstract list, rare in these files.
        counts = self._counters.setdefault(num_id, {})
        start = starts.get(str(ilvl), int(_num(_val(lvl.find(qn("w:start"))), 1)))
        counts[ilvl] = counts.get(ilvl, start - 1) + 1
        for deeper in [k for k in counts if k > ilvl]:
            del counts[deeper]

        fmt = _val(lvl.find(qn("w:numFmt"))) or "decimal"
        pattern = _val(lvl.find(qn("w:lvlText"))) or ""
        if fmt == "bullet":
            text = "".join(_BULLET_GLYPHS.get(ch, "\u2022" if "\uf000" <= ch <= "\uf0ff" else ch) for ch in pattern)
        else:
            levels = self._numbering[num_id][0]

            def number(match):
                n = int(match.group(1)) - 1
                other = levels.get(str(n))
                other_fmt = (_val(other.find(qn("w:numFmt"))) if other is not None else None) or "decimal"
                return _format_number(counts.get(n, 1), other_fmt)

            text = re.sub(r"%([1-9])", number, pattern)
        suffix = _val(lvl.find(qn("w:suff"))) or "tab"
        if suffix == "space" or (suffix == "tab" and not hanging):
            text += " "
        return {"text": text, "width": hanging if suffix == "tab" else 0}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: `render fidelity OK` including `lists OK`.

- [ ] **Step 5: Commit**: `git commit -am "Document view: list numbers and bullets from the file's numbering"` (plus trailer).

---

### Task 4: Pictures

**Files:**
- Modify: `backend/services/docx_layout.py` (`pictures`, `_picture`, `_anchor_css`, `_BROWSER_IMAGES`)
- Test: `backend/test_render_fidelity.py`

**Interfaces:**
- Consumes: `_run_html` already calls `layout.pictures(run._r)` (Task 1).
- Produces: `Layout.pictures(r_el) -> str`, zero or more `<img src="data:...;base64,..." alt="" style="...">` tags.

- [ ] **Step 1: Add the failing test** (call it from `main()` after `check_lists()`):

```python
def _png():
    """A valid one-pixel PNG, built here so the test carries no binary file."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _make_floating(r_el):
    """Turn an inline picture into a square-wrapped one, 1pt from its column."""
    inline = r_el.find(".//" + qn("wp:inline"))
    anchor = parse_xml(
        '<wp:anchor %s distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="1" '
        'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="column"><wp:posOffset>12700</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        '</wp:anchor>' % nsdecls("wp"))
    for child in list(inline):
        anchor.append(child)
        if child.tag == qn("wp:extent"):
            anchor.append(parse_xml('<wp:wrapSquare %s wrapText="bothSides"/>' % nsdecls("wp")))
    inline.getparent().replace(inline, anchor)


def check_pictures():
    doc = Document()
    doc.add_picture(io.BytesIO(_png()), width=Pt(40), height=Pt(20))
    floating = doc.add_paragraph().add_run()
    floating.add_picture(io.BytesIO(_png()), width=Pt(30), height=Pt(30))
    _make_floating(floating._r)
    broken = doc.add_paragraph().add_run()
    broken.add_picture(io.BytesIO(_png()), width=Pt(10), height=Pt(10))
    broken._r.find(".//" + qn("a:blip")).set(qn("r:embed"), "rIdMissing")
    html = _render(doc)
    styles = re.findall(r'<img src="data:image/png;base64,[A-Za-z0-9+/=]+" alt="" style="([^"]*)">', html)
    # The unreadable picture is left out and the page still renders.
    assert len(styles) == 2, styles
    assert styles[0].startswith("width:40pt;height:20pt"), styles
    assert "float:left" in styles[1] and "margin-left:1pt" in styles[1] and "margin-right:9pt" in styles[1], styles
    print("  pictures OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: FAIL in `check_pictures` (`[]`).

- [ ] **Step 3: Implement in `docx_layout.py`**

Module level:

```python
_BROWSER_IMAGES = {"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp", "image/svg+xml"}
```

Replace the `pictures` stub on `Layout`:

```python
    def pictures(self, r_el):
        """<img> tags for the pictures in a run ("" for none). A picture the
        browser can't show (EMF/WMF) or can't be read is left out."""
        out = []
        for drawing in r_el.findall(qn("w:drawing")):
            for frame in drawing:
                if not isinstance(frame.tag, str):
                    continue
                try:
                    out.append(self._picture(frame))
                except Exception:
                    _log.debug("Picture unreadable; left out.", exc_info=True)
        return "".join(out)

    def _picture(self, frame):
        extent = frame.find(f"{{{_WP}}}extent")
        blip = frame.find(f".//{{{_A}}}blip")
        if extent is None or blip is None:
            return ""
        part = self.doc.part.related_parts.get(blip.get(_R_EMBED))
        if part is None or part.content_type not in _BROWSER_IMAGES:
            return ""
        css = ["width:" + _pt(_num(extent.get("cx"), 0) / _EMU_PER_PT),
               "height:" + _pt(_num(extent.get("cy"), 0) / _EMU_PER_PT)]
        css += self._anchor_css(frame) if _local(frame) == "anchor" else ["vertical-align:bottom"]
        src = "data:%s;base64,%s" % (part.content_type, base64.b64encode(part.blob).decode("ascii"))
        return '<img src="%s" alt="" style="%s">' % (src, ";".join(css))

    def _anchor_css(self, frame):
        """Where a floating picture sits, and how text wraps around it."""
        def position(axis):
            pos = frame.find(f"{{{_WP}}}position{axis}")
            if pos is None:
                return None, 0.0, None
            offset = pos.find(f"{{{_WP}}}posOffset")
            align = pos.find(f"{{{_WP}}}align")
            return (pos.get("relativeFrom"),
                    _num(offset.text, 0) / _EMU_PER_PT if offset is not None else 0.0,
                    align.text if align is not None else None)

        h_from, h_offset, h_align = position("H")
        _v_from, v_offset, _v_align = position("V")
        wrap = next((_local(c) for c in frame if isinstance(c.tag, str) and _local(c).startswith("wrap")),
                    "wrapNone")
        # An offset from the page or its margins can't be placed inside a cell
        # or paragraph; one from the column or the text itself can.
        x = h_offset if h_from in ("column", "character") else 0.0
        y = max(v_offset, 0.0)
        if frame.get("behindDoc") in ("1", "true") or wrap == "wrapNone":
            return ["position:absolute", "left:" + _pt(x), "top:" + _pt(y)]
        if wrap == "wrapTopAndBottom":
            return ["display:block", "margin-left:" + _pt(x), "margin-top:" + _pt(y)]
        side = "right" if h_align == "right" else "left"
        return ["float:" + side, "margin-left:" + _pt(x), "margin-top:" + _pt(y),
                "margin-right:" + _pt(_num(frame.get("distR"), 0) / _EMU_PER_PT)]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && $PY test_render_fidelity.py`
Expected: `render fidelity OK` including `pictures OK`.

- [ ] **Step 5: Commit**: `git commit -am "Document view: inline and floating pictures, logos included"` (plus trailer).

---

### Task 5: Typed text style, the teacher's sample, and the full backend suite

**Files:**
- Test: `backend/test_render_fidelity.py`
- Local only (gitignored): copy `C:/tle/rel-Aligned/aligned/backend/uploads/T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx` into the worktree's `backend/uploads/` so the sample check runs. The file holds a teacher's real names, so it is never committed (`backend/uploads/` is in `.gitignore`).

**Interfaces:**
- Consumes: `docx_service._iter_items`, `_element_text`, `_plan_html_slots`, `_render_doc_body_html`; `Layout.slot_css` (Task 1) used by `_render_html_cell` (Task 2).

- [ ] **Step 1: Add the tests** (call both from `main()` after `check_pictures()`):

```python
def check_slot_takes_the_cell_style():
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "School:"
    table.cell(0, 1).paragraphs[0]._p.get_or_add_pPr().append(parse_xml(
        '<w:rPr %s><w:rFonts w:ascii="Century Gothic" w:hAnsi="Century Gothic"/><w:sz w:val="20"/></w:rPr>'
        % nsdecls("w")))
    path = _save(doc)
    try:
        doc = Document(path)
        items = docx_service._iter_items(doc)
        idx = next(i for i, it in enumerate(items) if docx_service._element_text(doc, it["el"]) == "School:")
        slots, targets = docx_service._plan_html_slots(doc, items, {"school": idx})
        html = docx_service._render_doc_body_html(doc, items, slots, targets)
    finally:
        os.remove(path)
    # Typed text looks the way Word (and the export) will set it in that cell.
    assert re.search(r'data-field-key="school" style="font-family:\'Century Gothic\',sans-serif;font-size:10pt',
                     html), html
    print("  field slot takes the cell's style OK")


def check_teacher_sample():
    """The teacher's own ILAW plan: the look the user asked for."""
    if not os.path.isfile(SAMPLE):
        print("  teacher sample not in backend/uploads; skipped")
        return
    html = docx_service.render_reference_html(SAMPLE)["html"]
    assert 'data-page-width="936"' in html
    assert len(re.findall(r"<img ", html)) == 2, "both logos"
    assert "'Arial Narrow'" in html
    assert 'data-marker="1."' in html, "numbered objectives"
    print("  teacher sample OK")
```

- [ ] **Step 2: Copy the sample and run the fidelity tests**

Run: `cp "C:/tle/rel-Aligned/aligned/backend/uploads/T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx" backend/uploads/ && cd backend && $PY test_render_fidelity.py`
Expected: `render fidelity OK`. If `numbered objectives` fails, print the sample's markers with `re.findall(r'data-marker="([^"]*)"', html)[:10]`. If its objectives are literal "1." text rather than numbering, change that assertion to check the literal text is present, and note it in the commit.

- [ ] **Step 3: Run every backend test**

Run: `cd backend && for t in test_*.py; do $PY "$t" > /dev/null 2>&1 && echo "ok $t" || echo "FAIL $t"; done`
Expected: 14 lines, all `ok`. Any FAIL: rerun that file alone and fix the cause before going on.

- [ ] **Step 4: Commit**: `git add backend/test_render_fidelity.py && git commit -m "Fidelity checks: field slots and the teacher's ILAW sample"` (plus trailer).

---

### Task 6: Frontend: the page, CSS zoom and Fit

**Files:**
- Modify: `frontend/css/style.css`
- Modify: `frontend/js/api.js` (add `docFitScale`, `fitDocPage` near `labelTableCells`)
- Modify: `frontend/js/doc-toolbar.js`
- Modify: `frontend/js/generator.js` (after `previewBody.innerHTML = ...` in the plan preview, about line 2757)
- Modify: `frontend/js/lesson-plan-list.js` (after `previewBody.innerHTML = ...`, about line 355)
- Modify: all `frontend/*.html` (asset version)

**Interfaces:**
- Consumes: `.lp-doc` carries `style="width:…pt;…"` and `data-page-width` (Task 1). Paragraphs carry `data-marker` and `--lp-marker-w` (Task 3).
- Produces: `docFitScale(wrapEl) -> number`, `fitDocPage(wrapEl)`; `initDocViewControls` returns `{ setZoom, applyZoom, toggleFullscreen }` with `setZoom(index)`, where index `-1` is Fit.

- [ ] **Step 1: CSS.** In `style.css`, replace the rules from `.lp-doc {` through `.lp-doc .lp-td-value {…}` (about lines 2949-2993) with:

```css
/* The page itself. Its width, margins and default text style come inline from
   the .docx (docx_layout.Layout), in points, so 100% zoom is the file's true
   size. Nothing here may set typography, spacing or borders, or the page
   stops looking like the file. */
.lp-doc {
  background: #fff;
  margin: 0 auto;
  box-shadow: 0 1px 3px rgba(31, 41, 55, 0.12), 0 8px 20px rgba(31, 41, 55, 0.08);
  color: #000;
  zoom: var(--doc-zoom, 1);
}

.lp-doc .lp-p {
  margin: 0;
  /* Word keeps runs of spaces, and its tabs stop every half inch. */
  white-space: pre-wrap;
  tab-size: 36pt;
  /* Pictures placed "in front of text" position against their paragraph. */
  position: relative;
}

/* A list number or bullet, hanging in the paragraph's indent the way Word
   draws it. Drawn here rather than written into the paragraph, so it is never
   read back and saved as typed text. */
.lp-doc .lp-p[data-marker]::before {
  content: attr(data-marker);
  display: inline-block;
  min-width: var(--lp-marker-w, 0);
  text-indent: 0;
  white-space: pre;
}

.lp-doc .lp-table {
  border-collapse: collapse;
}

.lp-doc .lp-td {
  padding: 0;
  vertical-align: top;
  overflow-wrap: break-word;
}

.lp-doc a {
  color: inherit;
  text-decoration: none;
}

.lp-doc img {
  max-width: none;
}
```

Delete `.doc-builder-canvas .lp-doc { max-width: 940px; }` (about line 3090). Replace the zoom block (about lines 4574-4592, `.lp-doc-wrap { --doc-zoom: 1; }` through the `.lp-doc-wrap.is-zoomed .lp-doc` rule) with:

```css
/* Zoom scales the page with CSS zoom, which rescales layout as well as
   drawing, so scroll size, caret and selection stay right at any scale.
   doc-toolbar.js and fitDocPage() set --doc-zoom; the wrapper scrolls both
   ways once the page is wider than it. */
.lp-doc-wrap {
  --doc-zoom: 1;
}
```

Then run `grep -n "lp-heading\|lp-bold\|is-zoomed" frontend/css/style.css frontend/js/*.js` and remove any leftover rule or reference.

- [ ] **Step 2: Shared Fit helpers in `api.js`** (add above `function labelTableCells`):

```js
// The scale that fits a document page to its panel's width, never past its
// true size. The page's width comes from the .docx, in points.
function docFitScale(wrapEl) {
  const page = wrapEl.querySelector(".lp-doc[data-page-width]");
  if (!page) return 1;
  const pageWidth = (parseFloat(page.dataset.pageWidth) * 96) / 72;
  const cs = getComputedStyle(wrapEl);
  const available = wrapEl.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  if (!(pageWidth > 0) || !(available > 0)) return 1;
  return Math.min(1, available / pageWidth);
}

// Fits a read-only document preview (no zoom toolbar) to its panel, and keeps
// it fitted when the panel resizes or first becomes visible in a modal.
function fitDocPage(wrapEl) {
  const apply = () => wrapEl.style.setProperty("--doc-zoom", String(docFitScale(wrapEl)));
  apply();
  if (window.ResizeObserver && !wrapEl._docFitObserver) {
    wrapEl._docFitObserver = new ResizeObserver(apply);
    wrapEl._docFitObserver.observe(wrapEl);
  }
}
```

- [ ] **Step 3: Zoom with Fit in `doc-toolbar.js`.** Replace lines 44-47 with:

```js
// Zoom steps, as multipliers of the page's true size (100% is what Word shows
// at 100%). A fixed ladder, so − and + always land somewhere sane.
const DOC_ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
// "Fit": the page scaled to the panel's width, never past 100%. The default.
const DOC_ZOOM_FIT = -1;
```

In `renderDocToolbar`, change the readout button's `title="Reset zoom to 100%"` and label `100%` to `title="Fit the page to the panel"` and `Fit`.

In `initDocViewControls`, replace the comment above it and everything from `let zoomIndex = DOC_ZOOM_DEFAULT_INDEX;` through the Ctrl+wheel listener (lines 153-217) with:

```js
// Zoom (a ladder of steps, plus Fit) and fullscreen for a document page.
function initDocViewControls({ toolbarEl, wrapEl, stageEl, storageKey }) {
  // What goes fullscreen. The toolbar has to be inside it or it vanishes the
  // moment fullscreen starts, so callers pass the element containing both.
  // Both call sites pass stageEl, and the wrapper-level fullscreen CSS was
  // removed when the stage was introduced, so fsEl is always the stage.
  const fsEl = stageEl;

  let zoomIndex = DOC_ZOOM_FIT;

  const readout = toolbarEl.querySelector(".doc-zoom-readout");
  const fullscreenBtn = toolbarEl.querySelector("[data-fullscreen=toggle]");

  // Remembered per page so a teacher who works zoomed in doesn't have to set
  // it again every visit. A failure here is ignored: private mode and blocked
  // storage must not stop the document from rendering.
  if (storageKey) {
    try {
      const saved = parseInt(localStorage.getItem(storageKey), 10);
      if (!Number.isNaN(saved) && saved >= DOC_ZOOM_FIT && saved < DOC_ZOOM_STEPS.length) zoomIndex = saved;
    } catch (err) {
      /* storage unavailable; Fit applies */
    }
  }

  function currentScale() {
    return zoomIndex === DOC_ZOOM_FIT ? docFitScale(wrapEl) : DOC_ZOOM_STEPS[zoomIndex];
  }

  function applyZoom() {
    const scale = currentScale();
    wrapEl.style.setProperty("--doc-zoom", String(scale));
    const pct = `${Math.round(scale * 100)}%`;
    if (readout) readout.textContent = zoomIndex === DOC_ZOOM_FIT ? `Fit ${pct}` : pct;
    if (storageKey) {
      try {
        localStorage.setItem(storageKey, String(zoomIndex));
      } catch (err) {
        /* storage unavailable; the zoom still applies for this visit */
      }
    }
  }

  function setZoom(index) {
    zoomIndex = Math.max(DOC_ZOOM_FIT, Math.min(DOC_ZOOM_STEPS.length - 1, index));
    applyZoom();
  }

  // − and + step along the ladder from wherever the page is now, Fit included.
  function stepZoom(direction) {
    const scale = currentScale();
    if (direction > 0) {
      const next = DOC_ZOOM_STEPS.findIndex((s) => s > scale + 0.001);
      setZoom(next === -1 ? DOC_ZOOM_STEPS.length - 1 : next);
    } else {
      let next = 0;
      DOC_ZOOM_STEPS.forEach((s, i) => {
        if (s < scale - 0.001) next = i;
      });
      setZoom(next);
    }
  }

  toolbarEl.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.zoom;
      if (action === "in") stepZoom(1);
      else if (action === "out") stepZoom(-1);
      else setZoom(DOC_ZOOM_FIT);
    });
  });

  // Ctrl+scroll over the document zooms, as it does in every document viewer.
  wrapEl.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      stepZoom(event.deltaY < 0 ? 1 : -1);
    },
    { passive: false }
  );

  // Fit follows the panel: a resize, fullscreen, or a new document loaded in.
  const refit = () => {
    if (zoomIndex === DOC_ZOOM_FIT) applyZoom();
  };
  if (window.ResizeObserver) new ResizeObserver(refit).observe(wrapEl);
  new MutationObserver(refit).observe(wrapEl, { childList: true });
```

Keep the rest of the function (fullscreen, the final `applyZoom(); syncFullscreenButton(); return { setZoom, applyZoom, toggleFullscreen };`). Then `grep -n "DOC_ZOOM_DEFAULT_INDEX\|setZoom(" frontend/js/*.js`. There must be no remaining `DOC_ZOOM_DEFAULT_INDEX`, and any external `setZoom(n)` caller must still pass a ladder index.

- [ ] **Step 4: Fit the two previews.** In `generator.js`, right after `previewBody.innerHTML = renderPreviewMeta() + toolbar + warning + content;`, add:

```js
  previewBody.querySelectorAll(".lp-doc-wrap").forEach(fitDocPage);
```

In `lesson-plan-list.js`, right after `previewBody.innerHTML = meta + toolbar + warning + content;`, add the same line.

- [ ] **Step 5: Bump the asset version.** Replace `?v=2026-09-26c` with `?v=2026-09-26d` in every `frontend/*.html` (`grep -l "2026-09-26c" frontend/*.html`, then edit each). Check with `grep -c "2026-09-26c" frontend/*.html`: all 0.

- [ ] **Step 6: Check it in the browser.**
  1. Copy the local database and point the server at the copy, since the demo server must never use the local MySQL: `DATABASE_URL=sqlite:///C:/Users/jmj11/.claude/jobs/d7419724/tmp/demo.db $PY backend/run.py` (run in the background).
  2. Log in as `admin@aligned.local` / `ChangeMe123!` at `http://127.0.0.1:5000`.
  3. Open Create Lesson Plan and pick the TUP DLP format.
  4. Check the live document at 1440px wide:
     - the page sits at Fit;
     - the readout says `Fit NN%`;
     - − and + step through the ladder, and the readout button returns to Fit;
     - text still types into the highlighted slots.
  5. Resize to 390px wide: the whole page width is visible (Fit), and + makes it scroll sideways.
  6. Open a saved plan's preview from List of Lesson Plans: the page fits the modal.
  7. Open the format builder on an uploaded format: its canvas fits too.

  Screenshot each check.

- [ ] **Step 7: Commit**: `git add frontend && git commit -m "Document page: file's own look on screen, CSS zoom with Fit"` (plus trailer).

---

### Task 7: Repair the five built-in templates against their PDFs

**Files:**
- Scratch (not committed): `$FID/repair.py`
- Replace: `backend/builtin/formats/{4as-lesson-plan,dlp,ilaw-lesson-plan,pal3-sdlp,snhs-dlp}.docx`
- Modify: `backend/test_builtins.py` (add `check_templates_keep_their_structure`, `check_views_show_logos`; call both in `main()` after `check_export_fills_frozen_anchors`)

**Interfaces:**
- Consumes: `docx_service._iter_items`, `_element_text`, `render_template_html`; `builtins.BUILTIN_DIR`.

- [ ] **Step 1: Add the failing guards to `test_builtins.py`**

Add `import re` to the imports. Then:

```python
# Paragraph counts of the built-in templates. The PDF repair changed fonts,
# widths and a few characters, never structure: a field's anchor_index still
# names the same paragraph, so saved plans keep their answers where they were.
TEMPLATE_ITEMS = {"4as-lesson-plan": 60, "dlp": 111, "ilaw-lesson-plan": 190, "pal3-sdlp": 96, "snhs-dlp": 91}


def check_templates_keep_their_structure(app):
    folder = os.path.join(builtins.BUILTIN_DIR, "formats")
    with open(os.path.join(folder, "formats.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    for entry in manifest:
        doc = Document(os.path.join(folder, entry["template"]))
        items = docx_service._iter_items(doc)
        assert len(items) == TEMPLATE_ITEMS[entry["key"]], (entry["key"], len(items))
        for field in entry["fields"]:
            text = " ".join(docx_service._element_text(doc, items[field["anchor_index"]]["el"]).split()).lower()
            words = [w for w in re.findall(r"[a-z]+", field["label"].lower()) if len(w) > 3]
            assert any(w in text for w in words), (entry["key"], field["label"], text)
        # Converted files wrote row heights as "exact", which clips a filled
        # answer in Word; repaired ones grow with their text.
        assert not doc.element.body.xpath('.//w:trHeight[@w:hRule="exact"]'), entry["key"]
    print("  templates keep their structure OK")


def check_views_show_logos(app):
    """Every picture on a built-in's original PDF shows in its document view."""
    import pymupdf

    for fmt in builtin_formats():
        html = docx_service.render_template_html(fmt)["html"]
        want = len(pymupdf.open(fmt.source_file_path)[0].get_image_info())
        got = len(re.findall(r'<img src="data:image/[a-z+]+;base64,[A-Za-z0-9+/=]{40,}', html))
        assert got == want, (fmt.builtin_key, got, want)
    print("  logos in the document view OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && $PY test_builtins.py`
Expected: FAIL in `check_templates_keep_their_structure` on the `hRule="exact"` assertion. The item counts and labels pass, since they record the current structure.

- [ ] **Step 3: Write `$FID/repair.py`**

```python
"""One-off: repair the five built-in templates against their source PDFs.

The .docx templates were converted from the PDFs and lost fonts, column
widths, list markers and a link; rows became fixed-height. This measures each
PDF with PyMuPDF and writes corrected .docx files in place (git keeps the
originals). Structure is never changed: same paragraphs in the same cells.
Run: $PY repair.py   (prints what it changed and any table it couldn't measure)
"""
import collections
import os
import re
import sys

import pymupdf
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

WT = r"C:\tle\rel-Aligned\aligned\.claude\worktrees\builtins-owl-layout"
sys.path.insert(0, os.path.join(WT, "backend"))
from services import docx_service  # noqa: E402

FOLDER = os.path.join(WT, "backend", "builtin", "formats")
NAMES = ["4as-lesson-plan", "dlp", "ilaw-lesson-plan", "pal3-sdlp", "snhs-dlp"]
MARKER = re.compile(r"^(?:[\u2022\u25cf\u25aa\u25cb\u25a0-]|[A-Za-z]\.|\d{1,2}\.|[ivxIVX]{1,4}\.)$")
TBL_PR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
                "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]


def squash(text):
    return " ".join((text or "").replace("\u200b", "").split())


def alnum(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def family(pdf_font):
    """'ABCDEF+CenturyGothic-Bold' -> 'Century Gothic'; Type3 -> Arial."""
    name = pdf_font.split("+")[-1].split("-")[0].split(",")[0]
    if name.startswith("Type3"):
        return "Arial"
    for suffix in ("PSMT", "MT", "PS"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def pdf_spans(pdf):
    spans = []
    for pno, page in enumerate(pdf):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                line_text = squash("".join(s["text"] for s in line["spans"]))
                for s in line["spans"]:
                    if s["text"].strip():
                        spans.append({"page": pno, "bbox": pymupdf.Rect(s["bbox"]), "text": squash(s["text"]),
                                      "font": s["font"], "line": line_text})
    return spans


def find_span(spans, text, start=0):
    text = text.lower()
    for order in (range(start, len(spans)), range(0, start)):
        for i in order:
            s = spans[i]["text"].lower()
            if s and (text in s or (len(s) >= 3 and s in text)):
                return i
    return None


def run_text(r):
    return "".join(t.text or "" for t in r.iter(qn("w:t")))


def para_text(p):
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def set_font(holder, tag, name):
    """Set rFonts on a run (tag w:rPr under w:r) or a paragraph mark (w:rPr under w:pPr)."""
    rpr = holder.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        holder.insert(0 if tag == "r" else len(holder), rpr)
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(1 if rpr.find(qn("w:rStyle")) is not None else 0, fonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(qn("w:" + attr), name)
    for attr in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        fonts.attrib.pop(qn("w:" + attr), None)


def repair_fonts(doc, spans):
    fallback = family(collections.Counter(s["font"] for s in spans).most_common(1)[0][0])
    cursor, changed = 0, 0
    for p in doc.element.body.iter(qn("w:p")):
        first = None
        for r in p.iter(qn("w:r")):
            text = squash(run_text(r))
            if not text:
                continue
            hit = find_span(spans, text, cursor)
            if hit is not None:
                cursor = hit
            name = family(spans[hit]["font"]) if hit is not None else fallback
            set_font(r, "r", name)
            first = first or name
            changed += 1
        ppr = p.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            p.insert(0, ppr)
        set_font(ppr, "p", first or fallback)
    return changed


def vertical_rules(page, with_fills):
    xs = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) < 1 and abs(p1.y - p2.y) > 3:
                    xs.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
            elif item[0] == "re":
                r = item[1]
                if r.width < 3 and r.height > 3:
                    xs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif with_fills and r.width >= 3 and r.height > 3:
                    xs += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    return xs


def cluster(values, tol=1.5):
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def table_columns(pdf, spans, table, cursor):
    """Column boundaries (pt) for a table, measured from its PDF region."""
    texts = [squash(c.text) for row in table.rows for c in row.cells if squash(c.text)]
    if not texts:
        return None, cursor
    first = find_span(spans, texts[0][:40], cursor)
    if first is None:
        return None, cursor
    last = find_span(spans, texts[-1][:40], first)
    page_no = spans[first]["page"]
    y0 = spans[first]["bbox"].y0 - 3
    y1 = spans[last]["bbox"].y1 + 3 if last is not None and spans[last]["page"] == page_no else pdf[page_no].rect.y1
    n_cols = len(table._tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol")))
    for with_fills in (False, True):
        xs = cluster([x for x, a, b in vertical_rules(pdf[page_no], with_fills) if b >= y0 and a <= y1])
        if len(xs) == n_cols + 1:
            return xs, first
    # A header table drawn without rules: logo, centred text, logo.
    images = sorted((pymupdf.Rect(i["bbox"]) for i in pdf[page_no].get_image_info()), key=lambda r: r.x0)
    images = [r for r in images if r.y1 >= y0 - 80 and r.y0 <= y1 + 80]
    if n_cols == 3 and len(images) == 2:
        left, right = images
        return [left.x0, left.x1 + 6, right.x0 - 6, right.x1], first
    return None, first


def sort_tbl_pr(tbl_pr):
    rank = {name: i for i, name in enumerate(TBL_PR_ORDER)}
    children = sorted(list(tbl_pr), key=lambda el: rank.get(el.tag.split("}")[-1], 99))
    for el in children:
        tbl_pr.append(el)


def set_dxa(parent, tag, value, index=None):
    el = parent.find(qn("w:" + tag))
    if el is None:
        el = OxmlElement("w:" + tag)
        parent.insert(0, el) if index == 0 else parent.append(el)
    el.set(qn("w:w"), str(int(round(value))))
    el.set(qn("w:type"), "dxa")


def apply_columns(tbl, xs):
    widths = [round((b - a) * 20) for a, b in zip(xs, xs[1:])]
    for col, w in zip(tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(w))
    for tr in tbl.findall(qn("w:tr")):
        col = 0
        for tc in tr.findall(qn("w:tc")):
            tc_pr = tc.find(qn("w:tcPr"))
            if tc_pr is None:
                tc_pr = OxmlElement("w:tcPr")
                tc.insert(0, tc_pr)
            span_el = tc_pr.find(qn("w:gridSpan"))
            span = int(span_el.get(qn("w:val"))) if span_el is not None else 1
            set_dxa(tc_pr, "tcW", sum(widths[col:col + span]), index=0)
            col += span
    tbl_pr = tbl.find(qn("w:tblPr"))
    set_dxa(tbl_pr, "tblW", sum(widths))
    set_dxa(tbl_pr, "tblInd", xs[0] * 20)
    sort_tbl_pr(tbl_pr)


def fit_inside_page(tbl, page_twips):
    """Fallback when a table can't be measured: whole-number indent, and the
    table scaled to fit inside the page with equal space either side."""
    tbl_pr = tbl.find(qn("w:tblPr"))
    ind_el = tbl_pr.find(qn("w:tblInd"))
    ind = int(round(float(ind_el.get(qn("w:w"), "0")))) if ind_el is not None else 0
    cols = tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))
    total = sum(int(float(c.get(qn("w:w"), "0"))) for c in cols)
    if total and ind + total > page_twips - ind:
        factor = (page_twips - 2 * ind) / total
        xs = [ind / 20]
        for c in cols:
            xs.append(xs[-1] + int(float(c.get(qn("w:w")))) * factor / 20)
        apply_columns(tbl, xs)
    elif ind_el is not None:
        ind_el.set(qn("w:w"), str(ind))
    sort_tbl_pr(tbl_pr)


def resize_pictures(doc, pdf):
    extents = list(doc.element.body.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"))
    rects = sorted(((pno, pymupdf.Rect(i["bbox"])) for pno, page in enumerate(pdf) for i in page.get_image_info()),
                   key=lambda pr: (pr[0], round(pr[1].y0), pr[1].x0))
    if len(extents) != len(rects):
        print("   pictures: %d in docx, %d in PDF; sizes left as they are" % (len(extents), len(rects)))
        return
    for extent, (_pno, rect) in zip(extents, rects):
        cx, cy = str(int(rect.width * 12700)), str(int(rect.height * 12700))
        extent.set("cx", cx)
        extent.set("cy", cy)
        frame = extent.getparent()
        for ext in frame.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}ext"):
            ext.set("cx", cx)
            ext.set("cy", cy)


def add_hyperlink(doc, p, text, url, like_run):
    rid = doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    if like_run is not None and like_run.find(qn("w:rPr")) is not None:
        run.append(__import__("copy").deepcopy(like_run.find(qn("w:rPr"))))
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run.append(rpr)
    for tag, attrs in (("color", {"w:val": "1155CC"}), ("u", {"w:val": "single"})):
        el = rpr.find(qn("w:" + tag))  # not `or`: an lxml element with no children is falsy
        if el is None:
            el = OxmlElement("w:" + tag)
            rpr.append(el)
        for k, v in attrs.items():
            el.set(qn(k), v)
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)
    link.append(run)
    p.append(link)


def restore_text(doc, pdf, spans):
    """Markers and trailing text the conversion lost from a paragraph that
    already has text. An empty paragraph (an answer space) is never filled."""
    all_text = squash("\n".join(para_text(p) for p in doc.element.body.iter(qn("w:p")))).lower()
    lines = list(dict.fromkeys(s["line"] for s in spans))
    links = [(pno, link) for pno, page in enumerate(pdf) for link in page.get_links() if link.get("uri")]
    changed = []
    for p in doc.element.body.iter(qn("w:p")):
        runs = [r for r in p.iter(qn("w:r")) if run_text(r)]
        text = squash(para_text(p))
        if not runs or not text:
            continue
        first_t = next(runs[0].iter(qn("w:t")))
        # "A.Content Standards" -> "A. Content Standards"
        glued = re.match(r"^(\s*(?:[A-Za-z]|\d{1,2})\.)(?=[A-Za-z])", first_t.text or "")
        if glued:
            first_t.text = glued.group(1) + " " + first_t.text[len(glued.group(1)):]
            changed.append("space after " + glued.group(1).strip())
        # Wrapped lines joined with runs of spaces: one space, like the PDF.
        for t in p.iter(qn("w:t")):
            fixed = re.sub(r"(?<=\S) {3,}(?=\S)", " ", t.text or "")
            if fixed != t.text:
                t.text = fixed
                changed.append("gap in " + text[:30])
        text = squash(para_text(p))
        for line in lines:
            if line.lower() == text.lower():
                break
            if line.lower().endswith(" " + text.lower()):
                prefix = line[: -len(text)].strip()
                if MARKER.match(prefix):
                    first_t.text = prefix + " " + (first_t.text or "").lstrip()
                    first_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    changed.append("marker " + prefix)
                break
            if line.lower().startswith(text.lower() + " "):
                suffix = line[len(text):].strip()
                if suffix and suffix.lower() not in all_text:
                    span = next((s for s in spans if s["text"] == suffix), None)
                    url = next((link["uri"] for pno, link in links
                                if span and pno == span["page"] and pymupdf.Rect(link["from"]).intersects(span["bbox"])),
                               None)
                    if url:
                        add_hyperlink(doc, p, (" " if not para_text(p).endswith(" ") else "") + suffix, url, runs[-1])
                    else:
                        t = OxmlElement("w:t")
                        t.text = " " + suffix
                        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        runs[-1].append(t)
                    changed.append("suffix " + suffix)
                break
    return changed


def repair(name):
    path = os.path.join(FOLDER, name + ".docx")
    pdf = pymupdf.open(os.path.join(FOLDER, name + ".pdf"))
    doc = Document(path)
    before = [para_text(p) for p in doc.element.body.iter(qn("w:p"))]
    items_before = len(docx_service._iter_items(doc))
    spans = pdf_spans(pdf)
    print("==", name)

    print("   fonts on %d runs" % repair_fonts(doc, spans))
    page_twips = int(float(doc.element.body.find(qn("w:sectPr")).find(qn("w:pgSz")).get(qn("w:w"))))
    cursor = 0
    for i, table in enumerate(doc.tables):
        xs, cursor = table_columns(pdf, spans, table, cursor)
        if xs:
            apply_columns(table._tbl, xs)
            print("   table %d columns %s" % (i, [round(b - a, 1) for a, b in zip(xs, xs[1:])]))
        else:
            fit_inside_page(table._tbl, page_twips)
            print("   table %d NOT MEASURED: fitted inside the page" % i)
    for tbl in doc.element.body.iter(qn("w:tbl")):
        if tbl not in [t._tbl for t in doc.tables]:
            fit_inside_page(tbl, page_twips)  # nested tables
    for h in doc.element.body.iter(qn("w:trHeight")):
        if h.get(qn("w:hRule")) == "exact":
            h.set(qn("w:hRule"), "atLeast")
    resize_pictures(doc, pdf)
    for change in restore_text(doc, pdf, spans):
        print("   " + change)

    after = [para_text(p) for p in doc.element.body.iter(qn("w:p"))]
    assert len(after) == len(before), (name, len(before), len(after))
    for b, a in zip(before, after):
        assert alnum(a).endswith(alnum(b)) or alnum(a).startswith(alnum(b)), (name, b, a)
    doc.save(path)
    assert len(docx_service._iter_items(Document(path))) == items_before, name


if __name__ == "__main__":
    for n in sys.argv[1:] or NAMES:
        repair(n)
```

- [ ] **Step 4: Run the repair on one format and look at it**

Run: `cd backend && PYTHONIOENCODING=utf-8 $PY $FID/repair.py dlp`
Expected:
- `table 0 columns [~73.5, ~363, ~130]` (the header: logo, text, logo);
- the other DLP tables measured, with no `NOT MEASURED` line;
- `space after A.` lines;
- `suffix www.tup.edu.ph`.

Then render it with `$PY $FID/compare.py dlp` and view `$FID/dlp-app.png` beside `$FID/src/dlp-pdf-p1.png`. The header should show both logos with the six centered lines between them. If a table prints `NOT MEASURED`, check that table's region in the PDF with `$PY $FID/vlines.py dlp` before going on.

- [ ] **Step 5: Run it on the rest**

Run: `cd backend && PYTHONIOENCODING=utf-8 $PY $FID/repair.py 4as-lesson-plan ilaw-lesson-plan pal3-sdlp snhs-dlp`
Expected: no assertion error. `NOT MEASURED` is acceptable only for a table whose PDF has no rules. The fallback keeps it inside the page.

- [ ] **Step 6: Run the guards and the suite**

Run: `cd backend && $PY test_builtins.py && $PY test_weekly_fields.py && $PY test_render_fidelity.py`
Expected: `builtins OK` including `templates keep their structure OK` and `logos in the document view OK`, then `weekly fields OK` and `render fidelity OK`.

- [ ] **Step 7: Check that exports no longer clip**

Run `$PY $FID/clip.py` (it fills every ILAW field with long text and renders the export through LibreOffice), then view `$FID/clip-p2.png`. Expected: each day cell shows all eight "Step N" sentences, with the row grown to fit.

- [ ] **Step 8: Commit**

```bash
git add backend/builtin/formats/*.docx backend/test_builtins.py
git commit -m "Built-in templates match their original PDFs: fonts, widths, headers, markers, rows that grow"
```
(plus trailer)

---

### Task 8: Side-by-side evidence

**Files:**
- Scratch: `$FID/evidence.py`
- Create: `docs/superpowers/screenshots/2026-09-26/fidelity/*.png`

- [ ] **Step 1: Write `$FID/evidence.py`**

```python
"""Original (PDF, or LibreOffice for the teacher's sample) beside the app's
view at 100%, same scale (96 dpi), for the five built-ins and the sample."""
import os, subprocess, sys
WT = r"C:\tle\rel-Aligned\aligned\.claude\worktrees\builtins-owl-layout"
sys.path.insert(0, os.path.join(WT, "backend"))
os.environ["DATABASE_URL"] = "sqlite://"
import pymupdf
from services import docx_service

OUT = os.path.join(WT, "docs", "superpowers", "screenshots", "2026-09-26", "fidelity")
os.makedirs(OUT, exist_ok=True)
FID = os.path.dirname(os.path.abspath(__file__))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
css = open(os.path.join(WT, "frontend", "css", "style.css"), encoding="utf-8").read()
formats = os.path.join(WT, "backend", "builtin", "formats")
sample = os.path.join(WT, "backend", "uploads", "T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx")

for name in ["4as-lesson-plan", "dlp", "ilaw-lesson-plan", "pal3-sdlp", "snhs-dlp", "sample"]:
    docx = sample if name == "sample" else os.path.join(formats, name + ".docx")
    if name == "sample":
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", FID, docx], check=True, capture_output=True)
        original = os.path.join(FID, os.path.splitext(os.path.basename(docx))[0] + ".pdf")
    else:
        original = os.path.join(formats, name + ".pdf")
    page = pymupdf.open(original)[0]
    page.get_pixmap(dpi=96).save(os.path.join(OUT, f"{name}-original.png"))
    width = int(page.rect.width * 96 / 72) + 40
    html = docx_service.render_reference_html(docx)["html"]
    doc_page = f"<!doctype html><meta charset=utf-8><style>{css}</style><body style='margin:0;padding:20px;background:#E9EBEE'>{html}</body>"
    path = os.path.join(FID, f"{name}-view.html")
    open(path, "w", encoding="utf-8").write(doc_page)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--screenshot={os.path.join(OUT, name + '-app.png')}", f"--window-size={width},{int(page.rect.height * 96 / 72) + 40}",
                    "file:///" + path.replace("\\", "/")], capture_output=True, timeout=60)
    print(name, "done")
```

- [ ] **Step 2: Run it and compare each pair**

Run: `$PY $FID/evidence.py`. Then read each `*-original.png` and `*-app.png` pair and check:
- page width and orientation;
- logos present and placed;
- fonts (sans vs serif, Century Gothic on 4A's);
- column widths;
- shading and borders;
- list markers;
- the DLP header centered between its logos.

Note any remaining difference in the final report instead of hiding it.

- [ ] **Step 3: Commit**: `git add docs/superpowers/screenshots/2026-09-26/fidelity && git commit -m "Screenshots: originals beside the app's document view"` (plus trailer).

---

### Task 9: Deploy to the VPS

- [ ] **Step 1: Back up.** Run `plink -batch -hostkey SHA256:JNYLdEK9qpcpHaKOGRmDiUeWmWUYpt6X4xYX7AxMbSA -pw '<password>' root@38.60.245.60 -m C:/Users/jmj11/.claude/jobs/d7419724/tmp/vps/backup.sh`. Expected: the new `.tgz` and `.sql` listed, with a non-zero INSERT count.
- [ ] **Step 2: Package and upload.** Run `git -C <worktree> archive HEAD backend frontend -o C:/Users/jmj11/.claude/jobs/d7419724/tmp/vps/aligned-deploy.tar`. Check the tar has no `backend/.env` (`tar -tf … | grep -c "\.env$"` gives 0). Then `pscp -hostkey … -pw '<password>' <tar> root@38.60.245.60:/tmp/aligned-deploy.tar`.
- [ ] **Step 3: Deploy.** Run `plink … -m C:/Users/jmj11/.claude/jobs/d7419724/tmp/vps/deploy.sh`. Expected: service `active`, health OK, no traceback in the log, 5 built-in formats.
- [ ] **Step 4: Verify in production.** Run `ilawcheck.sh` (ILAW fields 22, weekly 16, errors 0). Open the live site's generator on the TUP DLP format and confirm the header matches the PDF. Re-run `export22.sh` to confirm plan 22 still exports.

---

## Self-review notes

- **Spec coverage:**
  - §1 page and zoom: Tasks 1 and 6.
  - §2 text: Tasks 1 and 3.
  - §3 tables and pictures: Tasks 2 and 4. Hyperlinks take the Hyperlink character style through the `rStyle` chain in `_rpr_chain` (Task 1).
  - §4 structure: `docx_layout.py`; old helpers deleted in Tasks 1 and 2; typed-text style in Tasks 1, 2 and 5; frontend in Task 6; errors are the try/except in every public Layout method; tests in Tasks 1-5 and 7; visual check in Task 8; deploy in Task 9.
  - §5 repair: Task 7 (fonts, columns, headers, markers, link, rows, pictures, guard, export check).
- **Consistency checks:**
  - `Layout.paragraph` returns `(css, marker)`, which the renderer uses as `marker["text"]` and `marker["width"]`.
  - `Layout.table` returns `(css, grid)`.
  - `Layout.cell(tc_el, tbl_el, top, bottom, left, right)` is called with keyword flags.
  - `_render_html_cell`'s new signature is used by `_render_html_table` only.
  - `fitDocPage` and `docFitScale` live in `api.js`, which every page loads before `doc-toolbar.js`.
