"""Every AI call AlignED makes: scanning a format, writing a lesson plan, and
the owl chat in Guided mode.

Provider: OpenRouter when OPENROUTER_API_KEY is set (the server, which runs
Qwen3.7 Plus), otherwise Google Gemini directly (GEMINI_API_KEY, the local
copy). Both return the same JSON, so nothing else depends on which is used.

Two things keep the calls lean:
- The course guide is trimmed to the parts that match the lesson's topic
  (guide_excerpt), instead of always its first 12,000 characters, which cut
  off every topic further into a long guide.
- The unchanging part of a request (instructions, lesson details and the
  guide excerpt) is always sent first and the changing part last, so the
  provider can reuse the cached prefix across a plan's requests.
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from config import Config
from services import ai_limits, field_roles, grounding

_log = logging.getLogger(__name__)

PROVIDER = "openrouter" if Config.OPENROUTER_API_KEY else "gemini"
MODEL = Config.OPENROUTER_MODEL if PROVIDER == "openrouter" else Config.GEMINI_MODEL

if PROVIDER == "gemini" and not Config.GEMINI_API_KEY:
    _log.warning("Neither OPENROUTER_API_KEY nor GEMINI_API_KEY is set; AI generation and format scanning will fail.")

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_gemini_client = None

# Ceilings on what one field may contain, stated in the prompt and enforced on
# the reply. They are set to give a capable model room for complete,
# classroom-ready content (timings, steps, concrete examples): the old 15-word
# items and 3-sentence fields made a model like Mistral Large get chopped
# mid-sentence. They are a guard against runaway answers now, not a style rule,
# and the trim in ai_limits cuts at a sentence or clause when it has to cut.
_MAX_LIST_ITEMS = 8
_MAX_ITEM_WORDS = 40
_MAX_PROSE_SENTENCES = 6
_MAX_PROSE_WORDS = 140

# The length of one class session. Every day's plan, all parts together, must
# fit inside it (the teacher's rule: content is capped at 45 minutes). The
# Create Lesson Plan flow asks for the discussion length; this is the default.
_SESSION_MINUTES = 45


def _session_minutes(context) -> int:
    """The session cap for this plan: the discussion length Alan asked for,
    or _SESSION_MINUTES when none (or nonsense) was given."""
    try:
        minutes = int((context or {}).get("duration_minutes") or 0)
    except (TypeError, ValueError):
        return _SESSION_MINUTES
    return minutes if 5 <= minutes <= 240 else _SESSION_MINUTES

_SYSTEM_INSTRUCTION = (
    "You are helping a K-12 ICT/TLE teacher in the Philippines write a lesson plan. "
    "Follow DepEd K-12 tone and terminology. Return specific, classroom-ready content a "
    "teacher can use as written.\n\n"
    "Follow DepEd Order No. 016, s. 2026 (Guidelines on Lesson Planning and Learning Design, "
    "the ILAW framework):\n"
    "- Keep it simple: brief notes, no excessive detail. Another teacher must still be able "
    "to run the lesson without extra explanation.\n"
    "- Coherence: the intentions are evident in every section. Each learning objective is "
    "unpacked from the curriculum competency, is taught in the flow, is checked by the "
    "formative assessment, and is extended in ways forward. The resources listed are the "
    "ones the flow actually uses. Nothing appears in one section that the others ignore.\n"
    "- Intentions: learning objectives are the smaller knowledge, skills or tasks from the "
    "competency that learners can show by the end of the session(s), achievable in the time.\n"
    "- Learning experience: the pre-lesson is a brief routine or check-in that activates "
    "prior knowledge (its minutes count toward the session). The flow applies the learning "
    "design principles where they fit: make the objective clear to learners, guide or model "
    "before learners try on their own, check understanding during the lesson, connect to a "
    "past competency, use collaboration, let learners see why it matters, and include "
    "learners of varied abilities. Learning resources include an alternative for home-based "
    "learning in case face-to-face class is interrupted.\n"
    "- Assessing learning: formative checks happen during the session, include a way for "
    "learners to ask for help, and allow an accommodation (e.g. oral answer, visual aid, "
    "pair support).\n"
    "- Ways forward: an extended learning opportunity beyond class time; reflections are the "
    "teacher's own after teaching.\n\n"
    "Grounding rules (follow strictly):\n"
    "- Every field must be grounded in the specific topic, subject, and any course guide "
    "text given below — never generic filler that could apply to any lesson.\n"
    "- Before writing an activity, routine, energizer, or motivation, check the topic and "
    "prior sections already written and tie the activity directly to that content. Do not "
    "default to a generic warm-up (e.g. a plain stretch break or icebreaker) unless the "
    "topic itself is physical — make it about the subject matter.\n"
    "- Never reuse the same stock activity across different lessons or sections; if a "
    "course guide or references are provided, pull concrete details (terms, examples, "
    "page/unit names) from them rather than inventing generic ones.\n\n"
    "Length (concise, per DO 016): say what the teacher and learners do, no explanations of "
    "why, no repetition of other fields:\n"
    "- Most fields: one or two sentences, or three to five short items, one per line.\n"
    "- A flow, procedure or lesson-proper field: one short line per part (its heading, its "
    "minutes, what happens), about 60 to 90 words for a session in total.\n"
    "- Always finish the sentence; never stop mid-thought.\n"
    "- Time: each day is ONE class session lasting the discussion length given in the lesson "
    f"details ({_SESSION_MINUTES} minutes when none is given), a hard cap. "
    "Everything planned for a session (pre-lesson routine and review, motivation, discussion, "
    "practice, assessment) must fit inside that length together, never "
    "more; give the minutes for each part, including the pre-lesson, so it visibly adds up.\n"
    "- Never restate the field's own label, never open with filler such as 'In this "
    "lesson' or 'The teacher will', and never explain your reasoning or comment on "
    "the plan. Write the content only: no preamble, no closing sentence, no "
    "meta-text.\n\n"
    "Answer every field you are asked for with real content. Never return an empty "
    "string, a placeholder such as 'To be determined', or a restatement of the label "
    "(the one exception: integration and contextualization may be 'N/A' when there is "
    "genuinely no meaningful link). If a field is hard to ground in the topic or guide, "
    "still answer it with the most specific content the topic supports.\n\n"
    "Formatting: plain text only. Any field (or day of a weekly field) that holds "
    "several parts or items puts EACH ON ITS OWN LINE, so the app can show it as a "
    "bulleted list instead of one dense paragraph: the pre-lesson's routine and review "
    "steps, each part of the flow, materials and resources, assessment questions or "
    "tasks, extended-learning tasks, reflection questions, values, objectives. ONE thing "
    "per line: never join separate steps, items, materials or routines in one line with "
    "commas, semicolons or 'and' (write 'Prayer', 'Greetings', 'Attendance check' as three "
    "lines, not 'Prayer, greetings, and attendance check'). Commas belong only inside a "
    "real sentence. A line may start with its own short label ('Review:', 'Guided "
    "Practice (10 min):'). Only a "
    "single idea (a standard, a competency, learner context, a generalization) stays one "
    "sentence or short paragraph. Do not number items or add bullet characters yourself "
    "(the app adds bullets), except that a step-by-step procedure may number its steps "
    "('1. ', '2. '). Never use markdown syntax (no **bold**, no ## headings)."
)

_ANCHOR_SYSTEM_INSTRUCTION = (
    "You read a blank lesson-plan format document (DLP, SDLP, ILAP, or a school's own "
    "template) that has been broken into numbered lines in document order, including "
    "table cells. Identify which numbered lines are field LABELS a teacher must fill in "
    "(e.g. 'Learning Objectives:', 'I. Content', 'Materials Needed'). Some fields — like "
    "Objectives or Content — genuinely need room for several lines or bullet points; use "
    "field_type to say so instead of treating everything as a single short answer.\n\n"
    "Each numbered line is already at most one real label per document position (the "
    "caller has removed continuation/explanatory lines) — every position given to you is "
    "a genuine candidate, so err toward including a line rather than skipping it.\n\n"
    "Strict rule: every field's \"index\" must be copied exactly from one of the numbered "
    "lines given to you. Never invent an index that wasn't given, and never invent a label "
    "that isn't genuinely one of those lines — skip headings that aren't fillable, "
    "signature lines like 'Prepared by', and anything that already looks answered."
)

# Guided coaching (the user's design, 2026-11-22): the student chooses a
# direction first and only then sees the complete part, so Guided stays about
# analysing and choosing, not copying. A request that already says exactly
# what is wanted is answered in full straight away.
_OWL_SYSTEM_INSTRUCTION = (
    "You are the AlignED owl, an assistant inside a lesson-plan editor used by K-12 ICT/TLE "
    "teachers in the Philippines. The student writes one part of the lesson plan at a time "
    "and chats with you about it. Answer what they actually ask, about this lesson plan.\n\n"
    "Rules (follow strictly):\n"
    "- The reply is a short lead-in: one or two sentences, or one line and at most 5 short "
    "'- ' points. No greetings, praise, filler or markdown. Content goes in the choices, not the reply.\n"
    "- A GENERAL request for help or ideas for this part (\"help me\", \"give me ideas\", \"what "
    "should I write\"), except for the lesson proper or discussion, which always gets its complete "
    "content (see below): give exactly 2 directions, as choices of type \"direction\", that differ "
    "in approach (e.g. for objectives: 'Introductory: recall and identify' vs 'Performance: apply "
    "and create'; for a motivation: two different activities). Its label names it in at most 6 "
    "words, its text says in one or two sentences what that direction focuses on, its why says in "
    "at most 25 words why it fits this lesson. No \"use\" choice yet: the student chooses first. "
    "Add up to 2 \"ask\" choices.\n"
    "- When the student HAS CHOSEN a direction (it is named below), or the request already says "
    "exactly what is wanted (e.g. 'a game called Bit Hunt with its directions and questions'): "
    "give ONE \"use\" choice holding the complete part, written in that direction, nothing left "
    "out: for learning objectives exactly 3, one per line (no competency, no lead-in); for an "
    "activity, game or motivation its title, materials, complete step-by-step directions and every "
    "question with its answer; for an assessment the complete quiz with its answer key and/or the "
    "task with its rubric rows (cells separated by ' | '); for the lesson proper or discussion the "
    "whole lesson as that part's instructions describe, every concept, definition, term and example "
    "written out (never an outline of what to teach), taken only from the references' content and "
    "the sources the student selected or uploaded. Its label names it in at most 6 words, its why says in one sentence why it fits. "
    "Add 1 or 2 \"ask\" choices.\n"
    "- A \"use\" choice is read and learned from, never inserted: the student writes the part in "
    "their own words. Classroom-ready, DepEd K-12 terminology, grounded in the topic and guide.\n"
    "- Everything fits what is already written: the objectives are taught by the lesson proper "
    "and checked by the assessment; never test what the lesson does not teach. Never repeat "
    "content already written in other parts.\n"
    "- An \"ask\" choice is a follow-up question the student may want to ask next, at most 8 "
    "words; its label and text are that question.\n"
    "- If asked about something unrelated to the lesson plan, say so in one sentence and offer "
    "lesson-related choices.\n\n"
    "Return strict JSON: {\"reply\": \"...\", \"choices\": [{\"type\": \"direction\", \"use\" or "
    "\"ask\", \"label\": \"...\", \"text\": \"...\", \"why\": \"...\" (direction and use only)}]}"
)
_MAX_DIRECTIONS = 2
_MAX_USE_TEXT = 12000  # room for a whole lesson proper

# "Give me the whole content", "complete", "buong lesson": the content itself, now.
_WANTS_FULL = re.compile(r"\b(?:whole|complete|full|entire|everything|all of (?:the|it)|buo|buong|lahat)\b", re.I)
_TEACHING_NOTE = (
    "\nThis part is the lesson proper: the lesson itself as the teacher teaches it. Whatever the student asks "
    "for here (help, ideas, an example, the whole content), answer with ONE \"use\" choice holding the COMPLETE "
    "lesson content, never an outline, an overview, a summary or a guide to what to teach: every concept with its "
    "definition, the key terms, the parts, types, steps or rules, and worked examples, written out in full the "
    "way the teacher will say and show them. Take every fact only from the sources given above: the online "
    "references' pages, the Budget of Work or Curriculum Guide, and any files the student selected or uploaded "
    "(name the source a part comes from). Never invent facts the sources don't give. No \"direction\" choices."
)
_FLOW_NOTE = (
    " This part runs the whole session: give each step under its heading with its minutes, and inside the step "
    "where the topic is taught write that complete lesson content itself, not a description of it."
)
_FULL_RETRY = (
    "\nYour last answer gave directions or an outline instead of the content. Answer again with ONE \"use\" "
    "choice that holds the complete content itself, nothing left out."
)


# ---------------------------------------------------------------------------
# Course guide excerpt
# ---------------------------------------------------------------------------

GUIDE_BUDGET = 12000
_BLOCK_CHARS = 700
_STOPWORDS = set(
    "the and for with from that this into your their about what when where which while were been have has "
    "are was will can not all any how its our out use using grade level section program year college k-12 "
    "lesson plan subject topic introduction".split()
)


def _focus_terms(*values):
    words = re.findall(r"[a-z0-9][a-z0-9+#.-]{2,}", " ".join(str(v or "") for v in values).lower())
    # A stem so "conversion" also finds "convert" and "systems" "system". Six
    # letters, matched only at the start of a word: five let "underwater" hit
    # "understanding".
    return {w[:6] for w in words if w not in _STOPWORDS}


# Where a section's standards start. Competencies sit under these, so a topic
# found in a competency is read together with the standards above it. The
# Budget of Work writes them in Title Case, the curriculum guide in CAPITALS.
_STANDARDS_HEADING = re.compile(
    r"Performance Standards?|Content Standards?|Learning Competenc(?:y|ies)|(?:First|Second|Third|Fourth) "
    r"(?:Term|Quarter)|Quarter (?:\d|[IVX]+)|GRADE \d+", re.I)
_LOOK_BACK = 6000
_LOOK_AHEAD = 2500
_MAX_HITS = 3


_GRADE_HEADING = re.compile(r"\bgrade\s*(\d{1,2})\b", re.I)


def _topic_sections(text: str, terms: set, budget: int, needed: int = None, grade: str = "") -> str:
    """The guide searched for the topic: the passages that mention it most,
    each widened back to the standards heading it sits under and a little past
    it, merged and kept in document order. "" when the topic isn't in the guide.
    `needed`: how many of the topic's words a passage must hold (default: all
    of a short topic, most of a longer one). `grade` ("7"): a passage under
    that grade's heading wins over the same topic in another grade."""
    low = text.lower()
    patterns = {t: re.compile(r"\b" + re.escape(t)) for t in terms}
    # A passage that holds one stray word of the topic isn't the topic: a short
    # topic needs every word, a longer one most of them.
    if needed is None:
        needed = len(terms) if len(terms) <= 2 else -(-len(terms) * 3 // 5)
    hits = []
    for start in range(0, len(text), _BLOCK_CHARS // 2):
        block = low[start:start + _BLOCK_CHARS]
        counts = {t: len(p.findall(block)) for t, p in patterns.items()}
        present = [t for t, n in counts.items() if n]
        if len(present) >= needed:
            # Covering more of the topic's words beats repeating one of them,
            # and a passage inside a standards/competencies table beats the
            # guide's overview pages, which mention every topic in passing.
            score = len(present) ** 2 * 10 + sum(counts.values())
            if _STANDARDS_HEADING.search(text, max(0, start - 1500), start + _BLOCK_CHARS):
                score *= 2
            # Where the topic is first mentioned in this passage: the headings
            # it sits under are the ones before THAT, not before the passage's
            # start, which may lie in the previous section (a Grade 7 table
            # came back for a Grade 8 topic).
            at = start + min(patterns[t].search(block).start() for t in present)
            if grade:
                under = [m.group(1) for m in _GRADE_HEADING.finditer(text, max(0, at - 20000), at)]
                if under:
                    score *= 1.5 if under[-1] == grade else 0.6
            hits.append((score, start, at))
    if not hits:
        return ""
    hits.sort(reverse=True)

    windows = []
    for score, start, at in hits:
        # Further passages only when they are nearly as good a match as the
        # best one, so a passing mention doesn't pull in an unrelated section.
        if len(windows) == _MAX_HITS or score < hits[0][0] / 2:
            break
        if any(a <= at < b for a, b in windows):
            continue
        heads = [m.start() for m in _STANDARDS_HEADING.finditer(text, max(0, at - _LOOK_BACK), at)]
        begin = max(0, at - 1500)
        if heads:
            # Walk back through the run of headings nearest the hit (Term,
            # Performance Standard, Content Standard sit close together), not
            # to the first heading in range, which may be a section earlier.
            # The curriculum guide repeats its headers on every page and puts
            # PERFORMANCE STANDARD at the END of a table, so the walk stops at
            # one of those: it belongs to the previous table, not this one.
            begin = heads[-1]
            for h in reversed(heads[:-1]):
                if begin - h > 600 or text.startswith("PERFORMANCE", h):
                    break
                begin = h
        windows.append((begin, min(len(text), start + _BLOCK_CHARS + _LOOK_AHEAD)))

    out, used = [], 0
    for a, b in sorted(windows):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    parts = []
    for a, b in out:
        piece = text[a:b]
        if used + len(piece) > budget:
            piece = piece[: max(0, budget - used)]
        if piece:
            parts.append(piece)
            used += len(piece)
    return "\n[...]\n".join(parts)


def _guide_inputs(course_guide_text, context: dict):
    """(excerpt for the prompt, full text for the verbatim check).

    course_guide_text is one guide's text, or a list of (title, text) when the
    teacher picked a Budget of Work and a Curriculum Guide. Each document is
    searched for the topic on its own share of the budget and labelled, so one
    long guide can't crowd the other out of the prompt; the verbatim check
    runs against all of them."""
    if isinstance(course_guide_text, (list, tuple)):
        sources = [(t or "", x or "") for t, x in course_guide_text if (x or "").strip()]
    else:
        sources = [("", course_guide_text or "")] if (course_guide_text or "").strip() else []
    if not sources:
        return "", ""
    share = GUIDE_BUDGET // len(sources)
    parts = []
    for title, text in sources:
        excerpt, how = _guide_match(text, context, share)
        parts.append((f"[From: {title}]\n" if title else "") + _MATCH_NOTES[how].format(
            topic=context.get("topic") or "the topic", main=context.get("main_topic") or "its main topic") + excerpt)
    return "\n\n".join(parts), "\n\n".join(text for _, text in sources)


# Said above each document's excerpt, so the lesson is aligned to the right part.
_MATCH_NOTES = {
    "exact": "",
    "main": "[This document doesn't name \"{topic}\" itself; this is the section for its main topic, "
            "{main}. Align the lesson to it.]\n",
    "closest": "[This document doesn't name \"{topic}\"; this is its closest matching section. Align the "
               "lesson to it: teach the topic as this section's competency frames it, at the depth it sets.]\n",
    "none": "[\"{topic}\" wasn't found in this document; these are its opening and the passages nearest "
            "the topic. Align the lesson to whatever here is closest to the topic.]\n",
}


def guide_excerpt(text: str, context: dict, budget: int = GUIDE_BUDGET) -> str:
    """The parts of a course guide that cover this lesson, within budget.

    The guide is searched for the lesson's topic and only the sections that
    teach it are sent (with the standards they sit under), rather than reading
    the document from its first page. When the topic can't be found, the old
    fallback applies: the whole guide if it fits, otherwise its opening plus the
    passages that mention the topic and subject most. (Also used on reference
    pages, so no AI is asked here; see _guide_match.)"""
    return _guide_match(text, context, budget, ask_ai=False)[0]


def _grade_number(context) -> str:
    found = re.search(r"\d{1,2}", str((context or {}).get("grade_level") or ""))
    return found.group(0) if found else ""


def _guide_match(text: str, context: dict, budget: int = GUIDE_BUDGET, ask_ai: bool = True):
    """(excerpt, how) for one document. how: "exact" (the topic's section),
    "main" (the main topic's section), "closest" (the nearest section when the
    document doesn't name the topic: most of its words, else, with ask_ai, the
    competency an AI picked as the closest match), "none" (the old fallback).
    User, 2026-11-24: the plan is aligned to the selected curriculum, and a
    topic it doesn't name goes under its closest match."""
    text = (text or "").strip()
    # PDF extraction of the DepEd Budget of Work files puts every word on its
    # own line, which wastes most of the budget on line breaks and leaves the
    # line-based blocks below meaningless.
    lines = [l for l in text.split("\n") if l.strip()]
    if lines and sum(len(l) for l in lines) / len(lines) < 20:
        text = grounding.tidy_guide(text)
    grade = _grade_number(context)
    topic_terms = _focus_terms(context.get("topic"))
    main_terms = _focus_terms(context.get("main_topic"))
    tries = [(topic_terms, "exact", None), (main_terms, "main", None),
             (topic_terms, "closest", max(1, (len(topic_terms) + 1) // 2))]
    for terms, how, needed in tries:
        if terms:
            found = _topic_sections(text, terms, budget, needed, grade)
            if found:
                return found, how
    picked = _closest_line(text, context) if ask_ai else ""
    if picked:
        found = _topic_sections(text, _focus_terms(picked), budget, None, grade)
        if found:
            return found, "closest"
    return _guide_fallback(text, context, budget), "none"


# The closest competency for a topic a document doesn't name, by document and
# lesson, so the AI is asked once per worker, not on every chat turn.
_CLOSEST = {}
_CANDIDATE_LINES = 160


def _closest_line(text: str, context: dict) -> str:
    """The line of the curriculum document (a competency, content or
    standard) closest in meaning to the lesson's topic, as an AI picks it from
    the document's own lines; "" when none is close or the call fails."""
    topic = str(context.get("topic") or "").strip()
    if not topic:
        return ""
    key = (hash(text), topic.lower(), str(context.get("main_topic") or "").lower(), _grade_number(context))
    if key in _CLOSEST:
        return _CLOSEST[key]
    seen, lines = set(), []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if 20 <= len(line) <= 240 and re.search(r"[a-z]{3}", line) and line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    if len(lines) > _CANDIDATE_LINES:  # spread over the whole document
        step = len(lines) / _CANDIDATE_LINES
        lines = [lines[int(i * step)] for i in range(_CANDIDATE_LINES)]
    if not lines:
        return ""
    about = ", ".join(f"{k.replace('_', ' ')}: {context[k]}" for k in ("main_topic", "subject", "grade_level", "program")
                      if context.get(k))
    task = (f"Lesson topic: {topic}" + (f" ({about})" if about else "") + "\n\nLines of the curriculum document:\n"
            + "\n".join(f"{i}. {l[:200]}" for i, l in enumerate(lines))
            + '\n\nWhich line is the closest match in meaning to the lesson topic (the competency or content it '
              'belongs under)? Return strict JSON {"index": n}, or {"index": null} when none is related.')
    picked = ""
    try:
        index = _call("You match a lesson topic to a Philippine curriculum document. Return strict JSON only.",
                      [task], "Closest competency").get("index")
        if isinstance(index, int) and 0 <= index < len(lines):
            picked = lines[index]
    except Exception as exc:  # noqa: BLE001 - the plan still has the document's fallback excerpt
        _log.warning("Closest competency failed: %s", exc)
        return ""
    if len(_CLOSEST) < 500:
        _CLOSEST[key] = picked
    return picked


def _guide_fallback(text: str, context: dict, budget: int) -> str:
    """The whole guide if it fits, otherwise its opening plus the passages that
    mention the topic and subject most."""
    if len(text) <= budget:
        return text
    focus = " ".join(str(context.get(k) or "") for k in ("topic", "subject", "grade_level", "program"))
    terms = {w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]{2,}", focus.lower()) if w not in _STOPWORDS}
    if not terms:
        return text[:budget]

    blocks, current = [], []
    for line in text.split("\n"):
        current.append(line)
        if sum(len(l) + 1 for l in current) >= _BLOCK_CHARS:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))

    def score(block):
        low = block.lower()
        return sum(low.count(t) * (2 if len(t) > 5 else 1) for t in terms)

    chosen, used = {0}, len(blocks[0])
    # Most relevant passages first, then whatever still fits, in document order.
    by_relevance = sorted((i for i in range(1, len(blocks)) if score(blocks[i])), key=lambda i: score(blocks[i]), reverse=True)
    for i in by_relevance + list(range(1, len(blocks))):
        if i in chosen or used + len(blocks[i]) > budget:
            continue
        chosen.add(i)
        used += len(blocks[i])
    out, previous = [], None
    for i in sorted(chosen):
        if previous is not None and i != previous + 1:
            out.append("[...]")
        out.append(blocks[i])
        previous = i
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Prompt pieces
# ---------------------------------------------------------------------------

def _field_directive(field):
    """Extra per-field constraint appended after a field's own hint/label, based on
    what kind of field it is. Keeps the model from writing verbose prose where the
    field is meant to be short, and from padding lists with over-specific brand or
    model detail where a general category is what's wanted."""
    haystack = field_roles.part_text(field)

    if "pre-lesson" in haystack or "pre lesson" in haystack:
        return (
            " One short line per step, each its own bullet, never several steps in one line: "
            "e.g. 'Prayer (1 min)', 'Greetings (1 min)', 'Attendance check (1 min)', 'Wellness "
            "check (1 min): ...', 'Review (3 min): ...' with the question or task. About 5 "
            "minutes in total, counted toward the session."
        )
    # DO 016 s.2026: learner context is the teacher's own observation and
    # reflections are written after teaching. A model can't observe either, so
    # it drafts something the teacher confirms instead of inventing outcomes.
    if "learner context" in haystack:
        return (
            " The AI cannot observe this class: write one or two sentences of anticipated "
            "context for this grade and topic (likely strengths, interests, possible "
            "barriers), starting with 'Anticipated:' so the teacher confirms or edits it."
        )
    if "reflection" in haystack:
        return (
            " Reflections are written by the teacher after the session: give two or three "
            "short questions to answer then (e.g. which objective needs reteaching, who needs "
            "remediation or enrichment), not invented results."
        )
    if "declaration of ai" in haystack or "ai use" in haystack:
        return (
            " One honest sentence: the plan was drafted with AlignED's AI from the selected "
            "Budget of Work / Curriculum Guide and reviewed and edited by the teacher "
            "(DO 003 s.2026)."
        )
    if "integration" in haystack or "contextuali" in haystack:
        return (
            " One concrete link to another learning area or to the learners' local context "
            "that the flow actually uses; write N/A if there is genuinely none."
        )
    # Only when the format doesn't say how to write it (ILAW asks for the term
    # number alone, which must win over this).
    if not field.ai_hint and re.search(r"\b(?:semester|quarter|term)\b", field.label or "", re.I):
        return (
            " Use the guide's own heading for the section the lesson's competency sits in, "
            "worded as the guide words it (e.g. 'First Term' if the guide says Term, never "
            "'First Quarter' instead)."
        )
    if grounding.is_logistics_field(field):
        return (
            " Fill this only from the lesson details given above. If they don't state it, "
            "return an empty string: never invent a school, date, time, room or section."
        )
    if _is_objective_field(field):
        combined = re.search(r"competenc", field.label or "", re.I)
        lead_in = ("" if _stem_printed(field) else
                   " the line 'At the end of the lesson, the learners are expected to:' (not counted, not "
                   "numbered), then")
        return (
            (" First line: the learning competency copied word for word from the guide. Then"
             if combined else "")
            + lead_in
            + f" exactly {_MIN_OBJECTIVES} learning objectives, one per line with no "
            "numbers or bullet characters (the app bullets them; this overrides any 'numbered' "
            "wording above). Each is unpacked from the competency, achievable in the session, and "
            "starts in lowercase with a measurable action verb from the taxonomy of its domain, at a "
            "level fit for the grade:\n" + taxonomy_text() + "\nNever 'understand', 'know', 'learn' or "
            "'appreciate the importance of'. Use only the domains the lesson really has: an affective "
            "objective when the lesson builds an attitude or value, a psychomotor one ONLY when it has a "
            "real hands-on skill; never force a domain. No domain labels in the text. Order them from "
            "lower to higher level. Each is about today's specific topic and something the lesson proper "
            "can teach and the evaluation can check in this session."
        )
    if grounding.is_copy_only_field(field):
        return (
            " Copy exactly ONE statement from the course guide / budget of work above, WORD FOR "
            "WORD: the single one for this lesson's topic. Only that statement: no "
            "second statement, no heading, code or week number, nothing reworded, shortened or "
            "added. The length limits do not apply to this field. A line not found in the guide is "
            "removed, and only the first statement is kept."
        )
    if grounding.is_verbatim_field(field):
        return (
            " Copy the matching statement(s) from the course guide / budget of work above "
            "WORD FOR WORD: exact wording, no paraphrasing, shortening, merging or added "
            "words, one statement per line. The length limits do not apply to this field. "
            "Lines not found in the guide are removed."
        )
    if grounding.is_reference_field(field):
        return (
            " The sources this plan's content is drawn from: real, publicly accessible pages, "
            "one per line, each in APA 7th format exactly: Author. (Year). Title. Site Name. "
            "https://full-url (use n.d. when undated; no full stop after the URL). Put the "
            "course guide citation given above first. Never invent a URL or a source; every "
            "line is checked and any that isn't APA or whose link doesn't open is removed."
        )
    if "value" in haystack:
        return (
            " Each item must be a single word only (e.g. 'Patience', 'Accuracy') — "
            "no phrases, no explanation of how it's shown."
        )
    if "material" in haystack or "resource" in haystack:
        return (
            " Three to five items, one per line: the materials the flow actually uses, each a "
            "general category (e.g. 'Laptop', 'Whiteboard', 'Printed case study handouts'), no "
            "brand names, software names or model numbers. For learning resources, end with one "
            "line 'Home-based alternative: ...' for learners who cannot attend face to face "
            "(DO 016 s.2026)."
        )
    if any(kw in haystack for kw in ("energizer", "motivation", "warm up", "warm-up", "icebreaker", "routine")):
        return (
            " Must be a specific activity tied to today's actual topic (named above), "
            "not a generic stretch, game, or greeting that could belong to any lesson."
        )
    return ""


def _weekly_directive(field):
    """A weekly field answers once per day. The model is told how many parts
    and which days, and to return them as an array in that order, so each day's
    answer can go into its own cell of the plan."""
    names = getattr(field, "parts_list", None) or []
    if field.field_type != "weekly" or not names:
        return ""
    return (
        f" Return a JSON array of exactly {len(names)} strings, one per day in this "
        f"order: {', '.join(names)}. Each day's entry follows the same rules as a "
        "prose field. Make the days build on each other across the week; repeat an "
        "entry only when it genuinely stays the same."
    )


_RECAP_WORDS = ("review", "recap", "previous lesson", "reviewing previous", "checking of assignment",
                "pre-lesson", "pre lesson")
_ASSIGNMENT_WORDS = ("assignment", "agreement", "extended learning", "additional activities", "enrichment",
                     "remediation")
# Whole-procedure fields only: a single part (4A's "Activity") told the whole
# discussion's length may take all of it.
_TIMING_WORDS = ("procedure", "flow", "lesson proper", "learning experience")


def _grounding_directive(field, context: dict) -> str:
    """Ties the recap to the previous topic, the assignment to the next topic,
    and the procedure's times to the discussion's length, using what Alan asked
    during setup. Without it these fields were written blind."""
    haystack = field_roles.part_text(field)
    weekly = field.field_type == "weekly"
    topic = context.get("topic") or ""
    out = ""

    # Only when setup asked: a request without the key (an older draft) gets
    # no line, rather than "first lesson" by default.
    recap = any(w in haystack for w in _RECAP_WORDS)
    if recap and "previous_topic" not in context:
        pass
    elif recap:
        previous = context.get("previous_topic") or ""
        if previous:
            out += (f" The class's previous lesson was: {previous}. Base this recap on that lesson "
                    f"and connect it to today's topic, {topic}.")
            if weekly:
                out += " Only day 1 recaps the previous lesson; each later day recaps the day before it."
        else:
            out += (" This is the first lesson on this topic; open with what learners already know from "
                    "daily life or earlier grades instead of a recap of a previous lesson.")
    # "Checking of Assignment" looks back at the last lesson, so a recap match wins.
    elif "next_topic" in context and any(w in haystack for w in _ASSIGNMENT_WORDS):
        upcoming = context.get("next_topic") or ""
        if upcoming:
            out += (f" The next lesson is: {upcoming}. Write the assignment so it prepares learners for "
                    f"that next lesson while building on today's topic, {topic}.")
            if weekly:
                out += " Only the last day's assignment prepares for the next lesson; earlier days lead into the following day."
        else:
            out += " Base the assignment on today's topic."

    minutes = context.get("duration_minutes")
    if minutes and any(w in haystack for w in _TIMING_WORDS):
        span = f"{minutes} minutes per session" if weekly else f"{minutes} minutes"
        out += f" The whole discussion lasts {span}. Where the procedure gives times, they must add up to that."
    out += _objectives_for_assessment(field, context)
    if grounding.is_lesson_proper_field(field):
        out += _LESSON_FLOW_DIRECTIVE if grounding.is_lesson_flow(field) else _LESSON_PROPER_DIRECTIVE
    if _ASSESSMENT_FIELD.search(haystack) and "mastery" not in haystack:
        out += _ALIGNED_ASSESSMENT
    return out + _assessment_directive(haystack, context)


# Objective verbs by domain (the user's request, 2026-11-22): domain ->
# (taxonomy, [(level, verbs)]), lower levels first. The objectives directive,
# Alan's Guided chat and the coherence check all read it from here.
TAXONOMIES = {
    "cognitive": ("Revised Bloom's Taxonomy (Anderson & Krathwohl, 2001)", [
        ("Remember", ["define", "list", "identify", "name", "recall"]),
        ("Understand", ["explain", "describe", "classify", "summarize", "compare"]),
        ("Apply", ["use", "demonstrate", "solve", "carry out", "compute"]),
        ("Analyze", ["differentiate", "organize", "examine", "distinguish"]),
        ("Evaluate", ["judge", "critique", "justify", "assess"]),
        ("Create", ["design", "construct", "produce", "plan", "compose"]),
    ]),
    "affective": ("Krathwohl's Affective Taxonomy (1964)", [
        ("Receiving", ["listen attentively to", "show awareness of"]),
        ("Responding", ["participate in", "comply with", "answer", "volunteer"]),
        ("Valuing", ["value", "show commitment to", "defend", "support"]),
        ("Organization", ["integrate", "prioritize", "formulate", "balance"]),
        ("Characterization", ["act consistently with", "display", "practice"]),
    ]),
    "psychomotor": ("Dave's Psychomotor Taxonomy (1970)", [
        ("Imitation", ["copy", "follow", "replicate"]),
        ("Manipulation", ["perform from instructions", "execute", "assemble"]),
        ("Precision", ["perform accurately", "calibrate", "demonstrate with precision"]),
        ("Articulation", ["combine", "adapt", "coordinate"]),
        ("Naturalization", ["perform automatically", "improvise", "master"]),
    ]),
}


def taxonomy_text() -> str:
    """One line per domain: 'Cognitive (Revised Bloom's ...): Remember: define, list · ...'."""
    return "\n".join(
        f"{domain.title()} ({name}): " + " · ".join(f"{level}: {', '.join(verbs)}" for level, verbs in levels)
        for domain, (name, levels) in TAXONOMIES.items()
    )


# Testers wanted the lesson itself, as the teacher puts it on slides, not an
# overview of what the teacher will do.
_LESSON_PROPER_DIRECTIVE = (
    " Write the actual lesson the teacher teaches and shows on slides, not an overview or a list of "
    "steps the teacher follows. For each key concept of today's specific topic: a short heading or "
    "question on its own line (e.g. 'What is a Number System?'), its definition in one sentence, the "
    "key terms each with its meaning, its parts, rules or types as a numbered list ('1. Digits: the "
    "symbols it uses'), and concrete examples ('Binary has 2 digits (0 and 1), so its base is 2.'). "
    "One point per line: '• ' before a bullet point, '1. ' before a numbered one, nothing before a "
    "heading. The content is taken from the online references' content given above (what those pages "
    "say about today's specific topic): their definitions, facts, lists, steps and examples, kept close "
    "to their own wording and put simply for these learners, and only what is about today's specific "
    "topic, never the wider subject. Where no reference covers a point, use the course guide; never "
    "invent a fact, term, definition or example, and leave out what they don't cover. Draw on every "
    "reference whose content covers part of the topic, and end each definition, fact or example taken "
    "from one with its APA 7 in-text citation: the author's surname or organization and the year as "
    "that reference lists them, e.g. (Department of Education, n.d.). It teaches "
    "every learning objective already written for this plan, in order, so learners can do each one by "
    "the end. The length limits do not apply to this field."
)

# A format whose lesson is taught inside the session's flow (ILAW's "Flow", an
# older form's "Procedure"): the steps stay, the teaching step is the lesson.
_LESSON_FLOW_DIRECTIVE = (
    " This part runs the whole session: keep its steps in order, each with its minutes and what the "
    "teacher and learners do. In the step where today's topic is taught, write the actual lesson, "
    "taken from the online references' content given above (definitions, key terms, parts or rules, "
    "examples, on today's specific topic, close to their wording, each fact ending with its APA 7 "
    "in-text citation), one point per line with '• ' or '1. ', never invented. It teaches every "
    "learning objective already written for this plan."
)

# Testers found objectives, content and assessment drifting apart: the check
# is held to what the objectives promise and what the lesson taught.
_ALIGNED_ASSESSMENT = (
    " Every item, task step or rubric criterion checks one of the learning objectives already "
    "written for this plan (cover each objective at least once), using only the terms, facts and "
    "examples the lesson proper taught; never test anything the lesson did not teach."
)


# The evaluation part, not a practice activity that merely "leads to" one.
_ASSESSMENT_FIELD = re.compile(r"assess|evaluat|quiz|\btest\b", re.I)
_QUIZ_ITEMS = re.compile(r"(\d+)-item multiple-choice quiz")
# A 20-item quiz (question, four options, then the key) and a task and rubric.
_MAX_ASSESSMENT_LINES = 200
# A rubric row is five cells on one line; the usual 40-word ceiling cut rows short.
_MAX_ASSESSMENT_LINE_WORDS = 90

# The rubric is a table: rows of cells separated by " | ", which the document,
# the preview and the Word export draw as a real table.
_QUIZ_HOW = ("a multiple-choice quiz: each item a numbered question with four options, a. to d., one per "
             "line, then 'Answer key:' with the correct letter for every item")
_TASK_HOW = ("a performance task: the task, its step-by-step instructions, then 'Rubric:' followed by the "
             "rubric as a table, one row per line with its cells separated by ' | ': first the header row "
             "'Criteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)', then one row for each "
             "of 3 to 5 criteria, its name and then what each level looks like in at most 10 words per cell "
             "(e.g. 'Accuracy | All steps correct | One minor error | Several errors | Mostly incorrect'), "
             "then a line 'Total: N points'")
_NO_LIMITS = " The length limits do not apply to this field."


def _assessment_directive(haystack: str, context: dict) -> str:
    """The assessment the setup chose (step 2), for the field that assesses: a
    multiple-choice quiz of its item count with an answer key, a performance
    task with its rubric table, both, or whichever the objectives call for.
    Nothing when the setup didn't ask."""
    kind = str(context.get("assessment_type") or "")
    if not kind or not _ASSESSMENT_FIELD.search(haystack) or "mastery" in haystack:
        return ""
    quiz = _QUIZ_ITEMS.search(kind)
    n = int(quiz.group(1)) if quiz else 0
    items = f"exactly {n} item{'s' if n > 1 else ''}"
    if "objectives" in kind:
        return (" Choose the assessment from the learning objectives already written for this plan. A "
                "cognitive objective (identify, define, describe, explain, compare, classify) is checked by "
                "multiple-choice items; a psychomotor objective (perform, assemble, construct, operate, "
                "prepare, demonstrate the procedure) is checked by a performance task; an affective objective "
                "(value, cooperate, show willingness, practice) is checked by a criterion row in the task's "
                "rubric when there is a task, otherwise by one line 'Observed: <the behaviour the teacher "
                "watches for>' after the quiz. Use only what the objectives need: just a quiz, just a task, "
                "or both when the objectives include both kinds. Head each part on its own line, 'Multiple-choice "
                f"quiz:' or 'Performance task:'. The quiz has {f'up to {n} items' if n else 'up to 10 items'} "
                f"and is {_QUIZ_HOW}. The task is {_TASK_HOW}.{_NO_LIMITS}")
    task = "performance task" in kind
    if n and task:
        return (f" Assess with both, each headed on its own line: 'Multiple-choice quiz:' with {items}, "
                f"{_QUIZ_HOW}; then 'Performance task:', {_TASK_HOW}. The quiz checks the objectives about "
                f"knowing and understanding, the task the ones about doing or making.{_NO_LIMITS}")
    if n:
        return f" Assess with {items} on the lesson's specific topic in {_QUIZ_HOW}.{_NO_LIMITS}"
    if task:
        return f" Assess with {_TASK_HOW}, on the lesson's specific topic.{_NO_LIMITS}"
    return ""


def _chosen_assessment(context) -> str:
    """What the setup's assessment choice lets the objectives be: "" when the
    objectives choose it themselves or setup didn't ask."""
    kind = str((context or {}).get("assessment_type") or "")
    if not kind or "objectives" in kind:
        return ""
    if "performance task" not in kind:
        return (f"The teacher chose {kind} as the assessment, so every objective is one a quiz can check "
                "(knowing, understanding, applying or analyzing), never a hands-on or attitude objective.")
    if not _QUIZ_ITEMS.search(kind):
        return (f"The teacher chose {kind} as the assessment, so the objectives are ones a performance task "
                "and its rubric can check.")
    return f"The teacher chose {kind} as the assessment; the quiz and the task between them check every objective."


def _objectives_for_assessment(field, context) -> str:
    """Objectives written for the assessment the teacher chose: a quiz can't
    check "assemble a diagram", and the coherence check then flagged it."""
    if not _is_objective_field(field) or not _chosen_assessment(context):
        return ""
    return " " + _chosen_assessment(context)


def _sets_assessment(field, context) -> bool:
    """The field that carries the setup's quiz or performance task."""
    haystack = field_roles.part_text(field)
    return field.field_type != "weekly" and bool(_assessment_directive(haystack, context or {}))


# What the standard DepEd lesson-plan parts are for, used only when a format
# gives a field no hint of its own. Without them a model saw a bare label such
# as "Analysis" and had to guess (one read it as questions for learners,
# another as an analysis of the lesson plan itself). A format's own hint
# always wins; these only fill the silence, the same for every model.
_PART_MEANINGS = [
    (r"\bmotivation\b", "A short, engaging opener (about 5 minutes) on today's topic "
     "that gets learners curious; say what learners do."),
    (r"\banalysis\b", "Two to four questions the teacher asks so learners process the activity they just did "
     "and draw out the concept. Questions only, addressed to learners."),
    (r"\babstraction\b", "With the teacher's questions, learners draw out and state the key concepts the "
     "lesson proper taught (its definitions and rules), briefly; not the whole lesson again."),
    (r"\bapplication\b", "One task where learners use the new concept themselves (individually, in pairs or "
     "groups), with what they produce."),
    (r"\bgeneralization\b", "The key idea of the lesson in one to three sentences, as learners should be able to "
     "state it."),
    (r"\bevaluation\b|\bassessment\b", "A short check of the competency that fits the remaining time: three to "
     "five items or one task, with the answer key or criteria."),
    (r"\bassignment\b|\bagreement\b", "A brief task for home that extends today's lesson."),
    (r"\breview\b", "A quick recap of the previous lesson (a few questions or a short activity) that leads into "
     "today's topic."),
]


_LESSON_MEANING = "The lesson itself, as the teacher teaches it and shows it on slides: definitions, terms and examples."


def _part_meaning(field):
    if field.ai_hint:
        return ""
    if grounding.is_lesson_proper_field(field) and not grounding.is_lesson_flow(field):
        return f" ({_LESSON_MEANING})"  # whatever the format calls it (the 4A's Abstraction)
    label = (field.label or "").lower()
    for pattern, meaning in _PART_MEANINGS:
        if re.search(pattern, label):
            return f" ({meaning})"
    return ""


def _field_described(f):
    """The part's own name, and the format admin's account of what goes in it.
    Both: the name says which part of the plan it is, the context says how this
    school wants it written (sending only one used to drop the name)."""
    if not f.ai_hint:
        return f'"{f.label}"{_part_meaning(f)}'
    return f'"{f.label}". What this format wants here (follow it closely): {f.ai_hint.strip()}'


def _schema_block(fields, context=None):
    context = context or {}
    return "\n".join(
        f"- {f.field_key} ({f.field_type}): {_field_described(f)}"
        f"{_field_directive(f)}{_weekly_directive(f)}"
        f"{_grounding_directive(f, context) if context else ''}"
        for f in fields
    )


def _context_block(context: dict):
    return ", ".join(f"{k}: {v}" for k, v in context.items() if v and k != "sample_plan")


def _learners_directive(context: dict) -> str:
    """The class and the session, as setup gave them, for every part."""
    if str(context.get("level_type") or "").lower() == "college" or context.get("program"):
        who = " ".join(str(context.get(k) or "").strip() for k in ("year", "program")).strip()
        who = f"{who} college students".strip() if who else ""
    else:
        who = f"{str(context.get('grade_level') or '').strip()} learners".strip() if context.get("grade_level") else ""
    out = ""
    if who:
        out += (f"\nThe class: {who}. Pitch every part at their level, as the curriculum sets it for them: "
                "the vocabulary, the depth of the content, the examples (from their daily life in the Philippines), "
                "the reading load, the tasks they can really do, and the difficulty of the questions and quiz.\n")
    minutes = _session_minutes(context)
    if context.get("duration_minutes"):
        out += (f"\nThe session lasts {minutes} minutes: plan only what fits in it, with every timed part "
                f"together adding up to {minutes} minutes, and activities and the assessment sized for that time.\n")
    return out + _MODALITY_NOTES[learning_modality(context)]


# Step 1's learning modality (user, 2026-11-28): Face to Face unless the
# setup said Online, so a plan from before the choice reads as it did.
_MODALITY_NOTES = {
    "Face to Face": (
        "\nLearning modality: Face to Face, in the classroom. Every activity, material and assessment works in a "
        "room with the teacher present: the board and slides, printed or real materials, pairs and groups at their "
        "seats, and the real tools and equipment where the skill needs them.\n"),
    "Online": (
        "\nLearning modality: Online, a live class over a video call. Make every part work online: the routine done "
        "on camera and in chat (attendance in chat or a form, no classroom cleaning or seating), the lesson on a "
        "shared screen, activities in breakout rooms, chat, polls, shared documents, online whiteboards or "
        "simulations, hands-on tasks done with what learners have at home or in a simulator, and the quiz or task "
        "submitted online (e.g. a Google Form or a photo or file upload). Never ask for handouts, the board or "
        "classroom equipment.\n"),
}


def learning_modality(context: dict) -> str:
    return "Online" if str((context or {}).get("learning_modality") or "").strip().lower() == "online" else "Face to Face"


def _lesson_block(context: dict, guide_text: str, citation: str = "") -> str:
    """The part of every generation and chat request that stays the same for a
    lesson, sent first so it can be served from the provider's prompt cache."""
    block = f"Lesson details: {_context_block(context)}\n"
    # Testers found plans drifting to the main topic in general.
    topic = str(context.get("topic") or "").strip()
    main = str(context.get("main_topic") or "").strip()
    if topic:
        within = f" (part of the main topic {main})" if main and main.lower() != topic.lower() else ""
        block += (f"\nThis lesson teaches ONE specific topic: {topic}{within}. Every field (content, examples, "
                  f"activities, questions, assessment, assignment) is about {topic} itself; the main topic and "
                  f"the guide's section are only its frame. Do not drift into the main topic's other subtopics.\n")
    # Every setup answer shapes the plan (user, 2026-11-24): who it is for and
    # how long it runs, not only what it is about.
    block += _learners_directive(context)
    # College only: the syllabus week, typed by hand ("5" reads as "Week 5").
    week = str(context.get("week") or "").strip()
    if week and guide_text:
        week = f"Week {week}" if week.isdigit() else week
        block += (f"\nThis lesson is for {week} of the course syllabus: take its topic, outcomes and content "
                  f"from that week in the syllabus or guide below when it lists weeks, otherwise from the part "
                  f"that covers the topic.\n")
    if guide_text:
        block += f"""
This is the section of the selected curriculum (the course guide, Budget of Work and any other
documents chosen) that covers the lesson's topic, or its closest match where a note says so. The
whole plan is ALIGNED to it: this is the system's core. EVERY field must be
grounded in it or in a source listed under References: the lesson content, examples,
activities, questions, assessment and materials all come from this section's competencies,
suggested activities and performance tasks (or from a listed reference), using its terms.
Do not add facts, topics, activities or examples that neither the guide nor a listed
reference supports. Content standards, performance standards, learning competencies and
objectives are copied from it word for word, never reworded, and all from the SAME section
(term/quarter and week) as the lesson's topic, so they belong together. Every other field
builds on that one competency: the lesson, activities, generalization and evaluation teach
and assess exactly what it names, and the topic, term and dates agree with it:
---
{guide_text}
---
"""
    if citation:
        block += f"\nAPA citation of the curriculum documents above (list them first in References):\n{citation}\n"
    sample = context.get("sample_plan")
    if sample:
        block += f"""
A SAMPLE of a finished lesson plan, uploaded by the writer, most likely on another topic.
Use it only as a model of what goes in each part: the kind of content, how much, how
detailed, and how it is laid out (what its motivation, discussion or evaluation actually
contain). Never copy its topic, facts, examples or wording, and never take standards,
competencies or objectives from it: those come only from the course guide above.
--- SAMPLE ---
{sample}
--- END SAMPLE ---
"""
    return block


# ---------------------------------------------------------------------------
# Calling the model
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 5
_BASE_DELAY_SECONDS = 3


class _RetryableError(Exception):
    pass


def _post_openrouter(system_instruction: str, parts: list) -> str:
    payload = {
        "model": Config.OPENROUTER_MODEL,
        # OpenRouter moves to the next model at once when one is rate-limited or down.
        "models": [Config.OPENROUTER_MODEL] + [m for m in Config.OPENROUTER_FALLBACK_MODELS if m != Config.OPENROUTER_MODEL],
        "messages": [{"role": "system", "content": system_instruction}]
                    + [{"role": "user", "content": p} for p in parts if p],
        "response_format": {"type": "json_object"},
    }
    if not Config.OPENROUTER_REASONING:
        # Lesson content and chat replies don't need a thinking pass: it only
        # adds seconds and output tokens.
        payload["reasoning"] = {"enabled": False}
    if system_instruction == _COHERENCE_SYSTEM:
        payload["temperature"] = 0  # the same plan gets the same verdict each time it is checked
    response = requests.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {Config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code >= 500 or response.status_code == 429:
        raise _RetryableError(f"OpenRouter error {response.status_code}: {response.text[:300]}")
    if not response.ok:
        raise RuntimeError(f"OpenRouter request failed ({response.status_code}): {response.text[:300]}")
    data = response.json()
    if isinstance(data.get("error"), dict):
        raise _RetryableError(f"OpenRouter provider error: {str(data['error'].get('message', ''))[:300]}")
    usage = data.get("usage") or {}
    used = data.get("model") or Config.OPENROUTER_MODEL
    _log.info("%s%s: tokens in=%s (cached %s) out=%s cost=$%.5f",
              used, " (fallback)" if not used.startswith(Config.OPENROUTER_MODEL) else "",
              usage.get("prompt_tokens"), (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
              usage.get("completion_tokens"), float(usage.get("cost") or 0))
    return data["choices"][0]["message"]["content"]


def _post_gemini(system_instruction: str, parts: list) -> str:
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
    response = _gemini_client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents="\n".join(p for p in parts if p),
        config=types.GenerateContentConfig(system_instruction=system_instruction,
                                           response_mime_type="application/json"),
    )
    usage = getattr(response, "usage_metadata", None)
    if usage:
        _log.info("tokens in=%s out=%s", usage.prompt_token_count, usage.candidates_token_count)
    return response.text


def _is_retryable(exc) -> bool:
    if isinstance(exc, (_RetryableError, requests.ConnectionError, requests.Timeout)):
        return True
    if PROVIDER == "gemini":
        from google.genai import errors as genai_errors
        return isinstance(exc, genai_errors.ServerError)
    return False


def _call_raw(system_instruction: str, parts: list, label: str, on_attempt=None) -> str:
    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            post = _post_openrouter if PROVIDER == "openrouter" else _post_gemini
            text = post(system_instruction, parts)
            _log.info("[%s] answered in %.1fs", label, time.monotonic() - started)
            return text
        except Exception as exc:  # noqa: BLE001 - sorted into retryable or not below
            if not _is_retryable(exc):
                raise
            last_error = exc
            _log.warning("[%s] attempt %d/%d failed: %s", label, attempt, _MAX_ATTEMPTS, exc)
            if on_attempt:
                on_attempt(attempt, _MAX_ATTEMPTS, "retrying")
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    raise last_error


def _parse_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        # Some models wrap JSON in a code fence despite the JSON mode.
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _call(system_instruction: str, parts: list, label: str):
    return _parse_json(_call_raw(system_instruction, parts, label))


# ---------------------------------------------------------------------------
# Format scanning
# ---------------------------------------------------------------------------

def suggest_field_anchors(numbered_lines: list) -> list:
    """numbered_lines: [{"index": int, "text": str}, ...] — every label-like line
    docx_service.candidate_label_lines() found in the real reference document, in
    document order. Returns a list of field proposals, each anchored to one of the
    given indices — the caller must still validate every returned index against
    the original list before trusting it, since a model can misbehave."""
    if not numbered_lines:
        return []

    lines_block = "\n".join(f'{l["index"]}: {l["text"]}' for l in numbered_lines)
    prompt = f"""
Here are the label-like lines found in a blank lesson-plan format, one per line as
"INDEX: TEXT":
---
{lines_block}
---

Return strict JSON: {{"fields": [...]}} where each item is:
{{
  "index": <copied exactly from one of the lines above>,
  "label": "human-readable field name, e.g. 'Learning Objectives'",
  "field_type": "text" | "textarea" | "list" | "table",
  "is_required": true or false
}}
"""
    data = _call(_ANCHOR_SYSTEM_INSTRUCTION, [prompt], "Format scan")
    fields = data.get("fields") if isinstance(data, dict) else None
    return fields or []


# ---------------------------------------------------------------------------
# Writing a lesson plan (Building Proficiency)
# ---------------------------------------------------------------------------

def _is_exact(field):
    return grounding.is_verbatim_field(field) or grounding.is_reference_field(field)


def _trim(values, fields, guide_text="", citation="", context=None):
    """Every value the model returns goes through here before it leaves this
    module, so the length ceilings hold regardless of which call produced it.

    Curriculum statements and APA references are exempt from the word ceilings
    (a DepEd competency is often longer than 15 words, and clipping it is
    exactly the rewording that must not happen); instead they are snapped to
    the guide's own wording and held to links that open."""
    plain = [f for f in fields if not _is_exact(f)]
    exact = [f for f in fields if _is_exact(f)]
    # The setup's quiz or task (up to a 20-item quiz) and the lesson proper
    # (the lesson as taught) are as long as they need to be, and keep their
    # own headings, numbering and option letters.
    assess = [f for f in plain if _sets_assessment(f, context)
              or (f.field_type != "weekly" and grounding.is_lesson_proper_field(f))]
    out = ai_limits.enforce_limits(
        values, [f for f in plain if f not in assess],
        max_items=_MAX_LIST_ITEMS,
        max_item_words=_MAX_ITEM_WORDS,
        max_sentences=_MAX_PROSE_SENTENCES,
        max_prose_words=_MAX_PROSE_WORDS,
    )
    if assess:
        out.update(ai_limits.enforce_limits(
            values, assess, max_items=_MAX_ASSESSMENT_LINES, max_item_words=_MAX_ASSESSMENT_LINE_WORDS,
            max_sentences=_MAX_ASSESSMENT_LINES, max_prose_words=_MAX_ASSESSMENT_LINES * _MAX_ITEM_WORDS,
            keep_markers=True,
        ))
    if exact:
        kept = ai_limits.enforce_limits(
            values, exact, max_items=10, max_item_words=120, max_sentences=12, max_prose_words=400,
        )
        kept = grounding.snap_to_guide(kept, exact, guide_text)
        out.update(grounding.keep_working_links(kept, exact, citation))
    return _unnumber_objectives(grounding.keep_given_logistics(out, fields, context), fields)


_LIST_NUMBER = re.compile(r"^\s*\(?\d{1,2}[.)]\s+")


def _unnumber_objectives(values: dict, fields) -> dict:
    """Objectives are a bulleted list under an unnumbered lead-in ('At the end
    of the lesson, the learners are expected to:'), so any numbering the model
    added anyway (ILAW's own field hint says 'numbered') comes off here and the
    page bullets the lines. A numbered list would also keep the page from
    bulleting them, since it treats numbers as an ordered procedure. A lesson
    has three objectives (the DepEd standard testers asked for): any beyond
    the third are dropped."""
    out = dict(values)
    for f in fields:
        if f.field_key not in out or not _is_objective_field(f):
            continue
        # A combined "Competencies/Objectives" field leads with the competency.
        combined = bool(re.search(r"competenc", f.label or "", re.I))
        printed = _stem_printed(f)

        def clean(text):
            kept, objectives = [], 0
            for line in str(text or "").split("\n"):
                line = _LIST_NUMBER.sub("", line)
                if printed and grounding._OBJECTIVE_STEM.match(line.strip()):
                    continue  # the format prints its own lead-in
                is_objective = (line.strip() and not grounding._OBJECTIVE_STEM.match(line.strip())
                                and not (combined and not any(k.strip() for k in kept)))
                if is_objective:
                    objectives += 1
                    if objectives > _MAX_OBJECTIVES:
                        continue
                kept.append(line)
            return "\n".join(kept)

        value = out[f.field_key]
        out[f.field_key] = [clean(v) for v in value] if isinstance(value, list) else clean(value)
    return out


def _must_answer(fields):
    """The fields a reply is held to: logistics a teacher didn't give are left
    blank on purpose, so they are neither re-asked nor reported missing."""
    return [f for f in fields if not grounding.is_logistics_field(f)
            and not re.search(r"integration|contextuali", field_roles.part_text(f), re.I)]


# A learning objective field must carry at least this many objectives
# (the teacher's rule, matching DO 016's knowledge / skill / attitude split).
_MIN_OBJECTIVES = 3
_MAX_OBJECTIVES = 3  # exactly three, the DepEd standard
_OBJECTIVE_STEM = re.compile(r"(?i)^\s*at the end of the")


def _is_objective_field(field):
    return bool(re.search(r"objective", grounding._haystack(field), re.I))


def _stem_printed(field):
    """The format prints the objectives' lead-in ('At the end of the lesson...')
    itself, as the TUP SDLP does (its field hint says so): writing it again
    would show it twice."""
    return bool(re.search(r"at the end of the lesson", field.ai_hint or "", re.I))


def _cell_complete(field, value):
    """One cell (or a whole non-weekly field) really answered."""
    if not ai_limits.is_answered(value):
        return False
    if _is_objective_field(field):
        lines = [l for l in str(value).split("\n") if l.strip() and not _OBJECTIVE_STEM.match(l)]
        # A combined "Competencies / Objectives" field also holds the competency line.
        need = _MIN_OBJECTIVES + (1 if re.search(r"competenc", field.label or "", re.I) else 0)
        return len(lines) >= need
    return True


def _field_complete(field, value):
    """Whether a field came back usable: answered, every day of a weekly field
    filled (an answer for Monday alone used to count as done), and objective
    fields holding at least _MIN_OBJECTIVES objectives."""
    if field.field_type == "weekly":
        names = getattr(field, "parts_list", None) or []
        parts = value if isinstance(value, list) else [value]
        if names and len(parts) < len(names):
            return False
        return all(_cell_complete(field, p) for p in parts)
    return _cell_complete(field, value)


def _incomplete(values: dict, fields) -> list:
    """The field_keys of `fields` that still need work, in field order."""
    return [f.field_key for f in _must_answer(fields) if not _field_complete(f, (values or {}).get(f.field_key))]


def _fill_gaps(lesson: str, fields, all_values: dict, label: str, guide_text="", citation="",
               context=None) -> dict:
    """One more attempt at the fields that came back blank, as a placeholder,
    with days missing, or with too few objectives.

    A model asked for several fields at once will occasionally skip one, leave a
    day empty or answer it with "N/A". Re-asking for just those, naming what is
    wrong, recovers most of them. The callers run this after every batch (so a
    gap is fixed before the next batch builds on it) and once more at the end.
    """
    gaps = _incomplete(all_values, fields)
    if not gaps:
        return {}

    gap_fields = [f for f in fields if f.field_key in set(gaps)]
    task = f"""
These fields of the lesson plan came back incomplete: empty, a placeholder, a
weekly field with a day missing, or an objectives field with fewer than
{_MIN_OBJECTIVES} objectives. Answer each one again, in full, with real, specific
content grounded in the lesson details above and consistent with the fields
already written. Give every day of a weekly field. Return strict JSON with
field_key as keys and nothing else:
{_schema_block(gap_fields, context)}
"""
    try:
        recovered = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], f"{label} (filling gaps)"), gap_fields,
                          guide_text, citation, context)
    except Exception:
        # The gap pass is best-effort: a failure here must not lose the fields
        # that were generated successfully.
        _log.warning("[%s] gap-fill pass failed; reporting the blanks instead", label, exc_info=True)
        return {}

    # Only an improvement is taken: a second reply that is still empty must not
    # overwrite anything, nor make the field look answered.
    by_key = {f.field_key: f for f in gap_fields}
    return {k: v for k, v in recovered.items()
            if k in by_key and (_field_complete(by_key[k], v) or not ai_limits.is_answered(all_values.get(k)))
            and ai_limits.is_answered(v)}


# How many times a batch's incomplete fields are asked for again before the
# next batch starts.
_BATCH_RETRIES = 2

# The parts of one class session whose minutes must add up to at most
# _SESSION_MINUTES, matched by label: the pre-lesson, the flow/procedure, and
# the formative assessment when it is timed on its own.
_TIMED_PARTS = re.compile(r"pre-?lesson|\bflow\b|procedure|lesson proper|formative", re.I)
_PRE_LESSON = re.compile(r"pre-?lesson", re.I)
_MINUTES = re.compile(r"(\d{1,2})\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?min(?:ute)?s?\b", re.I)


def _timing_problems(values: dict, fields, cap: int = _SESSION_MINUTES) -> list:
    """(day index, total minutes, pre-lesson timed?) for every session that runs
    past _SESSION_MINUTES or whose pre-lesson gives no minutes (so its time is
    unaccounted for). The model was told the cap and still timed the flow
    alone to 45 with the routine on top, so the plan is checked, not trusted."""
    timed = [f for f in fields if _TIMED_PARTS.search(field_roles.part_text(f))]
    if not timed or not any(_PRE_LESSON.search(field_roles.part_text(f)) for f in timed):
        return []

    def cells(f):
        v = values.get(f.field_key)
        return v if isinstance(v, list) else [v]

    days = max(len(cells(f)) for f in timed)
    problems = []
    for d in range(days):
        total, pre_timed = 0, False
        for f in timed:
            parts = cells(f)
            text = str(parts[d] if d < len(parts) else "") or ""
            mins = sum(int(m) for m in _MINUTES.findall(text))
            total += mins
            if _PRE_LESSON.search(field_roles.part_text(f)) and mins:
                pre_timed = True
        if total > cap or not pre_timed:
            problems.append((d, total, pre_timed))
    return problems


def _fix_timing(lesson, fields, values, label, guide_text, citation, context):
    """Re-time the sessions that break the cap: the pre-lesson and the flow are
    asked for again with the exact totals, up to _BATCH_RETRIES times, and a
    reply is kept only when it actually brings every day within the cap."""
    cap = _session_minutes(context)
    for attempt in range(_BATCH_RETRIES):
        problems = _timing_problems(values, fields, cap)
        if not problems:
            return values
        targets = [f for f in fields if _TIMED_PARTS.search(field_roles.part_text(f))
                   and not re.search(r"formative", f.label or "", re.I)]
        if not targets:
            return values
        detail = "; ".join(
            f"day {d + 1} adds up to {total} minutes{'' if pre else ' and its pre-lesson has no minutes'}"
            for d, total, pre in problems
        )
        task = f"""
Already written fields (keep them consistent):
{json.dumps(values)}

The session timing is wrong: {detail}. Every session must total AT MOST
{cap} minutes INCLUDING the pre-lesson (about 5 minutes) and any
timed assessment. Rewrite these fields for every day so each part shows its
minutes and each day adds up to {cap} minutes or less; keep the
same activities, shortened if needed, one part per line. Return strict JSON with
field_key as keys:
{_schema_block(targets, context)}
"""
        try:
            fixed = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], f"{label} (timing {attempt + 1})"),
                          targets, guide_text, citation, context)
        except Exception:
            _log.warning("[%s] timing pass failed; keeping the plan as written", label, exc_info=True)
            return values
        candidate = dict(values)
        candidate.update({k: v for k, v in fixed.items() if ai_limits.is_answered(v)})
        if len(_timing_problems(candidate, fields, cap)) < len(problems) and not _incomplete(candidate, targets):
            values = candidate
    return values


