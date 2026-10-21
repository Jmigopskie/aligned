# Create Lesson Plan with Alan: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the format page and the generator's Setup tab with one flow where big 3D Alan (right half) asks one question at a time (left half), grounds the recap and assignment in the previous and next topic, and only lets teachers upload formats.

**Architecture:** `generator.html` stays the single page and its URLs keep working. A new `#flow` section is shown for new plans; the existing document view (`#content`) is shown after the mode pick or when `?plan_id=` reopens a plan. The flow UI is an ES module (`js/setup-flow.js`) that drives `generator.js` through a small bridge (`window.Generator`), writing answers into the existing (now hidden) setup inputs so draft saving, the gate and generation keep working unchanged. Pure step logic lives in a classic script (`js/setup-flow-steps.js`) with a node self-check. The backend gains a role check on format writes, a student-scoped format list, and per-field grounding instructions in the prompt.

**Tech Stack:** Vanilla HTML/CSS/JS (no build), three.js 0.160.0 from jsDelivr via importmap, existing `js/alan3d.js`; Flask + SQLAlchemy backend; self-check scripts run with `python test_x.py` (backend) and `node frontend/js/x.check.js` (frontend).

**Spec:** `docs/superpowers/specs/2026-10-22-alan-guided-setup-design.md` (approved 2026-10-22). Read it before any task.

## Global Constraints

- Students cannot create, scan, edit, re-detect or delete formats; enforced on the server. Refusal message: "Only teachers can upload or change formats. Pick a built-in format or one from your teacher."
- A student's format choices: built-in formats plus formats owned by the teacher of any section they are a member of, shared or not. No other teachers' public formats.
- Step order (students, 12): format, school, name, coop, subject, duration, class, prevTopic, topic, nextTopic, guide, mode. Teachers: the same without `coop` (11).
- Duration quick picks 30 / 45 / 60 / 90 minutes, 45 preselected; "Other" accepts whole minutes 5–240.
- Required answers: format, name, subject, duration, class, topic, guide (and mode to finish). School, coop, prevTopic, nextTopic are optional; prevTopic offers "This is the first lesson", nextTopic offers "Not sure yet".
- Context keys sent to generation: `school`, `student_teacher`, `duration_minutes`, `previous_topic`, `next_topic` (plus existing `topic`, `teacher_name` = cooperating teacher, `subject`, class keys).
- Big Alan has no rotate/zoom controls; poses: format=`hi`, school/name/coop/class=`present`, subject=`point`, duration=`check`, prevTopic/topic/nextTopic=`think`, guide=`reading`, mode=`idea`, reading a file or generating=`loading`, generation done=`celebrate`.
- If three.js or WebGL fails, the matching PNG from `img/owl/alan-<pose>.png` (closest of idle, wave, point, think, idea, check, celebrate, loading) stands in; the flow must work without Alan.
- Stay in AlignED's theme tokens in `css/style.css`; Space Grotesk for headings. Use the design skills (impeccable, ui-ux-pro-max:ui-styling, taste-skill:soft-skill) before the UI tasks; soft, calm, roomy, one authored motion moment.
- Reduced motion: Alan still, step transitions instant.
- `generator.html?format_id=<id>` starts the flow at step 2 with that format; `generator.html?plan_id=<id>` opens the document view directly.

## Review Focus

1. **three.js CDN or WebGL unavailable** → the flow still renders and works with the PNG Alan. A static `import` of `alan3d.js` would kill the whole module, so Alan is loaded with dynamic `import()` inside `try`. Test: Task 6 step "Alan fails to load".
2. **Refresh in the middle of the flow** (say step 8) → the same step comes back with every answer. Test: Task 5 `runDraftKey` assertions + Task 6 step "Refresh keeps the step".
3. **A student calls `POST /api/formats` or `/api/formats/scan` directly** → 403 with the refusal message, nothing saved. Test: Task 1 `test_format_access.py`.
4. **A student in no class** → step 1 shows only built-ins plus Alan's line "Join your teacher's class to see the formats they uploaded." Test: Task 1 (list returns built-ins only) + Task 3 `formatGroups` assertion.
5. **Previous topic left as "This is the first lesson"** → the recap prompt says to open from prior knowledge instead of inventing a previous lesson. Test: Task 2 `test_grounding.py`.

---

### Task 1: Format access rules (backend)

