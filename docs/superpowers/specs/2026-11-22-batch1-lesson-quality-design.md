# Batch 1: lesson-plan quality (objectives, assessment, Guided chat, coherence check, regenerate)

Date: 2026-11-22 · App: AlignED (https://align-ed.online) · Repo: C:\tle\rel-Aligned\aligned

## Intent

AlignED helps TUP Cavite student teachers (and their supervising teachers) write DepEd-style lesson
plans in two modes: **Building Proficiency** (Alan, the AI owl, writes the whole plan; 30 points per
plan) and **Guided** (the student writes each part themselves, Alan coaches in a chat; free).
Testers found the plans' parts drifting apart and Alan's Guided chat too narrow to be useful. This
batch makes the plan hang together (objectives → content → assessment), makes Guided coaching
useful without turning it into Building Proficiency, and lets a Building Proficiency plan be fixed
part by part.

The why behind Guided (user's words, paraphrased): if Guided only hands over complete output to
copy, it is the same as Building Proficiency; the student must analyse and choose.

## Goals

1. **Objectives** use the right taxonomy per domain: Cognitive = Revised Bloom's, Affective =
   Krathwohl's affective taxonomy, Psychomotor = Dave's psychomotor taxonomy.
2. **Assessment** follows the objectives: the setup lets the student let the objectives decide, or
   pick a quiz, a performance task, or both; a performance task's rubric is always a table.
3. **Guided chat**: Alan answers what the student actually asks, with complete content for the part,
   through a choose-a-direction-first flow.
4. **Coherence check**: a button that reviews a finished plan and lists each mismatch with its fix.
5. **Regenerate**: in Building Proficiency, rewrite only the parts the student ticks, for 5 points.

## Non-goals

- Batch 2 (gsfe-only sign-up with emailed code, admin activity logs, input validation everywhere).
- Any control in Guided that writes into a part for the student (no "Use this", no tap-to-fill).
- An "apply this fix" button for the coherence check.
- Changing the 30-point first build, or charging teachers anything.

## Anti-goals (a failure even if it works)

- Guided becoming copy-paste: Alan giving finished content before the student has chosen a
  direction for a general request.
- Regenerate touching a part that wasn't ticked, or replacing edits without warning.
- The coherence check silently changing the plan.
- A rubric shown anywhere as raw `a | b | c` text instead of a table.
- Invented curriculum statements (standards/competencies stay copied word for word from the guide).

## Constraints

- Production model: Mistral Large 4 via OpenRouter; `OPENROUTER_REASONING` is unset in prod, and the
  web search already retries without `reasoning` when refused (commit a0c53e1).
- Existing rules that stay: Alan is the chat's button in Guided (see memory aligned-owl-not-a-control);
  Guided never autofills; locked fields are coach-only; weekly fields answer one day at a time;
  objectives are exactly 3 (`_MIN_OBJECTIVES`), bulleted under the lead-in.
- No emoji icons; use icons.js SVGs; keep the app's existing theme/tokens.
- Tests are runnable self-check scripts in `backend/test_*.py` and `frontend/js/*.check.js`.
- Deploy: hash-check the server files against the last deployed commit, back up code + DB, unpack,
  restart `aligned.service`, verify (memory aligned-vps-deploy).

## Already drafted (uncommitted in worktree `teacher-download-submission`)

- `ai_service._assessment_directive`: four setup choices (objectives / quiz / task / both); rubric as
  ` | ` rows with header `Criteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)` and
  a `Total: N points` line; assessment lines may be 90 words (a rubric row) and up to 200 lines.
- `docx_service.pipe_rows_to_tables` in `_save`: two or more consecutive ` | ` rows (3+ cells)
  become a bordered Word table, header bold, in the body or inside a cell. Self-check
  `backend/test_assessment_rubric.py` passes.
- Setup step 2 (`setup-flow.js`, `setup-flow-steps.js` + check, `generator.js assessmentText`):
  "Based on my objectives (recommended)", "Multiple-choice quiz", "Performance task with a rubric",
  "Both"; quiz size 5/10/15/20 asked whenever a quiz is possible.

## Approaches (decided with the user)

| Piece | Considered | Picked | Why |
|---|---|---|---|
| Guided chat | A) prompt-only two steps · B) explicit step: a direction chip carries a flag the server reads | **B** | Same behaviour every time; doesn't depend on the model remembering the step |
| Coherence check | A) one AI review of the whole plan · B) fixed rules + AI | **A** | Rules only catch what the AI already catches; less code |
| Regenerate cost | A) server charges inside the regenerate request · B) pay first, then generate with a receipt | **A** | One request, can't be skipped from the browser |
| Rubric on screen | A) table only in read-only views · B) table everywhere incl. the editable document | **B** | The user asked for the rubric inside a table; a teacher editing it expects one |
| Objectives domains | A) always one per domain · B) only the domains the lesson really has | **B** (user's choice) | |

## Design

### 1. Objectives (all modes, incl. Alan's Guided cards and the coherence check)

Rewrite the objectives directive (`ai_service._field_directive`, objectives branch) so each objective
names its verb from the matching taxonomy and level, still exactly 3, still only the domains the
lesson really has (no forced psychomotor or affective), ordered lower to higher level:

- **Cognitive — Revised Bloom's (Anderson & Krathwohl, 2001):** Remember (define, list, identify,
  name, recall) · Understand (explain, describe, classify, summarize, compare) · Apply (use,
  demonstrate, solve, carry out, compute) · Analyze (differentiate, organize, examine, distinguish)
  · Evaluate (judge, critique, justify, assess) · Create (design, construct, produce, plan, compose).