def _complete_batch(lesson, chunk, values, label, guide_text, citation, context):
    """Ask again for whatever in this batch is incomplete, up to _BATCH_RETRIES
    times, so the next batch (which reads these as "already written") builds
    on complete fields. Returns the merged values."""
    values = dict(values)
    for attempt in range(_BATCH_RETRIES):
        if not _incomplete(values, chunk):
            break
        recovered = _fill_gaps(lesson, chunk, values, f"{label} (check {attempt + 1})",
                               guide_text, citation, context)
        if not recovered:
            continue
        values.update(recovered)
    return values


def _has_guide(course_guide_text) -> bool:
    if isinstance(course_guide_text, (list, tuple)):
        return any((x or "").strip() for _, x in course_guide_text)
    return bool((course_guide_text or "").strip())


def _split_uncopyable(fields, course_guide_text):
    """(fields to write, standards/competencies left blank). With no Budget
    of Work or Curriculum Guide there is nothing to copy those from word for
    word, and a model asked anyway makes them up, so they are left blank."""
    if _has_guide(course_guide_text):
        return list(fields), []
    skipped = [f for f in fields if grounding.is_copy_only_field(f)]
    return [f for f in fields if f not in skipped], skipped


def select_fields(fields, include_keys):
    """The fields to generate, in document order.

    include_keys is None for "generate everything", which is what a page that
    predates the checklist sends. An empty list genuinely means generate nothing.
    Order comes from `fields`, not from include_keys, because the chunking below
    relies on document order for coherent output.
    """
    if include_keys is None:
        return list(fields)
    wanted = set(include_keys)
    return [f for f in fields if f.field_key in wanted]


