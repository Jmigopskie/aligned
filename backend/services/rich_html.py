"""Server-side cleaning of a plan's styled field HTML.

The page already cleans what it saves (generator.js sanitizeRichValueHtml),
but the API takes whatever it is sent, and the saved HTML is painted back with
innerHTML for every teacher who opens the plan. So the server rebuilds it from
the same allowlist instead of trusting it: nothing outside the list survives,
and every attribute is written fresh rather than copied.
"""
import html as html_lib
import re
from html.parser import HTMLParser

from services.docx_service import FONT_COLOR_CLASSES, FONT_SIZE_CLASSES, HIGHLIGHT_CLASSES

_MARKS = {"b", "strong", "i", "em", "u", "ul", "ol", "li"}
_BLOCKS = {"div", "p"}
_DROP_WITH_CONTENT = {"script", "style", "template", "iframe", "object", "noscript", "textarea", "title"}
_SPAN_CLASSES = set(FONT_SIZE_CLASSES) | set(FONT_COLOR_CLASSES) | set(HIGHLIGHT_CLASSES)
_IMG_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Elements with no closing tag. They never go on the open-tag stack, or a later
# </span> would close the wrong thing.
_VOID = {"area", "base", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_IMG_ALIGN = ("left", "center", "right")
_IMG_WRAP = ("inline", "left", "right")


def _esc(text):
    return html_lib.escape(text, quote=False)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []      # what each open tag closes with: "</b>", "</span>", "" ...
        self.drop = 0        # inside <script> and friends: text is discarded
        self.in_picture = 0  # inside a picture, only its caption keeps content
        self.in_caption = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return  # pictures are rebuilt from their id, never copied
        if self.drop or tag in _DROP_WITH_CONTENT:
            if tag in _DROP_WITH_CONTENT:
                self.drop += 1
            self.stack.append(("drop" if tag in _DROP_WITH_CONTENT else "", ""))
            return
        if tag == "br":
            if not self.in_picture or self.in_caption:
                self.out.append("<br>")
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self.in_picture and not self.in_caption:
            # Inside a picture: only its caption carries content.
            if tag == "span" and "lp-img-cap" in classes:
                self.in_caption += 1
                self.out.append('<span class="lp-img-cap">')
                self.stack.append(("caption", "</span>"))
            else:
                self.stack.append(("", ""))
            return
        if tag == "span" and "lp-img" in classes and not self.in_picture:
            image_id = a.get("data-img-id") or ""
            if not _IMG_ID_RE.match(image_id):
                self.drop += 1  # a picture we can't vouch for is left out whole
                self.stack.append(("drop", ""))
                return
            try:
                pct = max(10, min(100, int(a.get("data-width-pct") or 50)))
            except ValueError:
                pct = 50
            align = next((c[10:] for c in classes if c.startswith("img-align-") and c[10:] in _IMG_ALIGN), "left")
            wrap = next((c[9:] for c in classes if c.startswith("img-wrap-") and c[9:] in _IMG_WRAP), "inline")
            border = " img-border" if "img-border" in classes else ""
            self.in_picture += 1
            self.out.append(
                f'<span class="lp-img img-align-{align} img-wrap-{wrap}{border}" data-img-id="{image_id}" '
                f'data-width-pct="{pct}" contenteditable="false"><img src="/api/images/{image_id}" alt="">'
            )
            self.stack.append(("picture", "</span>"))
            return
        if tag == "span":
            kept = [c for c in classes if c in _SPAN_CLASSES]
            if kept:
                self.out.append(f'<span class="{" ".join(kept)}">')
                self.stack.append(("", "</span>"))
            else:
                self.stack.append(("", ""))
            return
        if tag in _MARKS:
            self.out.append(f"<{tag}>")
            self.stack.append(("", f"</{tag}>"))
            return
        self.stack.append(("block" if tag in _BLOCKS else "", ""))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.handle_starttag(tag, attrs)
        # Every other void element (img, input...) is dropped: pictures are
        # rebuilt from their id above, never copied.

    def handle_endtag(self, tag):
        if tag == "br" or not self.stack:
            return
        kind, closing = self.stack.pop()
        if kind == "drop":
            self.drop -= 1
            return
        if self.drop:
            return
        self.out.append(closing)
        if kind == "caption":
            self.in_caption -= 1
        elif kind == "picture":
            self.in_picture -= 1
        elif kind == "block":
            self.out.append("<br>")

    def handle_data(self, data):
        if self.drop or (self.in_picture and not self.in_caption):
            return
        self.out.append(_esc(data))

    def result(self):
        # Close anything left open by malformed input, innermost first.
        while self.stack:
            kind, closing = self.stack.pop()
            if kind != "drop" and not self.drop:
                self.out.append(closing)
            elif kind == "drop":
                self.drop -= 1
        return "".join(self.out)


def sanitize_rich_html(value):
    if not isinstance(value, str) or not value:
        return ""
    cleaner = _Cleaner()
    cleaner.feed(value)
    cleaner.close()
    return cleaner.result()


def sanitize_rich_values(values):
    """A plan's {field_key: html} map. A weekly field holds one HTML string per
    day, so a list is cleaned item by item; anything else becomes ""."""
    if not isinstance(values, dict):
        return {}
    clean = {}
    for key, value in values.items():
        if isinstance(value, list):
            clean[key] = [sanitize_rich_html(v) for v in value]
        else:
            clean[key] = sanitize_rich_html(value)
    return clean
