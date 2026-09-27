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
_BROWSER_IMAGES = {"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp", "image/svg+xml"}


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


def _hex(value):
    """A CSS colour from a Word one. Converted files write "#1F4E79"; Word "1F4E79"."""
    return "#" + value.strip().lstrip("#")


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
    color = "#000000" if not color or color.lower() == "auto" else _hex(color)
    style = _BORDER_STYLE.get(val, "solid")
    if style == "double":
        size = max(size * 3, 2.25)  # both lines and the gap between them
    return "%s %s %s" % (_pt(max(size, 0.5)), style, color)


# Symbol and Wingdings bullets are stored as private-use code points that only
# mean something in those fonts; this is what they draw, in Unicode.
_BULLET_GLYPHS = {"": "•", "": "▪", "": "➢", "": "❖",
                  "": "✓", "": "■", "": "□"}


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
            css.append("color:" + _hex(color))
        highlight = _HIGHLIGHT.get(_val(_last(chain, "highlight")) or "")
        fill = _val(_last(chain, "shd"), "fill")
        if highlight:
            css.append("background-color:" + highlight)
        elif fill and fill.lower() != "auto":
            css.append("background-color:" + _hex(fill))
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
        if self._holds_only_pictures(p_el):
            css.append("min-height:" + _pt(self._pictures_height(p_el)))
        return ";".join(css), self._marker(chain, hanging)

    def _holds_only_pictures(self, p_el):
        """Whether a paragraph has floating pictures and no text of its own."""
        if p_el is None or "".join(t.text or "" for t in p_el.iter(qn("w:t"))).strip():
            return False
        return p_el.find(f".//{{{_WP}}}anchor") is not None

    def _pictures_height(self, p_el):
        """How far down this paragraph's floating pictures reach, in pt."""
        bottom = 0.0
        for frame in p_el.iter(f"{{{_WP}}}anchor"):
            extent = frame.find(f"{{{_WP}}}extent")
            offset = frame.find(f"{{{_WP}}}positionV/{{{_WP}}}posOffset")
            top = max(_num(offset.text, 0) / _EMU_PER_PT, 0.0) if offset is not None else 0.0
            if extent is not None:
                bottom = max(bottom, top + _num(extent.get("cy"), 0) / _EMU_PER_PT)
        return bottom

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
            text = "".join(_BULLET_GLYPHS.get(ch, "•" if "" <= ch <= "" else ch) for ch in pattern)
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
                    css.append("background-color:" + _hex(fill))
                valign = _VALIGN.get(_val(tc_pr.find(qn("w:vAlign"))) or "")
                if valign:
                    css.append("vertical-align:" + valign)
            return ";".join(css)
        except Exception:
            _log.debug("Cell layout unreadable; drawn plain.", exc_info=True)
            return ""

    # -- pictures ------------------------------------------------------------

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
        in_cell = frame.get("layoutInCell") in ("1", "true") and next(frame.iterancestors(qn("w:tc")), None) is not None
        # An offset from the page or its margins can't be placed inside a cell
        # or paragraph; one from the column or the text itself can. Word lays a
        # picture that keeps to its cell out from the cell whatever it names.
        x = h_offset if in_cell or h_from in ("column", "character") else 0.0
        y = max(v_offset, 0.0)
        if (frame.get("behindDoc") in ("1", "true") or wrap == "wrapNone"
                or self._holds_only_pictures(next(frame.iterancestors(qn("w:p")), None))):
            # A line holding nothing but pictures (a title cell's logos): each
            # at its own offset; paragraph() makes the line as tall as they are,
            # so the text after it flows below them, as Word wraps it.
            return ["position:absolute", "left:" + _pt(x), "top:" + _pt(y)]
        if wrap == "wrapTopAndBottom":
            return ["display:block", "margin-left:" + _pt(x), "margin-top:" + _pt(y)]
        side = "right" if h_align == "right" else "left"
        return ["float:" + side, "margin-left:" + _pt(x), "margin-top:" + _pt(y),
                "margin-right:" + _pt(_num(frame.get("distR"), 0) / _EMU_PER_PT)]