def _plan_references(fields, context: dict):
    """(references found online, their block for the prompt). Found before
    writing, so the lesson proper is taught from what those pages say and the
    references part lists the same pages afterwards."""
    if not any(grounding.is_reference_field(f) or grounding.is_lesson_proper_field(f) for f in fields):
        return [], ""
    found = find_references(context)
    teaches = any(grounding.is_lesson_proper_field(f) for f in fields)
    return found, _references_block(found, reference_material(found, context) if teaches and found else "")


# The parts a regenerate leaves as they are: told to the model so the new ones
# fit them (the final review found they were never sent). Capped per part and
# in all, so a long plan can't flood every call.
_WRITTEN_PART_BUDGET = 3000
_WRITTEN_BUDGET = 16000


def _written_block(written) -> str:
    if not written:
        return ""
    parts, used = {}, 0
    for key, value in written.items():
        text = "\n".join(str(v) for v in value) if isinstance(value, list) else str(value or "")
        text = text.strip()[:_WRITTEN_PART_BUDGET]
        if not text or used + len(text) > _WRITTEN_BUDGET:
            continue
        parts[str(key)[:80]] = text
        used += len(text)
    if not parts:
        return ""
    return ("\nParts of this plan that stay as they are (the parts you write must fit them: the objectives "
            f"are taught and assessed; do not repeat them):\n{json.dumps(parts)}\n")