- **Affective — Krathwohl (1964):** Receiving (listen attentively to, show awareness of) · Responding
  (participate in, comply with, answer, volunteer) · Valuing (value, show commitment to, justify)
  · Organization (organize, integrate, prioritize) · Characterization (act consistently with,
  display, practice).
- **Psychomotor — Dave (1970):** Imitation (copy, follow, replicate) · Manipulation (perform from
  instructions, execute, assemble) · Precision (perform accurately, calibrate, demonstrate with
  precision) · Articulation (combine, adapt, coordinate) · Naturalization (perform automatically,
  improvise, master).

The banned verbs stay (understand, know, learn, appreciate the importance of). Objectives text stays
plain (no domain labels printed in the plan). The taxonomy table lives in one constant so the
directive, Guided directions and the coherence check share it.

### 2. Assessment

As drafted (above), plus the domain mapping in the "based on the objectives" choice: cognitive →
multiple-choice items; psychomotor → performance task with rubric; affective → a criterion row in the
task's rubric when there is a task, otherwise one observation line ("Observed: …") after the quiz
(builder's call on wording). Rubric display:

- **Word export**: done for text (`pipe_rows_to_tables`). *Builder-check answer, my call*: export
  prefers `rich_field_values`, so `parse_rich_value` must also turn an HTML table into ` | ` rows;
  then a rubric edited on screen still reaches Word as a table.
- **Screen** (live document canvas, preview modal + Save as PDF, Student Submissions review, Guided
  review screen, Alan's chat card): one shared renderer turns 2+ consecutive ` | ` rows into an HTML
  `<table class="lp-rubric">` (header row `<th>`), other lines unchanged.
- **Editable document**: the table cells stay editable; one helper `slotText(el)` reads a slot back as
  text, writing a table as one ` | ` row per line. It replaces `el.textContent` in the four save paths
  in `generator.js` (`syncActiveStepValue`, `wireDocCanvasEditing`, `syncFieldFromEl`, and the input
  listener at ~1702 if it ever sees a slot), and `sanitizeRichValueHtml` allows table/tr/th/td.
- Guided part editor (the student's own box): the student may type ` | ` rows; the review screen and
  document show them as a table. No table-editing toolbar in this batch.

### 3. Guided chat with Alan: choose a direction, then the complete part

API `POST /api/generate/chat` (generate_routes → `ai_service.owl_chat`) gains an optional
`direction: {label, text}`.

- **General request, no direction** ("help me", "ideas", the part's first help): reply = one short
  line + exactly **2 direction choices**, new choice type `"direction"`: `label` (≤6 words, e.g.
  "Introductory: recall and identify"), `text` (what that direction focuses on, 1–2 sentences), `why`
  (≤25 words), plus up to 2 `"ask"` follow-ups. No finished content yet.
- **Direction chosen** (student taps a direction chip; the frontend sends `message: "Go with:
  <label>"` and `direction`): reply = one short line + **one `"use"` card with the complete part**
  written in that direction (e.g. objectives: all 3; motivation game: title, materials, complete
  directions, every question and answer; evaluation: full quiz with answer key and/or task + rubric
  table), plus 1–2 `"ask"` follow-ups. Card cap raised from 1,500 to 8,000 characters (lesson proper
  stays 6,000+; builder may unify).
- **Specific request** (the message already says what they want, e.g. "a game called Bit Hunt, give
  me the directions and questions"): skip directions, answer it completely as one `"use"` card. The
  prompt decides general vs specific; the explicit `direction` flag is the reliable path.
- Every card must fit what's already written: the objectives, the lesson proper, the assessment
  choice from setup, the previous/next topic. The prompt includes all written parts (it already does)
  and the coherence rule ("never test what the lesson didn't teach", "every objective taught and
  assessed").
- The reply's "two short sentences / 5 points" cap is loosened to "a short lead-in" — content goes in
  the card, not the reply.
- UI: a direction chip is tappable (it only sends the choice, like `ask` chips — allowed under the
  no-autofill rule). The complete card stays read-only and gets a **Copy** button (copies its text to
  the clipboard; it never writes into the part). Rubric rows in a card render as a table.
- Unchanged: locked parts (coach only: directions may be offered as questions to think about, but no
  `use` cards), weekly parts (one day per card), references part (the found-references card), lesson
  proper reads the student's references.

### 4. Coherence check

- **Endpoint** `POST /api/lesson-plans/coherence` (login required, enrolled student or teacher):
  body = `{format_id, field_values, setup context}` (the page's current values, so unsaved drafts
  work). One AI call with the whole plan, the setup (topic, competency, assessment choice), and the
  taxonomy table. Returns `{"status": "ok", "coherent": bool, "summary": "...", "issues": [{"part_key",
  "part_label", "problem", "fix"}]}`. Free (no points). Issue keys not in the format are dropped.
  The request says which mode the plan is in (`mode`: `full` or `step`). What `fix` holds
  (user's decision):
  - **Building Proficiency**: the complete corrected content for that part (e.g. the full task + rubric
    rows), ready to copy.
  - **Guided**: a specific instruction of what to change or add (e.g. "Add a performance task where
    learners design a flyer on kitchen safety, with a rubric on layout, accuracy and creativity"),
    never ready-made content; the student writes it.
  - **Locked parts** (any mode): always an instruction only.
- **Checks**: every objective taught in the lesson proper and assessed; assessment tests only what was
  taught; assessment type matches objective domains; objective verbs fit their taxonomy/domain;
  motivation/activities lead into the topic; assignment fits the next topic; competency ↔ objectives.
- **Where**: a "Check coherence" button on Guided's final review screen (`guided-flow.js review()`)
  and in the document view action row beside Save / Save as PDF / Export (`generator.html` ~365).
  Shown when the plan has content in its objectives and assessment parts; can be run again.
- **Result**: a modal listing issues grouped by part, each: problem, then the fix in a read-only box
  (Copy only on Building Proficiency's complete-content fixes); or "Everything lines up" with the
  summary. Nothing is written into the plan.
- After a Regenerate finishes, a toast offers "Check coherence".

### 5. Regenerate (Building Proficiency)

- **Button** "Regenerate" in the document view action row, only for plans Alan wrote in Building
  Proficiency (mode `full`) and only after the first build is paid (plan has `build_id`, or the
  teacher path).
- **Modal**: the format's parts as checkboxes, all unticked, "Select all"; locked parts and parts the
  setup can't write (copy-only standards with no guide) shown disabled with the reason; a warning
  line "The ticked parts will be replaced, including your edits."; button "Regenerate N parts (5
  points)" (teachers: no points text). Confirm runs `runGeneration(tickedKeys)` with `regenerate:
  true`.
- **Charge (server decides, not a browser flag)** — *builder-check answer, my call*: today a paid plan
  is rewritten free ("Regenerate full plan", `pointsNote()` "Alan writes it again for free"). From now
  on the server charges a student 5 points (`REGENERATE_COST = 5` beside `BUILD_COST`) for **any**
  Building Proficiency write on a plan/run whose first build already **finished** (new marker, e.g.
  `Build.completed_at` set when the first stream completes). A retry of a first build that failed
  before completing stays free. `PointEvent(reason="regenerate", delta=-5)`; 402 + "Regenerating uses
  5 points, and you have N" when short. Charged once per run, whatever the number of parts.
  Guided's "Generate these too" keeps its 30-point first build; after that it counts as a regenerate.
  The old full-plan regenerate is replaced by this button ("Select all" = whole plan). FAQ and
  `pointsNote()` text updated.
- **Refund** — *my call*: if the stream errors, or none of the ticked parts comes back filled, the 5
  points are returned (a `PointEvent(reason="regenerate_refund", delta=+5)` written in its own app
  context from inside the stream generator).
- **Writing**: `include_keys` = ticked parts; the other parts are passed as already-written context
  (existing behaviour), so new parts fit them.
- **References follow the lesson** — *my call*: ticking Lesson Proper also ticks References (shown
  ticked and locked in the modal with "updated too: the lesson is taught from these pages"), so the
  lesson never cites pages its References part doesn't list, and nothing unticked is touched.
- Points note in the modal: "Regenerating uses 5 of your N points." (same style as `pointsNote()`).

## Left to the builder

- Exact copy of buttons, modal titles, hints (plain, DepEd/TUP vocabulary).
- How the shared rubric renderer is shared between `generator.js`, `submissions.js`, `guided-flow.js`
  (e.g. a function in `api.js`, which all pages load).
- Prompt wording, as long as the behaviours above hold; JSON shapes may gain fields.
- Styling of the rubric table and the coherence modal within the existing tokens.
- Test granularity: at least one self-check per piece (objectives directive, owl direction flow with
  a stubbed model, coherence endpoint with a stubbed model, regenerate charge, slotText round-trip in a
  node check).
