"""Holding the curriculum fields and references to what actually exists.

Asking a model to "follow the course guide" got paraphrase: content standards,
performance standards, learning competencies and objectives came back reworded,
shortened by the length trim, or invented outright, and references came back
with plausible links that led nowhere. A prompt can't guarantee either, so the
reply is checked after the fact:

- snap_to_guide() replaces each line of a curriculum field with the guide's own
  statement it matches, word for word, and drops a line the guide doesn't
  contain rather than passing an invented one on to the plan.
- keep_working_links() keeps only reference lines whose URL really opens.

Kept free of Flask and the provider so it can be checked offline
(see test_grounding.py).
"""
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import certifi
import urllib3

# Fields whose wording must come from the curriculum documents verbatim.
_VERBATIM_FIELD = re.compile(r"content standard|performance standard|competenc|objective|melc", re.I)
_REFERENCE_FIELD = re.compile(r"reference", re.I)


def _haystack(field):
    # kind_text: what a field is taken for when its own label says more (see competency_view).
    return getattr(field, "kind_text", None) or f"{field.field_key or ''} {field.label or ''}"


class _AsCompetency:
    """A "Learning Competencies/ Objectives" field read as the competency
    alone: everything else about the field (its key, type, place) is its own."""

    def __init__(self, field):
        self._field = field
        self.kind_text = "learning competency"
        self.label = re.sub(r"\s*/\s*objectives?\b", "", field.label or "", flags=re.I).strip() or "Learning Competency"

    def __getattr__(self, name):
        return getattr(self._field, name)


def competency_view(fields):
    """The format's fields as they are written. A combined "Learning
    Competencies/ Objectives" field holds only the competency, copied from the
    guide, when the format has its own objectives field: writing objectives in
    both put them twice, the first time under the competency."""
    fields = list(fields)

    def says(f, word):
        return re.search(word, _haystack(f), re.I)

    if not any(says(f, "objective") and not says(f, "competenc") for f in fields):
        return fields
    return [_AsCompetency(f) if says(f, "objective") and says(f, "competenc") else f for f in fields]


def is_verbatim_field(field) -> bool:
    return bool(_VERBATIM_FIELD.search(_haystack(field)))


def is_copy_only_field(field) -> bool:
    """Standards and competencies: only ever copied from a Budget of Work or
    Curriculum Guide, never written. Objectives are unpacked from the
    competency (DO 016), so they are written, then held to the guide."""
    return is_verbatim_field(field) and not re.search(r"objective", _haystack(field), re.I)


def is_reference_field(field) -> bool:
    return bool(_REFERENCE_FIELD.search(_haystack(field)))


# The part that teaches the topic itself (TUP's "Lesson Proper").
_LESSON_PROPER_FIELD = re.compile(r"lesson.proper|discussion", re.I)


def is_lesson_proper_field(field) -> bool:
    return bool(_LESSON_PROPER_FIELD.search(_haystack(field)))


def reference_urls(lines) -> list:
    """The links in a references list, in order, each once."""
    seen = []
    for line in lines:
        for u in _URL.findall(str(line or "")):
            u = u.rstrip(".,;")
            if u not in seen:
                seen.append(u)
    return seen


# Facts about the class session that no guide contains: which school, which day,
# what time, which room or section. A model asked to fill them made them up
# ("Philippine National High School", "October 15, 2026"), so they are only
# filled from the setup the teacher gave and otherwise left for the teacher.
# "Time allotment" is the lesson's length, not its clock time, so it isn't one.
_LOGISTICS_FIELD = re.compile(r"\b(?:school|date|time|room|section)\b(?!\s*(?:allot|frame))", re.I)


def is_logistics_field(field) -> bool:
    return bool(_LOGISTICS_FIELD.search(field.label or ""))