def generate_full(context: dict, fields, course_guide_text: str = "", include_keys=None,
                  course_guide_citation: str = "", written=None) -> dict:
    targets, _ = _split_uncopyable(select_fields(fields, include_keys), course_guide_text)
    if not targets:
        return {}
    cite = course_guide_citation
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    found, refs_block = _plan_references(targets, context)
    lesson = _lesson_block(context, excerpt, cite) + refs_block + _written_block(written)
    task = f"""
Fill ONLY the following fields and return strict JSON with field_key as keys:
{_schema_block(targets, context)}
"""
    values = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], "Building Proficiency"), targets,
                   course_guide_text, cite, context)
    values = _complete_batch(lesson, targets, values, "Building Proficiency", course_guide_text, cite, context)
    values = _fix_timing(lesson, targets, values, "Building Proficiency", course_guide_text, cite, context)
    return {**values, **_with_web_references(values, targets, context, found, cite)}


_STREAM_CHUNK_SIZE = 4


def _not_references(fields):
    return [f for f in fields if not grounding.is_reference_field(f)]


def _apply_coherence(context, fields, values, written, guide_text, citation, plan_fields=None):
    """The coherence check's fixes for the parts just written, cleaned like
    any written value. The check reads the whole plan (plan_fields, with the
    parts that stay); only the parts just written change. Never a standard or
    competency copied from the guide, the references, or a part not being
    written. {} when it all lines up or the check can't run."""
    by_key = {f.field_key: f for f in fields}
    try:
        result = check_coherence(context, list(plan_fields or fields), {**(written or {}), **values})
    except Exception as exc:  # noqa: BLE001 - the plan stands without the extra pass
        _log.warning("Coherence pass failed: %s", exc)
        return {}
    fixes = {}
    for issue in result.get("issues") or []:
        f = by_key.get(issue["part_key"])
        if not f or _is_exact(f) or getattr(f, "locked", False) or not issue.get("fix", "").strip():
            continue
        if f.field_type == "weekly":
            continue  # a day-by-day part isn't replaced by one block of text
        if _INSTRUCTION.match(issue["fix"]):
            continue  # "Add a performance task ..." pasted over the quiz (server run 2026-11-24)
        cleaned = _trim({f.field_key: issue["fix"]}, [f], guide_text, citation, context).get(f.field_key)
        quiz = _QUIZ_ITEMS.search(str(context.get("assessment_type") or ""))
        if quiz and _sets_assessment(f, context) and "answer key" not in str(cleaned).lower():
            continue  # the teacher's quiz stays a quiz
        if cleaned and ai_limits.is_answered(cleaned):
            fixes[f.field_key] = cleaned
    return fixes


