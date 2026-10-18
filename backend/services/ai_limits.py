"""Trimming and completeness checks applied to whatever the model returns.

The prompt in ai_service asks for short, specific, fully-answered fields. This
module is what makes that true rather than hoped for: a model told "at most 5
items of at most N words" will still sometimes write nine items of twice that, and a
model told "answer every field" will still sometimes return an empty string or
"N/A". Both are the caller's problem to catch, because by the time the text
reaches the page it is already being pasted into a teacher's form.

Kept separate from ai_service so it can be checked without a provider key or a
network call (see test_ai_limits.py).
"""
import re

# Matches the bullet and numbering a model prepends despite being asked not to,
# plus the markdown emphasis it sometimes adds anyway.
# Field keys are slugs and never contain brackets, so any trailing "(...)" is
# the field type the model copied from the prompt.
_TYPE_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")
_LEADING_MARKER = re.compile(r"^\s*(?:[-*•·●▪]|\(?\d{1,2}[.)])\s+")
_MARKDOWN_EMPHASIS = re.compile(r"\*{1,3}(.+?)\*{1,3}")
_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s*")
# Just the numbered form of _LEADING_MARKER, used to tell an ordered procedure
# apart from an unordered list before the markers are stripped off.
_NUMBER_MARKER = re.compile(r"^\s*\(?\d{1,2}[.)]\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Answers that are technically a string but say nothing. A field coming back as
# one of these is treated as unanswered, so the caller retries it instead of
# reporting the plan complete.
_PLACEHOLDERS = {
    "n/a", "na", "none", "null", "nil", "-", "--", "tbd", "tba",
    "to be determined", "to be announced", "to be filled", "to be filled in",
    "not applicable", "not available", "no answer", "answer here",
    "insert here", "insert content here", "lorem ipsum", "todo", "to do",
    "placeholder", "pending", "text", "content",
}


def _strip_markdown(text: str) -> str:
    """Drop the markdown a model adds despite being told not to. The document
    editor keeps its own rich text, so asterisks and hashes arriving in a plain
    field would be shown literally to the teacher."""
    text = _MARKDOWN_HEADING.sub("", text)
    return _MARKDOWN_EMPHASIS.sub(r"\1", text)


# Words a cut must never end on: a list or clause that stops here reads as
# broken off ("Bill Gates, Mark Zuckerberg, or.").
_DANGLING = {"a", "an", "the", "and", "or", "but", "nor", "of", "to", "for", "with", "in", "on", "at", "by",
             "from", "as", "how", "why", "what", "which", "that", "who", "they", "it", "is", "are", "e.g.",
             "i.e.", "such", "like", "including", "via", "into", "its", "their", "your", "our"}
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_CLAUSE_END = re.compile(r"[,;:]|\s[-–—]\s")


def _finish(text: str) -> str:
    """A clipped fragment made to end cleanly: no dangling connective, no
    bracket left open, exactly one full stop."""
    if text.count("(") > text.count(")"):
        text = text[: text.rfind("(")]
    words = text.split()
    while len(words) > 1 and words[-1].strip(",;:-–—").lower() in _DANGLING:
        words.pop()
    text = " ".join(words).rstrip(" ,;:-–—")
    return text if re.search(r"[.!?]$", text) else text + "."


def _clip_words(text: str, max_words: int) -> str:
    """Hold text to about max_words without breaking it mid-sentence.

    In order of preference: let it run up to half again as long when that
    finishes the sentence; cut at the last sentence end in that allowance;
    cut at a clause boundary (comma, semicolon, dash) inside the limit; and
    only then cut at the limit itself, trimmed so it doesn't end on "or",
    "and", an open bracket and the like. A model that writes long (Mistral
    did, routinely) used to come out as "...three qualities and how they."
    """
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)
    words = text.split()
    if len(words) <= max_words:
        return text
    allowance = max_words + max_words // 2
    if len(words) <= allowance and re.search(r"[.!?]$", text.strip()):
        return text

    window = " ".join(words[:allowance])
    limit = len(" ".join(words[:max_words]))
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends:
        # The last sentence end inside the limit, or failing that the first
        # one past it (still within the allowance).
        inside = [e for e in ends if e <= limit and e > limit // 3]
        cut = inside[-1] if inside else ends[0]
        if cut > limit // 3:
            return window[:cut].strip()

    head = " ".join(words[:max_words])
    clauses = [m.start() for m in _CLAUSE_END.finditer(head) if m.start() > len(head) // 2]
    for cut in reversed(clauses):
        piece = head[:cut]
        if piece.count("(") == piece.count(")"):
            return _finish(piece)
    return _finish(head)


def _looks_listy(field_type: str, lines: list) -> bool:
    """A field is treated as a list when the format says so, or when the model
    answered with several lines regardless of what the format said."""
    return field_type in ("list", "table") or len(lines) > 1


def is_answered(value) -> bool:
    """Whether a returned value counts as a real answer.

    An empty string, whitespace, or a placeholder like "N/A" is not an answer
    even though it is a non-empty response, which is exactly the case that used
    to let the page announce a finished plan over blank fields.
    """
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(is_answered(item) for item in value)
    text = str(value).strip()
    if not text:
        return False
    # Compared with the markers and punctuation stripped, so "- N/A" and "1. TBD"
    # are caught as readily as a bare "N/A".
    bare = _LEADING_MARKER.sub("", text).strip().strip(".:;,").lower()
    return bare not in _PLACEHOLDERS


def clean_value(value, field_type: str = "text", *, max_items: int, max_item_words: int,
                max_sentences: int, max_prose_words: int) -> str:
    """One field's returned value, trimmed to the ceilings and stripped of
    markdown and stray bullet markers. Returns plain text with one item per line
    for list-like fields, which is the shape the page's own bullet formatting
    expects."""
    if value is None:
        return ""

    if isinstance(value, (list, tuple)):
        lines = [str(item).strip() for item in value]
    else:
        lines = str(value).split("\n")

    lines = [_strip_markdown(line).strip() for line in lines]

    # Whether this was a numbered list has to be read before the markers come
    # off, and only counts when at least two lines carry a number: one stray
    # "1." in front of a single line is not a procedure.
    numbered = sum(1 for line in lines if _NUMBER_MARKER.match(line)) >= 2

    lines = [_LEADING_MARKER.sub("", line).strip() for line in lines]
    lines = [line for line in lines if line]

    if not lines:
        return ""

    if _looks_listy(field_type, lines):
        items = [_clip_words(line, max_item_words) for line in lines[:max_items]]
        # A procedure's numbering carries meaning that order alone does not:
        # step 3 is "third", not merely "the line after the second". So when the
        # model numbered its items they are re-numbered cleanly, rather than
        # stripped to bare lines the page would then bullet. Anything else stays
        # unmarked and the page applies its own bullets.
        if numbered:
            # A lead-in line ("At the end of the lesson, the learners are
            # expected to:") introduces the list; it is not item 1.
            out, n = [], 0
            for item in items:
                if item.rstrip().endswith(":"):
                    out.append(item)
                else:
                    n += 1
                    out.append(f"{n}. {item}")
            return "\n".join(out)
        return "\n".join(items)

    # Prose: cap the sentence count first, then the overall word count, so a
    # single rambling sentence is cut as well as three tidy ones.
    text = " ".join(lines)
    sentences = [part for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if len(sentences) > max_sentences:
        text = " ".join(sentences[:max_sentences])
    return _clip_words(text, max_prose_words)


def weekly_parts(value, names) -> list:
    """A weekly field's answer as one entry per part, in part order, whatever
    shape the model sent: a list, an object keyed by day name, or a single
    string (which becomes the first part rather than being lost)."""
    count = len(names) or 1
    if isinstance(value, dict):
        lowered = {str(k).strip().lower(): v for k, v in value.items()}
        parts = [lowered.get(str(name).strip().lower(), "") for name in names]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    elif value is None:
        parts = []
    else:
        parts = [value]
    parts = ["" if p is None else p for p in parts][:count]
    return parts + [""] * (count - len(parts))


def enforce_limits(values: dict, fields, *, max_items: int, max_item_words: int,
                   max_sentences: int, max_prose_words: int) -> dict:
    """Trim every value the model returned, keyed by field_key.

    Values for keys that aren't part of this format are dropped: a model
    occasionally invents a field, and letting that through would put content in
    the plan with nowhere to show it.
    """
    types_by_key = {f.field_key: (f.field_type or "text") for f in fields}
    parts_by_key = {f.field_key: (getattr(f, "parts_list", None) or []) for f in fields}
    out = {}
    for key, value in (values or {}).items():
        # The prompt lists fields as "- flow (weekly): ...", and the model
        # sometimes echoes "flow (weekly)" back as the key.
        key = _TYPE_SUFFIX.sub("", str(key)).strip()
        if key not in types_by_key:
            continue
        if types_by_key[key] == "weekly":
            out[key] = [
                clean_value(part, "textarea", max_items=max_items, max_item_words=max_item_words,
                            max_sentences=max_sentences, max_prose_words=max_prose_words)
                for part in weekly_parts(value, parts_by_key[key])
            ]
            continue
        out[key] = clean_value(
            value,
            types_by_key[key],
            max_items=max_items,
            max_item_words=max_item_words,
            max_sentences=max_sentences,
            max_prose_words=max_prose_words,
        )
    return out


def missing_keys(values: dict, fields) -> list:
    """The field_keys of `fields` that still have no real answer, in the order
    the fields themselves are in, so the page can name them to the teacher."""
    return [f.field_key for f in fields if not is_answered((values or {}).get(f.field_key))]
