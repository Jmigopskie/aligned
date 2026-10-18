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

import requests

# Fields whose wording must come from the curriculum documents verbatim.
_VERBATIM_FIELD = re.compile(r"content standard|performance standard|competenc|objective|melc", re.I)
_REFERENCE_FIELD = re.compile(r"reference", re.I)


def _haystack(field):
    return f"{field.field_key or ''} {field.label or ''}"


def is_verbatim_field(field) -> bool:
    return bool(_VERBATIM_FIELD.search(_haystack(field)))


def is_reference_field(field) -> bool:
    return bool(_REFERENCE_FIELD.search(_haystack(field)))


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
_STATEMENT_START = r"(?<=\s)(?=\d{1,2}\.\s+[a-z])|(?<=\s)(?=demonstrates? an understanding\b)"
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


def snap_text(value: str, guide_text: str) -> str:
    """One field value rewritten to the guide's exact wording, line by line.
    A line is tried whole first and then sentence by sentence, because a prose
    field arrives as one paragraph holding several statements."""
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
        matches = [whole] if whole else [_best_statement(s, statements) for s in _SENTENCE.split(line)]
        for m in matches:
            if m and m not in out:
                out.append(m)
    return "\n".join(out)


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
        if isinstance(value, list):
            out[f.field_key] = [snap_text(v, guide_text) for v in value]
        else:
            out[f.field_key] = snap_text(value, guide_text)
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


def _public_host(url) -> bool:
    """Only public internet addresses are fetched. The URLs come from model
    output, which a teacher's chat message or uploaded file can steer, so this
    is what keeps the check from probing the server's own network."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError:
        return False
    return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)


@lru_cache(maxsize=512)
def link_works(url: str) -> bool:
    """Whether the URL opens (status below 400), following redirects by hand
    so every hop is held to _public_host. HEAD first; GET when a site refuses
    HEAD, as many do."""
    try:
        for method in ("head", "get"):
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                if not _public_host(current):
                    return False
                resp = requests.request(method, current, headers=_UA, timeout=8,
                                        allow_redirects=False, stream=True)
                resp.close()
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                break
            else:
                return False  # redirect loop
            if resp.status_code < 400:
                return True
            if resp.status_code not in (403, 405, 501):
                return False
    except requests.RequestException:
        return False
    return False


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
            out[f.field_key] = ["\n".join(_check_lines(str(v or "").split("\n"), citation)) for v in value]
        else:
            out[f.field_key] = "\n".join(_check_lines(str(value or "").split("\n"), citation))
    return out