# A coherence "fix" that tells the student what to do rather than being the part itself.
_INSTRUCTION = re.compile(r"\s*['\"]?(?:add|change|replace|include|revise|rewrite|ensure|make|remove|update|modify|"
                          r"insert|create|align|adjust|consider)\b", re.I)


def _chunk_label(chunk):
    return chunk[0].label if len(chunk) == 1 else f"{chunk[0].label} – {chunk[-1].label}"


def generate_full_streaming(context: dict, fields, course_guide_text: str = "", include_keys=None,
                            course_guide_citation: str = "", written=None):
    """Fields have no meaningful grouping anymore (section_group isn't
    collected — see the format builder), so this batches them in fixed-size
    groups by document order instead: enough fields per AI call to stay fast
    and coherent, small enough that the caller (the generator's live
    document view) gets real, separate network responses to reveal
    progressively rather than one big call that arrives all at once."""
    # Only the requested fields are generated, and only they are held to account
    # in the completeness report at the end.
    plan_fields = list(fields)  # the whole format, for the coherence pass
    fields, skipped = _split_uncopyable(select_fields(fields, include_keys), course_guide_text)
    needs_guide = {"needs_guide": [f.field_key for f in skipped], "needs_guide_labels": [f.label for f in skipped]}
    if not fields:
        yield {"type": "complete", "values": {}, "missing": [], "missing_labels": [], **needs_guide}
        return
    # Top to bottom (user, 2026-11-24): one batch after another in document
    # order, each told everything written above it. The lesson proper ends its
    # batch, so the assessment and everything after it are written from it.
    chunks, current = [], []
    for f in fields:
        current.append(f)
        if len(current) == _STREAM_CHUNK_SIZE or grounding.is_lesson_proper_field(f):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    cite = course_guide_citation
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    base = _lesson_block(context, excerpt, cite) + _written_block(written)

    # The reference search (web search + reading the pages, about 10 seconds)
    # runs beside the batches before the lesson proper; the references are
    # in the plan before the lesson proper is written from them.
    pool = ThreadPoolExecutor(max_workers=1)
    refs = pool.submit(_plan_references, fields, context)

    def needs_refs(chunk):
        return any(grounding.is_lesson_proper_field(f) or grounding.is_reference_field(f) for f in chunk)

    def lesson_for(chunk):
        return base + (refs.result()[1] if needs_refs(chunk) else "")

    def write(i, chunk, already):
        lesson = lesson_for(chunk)
        task = f"""
The parts of this plan already written above the ones you write now (build on them, do not repeat them):
{json.dumps(already)}

The parts you write continue those: they work toward exactly the learning objectives written above,
and any part that assesses or practises checks only what the lesson proper above teaches, in its
terms, facts and examples.

Now fill ONLY the following fields. Return strict JSON with field_key as keys:
{_schema_block(chunk, context)}
"""
        label = f"Building Proficiency {i}/{len(chunks)}"
        values = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], label), chunk, course_guide_text, cite, context)
        # Anything blank, a weekly field with a day missing, or objectives
        # short of the minimum is asked for again now, in the same batch. Not
        # the references: the model's own links are dropped unless they check
        # out, and the verified ones fill the part at the end, so asking again
        # only cost time (two extra calls per build, then one more).
        if _incomplete(values, _not_references(chunk)):
            values = _complete_batch(lesson, chunk, values, label, course_guide_text, cite, context)
        return values

    all_values, referenced = {}, {}
    try:
        for i, chunk in enumerate(chunks, start=1):
            yield {"type": "section_start", "section": _chunk_label(chunk), "index": i, "total": len(chunks)}
            if needs_refs(chunk) and not referenced:
                # The verified references go in first; the model's own list
                # for that part is never used once they exist.
                found, _ = refs.result()
                referenced = _with_web_references(all_values, fields, context, found, cite)
                if referenced:
                    all_values.update(referenced)
                    yield {"type": "section_done", "section": "Online references", "index": i,
                           "total": len(chunks), "values": referenced}
            todo = [f for f in chunk if f.field_key not in referenced]
            values = {k: v for k, v in write(i, todo, dict(all_values)).items() if k not in referenced} if todo else {}
            all_values.update(values)
            yield {"type": "section_done", "section": _chunk_label(chunk), "index": i, "total": len(chunks),
                   "values": values}
        found, refs_block = refs.result()
    finally:
        pool.shutdown(wait=False)
    lesson = base + refs_block

    # Anything still blank or answered with a placeholder gets one more,
    # targeted attempt before this reports back. Without it the page announced
    # a finished plan over fields the model had quietly skipped.
    gaps = _incomplete(all_values, _not_references(fields))
    if gaps:
        yield {"type": "filling_gaps", "count": len(gaps)}
        recovered = _fill_gaps(lesson, _not_references(fields), all_values, "Building Proficiency",
                               course_guide_text, cite, context)
        if recovered:
            all_values.update(recovered)
            yield {"type": "section_done", "section": "Filled-in gaps",
                   "index": len(chunks), "total": len(chunks), "values": recovered}

    # The whole session, pre-lesson included, must fit the cap. Only checkable
    # once every timed part is written, so it runs after the batches.
    cap = _session_minutes(context)
    if _timing_problems(all_values, fields, cap):
        yield {"type": "filling_gaps", "count": len(_timing_problems(all_values, fields, cap))}
        retimed = _fix_timing(lesson, fields, all_values, "Building Proficiency", course_guide_text, cite, context)
        changed = {k: v for k, v in retimed.items() if all_values.get(k) != v}
        if changed:
            all_values.update(changed)
            yield {"type": "section_done", "section": "Session timing",
                   "index": len(chunks), "total": len(chunks), "values": changed}

    # Coherent as written (user report 2026-11-23): one review of the whole
    # plan, and its fixes go straight into the parts just written.
    fixed = _apply_coherence(context, fields, all_values, written, course_guide_text, cite, plan_fields)
    if fixed:
        all_values.update(fixed)
        yield {"type": "section_done", "section": "Coherence check",
               "index": len(chunks), "total": len(chunks), "values": fixed}

    # `missing` answers "did everything I was asked to write come back": the
    # requested field keys with no real content even after the retry. It says
    # nothing about fields outside include_keys, so the page must combine this
    # with its own check of any fields the teacher chose to write themselves
    # before it can claim the plan is finished.
    missing = _incomplete(all_values, fields)
    yield {
        "type": "complete",
        "values": all_values,
        "missing": missing,
        "missing_labels": [f.label for f in fields if f.field_key in set(missing)],
        **needs_guide,
    }


