# Batch 1: Lesson-Plan Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Objectives by domain taxonomy, assessment chosen from the objectives with rubric tables everywhere, Guided chat that offers two directions and then the complete part, a coherence check with fixes, and a 5-point part-by-part Regenerate in Building Proficiency.

**Architecture:** Prompt rules live in `backend/services/ai_service.py`; routes in `backend/routes/generate_routes.py` and `points_routes.py`; Word export in `docx_service.py`. The browser side is vanilla JS: `generator.js` (document view, Alan's chat, generation), `guided-flow.js` (Guided screens), `setup-flow.js` (setup steps), `submissions.js` / `lesson-plan-list.js` (read-only plan views). A new `frontend/js/rubric.js` holds the rubric table logic every page shares.

**Tech Stack:** Flask + SQLAlchemy (MySQL prod, sqlite tests), python-docx, OpenRouter (Mistral Large 4), vanilla JS (classic scripts + ES modules for the setup flow), node for `*.check.js` self-checks.

**Spec:** `docs/superpowers/specs/2026-11-22-batch1-lesson-quality-design.md` (read it with this plan).

## Global Constraints

- Work in worktree `C:\tle\rel-Aligned\aligned\.claude\worktrees\teacher-download-submission`, branch `worktree-teacher-download-submission`; base is live commit `33b22c3`.
- Backend tests are self-check scripts: `cd backend; python -W ignore test_<name>.py` prints `... OK` lines and exits 0. Frontend rule checks: `node frontend/js/<name>.check.js`. No pytest.
- Guided never writes into a part for the student: no "Use this", no tap-to-fill. Only `ask` and `direction` chips are tappable, and they only send a message.
- Locked parts are coach-only (no `use` cards; coherence fixes for them are instructions).
- Objectives stay exactly 3 (`_MIN_OBJECTIVES`), plain lines under the lead-in, no domain labels.
- Rubric header row, verbatim: `Criteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)`; last line `Total: N points`.
- `REGENERATE_COST = 5`; `BUILD_COST = 30` unchanged; teachers and admins never pay.
- No emoji icons (icons.js SVGs only); existing CSS tokens; every changed HTML page bumps its `?v=2026-11-22b` cache-buster on the files it changed.
- Commit message footer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. On Windows PowerShell, commit with `git commit -F <file>` when the message has quotes.

## Review Focus

1. A **teacher** regenerates: no charge, no points text in the modal (Task 9 test `teacher_never_charged`).
2. The regenerate **stream fails or returns the ticked parts empty**: the 5 points come back (Task 9 test `refund_on_failure`).
3. A rubric **pasted with a markdown `|---|` rule line**: the rule disappears on screen and in Word, the rows still form one table (Task 4 check `markdown_rule_dropped`; Word side already covered by `test_assessment_rubric.py`).
4. **Weekly parts** (an answer per day, values are arrays) sent to the coherence check: flattened as `Monday: …` lines, not `["…"]` (Task 7 test `weekly_values_flattened`).
5. A student taps a **direction chip on a locked part**: the reply has no `use` card (Task 5 test `locked_direction_coaches`).

---

### Task 1: Commit the drafted assessment step

The four-choice setup step, `_assessment_directive`, the ` | ` rubric rows and the Word table conversion are already written but uncommitted.

**Files:**
- Modify (already drafted): `backend/services/ai_service.py` (`_assessment_directive`, `_MAX_ASSESSMENT_LINE_WORDS = 90`, `_MAX_ASSESSMENT_LINES = 200`), `backend/services/docx_service.py` (`pipe_cells`, `pipe_rows_to_tables`, `_insert_table`, call in `_save`), `frontend/js/setup-flow.js`, `frontend/js/setup-flow-steps.js`, `frontend/js/setup-flow-steps.check.js`, `frontend/js/generator.js` (`assessmentText`)
- Test: `backend/test_assessment_rubric.py` (already written)

**Interfaces:**
- Produces: `docx_service.pipe_cells(line: str) -> list[str]` (3+ cells or `[]`), `docx_service.pipe_rows_to_tables(doc) -> None`; setup answer `assessment ∈ {"objectives","quiz","task","both"}` with `quizItems ∈ {5,10,15,20}`; context key `assessment_type` text as built by `assessmentText`.

- [ ] **Step 1:** Add the affective mapping to the `"objectives"` branch of `_assessment_directive`: an affective objective is checked by a criterion row in the task's rubric when there is a task, otherwise by one line `Observed: <behaviour>` after the quiz. Add to `test_assessment_rubric.py`: `assert "affective" in by_objectives and "Observed:" in by_objectives`.
- [ ] **Step 2:** Run `cd backend; python -W ignore test_assessment_rubric.py` → `assessment and rubric OK`; `node frontend/js/setup-flow-steps.check.js` → exits 0 with no output errors.
- [ ] **Step 3:** Bump `generator.html` cache-busters for `setup-flow.js` / `setup-flow-steps.js` / `generator.js` to `2026-11-22b`, and the `guided-flow.js` import in `setup-flow.js` if it changed. Commit: `feat(assessment): choose by objectives, quiz, task or both; rubric rows export as Word tables`.

### Task 2: Objectives by domain taxonomy

**Files:**
- Modify: `backend/services/ai_service.py` (objectives branch of `_field_directive`, ~line 422)
- Test: `backend/test_objective_taxonomy.py` (create)

**Interfaces:**
- Produces: `ai_service.TAXONOMIES: dict[str, tuple[str, list[tuple[str, list[str]]]]]` — domain → (taxonomy name, [(level, verbs)]), keys `"cognitive"`, `"affective"`, `"psychomotor"`; `ai_service.taxonomy_text() -> str` (one line per domain: `Cognitive (Revised Bloom's): Remember: define, list, … · Understand: …`). Used by Tasks 5 and 7.

- [ ] **Step 1: Write the failing test** `test_objective_taxonomy.py`:
  - `t = ai_service.taxonomy_text()`; assert `"Revised Bloom's" in t and "Krathwohl" in t and "Dave" in t`.
  - assert each level appears: `Remember, Understand, Apply, Analyze, Evaluate, Create, Receiving, Responding, Valuing, Organization, Characterization, Imitation, Manipulation, Precision, Articulation, Naturalization`.
  - `d = ai_service._field_directive(Field("objectives", "Objectives", "list"))`; assert `t in d`, `"exactly 3" in d`, `"only the domains" in d.lower()` (no forced domain), `"understand', 'know', 'learn'" in d` (banned verbs kept), `"lower to higher" in d`.
- [ ] **Step 2:** Run it → fails (`TAXONOMIES` missing).
- [ ] **Step 3:** Add `TAXONOMIES` with the spec's levels and verbs (spec §1, verbatim), `taxonomy_text()`, and rewrite the objectives directive: each objective starts with a verb from the matching domain's taxonomy at a level fit for the grade; only the domains the lesson really has; ordered lower to higher; keep the existing lead-in, numbering and banned-verb text.
- [ ] **Step 4:** Run `test_objective_taxonomy.py` → `objective taxonomy OK`; rerun `test_generate_selection.py` and `test_references_coherence.py` (both assert on objectives wording) → OK, fixing any assertion on old wording only where the spec changed it.
- [ ] **Step 5:** Commit `feat(objectives): verbs from Revised Bloom's, Krathwohl and Dave by domain`.

### Task 3: Edited rubric tables survive Word export

**Files:**
- Modify: `backend/services/docx_service.py` (`_RichParser` ~1360, `parse_rich_value` ~1487)
- Test: `backend/test_assessment_rubric.py` (extend)

**Interfaces:**
- Consumes: `pipe_rows_to_tables` (Task 1).
- Produces: `parse_rich_value(html)` returns one line per `<tr>`, cells joined with `" | "` (text of each `<th>`/`<td>`), so `_save` turns them into a table.

- [ ] **Step 1:** Add test: `lines = docx_service.parse_rich_value("<p>Rubric:</p><table><tr><th>Criteria</th><th>Excellent (4)</th><th>Good (3)</th></tr><tr><td>Accuracy</td><td>All correct</td><td>One error</td></tr></table>")`; assert the plain text of the lines equals `["Rubric:", "Criteria | Excellent (4) | Good (3)", "Accuracy | All correct | One error"]` (read the line text the way `_set_paragraph_rich` does).
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** In `_RichParser`: `<tr>` starts a new line, `<th>`/`<td>` after the first in a row emits `" | "`, `</table>` ends the line; table tags are otherwise ignored.
- [ ] **Step 4:** Run `test_assessment_rubric.py` and `test_doc_edits.py` → OK.
- [ ] **Step 5:** Commit `fix(export): rubric tables edited on screen export as Word tables`.

### Task 4: Rubric tables on every screen

**Files:**
- Create: `frontend/js/rubric.js`, `frontend/js/rubric.check.js`
- Modify: `frontend/js/generator.js` (slot painting at ~2156, ~2180, ~2696-2699, ~3450, ~3832; slot reading at 1572, 3467, `syncFieldFromEl` 1797; `RICH_VALUE_TAGS` / `sanitizeRichValueHtml` ~1760; `fillLines` for `use` cards), `frontend/js/lesson-plan-list.js` (`fillAndLockDocCanvas` ~441), `frontend/js/submissions.js` (`renderPreviewValue`), `frontend/js/guided-flow.js` (review `preview(p)` if it shows full text), `frontend/css/style.css`, `frontend/generator.html`, `frontend/lesson-plan-list.html` (load `rubric.js` before the scripts that use it; plus any other page that renders plan values, found by grepping for `renderPreviewValue|fillDocCanvas|fillAndLockDocCanvas`)

**Interfaces:**
- Produces (globals from `rubric.js`, a classic script):
  - `rubricBlocks(text: string) -> Array<{rows: string[][]} | {line: string}>` — pure; 2+ consecutive lines with 3+ ` | ` cells form one `{rows}` block; `|---|` rule lines inside a block are dropped; everything else is `{line}`.
  - `setSlotText(el: Element, text: string) -> void` — writes text into `el`, rubric blocks as `<table class="lp-rubric">` (first row `<th>`), other lines as text with line breaks, exactly as `el.textContent = text` looked before for non-rubric text.
  - `slotText(el: Element) -> string` — inverse: tables read back as one ` | ` row per `<tr>`, other content as `el.textContent` did (line breaks kept).
- Consumes: none.

- [ ] **Step 1: Write the failing check** `rubric.check.js` (vm-load `rubric.js` like `setup-flow-steps.check.js` does; test the pure function only):
  - `rubricBlocks("Rubric:\nCriteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)\nAccuracy | a | b | c | d\nTotal: 8 points")` deep-equals `[{line:"Rubric:"},{rows:[["Criteria","Excellent (4)","Good (3)","Fair (2)","Needs Improvement (1)"],["Accuracy","a","b","c","d"]]},{line:"Total: 8 points"}]`.
  - `markdown_rule_dropped`: `"A | B | C\n|---|---|---|\nx | y | z"` → one `{rows}` block of 2 rows.
  - A single ` | ` line and a 2-cell line stay `{line}`.
- [ ] **Step 2:** Run `node frontend/js/rubric.check.js` → fails (file missing).
- [ ] **Step 3:** Write `rubric.js` (pure function + the two DOM helpers; the DOM helpers are not run under node). CSS: `.lp-rubric` full-width, collapsed 1px borders in the existing border token, cell padding 6px 8px, `th` bold on the existing surface tint, cells editable when the slot is.
- [ ] **Step 4:** Replace field-slot `el.textContent = text` writes with `setSlotText(el, text)` and slot reads `el.textContent` with `slotText(el)` at the listed lines; let `sanitizeRichValueHtml` keep `TABLE, TBODY, TR, TH, TD` (rebuilt bare, no attributes); render `use` card text and the submissions/preview/read-only views through `setSlotText` (or a `div` filled by it).
- [ ] **Step 5:** Run `node frontend/js/rubric.check.js` → passes. Manual check on the local seeded server (`serve_seeded.py` pattern with `mimetypes.add_type("text/javascript", ".js")`): a plan whose evaluation holds the rubric text shows a table in the document view, the preview, Save as PDF print root, and Student Submissions review; editing a cell then saving keeps ` | ` rows in `field_values`.
- [ ] **Step 6:** Bump cache-busters; commit `feat(rubric): rubric rows show as a table everywhere, editable in the document`.

### Task 5: Guided chat backend — directions, then the complete part

**Files:**
- Modify: `backend/services/ai_service.py` (`_OWL_SYSTEM_INSTRUCTION` ~153, `owl_chat` ~1547, `_clean_owl_reply` ~1648), `backend/routes/generate_routes.py` (`owl_chat` route ~196)
- Test: `backend/test_owl_directions.py` (create; stub `ai_service._call` like `test_lesson_proper.py` does)

**Interfaces:**
- Consumes: `taxonomy_text()` (Task 2) for the objectives part's directions and content.
- Produces: `ai_service.owl_chat(context, field, prior_values, course_guide_text, history, message, course_guide_citation="", direction=None) -> {"reply": str, "choices": [...]}` where a choice is `{"type": "direction", "label": str, "text": str, "why": str}` | `{"type": "use", ...}` | `{"type": "ask", ...}`. Route `POST /api/generate/chat` accepts `direction: {"label": str, "text": str}` (each trimmed to 300 chars; anything else ignored).

- [ ] **Step 1: Write the failing test** with a stubbed `_call` that records the prompt and returns canned JSON:
  - `general_gives_two_directions`: no `direction`, message "Help me with this part"; stub returns 3 directions + 1 use; result has exactly 2 `direction` choices and no `use` (server enforces: directions kept ≤2, `use` dropped when no direction was chosen and the prompt was the "directions" prompt); the prompt sent contains `"exactly 2 directions"`.
  - `direction_gives_complete_part`: `direction={"label": "Introductory", "text": "recall and identify"}`; stub returns one `use` of 7,000 chars; result keeps it whole (cap 8,000) and the prompt contains `Introductory` and `"complete"`.
  - `specific_request_answered`: message "Give me the directions and questions for a game called Bit Hunt" with no direction; stub returns one complete `use`; result keeps it (the prompt tells the model a specific request gets the complete answer; the server only drops `use` when the model also returned directions).
  - `locked_direction_coaches`: locked field + direction; stub returns a `use`; result has no `use`.
  - Prompts include the already-written parts and the line about objectives taught and assessed.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Rewrite `_OWL_SYSTEM_INSTRUCTION`: short lead-in reply (content goes in cards); a general request → exactly 2 `direction` choices (label ≤6 words, text 1-2 sentences, why ≤25 words) + up to 2 `ask`; a chosen direction or a specific request → one `use` card with the complete part (spec §3 examples: objectives all 3; game: title, materials, complete directions, every question and answer; evaluation: full quiz + answer key and/or task + rubric rows) + 1-2 `ask`; everything fits the written parts. Add the direction to the task block when given. `_clean_owl_reply(data, max_text)` accepts `direction`; use-card cap 8,000 (lesson proper keeps its larger cap). Route passes `direction`.
- [ ] **Step 4:** Run `test_owl_directions.py`, `test_lesson_proper.py`, `test_references_coherence.py`, `test_generate_selection.py` → all OK.
- [ ] **Step 5:** Commit `feat(guided): Alan offers two directions, then writes the complete part`.

### Task 6: Guided chat frontend — direction chips and Copy

**Files:**
- Modify: `frontend/js/generator.js` (`addOwlMessage` ~417, `sendToOwl` ~548, `pickOwlChoice` ~590, `recordTurn` call ~576), `frontend/css/style.css`, `frontend/js/api.js` only if `Api.owlChat` filters the payload
- Test: manual on the local seeded server (no node harness exists for the chat DOM)

**Interfaces:**
- Consumes: Task 5 choice shapes; `setSlotText` (Task 4) for card text.
- Produces: `sendToOwl(text: string, extra: {direction?: {label, text}} = {})`.

- [ ] **Step 1:** Render `direction` choices as tappable chips (label bold, `text` beneath, `why` small), class `owl-choice owl-choice-direction`; tapping calls `sendToOwl(\`Go with: ${choice.label}\`, {direction: {label: choice.label, text: choice.text}})`. Old chips disable as today.
- [ ] **Step 2:** `use` cards get a **Copy** button (icon `copy`, label "Copy") that writes the card text to the clipboard (`navigator.clipboard.writeText`, toast "Copied"); it never touches the part. Card text renders through `setSlotText` so rubric rows show as a table.
- [ ] **Step 3:** `sendToOwl` sends `direction` when given; history keeps working as before.
- [ ] **Step 4:** Manual check on the local seeded server (no API key locally): in the launcher script only, monkeypatch `ai_service._call` to return Task 5's canned replies. Check that chips render, tapping one sends `direction` (network panel), the complete card shows with Copy and a rubric table, and a locked part shows no card. Nothing of the stub is committed.
- [ ] **Step 5:** Bump cache-busters; commit `feat(guided): direction chips and a Copy button on Alan's cards`.

### Task 7: Coherence check backend

**Files:**
- Modify: `backend/services/ai_service.py` (new `check_coherence`), `backend/routes/generate_routes.py` (new route)
- Test: `backend/test_coherence_check.py` (create; stubbed `_call`)

**Interfaces:**
- Consumes: `taxonomy_text()` (Task 2).
- Produces:
  - `ai_service.check_coherence(context: dict, fields, values: dict, mode: str) -> {"coherent": bool, "summary": str, "issues": [{"part_key", "part_label", "problem", "fix"}]}`; `mode` is `"full"` or `"step"`.
  - Route `POST /api/lesson-plans/coherence` (`@login_required @enrollment_required`), body = the generation payload (`format_id`, setup context, guides) + `field_values`, `mode`; returns `{"status": "ok", **result}`; 400 when `field_values` has no objectives and no assessment content (`"Write the objectives and the assessment first."`).

- [ ] **Step 1: Write the failing test:**
  - `issues_cleaned`: stub returns 3 issues, one with an unknown `part_key`; result has 2, each `part_label` filled from the format's field label.
  - `full_mode_complete_fix` / `step_mode_instruction`: the prompt for `mode="full"` contains `"complete corrected content"`; for `mode="step"` contains `"instruction"` and `"never write the content"`.
  - `locked_fix_is_instruction`: a locked field is named in the prompt as instruction-only.
  - `weekly_values_flattened`: a weekly value `["a", "b"]` with parts `["Monday", "Tuesday"]` appears in the prompt as `Monday: a` and `Tuesday: b`.
  - `coherent_plan`: stub returns `{"coherent": true, "issues": []}` → `coherent` true, `issues` `[]`.
  - The prompt lists the checks from spec §4 and includes `taxonomy_text()`.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement: build the plan text (label: value, weekly flattened), one `_call` with a coherence system prompt, clean the result (drop unknown keys, trim fields, `coherent = not issues`). Route uses `_build_context`, `_resolve_guides`, `grounding.competency_view(fmt.fields)`.
- [ ] **Step 4:** Run `test_coherence_check.py` → `coherence check OK`.
- [ ] **Step 5:** Commit `feat(coherence): check a plan's objectives, content and assessment line up`.

### Task 8: Coherence check frontend

**Files:**
- Modify: `frontend/generator.html` (button `#coherence-btn` "Check coherence" in the action row beside `#pdf-btn`; a modal `#coherence-overlay` built like `#preview-overlay`), `frontend/js/generator.js` (handler + bridge `G.checkCoherence()`), `frontend/js/guided-flow.js` (`review()` adds a "Check coherence" button above the parts list), `frontend/js/api.js` (`Api.checkCoherence(payload)`), `frontend/css/style.css`
- Test: manual on the local server with `check_coherence` stubbed

**Interfaces:**
- Consumes: Task 7 route; `setSlotText` (Task 4) for fixes.
- Produces: `window.Generator.checkCoherence()` (bridge used by `guided-flow.js`).

- [ ] **Step 1:** `Api.checkCoherence(payload)` POSTs to `/api/lesson-plans/coherence`. `checkCoherence()` sends `baseGenerationPayload()` + `field_values` + `mode` (`"step"` when Guided, else `"full"`), shows a loading state on the button, opens the modal: either "Everything lines up" + summary, or issues grouped by part label, each problem then the fix in a read-only box (rubric rows as a table); a Copy button only when `mode === "full"`. Errors show in the modal.
- [ ] **Step 2:** Button visible in the document view and on Guided's review screen; disabled with a hint when objectives or assessment are empty.
- [ ] **Step 3:** Manual check: both buttons open the modal with stubbed issues; Guided shows no Copy; Escape and the close button close it.
- [ ] **Step 4:** Bump cache-busters; commit `feat(coherence): Check coherence button in the document and Guided review`.

### Task 9: Regenerate backend — 5 points, server-decided, refunded on failure

**Files:**
- Modify: `backend/models/points.py` (`REGENERATE_COST = 5`; `Build.completed_at = db.Column(db.DateTime)`; `PointEvent.reason` comment adds `"regenerate" | "regenerate_refund"`), `backend/app.py` (add `completed_at` via the existing `_add_column` helper in a `_migrate_build_columns()` called at boot), `backend/routes/points_routes.py` (new functions), `backend/routes/generate_routes.py` (`generate_full_stream`, and `generate_full` the same way)
- Test: `backend/test_regenerate_points.py` (create; sqlite app like `test_teacher_download.py`; stub `ai_service.generate_full_streaming`)

**Interfaces:**
- Produces:
  - `points_routes.charge_regenerate(user, data) -> tuple[Response | None, int | None]` — `(None, None)` when free (teacher/admin, or the plan/run's first build not completed yet), `(None, event_id)` when 5 points were taken, `(402 response, None)` when short (`code: "no_points"`, message `f"Regenerating uses {REGENERATE_COST} points, and you have {n}. Ask your teacher for more points."`).
  - `points_routes.mark_build_completed(user_id, data) -> None` and `points_routes.refund_regenerate(event_id) -> None` (writes `+5`, `reason="regenerate_refund"`), both safe to call inside the stream.
  - A legacy paid plan without a build (created before `POINTS_STARTED_UTC`) counts as completed (charged).

- [ ] **Step 1: Write the failing test** (`test_regenerate_points.py`):
  - `first_build_free`: student with a paid build (`completed_at` None), points 40 → stream runs, points stay 40; after a `complete` event the build has `completed_at`.
  - `regenerate_charged`: same build now completed → points 35, a `PointEvent(reason="regenerate", delta=-5)`.
  - `short_points_refused`: points 3 → 402, `code == "no_points"`, points stay 3, generator never called.
  - `refund_on_failure`: stub raises mid-stream → points back to the starting value, a `regenerate_refund` event; and a `complete` event whose `values` leave every requested key empty → refunded too.
  - `teacher_never_charged`: teacher, any number of runs → no PointEvent rows.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement: routes call `charge_regenerate` after `require_paid_build`; inside `_stream()` call `mark_build_completed` on the `complete` event, and `refund_regenerate(event_id)` on exception or when no requested key came back answered (`ai_limits.is_answered`). Charge with a row lock or conditional `UPDATE users SET points = points - 5 WHERE id = :id AND points >= 5` (as `start_build` already does).
- [ ] **Step 4:** Run `test_regenerate_points.py` → `regenerate points OK`; rerun `test_teacher_download.py` and any test touching builds (`git grep -l "BUILD_COST\|/builds" backend/test_*.py`) → OK.
- [ ] **Step 5:** Commit `feat(points): regenerating a finished plan costs 5 points, refunded on failure`.

### Task 10: Regenerate frontend — pick parts, warn, 5 points

**Files:**
- Modify: `frontend/generator.html` (button `#regenerate-btn` "Regenerate" in the action row before `#save-btn`; modal `#regen-overlay`), `frontend/js/generator.js` (modal, `runGeneration(keys)` call, `pointsNote()` text, remove the "Regenerate full plan" relabel at ~3055 and the "writes it again for free" line at ~3793, toast offering Check coherence when a regenerate completes), `frontend/faq.html` (points answer: 30 for the first build, 5 per regenerate, Guided free), `frontend/css/style.css`
- Test: manual on the local server with `generate_full_streaming` stubbed

**Interfaces:**
- Consumes: Task 9 (402 `no_points` message from the stream route), `checkCoherence()` (Task 8), `runGeneration(includeKeys)` (existing).

- [ ] **Step 1:** Show `#regenerate-btn` only in the document view of a Building Proficiency plan (`flowFlags.mode === "full"`) that has content. The modal lists the format's fields as checkboxes, all unticked, plus "Select all"; locked and reflection fields disabled with "You write this part"; copy-only standards with no guide disabled with "Needs a Budget of Work or Curriculum Guide". Ticking the lesson proper part (`isLessonProper`) also ticks and disables the references part with "Updated too: the lesson is taught from these pages".
- [ ] **Step 2:** Warning line "The ticked parts will be replaced, including your edits." Confirm button "Regenerate N parts" + for students " (5 points)" and a points note "Regenerating uses 5 of your N points."; disabled when nothing is ticked. Confirm closes the modal and calls `runGeneration(ticked)`.
- [ ] **Step 3:** When the stream answers 402, the existing error path shows the server's message (verify `Api.generateFullStream` surfaces it; fix if it shows a generic error). On completion, update `currentUser.points` from the server if returned, and show a toast "Parts rewritten. Check coherence?" with a button calling `checkCoherence()`.
- [ ] **Step 4:** Manual check: tick two parts → only they change, others identical; lesson proper ticks references; a teacher sees no points text; a student with 3 points sees the 402 message.
- [ ] **Step 5:** Bump cache-busters; commit `feat(regenerate): pick the parts to rewrite, 5 points`.

### Task 11: Verify, deploy, push

**Files:** none new.

- [ ] **Step 1:** Run every touched self-check: `test_assessment_rubric`, `test_objective_taxonomy`, `test_owl_directions`, `test_coherence_check`, `test_regenerate_points`, `test_lesson_proper`, `test_references_coherence`, `test_generate_selection`, `test_grounding`, `test_doc_edits`, `test_teacher_download`; `node frontend/js/setup-flow-steps.check.js`, `node frontend/js/rubric.check.js` → all OK.
- [ ] **Step 2:** Run the impeccable detector once on the changed HTML/CSS/JS (`impeccable.cmd detect --json <files>`); fix real findings.
- [ ] **Step 3:** Deploy per memory `aligned-vps-deploy`: hash-check the server's copies of every changed file against `33b22c3` (`git archive` output, CRLF), back up code + DB, unpack `git archive HEAD <files>`, `chown www-data`, import check, restart `aligned.service`, check `is-active` and the journal for "Worker failed to boot" (Task 9 adds a column), fetch the changed files over HTTPS.
- [ ] **Step 4:** Live smoke test as a teacher-run script on the server (real model, ≤3 calls): one owl chat general request returns 2 directions; one coherence check returns JSON; no regenerate charge for a teacher.
- [ ] **Step 5:** Push the branch and fast-forward `master` on GitHub; update memory `aligned-vps-deploy` (live commit, backups) and `aligned-guided-no-autofill` (direction chips + Copy allowed, still no fill).