**Files:**
- Modify: `backend/routes/auth_routes.py` (add `staff_required` beside `admin_required`)
- Modify: `backend/routes/format_routes.py` (`list_formats`, and decorate `scan_format`, `create_format`, `update_format`, `delete_format`, `edit_format_content`, `set_field_roles`, `edit_scanned_content`)
- Test: `backend/test_format_access.py` (new, same harness as `test_lesson_plan_drafts.py`: in-memory SQLite, `app.test_client()`, session `user_id`)

**Interfaces:**
- Produces: `staff_required(view_func)` decorator: 401 when signed out; 403 `{"status":"error","message":"Only teachers can upload or change formats. Pick a built-in format or one from your teacher."}` when `user.role == "student"`.
- Produces: `GET /api/formats` for a student returns formats where `is_builtin` OR `owner_id` in the teacher ids of the student's sections. For teachers and admins it is unchanged (own + public).

- [ ] **Step 1: Write the failing test** `backend/test_format_access.py` with `main()` that builds: teacher T (owns private format "T-private" and public "T-public"), other teacher O (owns public "O-public"), a built-in format (`is_builtin=True`), student S in a section of T, student N in no section. Assertions:
  - S: `GET /api/formats` names == {"T-private", "T-public", builtin name}; "O-public" absent.
  - N: list contains only the built-in.
  - T: list contains "T-private", "T-public", "O-public", built-in (unchanged).
  - S: `POST /api/formats` `{"name":"x","fields":[{"label":"A"}]}` → 403 and message equals the refusal text; `LessonPlanFormat.query.filter_by(name="x").count() == 0`.
  - S: `POST /api/formats/scan` (multipart, any `.docx` bytes) → 403.
  - S: `PATCH /api/formats/<T-private id>` and `DELETE` → 403.
  - A format S uploaded before the change ("S-old", `owner_id=S`): absent from S's list, but `GET /api/formats/<S-old id>` → 200 (old plans still open).
  - Print `format access OK`.
- [ ] **Step 2: Run it and see it fail.** `cd backend; python test_format_access.py` → AssertionError on the S list (O-public present) or on the 403.
- [ ] **Step 3: Implement** `staff_required` in `auth_routes.py`; replace `@login_required` with `@staff_required` on the seven write routes; branch `list_formats` on `user.role == "student"` using `SectionMembership` → `Section.teacher_id`.
- [ ] **Step 4: Run it and see it pass**, plus the neighbours: `python test_format_access.py; python test_builtins.py; python test_lesson_plan_drafts.py` → each prints its OK line.
- [ ] **Step 5: Commit** `feat(formats): only teachers upload; students see built-ins and their teachers' formats`.

### Task 2: Grounding the recap, assignment and timing (backend)

**Files:**
- Modify: `backend/services/ai_service.py` (`_schema_block`, `owl_chat`; new `_grounding_directive`)
- Test: `backend/test_grounding.py` (new; pure, no app, like `test_field_roles.py`)

**Interfaces:**
- Produces: `_grounding_directive(field, context: dict) -> str`. Reads `field.field_key`, `field.label`, `field.field_type`; context keys `topic`, `previous_topic`, `next_topic`, `duration_minutes`.
  - Recap keywords (lowercased key+label): `review`, `recap`, `previous lesson`, `reviewing previous`, `checking of assignment`, `pre-lesson`, `pre lesson`.
  - Assignment keywords: `assignment`, `agreement`, `extended learning`, `additional activities`, `enrichment`, `remediation`.
  - Procedure/timing keywords: `procedure`, `flow`, `lesson proper`, `learning experience`, `activity`.
- Changes: `_schema_block(fields, context=None)` appends `_grounding_directive(f, context or {})` after the existing directives; every call site passes the request `context`. `owl_chat` appends it after `_field_directive(field)`.
- Exact copy (spec):
  - Recap with previous topic: ` The class's previous lesson was: {previous_topic}. Base this recap on that lesson and connect it to today's topic, {topic}.`
  - Recap without: ` This is the first lesson on this topic; open with what learners already know from daily life or earlier grades instead of a recap of a previous lesson.`
  - Assignment with next topic: ` The next lesson is: {next_topic}. Write the assignment so it prepares learners for that next lesson while building on today's topic, {topic}.`
  - Assignment without: ` Base the assignment on today's topic.`
  - Timing (procedure fields, when `duration_minutes` set): ` The whole discussion lasts {duration_minutes} minutes. Where the procedure gives times, they must add up to that.`
  - Weekly fields (`field_type == "weekly"`) add: recap ` Only day 1 recaps the previous lesson; each later day recaps the day before it.`; assignment ` Only the last day's assignment prepares for the next lesson; earlier days lead into the following day.`; timing reads `{duration_minutes} minutes per session`.

