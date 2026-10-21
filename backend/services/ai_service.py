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

import requests

from config import Config
from services import ai_limits

_log = logging.getLogger(__name__)

PROVIDER = "openrouter" if Config.OPENROUTER_API_KEY else "gemini"
MODEL = Config.OPENROUTER_MODEL if PROVIDER == "openrouter" else Config.GEMINI_MODEL

if PROVIDER == "gemini" and not Config.GEMINI_API_KEY:
    _log.warning("Neither OPENROUTER_API_KEY nor GEMINI_API_KEY is set; AI generation and format scanning will fail.")

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_gemini_client = None

# Ceilings on what one field may contain. Stated in the prompt AND enforced on
# the reply in _enforce_limits(), because asking a model for brevity is a
# request, not a guarantee: the trim is what actually holds the line when it
# writes four sentences anyway.
_MAX_LIST_ITEMS = 5
_MAX_ITEM_WORDS = 15
_MAX_PROSE_SENTENCES = 3
_MAX_PROSE_WORDS = 60

_SYSTEM_INSTRUCTION = (
    "You are helping a K-12 ICT/TLE teacher in the Philippines write a lesson plan. "
    "Follow DepEd K-12 tone and terminology. Return concise, classroom-ready content.\n\n"
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
    "Length rules (follow strictly. A teacher is copying this into a form, not "
    "reading an essay):\n"
    f"- A list field: at most {_MAX_LIST_ITEMS} items, one per line, each a single "
    f"line of at most {_MAX_ITEM_WORDS} words. No item may be a paragraph.\n"
    f"- A prose field: at most {_MAX_PROSE_SENTENCES} sentences.\n"
    "- Never restate the field's own label, never open with filler such as 'In this "
    "lesson' or 'The teacher will', and never explain your reasoning or comment on "
    "the plan. Write the content only: no preamble, no closing sentence, no "
    "meta-text.\n\n"
    "Answer every field you are asked for with real content. Never return an empty "
    "string, a placeholder such as 'N/A' or 'To be determined', or a restatement "
    "of the label. If a field is hard to ground in the topic or guide, still answer "
    "it with the most specific content the topic supports.\n\n"
    "Formatting: plain text only, except that a step-by-step procedure may number "
    "its steps ('1. ', '2. ') and a list may put one item per line. Never use "
    "markdown syntax (no **bold**, no ## headings, no - bullets); the app applies "
    "its own formatting."
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
    "- Reply in at most 2 short sentences and no more than 35 words. No greetings, no "
    "praise, no filler, no markdown, no lists. Answer exactly what was asked.\n"
    "- Always give 2 to 4 choices the teacher can tap.\n"
    "- A \"use\" choice is finished content for the current field that the teacher can "
    "insert as is: classroom-ready, in DepEd K-12 terminology, grounded in the lesson's "
    "topic, subject and course guide. Fit the field: one line for a short text field; for "
    "a list, one item per line and at most 5 items. Its label names the option in at most "
    "6 words.\n"
    "- An \"ask\" choice is a follow-up question the teacher may want to ask next, at most "
    "8 words; its label and text are that question.\n"
    "- When the teacher wants content, suggestions or examples, give mostly \"use\" "
    "choices that differ from each other in approach, not just in wording.\n"
    "- Never repeat content already written in other fields. If asked about something "
    "unrelated to the lesson plan, say so in one sentence and offer lesson-related choices.\n\n"
    "Return strict JSON: {\"reply\": \"...\", \"choices\": [{\"type\": \"use\" or \"ask\", "
    "\"label\": \"...\", \"text\": \"...\"}]}"
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


def guide_excerpt(text: str, context: dict, budget: int = GUIDE_BUDGET) -> str:
    """The parts of a course guide most relevant to this lesson, within budget.

    A guide that fits is used whole. A longer one keeps its opening (scope and
    overview) and then the passages that mention the lesson's topic and
    subject most, in their original order, so the AI sees the section being
    taught even when it sits deep in the guide."""
    text = (text or "").strip()
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

    if "value" in haystack:
        return (
            " Each item must be a single word only (e.g. 'Patience', 'Accuracy') — "
            "no phrases, no explanation of how it's shown."
        )
    if "material" in haystack or "resource" in haystack:
        return (
            " Each item must be a general category only (e.g. 'Laptop', 'Whiteboard', "
            "'Printed handouts') — no brand names, software names, or specific model "
            "numbers, and no parenthetical examples."
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
_TIMING_WORDS = ("procedure", "flow", "lesson proper", "learning experience", "activity")


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
    return out


def _schema_block(fields, context=None):
    context = context or {}
    return "\n".join(
        f"- {f.field_key} ({f.field_type}): {f.ai_hint or f.label}{_field_directive(f)}{_weekly_directive(f)}"
        f"{_grounding_directive(f, context) if context else ''}"
        for f in fields
    )


def _context_block(context: dict):
    return ", ".join(f"{k}: {v}" for k, v in context.items() if v)


def _lesson_block(context: dict, guide_text: str) -> str:
    """The part of every generation and chat request that stays the same for a
    lesson, sent first so it can be served from the provider's prompt cache."""
    block = f"Lesson details: {_context_block(context)}\n"
    if guide_text:
        block += f"""
Base the content on this course guide (follow its scope, sequence, and terminology closely).
Every field that references material, examples, or activities must be traceable back to
something in this guide — do not introduce topics, terms, or activities that aren't
supported by it:
---
{guide_text}
---
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

def _trim(values, fields):
    """Every value the model returns goes through here before it leaves this
    module, so the length ceilings hold regardless of which call produced it."""
    return ai_limits.enforce_limits(
        values, fields,
        max_items=_MAX_LIST_ITEMS,
        max_item_words=_MAX_ITEM_WORDS,
        max_sentences=_MAX_PROSE_SENTENCES,
        max_prose_words=_MAX_PROSE_WORDS,
    )


def _fill_gaps(lesson: str, fields, all_values: dict, label: str, context=None) -> dict:
    """One more attempt at the fields that came back blank or as a placeholder.

    A model asked for twelve fields at once will occasionally skip one or answer
    it with "N/A". Re-asking for just those, naming them, recovers most of them
    on the second try. Only one extra pass: if a field is still empty after
    being asked on its own, the caller reports it as unanswered rather than
    looping and spending a teacher's time.
    """
    gaps = ai_limits.missing_keys(all_values, fields)
    if not gaps:
        return {}

    gap_fields = [f for f in fields if f.field_key in set(gaps)]
    task = f"""
These fields of the lesson plan came back empty or unanswered. Answer each one
now with real, specific content grounded in the lesson details above. Return
strict JSON with field_key as keys and nothing else:
{_schema_block(gap_fields, context)}
"""
    try:
        recovered = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], f"{label} (filling gaps)"), gap_fields)
    except Exception:
        # The gap pass is best-effort: a failure here must not lose the fields
        # that were generated successfully.
        _log.warning("[%s] gap-fill pass failed; reporting the blanks instead", label, exc_info=True)
        return {}

    # Only real answers are taken: a second empty reply must not overwrite
    # anything, nor make the field look answered.
    return {k: v for k, v in recovered.items() if ai_limits.is_answered(v)}


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


def generate_full(context: dict, fields, course_guide_text: str = "", include_keys=None) -> dict:
    targets = select_fields(fields, include_keys)
    if not targets:
        return {}
    lesson = _lesson_block(context, guide_excerpt(course_guide_text, context))
    task = f"""
Fill ONLY the following fields and return strict JSON with field_key as keys:
{_schema_block(targets, context)}
"""
    values = _trim(_call(_SYSTEM_INSTRUCTION, [lesson, task], "Building Proficiency"), targets)
    values.update(_fill_gaps(lesson, targets, values, "Building Proficiency", context))
    return values


_STREAM_CHUNK_SIZE = 4


def _chunk_label(chunk):
    return chunk[0].label if len(chunk) == 1 else f"{chunk[0].label} – {chunk[-1].label}"


def generate_full_streaming(context: dict, fields, course_guide_text: str = "", include_keys=None):
    """Fields have no meaningful grouping anymore (section_group isn't
    collected — see the format builder), so this batches them in fixed-size
    groups by document order instead: enough fields per AI call to stay fast
    and coherent, small enough that the caller (the generator's live
    document view) gets real, separate network responses to reveal
    progressively rather than one big call that arrives all at once."""
    # Only the requested fields are generated, and only they are held to account
    # in the completeness report at the end.
    fields = select_fields(fields, include_keys)
    if not fields:
        yield {"type": "complete", "values": {}, "missing": [], "missing_labels": []}
        return
    chunks = [fields[i:i + _STREAM_CHUNK_SIZE] for i in range(0, len(fields), _STREAM_CHUNK_SIZE)]
    # Built once per plan: every chunk shares this exact prefix.
    lesson = _lesson_block(context, guide_excerpt(course_guide_text, context))

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
            chunk,
        )
        all_values.update(values)
        yield {"type": "section_done", "section": name, "index": i, "total": len(chunks), "values": values}

    # Anything still blank or answered with a placeholder gets one more,
    # targeted attempt before this reports back. Without it the page announced
    # a finished plan over fields the model had quietly skipped.
    gaps = ai_limits.missing_keys(all_values, fields)
    if gaps:
        yield {"type": "filling_gaps", "count": len(gaps)}
        recovered = _fill_gaps(lesson, fields, all_values, "Building Proficiency", context)
        if recovered:
            all_values.update(recovered)
            yield {"type": "section_done", "section": "Filled-in gaps",
                   "index": len(chunks), "total": len(chunks), "values": recovered}

    # `missing` answers "did everything I was asked to write come back": the
    # requested field keys with no real content even after the retry. It says
    # nothing about fields outside include_keys, so the page must combine this
    # with its own check of any fields the teacher chose to write themselves
    # before it can claim the plan is finished.
    missing = ai_limits.missing_keys(all_values, fields)
    yield {
        "type": "complete",
        "values": all_values,
        "missing": missing,
        "missing_labels": [f.label for f in fields if f.field_key in set(missing)],
    }


# ---------------------------------------------------------------------------
# Guided mode: chatting with the owl
# ---------------------------------------------------------------------------

_MAX_CHOICES = 4


def owl_chat(context: dict, field, prior_values: dict, course_guide_text: str,
             history: list, message: str) -> dict:
    """One turn of the Guided mode chat about `field`. Returns
    {"reply": str, "choices": [{"type": "use"|"ask", "label": str, "text": str}]}."""
    lesson = _lesson_block(context, guide_excerpt(course_guide_text, context))
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
    task = f"""
Fields already written (do not repeat them):
{json.dumps(written)}

The teacher is writing the field "{field.label}" ({field.field_type}).
{f"What belongs in it: {field.ai_hint}" if field.ai_hint else ""}{_field_directive(field)}{_grounding_directive(field, context)}{weekly_note}
{typed}

{f"Conversation so far:{chr(10)}{turns}{chr(10)}" if turns else ""}Teacher: {message}
"""
    data = _call(_OWL_SYSTEM_INSTRUCTION, [lesson, task], "Owl chat")
    return _clean_owl_reply(data)


def _clean_owl_reply(data) -> dict:
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
        choices.append({"type": kind, "label": label[:80], "text": text[:1500]})
        if len(choices) == _MAX_CHOICES:
            break
    return {"reply": reply[:400] or "Here are some options for this field.", "choices": choices}
