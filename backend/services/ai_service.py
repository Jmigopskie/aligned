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

_log = logging.getLogger(__name__)

PROVIDER = "openrouter" if Config.OPENROUTER_API_KEY else "gemini"
MODEL = Config.OPENROUTER_MODEL if PROVIDER == "openrouter" else Config.GEMINI_MODEL

if PROVIDER == "gemini" and not Config.GEMINI_API_KEY:
    _log.warning("Neither OPENROUTER_API_KEY nor GEMINI_API_KEY is set; AI generation and format scanning will fail.")

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_gemini_client = None

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
    "page/unit names) from them rather than inventing generic ones."
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


def _schema_block(fields):
    return "\n".join(
        f"- {f.field_key} ({f.field_type}): {f.ai_hint or f.label}{_field_directive(f)}"
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

def generate_full(context: dict, fields, course_guide_text: str = "") -> dict:
    lesson = _lesson_block(context, guide_excerpt(course_guide_text, context))
    task = f"""
Fill ONLY the following fields and return strict JSON with field_key as keys:
{_schema_block(fields)}
"""
    return _call(_SYSTEM_INSTRUCTION, [lesson, task], "Building Proficiency")


_STREAM_CHUNK_SIZE = 4


def _chunk_label(chunk):
    return chunk[0].label if len(chunk) == 1 else f"{chunk[0].label} – {chunk[-1].label}"


def generate_full_streaming(context: dict, fields, course_guide_text: str = ""):
    """Fields have no meaningful grouping anymore (section_group isn't
    collected — see the format builder), so this batches them in fixed-size
    groups by document order instead: enough fields per AI call to stay fast
    and coherent, small enough that the caller (the generator's live
    document view) gets real, separate network responses to reveal
    progressively rather than one big call that arrives all at once."""
    fields = list(fields)
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
{_schema_block(chunk)}
"""
        values = _call(_SYSTEM_INSTRUCTION, [lesson, task], f"Building Proficiency {i}/{len(chunks)}")
        all_values.update(values)
        yield {"type": "section_done", "section": name, "index": i, "total": len(chunks), "values": values}

    yield {"type": "complete", "values": all_values}


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
    turns = "\n".join(f"{'Teacher' if t.get('role') == 'teacher' else 'Owl'}: {t.get('text', '')}" for t in history)
    typed = f'What the teacher has typed in it so far: "{current}"' if str(current).strip() else "The field is still empty."
    task = f"""
Fields already written (do not repeat them):
{json.dumps(written)}

The teacher is writing the field "{field.label}" ({field.field_type}).
{f"What belongs in it: {field.ai_hint}" if field.ai_hint else ""}{_field_directive(field)}
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