# ---------------------------------------------------------------------------
# Online references, found by a web search
# ---------------------------------------------------------------------------
# A model asked for references writes plausible links that lead nowhere, and
# the link check then drops them all, so plans went out with none (tester
# report). These come from a real web search (OpenRouter's web plugin): a
# reference is kept only if its URL is one the search returned, it is in APA
# 7 form, and the link opens.

# Testers saw two references at most, usually beside the course guide: one
# search's ten results thinned out by the checks below. Two searches now run
# side by side, and every page that passes is kept, up to this ceiling (it
# bounds how much reading goes into the lesson proper's prompt).
_WEB_REFERENCES = 10
_WEB_RESULTS = 10
_REFERENCE_SEARCHES = (
    "Find {n} accessible online pages, each on a different website, that explain this lesson's topic "
    "itself (definitions, key terms, explanations, examples).",
    "Find {n} accessible online pages from government (DepEd), university, school or other educational "
    "organizations, each on a different website, that teach this lesson's topic.",
)


def _web_search_post(prompt: str) -> dict:
    """{url: title} of the pages one web search returned. The model is told
    to say nothing: asked to write the references itself, Mistral Large 4
    reasoned for about 12,000 tokens, over 5 minutes a search (timed on the
    server 2026-11-24), while the results alone come back in about 3 seconds.
    The reply is capped so it can't think at length; the APA lines are
    written from the pages themselves (_apa_from_result)."""
    payload = {
        "model": Config.OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": "Search the web for the request. Reply with {} only."},
                     {"role": "user", "content": prompt}],
        "plugins": [{"id": "web", "max_results": _WEB_RESULTS}],
        "max_tokens": 16,
    }
    response = requests.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {Config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    cited = {}
    for a in message.get("annotations") or []:
        if a.get("type") == "url_citation":
            c = a.get("url_citation") or {}
            if c.get("url"):
                cited.setdefault(c["url"].rstrip("/"), str(c.get("title") or "").strip())
    return cited


_TITLE_SITE = re.compile(r"^(.{3,}?)\s+[-–—|•/:]{1,2}\s+([^-–—|•/]{2,40})$")


def _split_site(title: str, host: str = "") -> tuple:
    """("Parts of a Flower", "Gardening Solutions") from a page title like
    "Parts of a Flower – Gardening Solutions" on gardeningsolutions.ifas.ufl.edu;
    (title, "") when the end of the title isn't the site's name ("TLE 7 - Module 5").
    With no host (a site name), any trailing part splits off."""
    found = _TITLE_SITE.match(title or "")
    if not found:
        return title, ""
    site = found.group(2).strip()
    compact = re.sub(r"[^a-z0-9]", "", host.lower())
    if host and not any(len(w) >= 3 and w in compact for w in re.findall(r"[a-z0-9]+", site.lower())):
        return title, ""
    return found.group(1).strip(), site


def _apa_from_result(url: str, title: str) -> str:
    """An APA 7 line for a search result, from what the page says about
    itself once page_text has read it: its author (a person as "Last, F."),
    its date (n.d. when it has none), the title, and the site, left out when
    the site is the author."""
    meta = grounding.page_meta(url)
    host = (urlparse(url).hostname or "").removeprefix("www.")
    title, site = _split_site(re.sub(r"\s+", " ", title or "").strip(), host)
    site = (_split_site(meta.get("site", ""))[1] or meta.get("site") or site or host).strip(" .")
    author = grounding.apa_author(meta.get("author", "")) or site
    title = title.rstrip(" .?!:;") or host
    date = grounding.apa_date(meta.get("date", ""), time.gmtime().tm_year)
    where = "" if site.lower() == author.lower() else f" {site}."
    return grounding.to_apa(f"{author.rstrip('.')}. ({date}). {title}.{where} {url}")


def _search_references(prompt: str) -> dict:
    """{url: title} of one search's results; {} when the search fails."""
    try:
        return _web_search_post(prompt)
    except Exception as exc:  # noqa: BLE001 - the other search may still find some
        _log.warning("Reference search failed: %s", exc)
        return {}


# References found, by topic. A set of fewer than three isn't remembered, so a
# topic that came back thin is searched again next time rather than staying thin.
_FOUND_REFERENCES = {}
_MIN_PAGE_TEXT = 800
_REMEMBER_AT = 3


def find_references(context: dict, count: int = _WEB_REFERENCES) -> list:
    """Up to `count` APA 7 references for the lesson's topic: pages a web
    search returned that come from a reliable kind of site, really open with
    readable text that covers the topic, one per website, government, school
    and university pages first. [] when search is unavailable or finds none."""
    topic = str(context.get("topic") or context.get("main_topic") or "").strip()
    if PROVIDER != "openrouter" or not topic:
        return []
    about = ", ".join(str(context.get(k)) for k in ("subject", "grade_level") if context.get(k))
    key = (topic.lower(), about.lower())
    if key in _FOUND_REFERENCES:
        return _FOUND_REFERENCES[key][:count]
    ask = f"\nLesson topic: {topic}" + (f"\nFor: {about}" if about else "")
    with ThreadPoolExecutor(max_workers=len(_REFERENCE_SEARCHES)) as pool:
        results = list(pool.map(_search_references, [q.format(n=count) + ask for q in _REFERENCE_SEARCHES]))
    cited = {}
    for found in results:
        for u, t in found.items():
            cited.setdefault(u, t)
    candidates = [u for u in cited if not grounding.is_unreliable_site(u)]
    # A link that only answers a status check can still fail in a browser, so
    # each page must actually open, with readable text about this topic.
    # All at once: twenty pages read eight at a time took a minute on slow sites.
    with ThreadPoolExecutor(max_workers=16) as pool:
        texts = list(pool.map(grounding.page_text, candidates))
    terms = grounding.topic_terms(topic)
    ranked = []
    for u, page in zip(candidates, texts):
        line = _apa_from_result(u, cited[u]) if len(page) >= _MIN_PAGE_TEXT else ""
        if line and grounding.covers_topic(page, terms):
            share, mentions = grounding.topic_coverage(page, terms)
            ranked.append((grounding.source_rank(u), -share, -mentions, u, line))
    ranked.sort(key=lambda r: r[:3])
    kept, sites = [], set()
    for *_, u, line in ranked:
        site = grounding.site_of(u)
        if site in sites:
            continue
        sites.add(site)
        kept.append(line)
        if len(kept) == count:
            break
    if len(kept) >= min(_REMEMBER_AT, count) and len(_FOUND_REFERENCES) < 500:
        _FOUND_REFERENCES[key] = kept
    return kept


# What the lesson proper reads from its references: every one of them, each
# page's share of this budget (never under the floor).
_REFERENCE_MATERIAL_BUDGET = 24000
_REFERENCE_PAGE_FLOOR = 2400


def reference_material(lines, context: dict) -> str:
    """What the references' pages say about the lesson's topic: for each
    link, the passages of the page that cover the topic, labelled with its
    reference line. "" when no page could be read."""
    urls = grounding.reference_urls(lines)[:_WEB_REFERENCES + 2]
    if not urls:
        return ""
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        texts = list(pool.map(grounding.page_text, urls))
    by_url = {u: next((str(l).strip() for l in lines if u in str(l)), u) for u in urls}
    readable = [(u, t) for u, t in zip(urls, texts) if t.strip()]
    budget = max(_REFERENCE_PAGE_FLOOR, _REFERENCE_MATERIAL_BUDGET // max(1, len(readable)))
    return "\n\n".join(f"[From: {by_url[u]}]\n{guide_excerpt(t, context, budget)}" for u, t in readable)


def _references_block(lines, material: str) -> str:
    """The references and what their pages say, for the lesson proper."""
    if not lines:
        return ""
    listed = "\n".join(str(l).strip() for l in lines if str(l).strip())
    block = f"\nThe lesson's online references (the lesson proper is taught from these and cites them):\n{listed}\n"
    if material:
        block += f"\nWhat those references' pages say about the topic (the online references' content):\n---\n{material}\n---\n"
    return block


def _with_web_references(values: dict, fields, context: dict, found=None, citation: str = "") -> dict:
    """The reference fields as the course guide's own citation first, then
    the references found and checked online. Links the model wrote itself are
    dropped once checked ones exist: they open, but often onto a home page
    that isn't about the topic. {} when nothing changes."""
    refs = [f for f in fields if grounding.is_reference_field(f)]
    if found is None:
        found = find_references(context) if refs else []
    guide_lines = [l.strip() for l in str(citation or "").split("\n") if l.strip()]
    guide = set(guide_lines)
    changed = {}
    for f in refs if found else []:
        value = values.get(f.field_key)
        first = value[0] if isinstance(value, list) and value else value
        # Not written yet (it is filled before the lesson proper): the guide's own citation.
        lines = [l for l in str(first or "").split("\n") if l.strip() in guide] if first else guide_lines
        merged = "\n".join(lines + [l for l in found if l not in lines])
        # A weekly field cites its references once, on its first day.
        changed[f.field_key] = [merged] + list(value[1:]) if isinstance(value, list) and value else merged
    return changed


# ---------------------------------------------------------------------------
# Guided mode: chatting with the owl
# ---------------------------------------------------------------------------

_MAX_CHOICES = 4

# Guided finished (user, 2026-11-24: "the system should arrange and fix the
# inputted texts and words"): spelling, grammar, capitals and punctuation only.
_PROOFREAD_SYSTEM = (
    "You proofread parts of a lesson plan that a student teacher wrote. Fix ONLY spelling, grammar, "
    "capitalization and punctuation. Never add, remove, reorder or reword content; never change a "
    "name, number, link, reference, code or technical term that is spelled right; keep every line "
    "and its bullet, number or ' | ' separators exactly where it is. Return strict JSON with the same "
    "keys and the corrected text as values."
)
# A correction is kept only when it stays this close to what was written:
# a proofread, not a rewrite.
_PROOFREAD_SIMILARITY = 0.85
_PROOFREAD_BUDGET = 30000
_PROOFREAD_WAIT = 20


def proofread(values: dict) -> dict:
    """{key: corrected text} for the changed ones among {key: text}. A
    correction that changes the line count or more than a proofread would is
    dropped, and so is everything when the call fails: the words stand."""
    from difflib import SequenceMatcher

    texts = {k: v for k, v in values.items() if isinstance(v, str) and re.search(r"[A-Za-z]{3}", v)}
    if not texts or sum(len(v) for v in texts.values()) > _PROOFREAD_BUDGET:
        return {}
    # At most _PROOFREAD_WAIT seconds: a busy provider's retries (up to a
    # minute) would keep the student waiting at "Open the document".
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        data = pool.submit(_call, _PROOFREAD_SYSTEM, [json.dumps(texts)], "Proofread").result(timeout=_PROOFREAD_WAIT)
    except Exception as exc:  # noqa: BLE001 - the plan stands as written (laid out, not proofread)
        _log.warning("Proofread skipped: %s", exc)
        return {}
    finally:
        pool.shutdown(wait=False)
    fixed = {}
    for key, before in texts.items():
        after = data.get(key) if isinstance(data, dict) else None
        if not isinstance(after, str) or after == before:
            continue
        if len(after.splitlines()) != len(before.splitlines()):
            continue
        if SequenceMatcher(None, before, after).ratio() < _PROOFREAD_SIMILARITY:
            continue
        fixed[key] = after
    return fixed


def _written_by_label(prior_values, fields, current):
    """The other parts already written, as {label: value} in the plan's
    order, the lesson proper and references marked as such whatever the
    format calls them, so Alan can tell which part is which (keys alone said
    "abstraction" for a 4A's lesson proper). By key without `fields`."""
    values = {k: v for k, v in (prior_values or {}).items() if v and k != current.field_key}
    if not fields:
        return values
    out = {}
    for f in fields:
        if f.field_key in values:
            tag = (" (the lesson proper)" if grounding.is_lesson_proper_field(f)
                   else " (the references)" if grounding.is_reference_field(f) else "")
            out[f"{f.label}{tag}"] = values.pop(f.field_key)
    return {**out, **values}


def owl_chat(context: dict, field, prior_values: dict, course_guide_text: str,
             history: list, message: str, course_guide_citation: str = "", direction=None, fields=None) -> dict:
    """One turn of the Guided mode chat about `field`. `direction` is the
    {label, text} the student picked from Alan's two directions, if any. Returns
    {"reply": str, "choices": [{"type": "direction"|"use"|"ask", "label", "text", "why" (not "ask")}]}."""
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    lesson = _lesson_block(context, excerpt, course_guide_citation)
    written = _written_by_label(prior_values, fields, field)
    current = (prior_values or {}).get(field.field_key) or ""
    names = getattr(field, "parts_list", None) or []
    weekly_note = ""
    if field.field_type == "weekly" and names:
        # A weekly field is answered one day (one cell) at a time in the editor,
        # so a suggestion is one day's answer, never the whole week at once.
        parts = current if isinstance(current, list) else [current]
        current = "; ".join(f"{n}: {p}" for n, p in zip(names, parts) if str(p or "").strip())
        weekly_note = (f"\nThis field has one answer per day ({', '.join(names)}). "
                       "Every \"use\" choice is the answer for a single day, not the whole week.")
    turns = "\n".join(f"{'Teacher' if t.get('role') == 'teacher' else 'Owl'}: {t.get('text', '')}" for t in history)
    typed = f'What the teacher has typed in it so far: "{current}"' if str(current).strip() else "The field is still empty."
    if grounding.is_lesson_proper_field(field):
        lesson += _lesson_references(prior_values, context, fields)
    locked = bool(getattr(field, "locked", False))
    if locked:
        weekly_note += ("\nThe supervising teacher locked this field: the student must write it in their own words. "
                        "Coach them instead: say what it should contain, ask guiding questions, point to the guide. "
                        "Never write the field's content for them; offer only \"direction\" and \"ask\" choices.")
    # The lesson proper (user, 2026-11-28): asked for help or for "the whole
    # content", Alan used to answer with directions, an outline of what to
    # teach. It is the lesson itself, so it always comes in full, from the
    # sources. Any other part asked for its complete content gets it too.
    teaching = grounding.is_lesson_proper_field(field) and not locked
    full = bool(direction) or teaching or bool(_WANTS_FULL.search(message))
    if teaching:
        weekly_note += _TEACHING_NOTE + (_FLOW_NOTE if grounding.is_lesson_flow(field) else "")
    elif full and not locked:
        weekly_note += ("\nThe student asks for the complete content: give it now as ONE \"use\" choice with "
                        "nothing left out, not directions or an outline.")
    chosen = ""
    if direction:
        picked = f"{direction.get('label', '')}: {direction.get('text', '')}"
        chosen = (f"\nThe student chose this direction: {picked}\n"
                  + ("Coach them toward it: say what the part should contain in that direction and ask guiding "
                     "questions, but do not write it; offer only \"ask\" choices." if locked else
                     "Write the complete part in that direction as one \"use\" choice."))
    task = f"""
The parts of this plan the student has already written, in the plan's order (do not repeat them):
{json.dumps(written)}

Build on them (user, 2026-11-24: Guided plans must be as coherent as Building Proficiency): what you
suggest works toward exactly the learning objectives written there; the lesson proper is taught from
the references listed there and what their pages say; any part that assesses or practises checks only
what the lesson proper written there teaches, in its terms, facts and examples; and it never
contradicts another part. Where a part it depends on is still empty, say so in the reply.

The teacher is writing the field "{field.label}" ({field.field_type}).
{f"What belongs in it: {field.ai_hint}" if field.ai_hint else ""}{_field_directive(field)}{_grounding_directive(field, context)}{weekly_note}{chosen}
{typed}

{f"Conversation so far:{chr(10)}{turns}{chr(10)}" if turns else ""}Teacher: {message}
"""
    # The references search runs beside the reply instead of after it (testers
    # found Alan slow on the references part).
    pool = ThreadPoolExecutor(max_workers=1) if grounding.is_reference_field(field) and not locked else None
    searching = pool.submit(find_references, context) if pool else None
    try:
        data = _call(_OWL_SYSTEM_INSTRUCTION, [lesson, task], "Owl chat")
        answer = _clean_owl_reply(data, _MAX_USE_TEXT)
        if full and not locked and not any(c["type"] == "use" for c in answer["choices"]):
            # Directions again instead of the content: asked once more, plainly.
            data = _call(_OWL_SYSTEM_INSTRUCTION, [lesson, task + _FULL_RETRY], "Owl chat (full content)")
            answer = _clean_owl_reply(data, _MAX_USE_TEXT)
    finally:
        if pool:
            pool.shutdown(wait=False)
    choices = answer["choices"]
    if full:
        # Chosen, or asked for in full: the complete part, not another round of directions.
        choices = [c for c in choices if c["type"] != "direction"]
    elif any(c["type"] == "direction" for c in choices):
        # Directions offered: the student chooses before any finished content.
        choices = [c for c in choices if c["type"] != "use"]
        kept, seen = [], 0
        for c in choices:
            if c["type"] == "direction":
                seen += 1
                if seen > _MAX_DIRECTIONS:
                    continue
            kept.append(c)
        choices = kept
    answer = {**answer, "choices": choices[:_MAX_CHOICES]}
    if locked:
        # Whatever the model sends, nothing ready-made goes into a locked field.
        return {**answer, "choices": [c for c in answer["choices"] if c["type"] != "use"]}
    answer = _ground_choices(answer, field, course_guide_text, course_guide_citation)
    if searching:
        # References Alan offers are real pages from a web search, not the model's guesses.
        try:
            # Two web searches plus reading every page took about 95s live.
            found = searching.result(timeout=150)
        except Exception:  # noqa: BLE001 - the reply still stands without them
            found = []
        if found:
            card = {"type": "use", "label": "Online references", "text": "\n".join(found),
                    "why": "Real pages found for this topic, in APA 7; every link was checked and opens."}
            answer = {**answer, "choices": [card] + [c for c in answer["choices"] if c["type"] != "use"][:_MAX_CHOICES - 1]}
    return answer


# ---------------------------------------------------------------------------
# Coherence check: does the finished plan hang together?
# ---------------------------------------------------------------------------

_COHERENCE_SYSTEM = (
    "You review a Philippine K-12 lesson plan for coherence: whether its parts are connected. Check:\n"
    "- every learning objective is taught in the lesson proper and checked by the assessment;\n"
    "- the assessment tests only what the lesson proper taught;\n"
    "- the assessment fits the objectives' domains (cognitive by test items, psychomotor by a "
    "performance task with a rubric, affective by a rubric criterion or an observation);\n"
    "- each objective's verb fits its domain and taxonomy (below), measurable, never understand/know/learn;\n"
    "- the objectives are unpacked from the learning competency;\n"
    "- the motivation and activities lead into today's topic;\n"
    "- the assignment fits the next lesson's topic, when one is given.\n"
    "Only the learning objectives must be assessed: the motivation, activity, analysis, application and "
    "other practice parts are how learners get there, never something the assessment must also check.\n"
    "Report an issue only when one of these checks clearly fails and you can name the exact objective, "
    "term or item that doesn't match. Never report wording, style, formatting, length, grammar, "
    "optional extras or ideas to make a part better; never report an empty part or the school, date, "
    "time, section or teacher details. Put each issue on the one part that must change, with what is "
    "wrong in one or two sentences. A plan that passes every check is coherent: return "
    "{\"coherent\": true, \"summary\": \"one sentence\", \"issues\": []}.\n"
    "First map the plan: for each objective, quote the lesson proper line that teaches it and name the "
    "assessment item or criterion that checks it (an objective's verb is judged by its taxonomy level, "
    "not by whether it sounds hands-on: 'select', 'identify' and 'analyze' are cognitive). An objective "
    "with both is fine. Then report issues only for real gaps the map shows, or a check above that "
    "clearly fails.\n"
    "Return strict JSON: {\"map\": [{\"objective\": \"...\", \"taught_by\": \"...\", \"checked_by\": \"...\"}], "
    "\"coherent\": true or false, \"summary\": \"one sentence\", \"issues\": "
    "[{\"part_key\": \"...\", \"problem\": \"...\", \"fix\": \"...\"}]} with part_key exactly as given."
)
# The user (2026-11-24): the check gives the exact input the part needs, in
# both modes; the student copies it in. A locked part still gets an instruction.
_FIX = ("Each fix is the exact text to put in that part in place of what is there now: the whole part, "
        "complete and ready to paste, in the plan's own style (rubric rows with cells separated by ' | '), "
        "fixing the mismatch and keeping everything else in the part that is right. Never an instruction "
        "('Add ...', 'Change ...'): write the part itself.")


# A plan read by the coherence check: each part and the whole are capped, so
# the free check can't be made to spend credits on a huge paste.
_COHERENCE_PART_BUDGET = 6000
_COHERENCE_BUDGET = 40000


def _plan_text(fields, values: dict) -> str:
    """The plan as 'Label (key):' blocks; a weekly part as 'Day: answer' lines."""
    blocks, used = [], 0
    for f in fields:
        value = values.get(f.field_key)
        if isinstance(value, list):
            names = getattr(f, "parts_list", None) or []
            text = "\n".join(f"{names[i] if i < len(names) else f'Day {i + 1}'}: {v}"
                             for i, v in enumerate(value) if str(v or "").strip())
        else:
            text = str(value or "").strip()
        text = text[:_COHERENCE_PART_BUDGET]
        if text and used + len(text) <= _COHERENCE_BUDGET:
            blocks.append(f"{f.label} ({f.field_key}):\n{text}")
            used += len(text)
    return "\n\n".join(blocks)


def check_coherence(context: dict, fields, values: dict) -> dict:
    """{"coherent", "summary", "issues": [{"part_key", "part_label", "locked", "problem", "fix"}]}
    for a plan. Each fix is the exact text the part needs, in both modes; a
    locked part gets an instruction. Nothing in the plan is changed."""
    labels = {f.field_key: f.label for f in fields}
    locked_keys = {f.field_key for f in fields if getattr(f, "locked", False)}
    locked = [f.label for f in fields if f.field_key in locked_keys]
    about = "\n".join(f"{k.replace('_', ' ').title()}: {context[k]}" for k in
                      ("topic", "main_topic", "subject", "grade_level", "previous_topic", "next_topic",
                       "assessment_type") if context.get(k))
    chosen = _chosen_assessment(context)
    teaching = [f.label for f in fields if grounding.is_lesson_proper_field(f)]
    task = (f"Lesson:\n{about}\n\nObjective verb taxonomies:\n{taxonomy_text()}\n\n"
            + (f"In this school's format the lesson proper is the part \"{teaching[0]}\".\n" if teaching else "")
            + (f"{chosen} Never change the assessment's kind or its number of items; when an objective "
               "can't be checked by it, the fix goes on the objectives.\n" if chosen else "")
            + f"{_FIX}\n"
            + (f"Locked parts (their fix is an instruction only): {', '.join(locked)}\n" if locked else "")
            + f"\nThe lesson plan:\n{_plan_text(fields, values)}")
    data = _call(_COHERENCE_SYSTEM, [task], "Coherence check")
    data = data if isinstance(data, dict) else {}
    # A model often names a part by its label; matched either way.
    by_label = {str(label).strip().lower(): key for key, label in labels.items()}
    issues, raised = [], [i for i in data.get("issues") or [] if isinstance(i, dict)]
    for i in raised:
        named = str(i.get("part_key") or "").strip()
        key = named if named in labels else by_label.get(named.lower())
        problem, fix = str(i.get("problem") or "").strip(), str(i.get("fix") or "").strip()
        if key and problem:
            issues.append({"part_key": key, "part_label": labels[key], "locked": key in locked_keys,
                           "problem": problem[:600], "fix": fix[:_MAX_USE_TEXT]})
    # The issues decide, not the model's yes/no: a "false" with nothing listed
    # showed "doesn't line up" over an empty list. An issue we couldn't place
    # still means the plan doesn't line up.
    coherent = not raised
    summary = str(data.get("summary") or "").strip()[:300] if (data.get("coherent") is True) == coherent else ""
    return {"coherent": coherent,
            "summary": summary or ("Everything lines up." if coherent else "Some parts don't line up yet."),
            "issues": issues}


def _lesson_references(prior_values: dict, context: dict, fields=None) -> str:
    """For the lesson proper in Guided: the references the student listed in
    the plan (in its references part, whatever the format calls it) and what
    their pages say, so Alan teaches from them."""
    ref_keys = {f.field_key for f in fields or [] if grounding.is_reference_field(f)}
    lines = []
    for key, value in (prior_values or {}).items():
        if key in ref_keys or (not ref_keys and "reference" in str(key).lower()):
            for v in value if isinstance(value, list) else [value]:
                lines += [l.strip() for l in str(v or "").split("\n") if l.strip()]
    if not grounding.reference_urls(lines):
        return ("\nThe student has not listed any online references yet. Say so in one sentence in the reply "
                "(they can add them in the references part), and meanwhile write the lesson from the sources "
                "selected or uploaded in the setup (the guide and files above).\n")
    return _references_block(lines, reference_material(lines, context)) + (
        "\nIn the reply, remind the student in one short sentence that their discussion must come from "
        "these references.\n")


def _ground_choices(answer, field, guide_text, citation):
    """The owl's insertable choices held to the same rules as generation: a
    curriculum field only gets the guide's own statements, a references field
    only links that open. A choice with nothing left after that is dropped."""
    if not _is_exact(field):
        return answer
    choices = []
    key = field.field_key
    for c in answer["choices"]:
        if c["type"] == "use":
            text = grounding.snap_to_guide({key: c["text"]}, [field], guide_text)[key]
            text = grounding.keep_working_links({key: text}, [field], citation)[key]
            if not text.strip():
                continue
            c = {**c, "text": text}
        choices.append(c)
    return {**answer, "choices": choices}


def _clean_owl_reply(data, max_text: int = 1500) -> dict:
    if not isinstance(data, dict):
        data = {}
    reply = str(data.get("reply") or "").strip()
    choices = []
    for c in data.get("choices") or []:
        if not isinstance(c, dict):
            continue
        kind = c.get("type") if c.get("type") in ("use", "ask", "direction") else "ask"
        text = c.get("text")
        if isinstance(text, list):
            text = "\n".join(str(t).strip() for t in text if str(t).strip())
        text = str(text or c.get("label") or "").strip()
        label = str(c.get("label") or text).strip()
        if not text:
            continue
        choice = {"type": kind, "label": label[:80], "text": text[:max_text if kind == "use" else 600]}
        why = str(c.get("why") or "").strip()
        if kind in ("use", "direction") and why:
            choice["why"] = why[:240]  # the option's explanation, shown under it
        choices.append(choice)
        if len(choices) == 2 * _MAX_CHOICES:  # owl_chat filters, then caps at _MAX_CHOICES
            break
    return {"reply": reply[:700] or "Here are some options for this field.", "choices": choices}
