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
from services import ai_limits, grounding

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

_OWL_SYSTEM_INSTRUCTION = (
    "You are the AlignED owl, an assistant inside a lesson-plan editor used by K-12 ICT/TLE "
    "teachers in the Philippines. The teacher writes one field of the lesson plan at a time "
    "and chats with you about it.\n\n"
    "Rules (follow strictly):\n"
    "- Reply briefly and organised: one or two short sentences, or, when the answer has "
    "several points or steps, one short lead-in line and then each point on its own line "
    "starting with '- ' (or '1. ', '2. ' for steps in order), at most 5 points of a few words "
    "each. Never run a list together in one sentence. No greetings, no praise, no filler, no "
    "headings, tables or other markdown. Answer exactly what was asked.\n"
    "- Always give 2 to 4 choices.\n"
    "- A \"use\" choice is an example of finished content for the current field, shown as "
    "an option to read and learn from (it is never inserted; the writer writes the field "
    "in their own words): classroom-ready, in DepEd K-12 terminology, grounded in the lesson's "
    "topic, subject and course guide. Fit the field: one line for a short text field; for "
    f"a list, one item per line and at most {_MAX_LIST_ITEMS} complete items; for learning objectives, exactly "
    "3 objectives, one per line (no competency, no lead-in); for the lesson proper or discussion, the "
    "whole lesson as that field's instructions describe (headings, definitions, terms, examples), taken "
    "only from the references' content given. Its label names the option in at most "
    "6 words. Its \"why\" explains that option in one short sentence (at most 25 words): "
    "why it fits this field and lesson, or what it does for the learners.\n"
    "- An \"ask\" choice is a follow-up question the teacher may want to ask next, at most "
    "8 words; its label and text are that question.\n"
    "- When the teacher wants content, suggestions or examples, give mostly \"use\" "
    "choices that differ from each other in approach, not just in wording.\n"
    "- Never repeat content already written in other fields. If asked about something "
    "unrelated to the lesson plan, say so in one sentence and offer lesson-related choices.\n\n"
    "Return strict JSON: {\"reply\": \"...\", \"choices\": [{\"type\": \"use\" or \"ask\", "
    "\"label\": \"...\", \"text\": \"...\", \"why\": \"...\" (\"use\" only)}]}"
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


def _topic_sections(text: str, terms: set, budget: int) -> str:
    """The guide searched for the topic: the passages that mention it most,
    each widened back to the standards heading it sits under and a little past
    it, merged and kept in document order. "" when the topic isn't in the guide."""
    low = text.lower()
    patterns = {t: re.compile(r"\b" + re.escape(t)) for t in terms}
    # A passage that holds one stray word of the topic isn't the topic: a short
    # topic needs every word, a longer one most of them.
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
            hits.append((score, start))
    if not hits:
        return ""
    hits.sort(reverse=True)

    windows = []
    for score, start in hits:
        # Further passages only when they are nearly as good a match as the
        # best one, so a passing mention doesn't pull in an unrelated section.
        if len(windows) == _MAX_HITS or score < hits[0][0] / 2:
            break
        if any(a <= start < b for a, b in windows):
            continue
        heads = [m.start() for m in _STANDARDS_HEADING.finditer(text, max(0, start - _LOOK_BACK), start)]
        begin = max(0, start - 1500)
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
    parts = [(f"[From: {title}]\n" if title else "") + guide_excerpt(text, context, share) for title, text in sources]
    return "\n\n".join(parts), "\n\n".join(text for _, text in sources)


def guide_excerpt(text: str, context: dict, budget: int = GUIDE_BUDGET) -> str:
    """The parts of a course guide that cover this lesson, within budget.

    The guide is searched for the lesson's topic and only the sections that
    teach it are sent (with the standards they sit under), rather than reading
    the document from its first page. When the topic can't be found, the old
    fallback applies: the whole guide if it fits, otherwise its opening plus the
    passages that mention the topic and subject most."""
    text = (text or "").strip()
    # PDF extraction of the DepEd Budget of Work files puts every word on its
    # own line, which wastes most of the budget on line breaks and leaves the
    # line-based blocks below meaningless.
    lines = [l for l in text.split("\n") if l.strip()]
    if lines and sum(len(l) for l in lines) / len(lines) < 20:
        text = grounding.tidy_guide(text)
    topic_terms = _focus_terms(context.get("topic"))
    if topic_terms:
        found = _topic_sections(text, topic_terms, budget)
        if found:
            return found
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
    haystack = f"{field.field_key or ''} {field.label or ''}".lower()

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
            "starts with a measurable Bloom's taxonomy action verb in lowercase, never 'understand', "
            "'know', 'learn' or 'appreciate the importance of'. Cover the domains the lesson really "
            "has: cognitive (e.g. identify, describe, explain, compare, classify, analyze, evaluate, "
            "create), affective (e.g. value, show willingness to, demonstrate respect for, cooperate "
            "in, practice), and psychomotor (e.g. perform, construct, operate, assemble, demonstrate "
            "the procedure for) ONLY when the lesson has a real hands-on skill; never force a "
            "psychomotor objective. Order them from lower to higher thinking. Each is about today's "
            "specific topic and something the lesson proper can teach and the evaluation can check in "
            "this session."
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
    haystack = f"{field.field_key or ''} {field.label or ''}".lower().replace("_", " ")
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
    if grounding.is_lesson_proper_field(field):
        out += _LESSON_PROPER_DIRECTIVE
    if _ASSESSMENT_FIELD.search(haystack) and "mastery" not in haystack:
        out += _ALIGNED_ASSESSMENT
    return out + _assessment_directive(haystack, context)


# Testers wanted the lesson itself, as the teacher puts it on slides, not an
# overview of what the teacher will do.
_LESSON_PROPER_DIRECTIVE = (
    " Write the actual lesson the teacher teaches and shows on slides, not an overview or a list of "
    "steps the teacher follows. For each key concept of today's specific topic: a short heading or "
    "question on its own line (e.g. 'What is a Number System?'), its definition in one sentence, the "
    "key terms each with its meaning, its parts, rules or types as a numbered list ('1. Digits: the "
    "symbols it uses'), and concrete examples ('Binary has 2 digits (0 and 1), so its base is 2.'). "
    "One point per line: '• ' before a bullet point, '1. ' before a numbered one, nothing before a "
    "heading. Every fact, term, definition and example comes from the online references' content or "
    "the course guide given above; never invent one, and leave out what they don't cover. It teaches "
    "every learning objective already written for this plan, in order, so learners can do each one by "
    "the end. The length limits do not apply to this field."
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
# A 20-item quiz (question, four options, then the key) or a task and rubric.
_MAX_ASSESSMENT_LINES = 160


def _assessment_directive(haystack: str, context: dict) -> str:
    """The assessment the setup chose (step 2), for the field that assesses:
    a multiple-choice quiz of its item count with an answer key, or a
    performance task with its rubric. Nothing when the setup didn't ask."""
    kind = str(context.get("assessment_type") or "")
    if not kind or not _ASSESSMENT_FIELD.search(haystack) or "mastery" in haystack:
        return ""
    quiz = _QUIZ_ITEMS.search(kind)
    if quiz:
        n = int(quiz.group(1))
        return (f" Assess with a multiple-choice quiz of exactly {n} item{'s' if n > 1 else ''} on the lesson's "
                "specific topic: each item a numbered question with four options, a. to d., one per line, "
                "then 'Answer key:' with the correct letter for every item. The length limits do not apply "
                "to this field.")
    if "performance task" in kind:
        return (" Assess with a performance task on the lesson's specific topic: the task, its step-by-step "
                "instructions, then 'Rubric:' with 3 to 5 criteria, one per line, each giving its levels and "
                "points (e.g. 'Accuracy: Excellent 5 | Good 4 | Fair 3 | Needs improvement 2'), then the total "
                "points. The length limits do not apply to this field.")
    return ""


def _sets_assessment(field, context) -> bool:
    """The field that carries the setup's quiz or performance task."""
    haystack = f"{field.field_key or ''} {field.label or ''}".lower().replace("_", " ")
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
    (r"\babstraction\b|\blesson proper\b|\bdiscussion\b", "The lesson itself, as the teacher teaches it and "
     "shows it on slides: definitions, terms and examples."),
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


def _part_meaning(field):
    if field.ai_hint:
        return ""
    label = (field.label or "").lower()
    for pattern, meaning in _PART_MEANINGS:
        if re.search(pattern, label):
            return f" ({meaning})"
    return ""


def _schema_block(fields, context=None):
    context = context or {}
    return "\n".join(
        f"- {f.field_key} ({f.field_type}): {f.ai_hint or f.label}{_part_meaning(f)}"
        f"{_field_directive(f)}{_weekly_directive(f)}"
        f"{_grounding_directive(f, context) if context else ''}"
        for f in fields
    )


def _context_block(context: dict):
    return ", ".join(f"{k}: {v}" for k, v in context.items() if v and k != "sample_plan")


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
    # College only: the syllabus week, typed by hand ("5" reads as "Week 5").
    week = str(context.get("week") or "").strip()
    if week and guide_text:
        week = f"Week {week}" if week.isdigit() else week
        block += (f"\nThis lesson is for {week} of the course syllabus: take its topic, outcomes and content "
                  f"from that week in the syllabus or guide below when it lists weeks, otherwise from the part "
                  f"that covers the topic.\n")
    if guide_text:
        block += f"""
This is the section of the course guide that covers the lesson's topic. EVERY field must be
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
            values, assess, max_items=_MAX_ASSESSMENT_LINES, max_item_words=_MAX_ITEM_WORDS,
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
            and not re.search(r"integration|contextuali", f"{f.field_key} {f.label}", re.I)]


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
    timed = [f for f in fields if _TIMED_PARTS.search(f.label or "")]
    if not timed or not any(_PRE_LESSON.search(f.label or "") for f in timed):
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
            if _PRE_LESSON.search(f.label or "") and mins:
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
        targets = [f for f in fields if _TIMED_PARTS.search(f.label or "")
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


def generate_full(context: dict, fields, course_guide_text: str = "", include_keys=None,
                  course_guide_citation: str = "") -> dict:
    targets, _ = _split_uncopyable(select_fields(fields, include_keys), course_guide_text)
    if not targets:
        return {}
    cite = course_guide_citation
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    found, refs_block = _plan_references(targets, context)
    lesson = _lesson_block(context, excerpt, cite) + refs_block
    task = f"""
Fill ONLY the following fields and return strict JSON with field_key as keys:
{_schema_block(targets, context)}
"""
    values = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], "Building Proficiency"), targets,
                   course_guide_text, cite, context)
    values = _complete_batch(lesson, targets, values, "Building Proficiency", course_guide_text, cite, context)
    values = _fix_timing(lesson, targets, values, "Building Proficiency", course_guide_text, cite, context)
    return {**values, **_with_web_references(values, targets, context, found)}


_STREAM_CHUNK_SIZE = 4


def _chunk_label(chunk):
    return chunk[0].label if len(chunk) == 1 else f"{chunk[0].label} – {chunk[-1].label}"


def generate_full_streaming(context: dict, fields, course_guide_text: str = "", include_keys=None,
                            course_guide_citation: str = ""):
    """Fields have no meaningful grouping anymore (section_group isn't
    collected — see the format builder), so this batches them in fixed-size
    groups by document order instead: enough fields per AI call to stay fast
    and coherent, small enough that the caller (the generator's live
    document view) gets real, separate network responses to reveal
    progressively rather than one big call that arrives all at once."""
    # Only the requested fields are generated, and only they are held to account
    # in the completeness report at the end.
    fields, skipped = _split_uncopyable(select_fields(fields, include_keys), course_guide_text)
    needs_guide = {"needs_guide": [f.field_key for f in skipped], "needs_guide_labels": [f.label for f in skipped]}
    if not fields:
        yield {"type": "complete", "values": {}, "missing": [], "missing_labels": [], **needs_guide}
        return
    chunks = [fields[i:i + _STREAM_CHUNK_SIZE] for i in range(0, len(fields), _STREAM_CHUNK_SIZE)]
    # Built once per plan: every chunk shares this exact prefix.
    cite = course_guide_citation
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    found, refs_block = _plan_references(fields, context)
    lesson = _lesson_block(context, excerpt, cite) + refs_block

    all_values = {}
    for i, chunk in enumerate(chunks, start=1):
        name = _chunk_label(chunk)
        yield {"type": "section_start", "section": name, "index": i, "total": len(chunks)}

        task = f"""
Already written fields (for consistency, do not repeat):
{json.dumps(all_values)}

Now fill ONLY the following fields. Return strict JSON with field_key as keys:
{_schema_block(chunk, context)}
"""
        values = _trim(
            _call(_SYSTEM_INSTRUCTION, [lesson, task], f"Building Proficiency {i}/{len(chunks)}"),
            chunk, course_guide_text, cite, context,
        )
        # Check this batch before moving on: anything blank, a weekly field
        # with a day missing, or objectives short of the minimum is asked for
        # again now, while it is still the next batch's context.
        if _incomplete(values, chunk):
            yield {"type": "filling_gaps", "count": len(_incomplete(values, chunk))}
            values = _complete_batch(lesson, chunk, values, f"Building Proficiency {i}/{len(chunks)}",
                                     course_guide_text, cite, context)
        all_values.update(values)
        yield {"type": "section_done", "section": name, "index": i, "total": len(chunks), "values": values}

    # Anything still blank or answered with a placeholder gets one more,
    # targeted attempt before this reports back. Without it the page announced
    # a finished plan over fields the model had quietly skipped.
    gaps = _incomplete(all_values, fields)
    if gaps:
        yield {"type": "filling_gaps", "count": len(gaps)}
        recovered = _fill_gaps(lesson, fields, all_values, "Building Proficiency", course_guide_text, cite,
                               context)
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

    referenced = _with_web_references(all_values, fields, context, found)
    if referenced:
        all_values.update(referenced)
        yield {"type": "section_done", "section": "Online references",
               "index": len(chunks), "total": len(chunks), "values": referenced}

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

_WEB_REFERENCES = 4
_WEB_RESULTS = 10
_REFERENCES_SYSTEM = (
    "You list online references for a Philippine K-12 lesson plan, using ONLY the web search "
    "results you are given. Return strict JSON: {\"references\": [\"...\", ...]}. Each is one "
    "APA 7 reference: Author or organization. (Year, or n.d.). Title. Site Name. URL, with the "
    "URL copied exactly from a search result and nothing after it. Prefer educational, "
    "government (DepEd), university and reputable reference pages that teach the topic itself "
    "(definitions, explanations, examples), each from a different website; never social media, "
    "shops, forums, videos or pages behind a login. Never invent a source or a URL."
)


def _web_search_post(system_instruction: str, prompt: str):
    """(answer text, set of URLs the search returned) from one web-search call."""
    payload = {
        "model": Config.OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}],
        "plugins": [{"id": "web", "max_results": _WEB_RESULTS}],
        "response_format": {"type": "json_object"},
        "reasoning": {"enabled": False},
    }
    response = requests.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {Config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    cited = {}
    for a in message.get("annotations") or []:
        if a.get("type") == "url_citation":
            c = a.get("url_citation") or {}
            if c.get("url"):
                cited.setdefault(c["url"].rstrip("/"), str(c.get("title") or "").strip())
    return message.get("content") or "", cited


def _apa_from_result(url: str, title: str) -> str:
    """An APA 7 line for a search result the model didn't list: the site's
    own name (from its title, "Topic - Site", or its address), n.d., title."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    title = re.sub(r"\s+", " ", title or "").strip()
    head, sep, site = title.rpartition(" - ") if " - " in title else title.rpartition(" | ")
    if sep and 2 <= len(site) <= 40:
        title = head.strip()
    else:
        site = host
    title = title.rstrip(" .?!:;") or host
    return grounding.to_apa(f"{site}. (n.d.). {title}. {site}. {url}")


# References found, by topic; a search that found nothing isn't remembered.
_FOUND_REFERENCES = {}
_MIN_PAGE_TEXT = 800


def find_references(context: dict, count: int = _WEB_REFERENCES) -> list:
    """Up to `count` APA 7 references for the lesson's topic, each from a
    different website, whose pages came from a web search and really open
    with readable text; [] when search is unavailable or finds none."""
    topic = str(context.get("topic") or context.get("main_topic") or "").strip()
    if PROVIDER != "openrouter" or not topic:
        return []
    about = ", ".join(str(context.get(k)) for k in ("subject", "grade_level") if context.get(k))
    key = (topic.lower(), about.lower())
    if key in _FOUND_REFERENCES:
        return _FOUND_REFERENCES[key][:count]
    prompt = (f"Find {count * 2} accessible online pages, each on a different website, that a teacher could "
              f"use to teach this lesson, and list them as APA 7 references.\nLesson topic: {topic}"
              + (f"\nFor: {about}" if about else ""))
    try:
        text, cited = _web_search_post(_REFERENCES_SYSTEM, prompt)
        lines = _parse_json(text).get("references") or []
    except Exception as exc:  # noqa: BLE001 - no references is better than a failed plan
        _log.warning("Reference search failed: %s", exc)
        return []
    lines = [grounding.to_apa(str(l)) for l in lines if isinstance(l, str)]
    lines = [l for l in lines if l and any(u.rstrip("/") in cited for u in grounding.reference_urls([l]))]
    # Testers mostly got one reference: the search's other results become
    # references too, rather than being lost when the model lists only one.
    listed = {u.rstrip("/") for u in grounding.reference_urls(lines)}
    lines += [l for l in (_apa_from_result(u, t) for u, t in cited.items() if u not in listed) if l]
    urls = [grounding.reference_urls([l])[0] for l in lines]
    # A link that only answers a status check can still fail in a browser, so
    # each page must actually open with readable text; one per website.
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(grounding.page_text, urls)) if urls else []
    kept, sites = [], set()
    for line, url, page in zip(lines, urls, texts):
        site = (urlparse(url).hostname or "").removeprefix("www.")
        if len(page) < _MIN_PAGE_TEXT or site in sites:
            continue
        sites.add(site)
        kept.append(line)
        if len(kept) == count:
            break
    if kept and len(_FOUND_REFERENCES) < 500:
        _FOUND_REFERENCES[key] = kept
    return kept


_REFERENCE_PAGES = 4
_REFERENCE_PAGE_BUDGET = 5000


def reference_material(lines, context: dict) -> str:
    """What the references' pages say about the lesson's topic: for each of
    the first few links, the passages of the page that cover the topic,
    labelled with its reference line. "" when no page could be read."""
    urls = grounding.reference_urls(lines)[:_REFERENCE_PAGES]
    if not urls:
        return ""
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        texts = list(pool.map(grounding.page_text, urls))
    by_url = {u: next((str(l).strip() for l in lines if u in str(l)), u) for u in urls}
    parts = [f"[From: {by_url[u]}]\n{guide_excerpt(t, context, _REFERENCE_PAGE_BUDGET)}"
             for u, t in zip(urls, texts) if t.strip()]
    return "\n\n".join(parts)


def _references_block(lines, material: str) -> str:
    """The references and what their pages say, for the lesson proper."""
    if not lines:
        return ""
    listed = "\n".join(str(l).strip() for l in lines if str(l).strip())
    block = f"\nThe lesson's online references:\n{listed}\n"
    if material:
        block += f"\nWhat those references' pages say about the topic (the online references' content):\n---\n{material}\n---\n"
    return block


def _with_web_references(values: dict, fields, context: dict, found=None) -> dict:
    """The reference fields with found references added after what they hold
    (the course guide's own citation stays first). {} when nothing changes."""
    refs = [f for f in fields if grounding.is_reference_field(f)]
    if found is None:
        found = find_references(context) if refs else []
    changed = {}
    for f in refs if found else []:
        value = values.get(f.field_key)
        first = value[0] if isinstance(value, list) and value else value
        lines = [l for l in str(first or "").split("\n") if l.strip()]
        merged = "\n".join(lines + [l for l in found if l not in lines])
        # A weekly field cites its references once, on its first day.
        changed[f.field_key] = [merged] + list(value[1:]) if isinstance(value, list) and value else merged
    return changed


# ---------------------------------------------------------------------------
# Guided mode: chatting with the owl
# ---------------------------------------------------------------------------

_MAX_CHOICES = 4


def owl_chat(context: dict, field, prior_values: dict, course_guide_text: str,
             history: list, message: str, course_guide_citation: str = "") -> dict:
    """One turn of the Guided mode chat about `field`. Returns
    {"reply": str, "choices": [{"type": "use"|"ask", "label": str, "text": str, "why": str ("use" only)}]}."""
    excerpt, course_guide_text = _guide_inputs(course_guide_text, context)
    lesson = _lesson_block(context, excerpt, course_guide_citation)
    written = {k: v for k, v in (prior_values or {}).items() if v and k != field.field_key}
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
        lesson += _lesson_references(prior_values, context)
    locked = bool(getattr(field, "locked", False))
    if locked:
        weekly_note += ("\nThe supervising teacher locked this field: the student must write it in their own words. "
                        "Coach them instead: say what it should contain, ask guiding questions, point to the guide. "
                        "Never write the field's content for them; offer only \"ask\" choices.")
    task = f"""
Fields already written (do not repeat them):
{json.dumps(written)}

The teacher is writing the field "{field.label}" ({field.field_type}).
{f"What belongs in it: {field.ai_hint}" if field.ai_hint else ""}{_field_directive(field)}{_grounding_directive(field, context)}{weekly_note}
{typed}

{f"Conversation so far:{chr(10)}{turns}{chr(10)}" if turns else ""}Teacher: {message}
"""
    # The references search runs beside the reply instead of after it (testers
    # found Alan slow on the references part).
    pool = ThreadPoolExecutor(max_workers=1) if grounding.is_reference_field(field) and not locked else None
    searching = pool.submit(find_references, context) if pool else None
    try:
        data = _call(_OWL_SYSTEM_INSTRUCTION, [lesson, task], "Owl chat")
    finally:
        if pool:
            pool.shutdown(wait=False)
    # A lesson proper is the whole lesson; other options are short.
    answer = _clean_owl_reply(data, 6000 if grounding.is_lesson_proper_field(field) else 1500)
    if locked:
        # Whatever the model sends, nothing ready-made goes into a locked field.
        return {**answer, "choices": [c for c in answer["choices"] if c["type"] == "ask"]}
    answer = _ground_choices(answer, field, course_guide_text, course_guide_citation)
    if searching:
        # References Alan offers are real pages from a web search, not the model's guesses.
        try:
            found = searching.result(timeout=60)
        except Exception:  # noqa: BLE001 - the reply still stands without them
            found = []
        if found:
            card = {"type": "use", "label": "Online references", "text": "\n".join(found),
                    "why": "Real pages found for this topic, in APA 7; every link was checked and opens."}
            answer = {**answer, "choices": [card] + [c for c in answer["choices"] if c["type"] != "use"][:_MAX_CHOICES - 1]}
    return answer


def _lesson_references(prior_values: dict, context: dict) -> str:
    """For the lesson proper in Guided: the references the student listed in
    the plan and what their pages say, so Alan teaches from them."""
    lines = []
    for key, value in (prior_values or {}).items():
        if "reference" in str(key).lower():
            for v in value if isinstance(value, list) else [value]:
                lines += [l.strip() for l in str(v or "").split("\n") if l.strip()]
    if not grounding.reference_urls(lines):
        return ("\nThe student has not listed any online references yet. Say so in the reply: the discussion "
                "should come from references they choose, so they should add them in the references part "
                "first. Meanwhile use only the course guide.\n")
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
        kind = c.get("type") if c.get("type") in ("use", "ask") else "ask"
        text = c.get("text")
        if isinstance(text, list):
            text = "\n".join(str(t).strip() for t in text if str(t).strip())
        text = str(text or c.get("label") or "").strip()
        label = str(c.get("label") or text).strip()
        if not text:
            continue
        choice = {"type": kind, "label": label[:80], "text": text[:max_text]}
        why = str(c.get("why") or "").strip()
        if kind == "use" and why:
            choice["why"] = why[:240]  # the option's explanation, shown under it
        choices.append(choice)
        if len(choices) == _MAX_CHOICES:
            break
    return {"reply": reply[:700] or "Here are some options for this field.", "choices": choices}
