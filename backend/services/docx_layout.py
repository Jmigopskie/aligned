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