- [ ] **Step 1: Write the failing test** `backend/test_grounding.py` with a `Field(field_key, label, field_type="text")` stand-in. Assertions:
  - `"Review of the Previous Lesson"` + `{"topic":"Cell formulas","previous_topic":"Basic formatting"}` → contains `previous lesson was: Basic formatting` and `today's topic, Cell formulas`.
  - Same field, `previous_topic` "" → contains `This is the first lesson on this topic` and not `previous lesson was`.
  - `"Pre-Lesson"` (weekly) with previous topic → contains `Only day 1 recaps`.
  - `"Assignment"` + `next_topic:"Charts"` → contains `The next lesson is: Charts`.
  - `"Assignment"`, no next topic → equals ` Base the assignment on today's topic.`
  - `"Extended Learning Opportunities"` (weekly) + next topic → contains `Only the last day's assignment`.
  - `"Lesson Proper"` + `duration_minutes: 45` → contains `lasts 45 minutes`.
  - `"Materials"` → `""`.
  - `_schema_block([review_field], {"previous_topic":"X","topic":"Y"})` contains `previous lesson was: X`.
  - Print `grounding OK`.
- [ ] **Step 2: Run it and see it fail.** `cd backend; python test_grounding.py` → ImportError/AttributeError on `_grounding_directive`.
- [ ] **Step 3: Implement** `_grounding_directive` and thread `context` through `_schema_block`'s three call sites (gap fill, full, streaming chunk) and `owl_chat`. A field can match both recap and timing; append both.
- [ ] **Step 4: Run** `python test_grounding.py; python test_generate_selection.py; python test_weekly_fields.py` → all OK.
- [ ] **Step 5: Commit** `feat(ai): ground recap and assignment in previous/next topic, time the procedure`.

### Task 3: Flow step logic (frontend, pure)

**Files:**
- Create: `frontend/js/setup-flow-steps.js` (classic script, no DOM; top-level functions become globals)
- Test: `frontend/js/setup-flow-steps.check.js` (node, `vm` pattern of `doc-toolbar.check.js`)

**Interfaces (all produced; used by Tasks 5–8):**
- `FLOW_STEP_IDS`: `["format","school","name","coop","subject","duration","class","prevTopic","topic","nextTopic","guide","mode"]`
- `flowSteps(role: string) -> string[]`: the ids for that role (`teacher` drops `coop`).
- `FLOW_POSES`: object step id → pose key (values from Global Constraints).
- `isStepAnswered(stepId: string, answers: object) -> boolean`. `answers` shape: `{formatId, school, studentTeacher, coop, subject, durationMinutes, levelType ("k12"|"college"), grade, program, year, section, previousTopic, firstLesson (bool), topic, nextTopic, nextUnsure (bool), courseGuideId, mode ("full"|"step")}`. Optional steps always return true. `duration` requires an integer 5–240. `class` requires `grade` for k12, or `program` and `year` for college.
- `prefillFieldValues(fields: {field_key,label}[], answers, current: object) -> object`: label match (case-insensitive, trimmed) — `school`→answers.school; `student teacher`, `teacher`, `name of teacher`, `name of teachers`→answers.studentTeacher; `learning area`, `learning area(s)`→answers.subject; `grade level`, `grade level & section`→class label (`"Grade 7 · Section A"`; college `"BSIT · 2nd Year · A"`). Never overwrites a non-empty `current[field_key]`; returns only the keys it fills.
- `formatGroups(formats: object[], user: {id, role}) -> {builtin: object[], teacher: object[], mine: object[]}`: built-in by `is_builtin`; for a student every non-built-in goes to `teacher`; for a teacher non-built-ins they own go to `mine` and others are dropped.
- `rememberKey(userId) -> string`: `"alignedFlowMemory:v1:" + userId`. Remembered keys: `school`, `studentTeacher`, `coop`.
- `runDraftKey(runId) -> string`: `"alignedDraft:v2:run:" + runId`.