def keep_given_logistics(values: dict, fields, context: dict) -> dict:
    """Logistics fields keep a value only when it is something the teacher
    entered in setup (a section name, say); anything else was invented and is
    blanked for the teacher to fill in."""
    # Word by word, so "Grade 7 - Campos" stands when the grade and the
    # section were each given, even though setup never wrote them together.
    # A sample plan's school and dates are someone else's, never this lesson's.
    given = set(re.findall(r"[a-z0-9]+", " ".join(
        str(v) for k, v in (context or {}).items() if v and k != "sample_plan").lower()))
    out = dict(values)

    def entered(text):
        words = re.findall(r"[a-z0-9]+", str(text or "").lower())
        return bool(words) and set(words) <= given

    for f in fields:
        if f.field_key in out and is_logistics_field(f):
            value = out[f.field_key]
            parts = value if isinstance(value, list) else [value]
            kept = [p if entered(p) else "" for p in parts]
            out[f.field_key] = kept if isinstance(value, list) else kept[0]
    return out


# ---------------------------------------------------------------------------
# The guide's statements
# ---------------------------------------------------------------------------

# The Budget of Work uses ● ○ ■; the MATATAG curriculum guide uses • and §.
_BULLETS = r"[●○■•▪◦§]"
# Headings run straight into the statement after them once PDF text is
# flattened ("Performance Standard The learners convert ..."), so they are
# treated as separators, never as part of a statement. Both the Budget of
# Work's Title Case and the curriculum guide's UPPER CASE table headers.
_HEADINGS = (
    r"\b(?:Performance Standards?|Content Standards?|Learning Competenc(?:y|ies)"
    r"|PERFORMANCE STANDARDS?|CONTENT STANDARDS?|LEARNING COMPETENCIES|CONTENT"
    r"|Suggested (?:Performance Tasks|Activities)|(?:First|Second|Third|Fourth) (?:Term|Quarter)"
    r"|GRADE \d+(?: Quarter [IVX]+)?)\b|The learners…"
)
# Where one statement ends and the next begins inside a run of table text: a
# numbered competency ("10. perform food preservation ...") and a content
# standard ("demonstrate an understanding of ...") both start a new statement.
# A standard's own "The learners" lead-in stays with it, so the copy is word for word.
_STATEMENT_START = (r"(?<=\s)(?=\d{1,2}\.\s+[a-z])"
                    r"|(?<=\s)(?<!The learners )(?=(?:The learners )?demonstrates? an understanding\b)")