- [ ] **Step 1: Write the failing check** asserting: student steps length 12 and teacher 11 without `"coop"`; `isStepAnswered("duration", {durationMinutes: 45})` true, `4` false, `241` false, `"45"` false; `isStepAnswered("class", {levelType:"college", program:"BSIT"})` false; `isStepAnswered("prevTopic", {})` true; `prefillFieldValues` on DLP-like labels `["School","Student Teacher","Learning Area","Grade Level"]` fills all four, and with `current.school = "Kept"` leaves school out; `formatGroups` for a student with one built-in and two others gives `{builtin:1, teacher:2, mine:0}` and for a student with only a built-in gives `teacher:0`; `runDraftKey("abc") === "alignedDraft:v2:run:abc"`. Print `flow steps OK`.
- [ ] **Step 2: Run** `node frontend/js/setup-flow-steps.check.js` → fails (file missing).
- [ ] **Step 3: Implement** `setup-flow-steps.js`.
- [ ] **Step 4: Run** the check → `flow steps OK`; also `node frontend/js/doc-toolbar.check.js` still passes.
- [ ] **Step 5: Commit** `feat(flow): step order, answer rules, prefill and format grouping`.

### Task 4: Generator bridge and new setup data

**Files:**
- Modify: `frontend/generator.html` (hidden inputs; remove `#gen-tabs` and the Setup tab's visible chrome; add `#flow` container; load `setup-flow-steps.js` before `generator.js`)
- Modify: `frontend/js/generator.js` (`init`, `setupContext`, setup-apply around line 2015, `getAdvancedContext`, `baseGenerationPayload`, `draftKey`, `goToTab`, `updateGate`)

**Interfaces:**
- Consumes: Task 3 `runDraftKey`, `prefillFieldValues`.
- New hidden inputs in the old setup panel (kept as the data store, panel stays `hidden`): `#ctx-school`, `#ctx-student-teacher`, `#ctx-duration`, `#ctx-prev-topic`, `#ctx-next-topic`. `#ctx-teacher-name` now means the cooperating teacher only (stop prefilling it with `user.full_name` in `init`).
- `setupContext().setup` gains `school, studentTeacher, durationMinutes, previousTopic, nextTopic, runId`; restoring applies them back.
- `getAdvancedContext()` gains `school`, `student_teacher`, `duration_minutes`, `previous_topic`, `next_topic`.
- `draftKey()`: `?plan_id=` keeps today's per-plan key; otherwise `runDraftKey(currentRunId)`.
- Produces `window.Generator` (assigned at the top level of `generator.js`):
  - `ready: Promise<{user}>` resolves after auth.
  - `loadFormat(formatId) -> Promise<format>`: today's body of `init` from `Api.getFormat` through `initLiveDocView()`, without showing `#content`.
  - `getAnswers() -> answers` / `setAnswers(partial)`: read/write the inputs, fire `input`/`change` so `saveDraft` and `updateGate` run.
  - `searchCourseGuides() -> Promise<guide[]>`, `selectCourseGuide(guide)`, `uploadCourseGuide(file) -> Promise<guide>`: wrap the existing picker code (lines ~883–1000).
  - `applyPrefill()`: writes `prefillFieldValues(fmt.fields, getAnswers(), fieldValues)` into `fieldValues` and repaints.
  - `mountReview(container: HTMLElement)`: renders the existing field-review list (`renderReviewList()` markup, the "Generate all" / "Keep all static" bulk links and the hint) into `container` instead of the popup; the popup itself is no longer opened.
  - `startFull()`: selects mode `full`, applies the choices from the mounted review list (same logic as `#gen-review-confirm`), shows `#content`, and starts full generation.
  - `startGuided()`: selects mode `step`, shows `#content`, starts Guided as the mode switch does today.
  - `showDocument()` / `hideDocument()`.
  - `unfinishedRun() -> {runId, topic, formatName} | null` and `newRun() -> runId`.
  - `generationEvents`: an `EventTarget` firing `start`, `done`, `error` around full generation (for Alan's poses).
- `init()`: with `?plan_id=` behaves as today and calls `showDocument()`; otherwise it resolves `ready` and leaves the page to the flow (no "No format selected" error).

- [ ] **Step 1: Move** `init`'s format-loading body into `Generator.loadFormat`, keep `init`'s auth and plan_id branch, add the hidden inputs and the payload/context keys.
- [ ] **Step 2: Verify plan_id path unchanged.** Serve `frontend/` (`python -m http.server` with `.js` as `text/javascript`, backend running) and open a saved plan with `generator.html?plan_id=<id>` → document view shows as before, no console errors.
- [ ] **Step 3: Verify the bridge** in the browser console on `generator.html`: `await Generator.ready; await Generator.loadFormat(<builtin id>); Generator.setAnswers({topic:"Cell formulas", previousTopic:"Formatting"}); Generator.getAnswers().previousTopic === "Formatting"`; reload → `getAnswers()` still has both (draft per run).
- [ ] **Step 4: Run** `node frontend/js/setup-flow-steps.check.js` and the backend checks from Tasks 1–2 → OK.
- [ ] **Step 5: Commit** `refactor(generator): expose a bridge for the setup flow, add new setup answers`.

### Task 5: Flow shell, navigation and big Alan

**Files:**
- Create: `frontend/js/setup-flow.js` (ES module)
- Modify: `frontend/generator.html` (`#flow` markup, importmap for three 0.160.0, `<script type="module" src="js/setup-flow.js?v=...">`)
- Modify: `frontend/css/style.css` (new `.flow-*` block)

**Interfaces:**
- Consumes: Task 3 (`flowSteps`, `FLOW_POSES`, `isStepAnswered`, `rememberKey`), Task 4 (`window.Generator`).
- `#flow` structure: `.flow` (two columns) → `.flow-ask` (progress bar `.flow-progress`, "Step N of M" `.flow-count`, question `h1.flow-question`, help `p.flow-help`, answer area `.flow-answer`, actions Back / Next) and `.flow-stage` (canvas host + `.flow-say` speech line + fallback `<img>`).
- `setup-flow.js` exports nothing; internal `renderStep(stepId)`, `go(delta)`.
- Alan: `const { createAlan, POSES } = await import("./alan3d.js?v=2026-10-22a")` inside `try`; on failure keep the `<img>` and swap its `src` per pose.

- [ ] **Step 1: Load the design skills** (impeccable, ui-ux-pro-max:ui-styling, taste-skill:soft-skill) and settle the flow's type scale, spacing and the single step-transition moment within the Global Constraints.
- [ ] **Step 2: Build the shell and steps 2–10** (school, name, coop, subject, duration, class, prevTopic, topic, nextTopic) with Back/Next, Enter to submit, Next disabled until `isStepAnswered`, the 45-minute preselect, "This is the first lesson" / "Not sure yet", remembered school/name/coop from `localStorage[rememberKey(user.id)]` (wrapped in try/catch; written when a step is passed), the name step defaulting to `user.full_name` when nothing is remembered, and a pose + speech line per step.
- [ ] **Step 3: Check in the browser** at 1600×1000 and 390×844: one question visible at a time, Alan fills most of the right half (desktop) or a top band about a third high (phone), no horizontal scroll, keyboard focus visible on every control.
- [ ] **Step 4: Refresh keeps the step:** answer through step 8, reload → step 8 with all answers.
- [ ] **Step 5: Alan fails to load:** block `cdn.jsdelivr.net` in the browser's network tools and reload → PNG Alan, flow fully usable, no uncaught errors.
- [ ] **Step 6: Commit** `feat(flow): one-question-at-a-time setup with big Alan`.

### Task 6: Step 1 — formats, teacher upload, continue or start new

**Files:**
- Modify: `frontend/js/setup-flow.js`, `frontend/css/style.css`

**Interfaces:**
- Consumes: Task 3 `formatGroups`; Task 4 `Generator.loadFormat`, `unfinishedRun`, `newRun`; `Api.listFormats`, `Api.scanFormat(file) -> {source_temp_token, source_filename, scan_error}`, `Api.createFormat({name, is_public, source_temp_token, source_filename}) -> {format}`.

- [ ] **Step 1: Unfinished run first:** when `Generator.unfinishedRun()` returns one, step 1 shows "Continue where you left off" (its topic and format) and "Start a new plan" before the format cards.
- [ ] **Step 2: Format cards** grouped by `formatGroups`: students see "Built-in" and "From your teacher" (or Alan's "Join your teacher's class to see the formats they uploaded." when empty); teachers see "Built-in", "Uploaded by you" and the "Upload my school's format" tile. Picking a card calls `Generator.loadFormat` (Alan `loading` while it runs) then goes to step 2. `?format_id=` skips step 1.
- [ ] **Step 3: Teacher upload sub-step:** drop/browse `.docx/.dotx/.pdf` → `Api.scanFormat` (Alan `loading`, line "I'm reading your format…"); show `scan_error` text if present; name field prefilled from the file name without extension; "Share with other teachers" off by default; Save → `Api.createFormat` → select it → step 2.
- [ ] **Step 4: Check** as a student (in a class, and in none) and as a teacher: the right groups appear; a student never sees the upload tile.
- [ ] **Step 5: Commit** `feat(flow): format step with teacher upload and resume`.

### Task 7: Course guide, mode, generation wait, lesson details

**Files:**
- Modify: `frontend/js/setup-flow.js`, `frontend/js/generator.js` (Lesson details button in the document view), `frontend/generator.html`, `frontend/css/style.css`

**Interfaces:**
- Consumes: Task 4 `searchCourseGuides`, `selectCourseGuide`, `uploadCourseGuide`, `applyPrefill`, `startFull`, `startGuided`, `generationEvents`, `showDocument`, `hideDocument`.

- [ ] **Step 1: Guide step:** on entry run `searchCourseGuides()` for the chosen subject; list results as cards (keep the "Official DepEd" badge); "Upload my own" uses `uploadCourseGuide`; Next requires a selected guide.
- [ ] **Step 2: Mode step:** two large choices, "Building Proficiency" ("Alan writes the whole plan; you review and edit it.") and "Guided" ("You write each part with Alan helping beside you."). Both call `applyPrefill()` first. Guided → `startGuided()`. Building Proficiency → one more flow screen, "Which parts should I write?", whose answer area is filled by `Generator.mountReview(answerArea)` (everything Alan normally writes ticked; lesson title and session number unticked); its Next button reads "Write my plan" and calls `startFull()`.
- [ ] **Step 3: Generation wait:** on `generationEvents` `start` show the flow layout with Alan `loading` and the existing progress list on the left; on `done` Alan `celebrate` for about a second, then `showDocument()`; on `error` show the message with "Try again".
- [ ] **Step 4: Lesson details:** a "Lesson details" button in the document view (where the tabs were) calls `hideDocument()` and opens a summary screen in the flow layout listing every answer; clicking one jumps to that step; "Back to my plan" calls `showDocument()`. Works for `?plan_id=` too.
- [ ] **Step 5: Check end to end** with a built-in DLP: answers prefill School / Student Teacher / Learning Area / Grade Level; Building Proficiency's generated "Review of the Previous Lesson" mentions the previous topic and "Assignment" points at the next topic.
- [ ] **Step 6: Commit** `feat(flow): course guide, mode pick, generation wait and lesson details`.

### Task 8: Links, roles and the old pages

**Files:**
- Modify: `frontend/js/icons.js` (nav: "Create Lesson Plan" → `generator.html`; add teacher-only `{ key: "formats", href: "lesson-plan.html", icon: Icons.files, label: "Formats", role: "teacher" }`)
- Modify: `frontend/dashboard.html:69`, `frontend/lesson-plan-list.html:65`, `frontend/js/dashboard.js:82`, `frontend/js/lesson-plan-list.js:100` (links → `generator.html`)
- Modify: `frontend/lesson-plan.html` + `frontend/js/lesson-plan.js` (title "Formats", students redirected to `generator.html`; "Use" on a card opens `generator.html?format_id=`)
- Modify: `frontend/js/format-builder.js` (students redirected to `generator.html`), `frontend/js/owl-tour.js` (student track no longer points at `#new-format-btn`), `frontend/js/generator.js` back link

- [ ] **Step 1: Update** the links and the nav entry; `renderSidebarNav("lesson-plan")` on the generator still highlights Create Lesson Plan.
- [ ] **Step 2: Check** as a student: sidebar has no Formats; opening `lesson-plan.html` or `format-builder.html` lands on the flow. As a teacher: Formats lists their formats with edit/delete; New format still works.
- [ ] **Step 3: Run** all checks: `node frontend/js/setup-flow-steps.check.js`, `node frontend/js/doc-toolbar.check.js`, and in `backend/` every `python test_*.py` → all OK.
- [ ] **Step 4: Commit** `feat(nav): Create Lesson Plan opens the flow; Formats is teacher-only`.

### Task 9: Design pass and final verification

**Files:** whatever the findings touch.

- [ ] **Step 1: Run** `impeccable detect --json frontend/generator.html` and fix real findings (triage shared-CSS findings as in the 3D viewer).
- [ ] **Step 2: Look** at every step at 1600×1000, 1366×768 and 390×844, light only (the app has no dark theme); fix overflow, contrast below 4.5:1, and anything that reads as a form wall.
- [ ] **Step 3: Reduced motion** (emulate `prefers-reduced-motion: reduce`): Alan still, transitions instant.
- [ ] **Step 4: Commit** `polish(flow): design pass`.