# Running page headers that land mid-sentence wherever a statement crosses a page.
_PAGE_NOISE = re.compile(
    r"Page \d+ of \d+|Last updated [A-Z][a-z]+ \d{1,2}, \d{4}"
    r"|Budget of Work Grade [\d /]+\| (?:EPP|TLE): ?[A-Z]+(?: - [A-Z][a-z]+(?: [A-Z][a-z]+)*)?"
    r"|MATATAG Curriculum: EPP/TLE \(Grades 4-10\) [A-Z][a-z]+ \d{4} \d+"
)
_SPLIT = re.compile(f"{_BULLETS}|{_HEADINGS}|{_STATEMENT_START}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_STOP = set("the and for with from that this into their are was can its they them".split())
_MIN_WORDS = 4


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


def tidy_guide(text: str) -> str:
    """Guide text with the PDF extraction noise taken out: one word per line
    flattened back into running text, page headers removed, and a line break
    before every bullet so each statement reads as its own line."""
    text = _PAGE_NOISE.sub(" ", re.sub(r"\s+", " ", text or ""))
    return re.sub(rf"\s*({_BULLETS})\s*", r"\n\1 ", text).strip()


@lru_cache(maxsize=8)
def _statements(guide_text: str):
    """Every statement in the guide, as (exact text, token set). Whole
    bullet-or-heading segments and each sentence inside them both count, so a
    line can match either a full standard or one sentence of a longer one."""
    flat = _PAGE_NOISE.sub(" ", re.sub(r"\s+", " ", guide_text or ""))
    found, seen = [], set()
    for segment in _SPLIT.split(flat):
        segment = segment.strip(" ;,")
        pieces = [segment] + _SENTENCE.split(segment)
        for piece in pieces:
            # The guide's list number ("10. ") is its position, not its wording.
            piece = re.sub(r"^\d{1,2}\.\s+", "", re.sub(r"\s+", " ", piece).strip(" ;,"))
            if len(piece.split()) < _MIN_WORDS or piece in seen:
                continue
            seen.add(piece)
            found.append((piece, _tokens(piece)))
    return tuple(found)


def _best_statement(line: str, statements):
    words = _tokens(line)
    if len(words) < 2:
        return None
    best, best_score = None, 0.0
    for text, cand in statements:
        if not cand:
            continue
        shared = len(words & cand)
        dice = 2 * shared / (len(words) + len(cand))
        # A line that is most of one statement (a model dropping a trailing
        # clause) still finds it, but a short line can't claim a long passage.
        contained = shared / len(words) if len(cand) <= 2.5 * len(words) else 0
        score = max(dice, 0.95 * contained if contained >= 0.9 else 0)
        if score > best_score:
            best, best_score = text, score
    return best if best_score >= 0.6 else None


# The stem DepEd objectives open with. It isn't in any guide, but it isn't
# content either, so it is kept as written.
_OBJECTIVE_STEM = re.compile(r"^at the end of the (lesson|session|week)", re.I)


def snap_text(value: str, guide_text: str, strict: bool = True) -> str:
    """One field value rewritten to the guide's exact wording, line by line.
    A line is tried whole first and then sentence by sentence, because a prose
    field arrives as one paragraph holding several statements. Strict drops a
    line the guide doesn't contain; lenient (objectives) keeps it as written,
    since DO 016 objectives are unpacked from the competency, not copied."""
    statements = _statements(guide_text)
    out = []
    for line in str(value or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if _OBJECTIVE_STEM.match(line):
            out.append(line)
            continue
        whole = _best_statement(line, statements)
        if not strict:
            if line not in out:
                out.append(whole or line)
            continue
        matches = [whole] if whole else [_best_statement(s, statements) for s in _SENTENCE.split(line)]
        for m in matches:
            if m and m not in out:
                out.append(m)
    return "\n".join(out)


def _snap_competency_line(value, guide_text: str) -> str:
    """The first content line (the competency) in the guide's exact wording;
    the objectives after it untouched."""
    lines = str(value or "").split("\n")
    for i, line in enumerate(lines):
        if line.strip() and not _OBJECTIVE_STEM.match(line.strip()):
            snapped = snap_text(line, guide_text)
            if snapped:
                lines[i] = snapped
            break
    return "\n".join(lines)


def snap_to_guide(values: dict, fields, guide_text: str) -> dict:
    """Every curriculum field in `values` replaced with verbatim guide text.
    Without a guide there is nothing to copy from, so values pass through."""
    if not (guide_text or "").strip():
        return values
    out = dict(values)
    for f in fields:
        if f.field_key not in out or not is_verbatim_field(f):
            continue
        value = out[f.field_key]
        # Objectives are unpacked from the competency (DO 016), so they are
        # never snapped: matching them to the guide once replaced a measurable
        # objective with a look-alike activity line from the Budget of Work. In
        # a combined "Competencies / Objectives" field only the first line, the
        # competency itself, is held to the guide's wording.
        if re.search(r"objective", _haystack(f), re.I):
            snap = _snap_competency_line if re.search(r"competenc", _haystack(f), re.I) else (lambda v, g: v)
        else:
            # A standard or competency is the ONE statement for this lesson:
            # extra statements the model copied along with it are dropped.
            snap = lambda v, g: snap_text(v, g).split("\n")[0]
        if isinstance(value, list):
            out[f.field_key] = [snap(v, guide_text) for v in value]
        else:
            out[f.field_key] = snap(value, guide_text)
    return out


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def guide_citation(title, source_url, text="", author="Department of Education") -> str:
    """APA 7 reference for a published guide, or "" when it has no public link
    (an uploaded file), since a reference here must be one that opens."""
    if not source_url:
        return ""
    flat = re.sub(r"\s+", " ", (text or "")[:5000])
    m = (re.search(r"Last updated [A-Z][a-z]+ \d{1,2}, ((?:19|20)\d\d)", flat)
         or re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", f"{source_url} {title}"))
    year = m.group(1) if m else "n.d."
    return f"{author}. ({year}). {title} [PDF]. {source_url}"


_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_UA = {"User-Agent": "Mozilla/5.0 (AlignED reference check)"}
_MAX_REDIRECTS = 5


def _public_ip(url):
    """The public address to connect to for this URL, or None. Only public
    internet addresses are fetched: the URLs come from model output, which a
    teacher's chat message or uploaded file can steer, so this is what keeps
    the check from probing the server's own network. Every address the name
    resolves to must be public, not just the first."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (OSError, ValueError):
        return None
    addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addrs or not all(a.is_global for a in addrs):
        return None
    return str(sorted(addrs, key=lambda a: a.version)[0])  # IPv4 first


def _public_host(url) -> bool:
    return _public_ip(url) is not None


_REDIRECTS = (301, 302, 303, 307, 308)


def _status(method, url, read=0):
    """(status, Location) for one request, made to the very address
    _public_ip approved. Connecting by that IP, with the real host name for
    TLS and the Host header, is what defeats DNS rebinding: letting the HTTP
    library look the name up again could get a different, internal answer.
    With read > 0: (status, Location, Content-Type, up to `read` bytes of body)."""
    ip = _public_ip(url)
    if not ip:
        return None
    parts = urlparse(url)
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    opts = {"timeout": urllib3.Timeout(connect=8, read=8), "retries": False}
    if https:
        pool = urllib3.HTTPSConnectionPool(ip, port, server_hostname=parts.hostname,
                                           assert_hostname=parts.hostname, cert_reqs="CERT_REQUIRED",
                                           ca_certs=certifi.where(), **opts)
    else:
        pool = urllib3.HTTPConnectionPool(ip, port, **opts)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    try:
        resp = pool.urlopen(method, path, headers={**_UA, "Host": host}, redirect=False,
                            preload_content=False, retries=False)
        result = (resp.status, resp.headers.get("location"))
        if read:
            body = resp.read(read, decode_content=True) if resp.status < 300 else b""
            result += (resp.headers.get("content-type") or "", body or b"")
        resp.release_conn()
        return result
    finally:
        pool.close()


_PAGE_BYTES = 600_000
_PAGE_CHARS = 60_000
_DROP_BLOCKS = re.compile(r"<(script|style|noscript|svg|nav|header|footer|form|aside)\b.*?</\1\s*>", re.I | re.S)
_BLOCK_TAG = re.compile(r"<(?:br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\b[^>]*>", re.I)


# Pages read, by URL; like _WORKING, a failure is not remembered.
_PAGES = {}


def page_text(url: str) -> str:
    """The readable text of a public web page ("" when it can't be read):
    fetched like link_works (public addresses only, every redirect re-checked),
    HTML pages only, markup and page chrome stripped."""
    if url in _PAGES:
        return _PAGES[url]
    text = _read_page(url)
    if text and len(_PAGES) < 200:
        _PAGES[url] = text
    return text


def _read_page(url: str) -> str:
    current = url
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            result = _status("GET", current, read=_PAGE_BYTES)
            if result is None:
                return ""
            status, location, ctype, body = result
            if status in _REDIRECTS and location:
                current = urljoin(current, location)
                continue
            break
        else:
            return ""
    except (urllib3.exceptions.HTTPError, OSError, ValueError):
        return ""
    if status >= 300 or "html" not in ctype.lower():
        return ""
    charset = re.search(r"charset=([\w-]+)", ctype, re.I)
    try:
        html = body.decode(charset.group(1) if charset else "utf-8", errors="ignore")
    except LookupError:
        html = body.decode("utf-8", errors="ignore")
    main = re.search(r"<(main|article)\b.*?</\1\s*>", html, re.I | re.S)
    html = _DROP_BLOCKS.sub(" ", main.group(0) if main else html)
    text = re.sub(r"<[^>]+>", " ", _BLOCK_TAG.sub("\n", html))
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)[:_PAGE_CHARS]


# Only links that opened are remembered: a failure may be a passing timeout,
# and caching it would drop a working reference for the life of the worker.
_WORKING = set()
_WORKING_MAX = 2000


def link_works(url: str) -> bool:
    """Whether the URL opens (status below 400), following redirects by hand
    so every hop is held to _public_ip. HEAD first; GET when a site refuses
    HEAD, as many do."""
    if url in _WORKING:
        return True
    ok = False
    try:
        for method in ("HEAD", "GET"):
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                result = _status(method, current)
                if result is None:
                    return False
                status, location = result
                if status in _REDIRECTS and location:
                    current = urljoin(current, location)
                    continue
                break
            else:
                return False  # redirect loop
            if status < 400:
                ok = True
                break
            if status not in (403, 405, 501):
                break
    except (urllib3.exceptions.HTTPError, OSError, ValueError):
        ok = False
    if ok and len(_WORKING) < _WORKING_MAX:
        _WORKING.add(url)
    return ok


# APA 7 for a web source: Author. (Year[, Month Day]). Title. Site. URL
# The author may be a person ("Cruz, J. A.") or an organization; "n.d." when
# undated. Only one URL, at the end, with no full stop after it.
_APA = re.compile(
    r"^[^()]{2,}?\.?\s\((?:(?:19|20)\d{2}[a-z]?(?:,\s[A-Z][a-z]+(?:\s\d{1,2})?)?|n\.d\.)\)\.\s"
    r"[^\s].{2,}?\.\s(?:[^\s].*?\.\s)?https?://\S+$"
)
_APA6_LEFTOVER = re.compile(r"\s*(?:Retrieved from|Available (?:at|from):?)\s+(?=https?://)", re.I)


def to_apa(line: str) -> str:
    """The line as an APA 7 reference, or "" when it isn't one. Fixes only
    the mechanical slips (APA 6's "Retrieved from", a full stop after the URL,
    stray spaces); anything missing an author, year or title is not guessed at."""
    line = _APA6_LEFTOVER.sub(" ", re.sub(r"\s+", " ", line or "").strip())
    line = re.sub(r"(https?://\S+?)[.,;]+$", r"\1", line)
    return line if _APA.match(line) else ""


def _check_lines(lines, citation):
    lines = [to_apa(line) for line in lines]
    urls = {u.rstrip(".,;") for line in lines for u in _URL.findall(line)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = dict(zip(urls, pool.map(link_works, urls)))
    kept = [citation] if citation else []
    for line in lines:
        line = line.strip()
        found = [u.rstrip(".,;") for u in _URL.findall(line)]
        if not found or not all(ok.get(u) for u in found):
            continue
        if citation and any(u in citation for u in found):
            continue  # already leads the list
        kept.append(line)
    return kept


def keep_working_links(values: dict, fields, citation: str = "") -> dict:
    """Reference fields reduced to APA 7 lines whose links open, led by the
    course guide's own citation. A line without a link is dropped: it can't be
    checked, and a reference that can't be followed is what this replaces. So
    is a line that isn't in APA form (no author, year or title)."""
    out = dict(values)
    for f in fields:
        if f.field_key not in out or not is_reference_field(f):
            continue
        value = out[f.field_key]
        if isinstance(value, list):
            # A weekly field cites the guide once, on its first day, rather
            # than repeating the same reference in every day's cell.
            out[f.field_key] = ["\n".join(_check_lines(str(v or "").split("\n"), citation if i == 0 else ""))
                                for i, v in enumerate(value)]
        else:
            out[f.field_key] = "\n".join(_check_lines(str(value or "").split("\n"), citation))
    return out
