# Create Lesson Plan with Alan: one question at a time

Date: 2026-10-22
Status: design, awaiting approval

## Why

The current way to start a lesson plan feels overwhelming and hard on the eyes. A student teacher has to work through two pages before anything is written:

1. **Create Lesson Plan** (`lesson-plan.html`): a grid of format cards in three groups (Ready-to-use, My formats, Shared by other teachers) plus a New format button.
2. **Generator** (`generator.html`), tab 1 **Setup**: one long form (cooperating teacher, subject, topic, K-12 or college, grade or program and year, section) followed by a course-guide picker. Tab 2 **Generate & review**: a Building Proficiency / Guided switch, a "Which fields should Alan write?" popup, then the live document with Save / Preview / Export / Submit.

The redesign replaces the format page and the Setup tab with **one calm flow where Alan asks one question at a time**. The big 3D Alan (`frontend/js/alan3d.js`, built 2026-10-22) stands on the right half of the screen; the question sits on the left half.

There is a second reason, and it matters as much as the look. Today the recap of the past lesson ("Review of the Previous Lesson", "Reviewing previous lesson or presenting the new lesson", "Review") and the assignment ("Assignment", "Extended Learning Opportunities", "Additional activities…") are written blind: Alan never learns what the class did before or what comes next. In the new flow **Alan asks for the previous topic and the next topic**, so those parts are grounded in the real sequence of lessons and line up with it.

## Goals

- One question per screen, with a clear next step and a way back. Nothing else competes for attention.
- Big 3D Alan on the right half for the whole flow, posed to match what he's asking.
- Alan asks for the previous topic and the next topic, and the generated recap and assignment are built on them.
- Answers the student gives once (school, their name, cooperating teacher) go straight into the matching blanks of the chosen format, so they don't type them again in the document.
- The flow ends with the student choosing **Building Proficiency** (Alan writes the plan) or **Guided** (field by field with Alan's help).

## Non-goals (for now)

- Redesigning the live document editor, toolbar, preview, export or submit. After the mode pick they work as today. Only colours and spacing are touched where the flow hands over to them.
- Changing how formats are detected from uploaded files, or the format tidy-up editor itself.
- New AI models or a new generation pipeline. Generation uses the existing `/api/generate/*` routes.

## Anti-goals (what would make this a failure even if it works)

- Bringing the old wall of fields back in a new coat, for example several questions on one screen, or a sidebar of every answer.
- Alan as decoration that slows people down: long animations before a question can be answered, or speech that has to be clicked through.
- A recap or assignment that ignores the previous or next topic after the student typed them.
- Losing answers: going Back, refreshing, or leaving and returning must not wipe what was already answered.

## The flow

Twelve steps. Each is one screen: question on the left, Alan on the right with a short line above him.

| # | Alan asks | How it's answered | Notes |
|---|-----------|-------------------|-------|
| 1 | Which lesson plan format does your school use? | Pick one card | Students see two groups: **Built-in** (4A's, DLP, ILAW, PAL3, SNHS DLP) and **From your teacher** (formats uploaded by the teacher of any class the student has joined). Students cannot upload. Teachers see Built-in, **Uploaded by you**, and an **Upload my school's format** tile. See "Who can upload" below. Alan waves and introduces himself here. |
| 2 | What school are you teaching in? | Text | Remembered for next time |
| 3 | What's your name? | Text | The student teacher. Remembered; prefilled from the account's full name the first time |
| 4 | Who is your cooperating teacher? | Text | Remembered |
| 5 | What subject is this for? | Pick one | The six existing TLE subjects (ICT, CP, AFA, HE, IA, Electrical) |
| 6 | How long is the discussion? | Quick picks 30 / 45 / 60 / 90 minutes, plus "Other" (number of minutes) | **45 is preselected**; most discussions are 45 minutes |
| 7 | Which class is this for? | K-12: grade (4–12) + section. College: program + year + section | Same K-12/College switch as today, shown as two choices first |
| 8 | What did your class learn last meeting? | Text, or **This is the first lesson** | Grounds the recap |
| 9 | What's today's topic? | Text | Same as today's "Specific topic" |
| 10 | What comes next after this lesson? | Text, or **Not sure yet** | Grounds the assignment |
| 11 | Which curriculum or course guide should I follow? | Search the shared library, or upload | Same behaviour as today's course-guide picker, laid out as one step |
| 12 | How do you want to write it? | **Building Proficiency** or **Guided** | Short line under each saying what it means |

Each step has **Back** and **Next** (Next is disabled until a required answer is given; Enter submits a text answer). A thin progress bar and "Step N of 12" sit above the question. Required: format, name, subject, duration, class, today's topic, course guide. School, cooperating teacher, previous topic and next topic are encouraged. If the student can't answer them, they can move on using the "first lesson" / "not sure yet" choices or by leaving the box blank.

### Who can upload (the user's rule, 2026-10-22)

**Students cannot upload their own format.** A student picks from the built-in formats and the formats their teacher uploaded. Only teachers upload.

- **What a student sees:** Built-in, plus **From your teacher**: every format owned by the teacher of a section the student is a member of (`section_memberships` → `sections.teacher_id`). This applies whether or not the teacher ticked "share with other teachers"; joining the class is what grants access. A student in no class sees only Built-in, with a line from Alan: "Join your teacher's class to see the formats they uploaded."
- **Enforced on the server, not just hidden:** creating, uploading, scanning, editing or deleting a format is refused for student accounts (`format_routes.py`: create, scan/upload, update, delete, field-roles, re-detect). `list_formats` for a student returns built-in formats plus their teachers' formats. `format-builder.html` sends a student back to the flow.
- **Formats students uploaded before this change** are no longer offered in step 1 for new plans. Plans already made with them still open, edit and export.
- **Formats teachers shared publicly** are not shown to students of other teachers; a student sees only their own teacher's formats.

**Teacher upload, inside step 1.** Choosing **Upload my school's format** opens a short sub-step, still with Alan on the right:

1. Drop or browse a blank `.docx`, `.dotx` or `.pdf`. Alan says he's reading it (loading pose) while the existing upload and scan endpoint runs.
2. Name it (prefilled from the file name) and choose whether to share it with other teachers (off by default). Students in the teacher's classes see it either way.
3. It is saved through the existing create-format API, selected, and the flow continues to step 2.

The document tidy-up editor (`format-builder.html`) is **not** part of the flow. The old **Create Lesson Plan** format page (`lesson-plan.html`) becomes a teacher-only **Formats** page for editing, tidying, sharing and deleting their formats; students never see it.

### After step 12

- **Building Proficiency:** the existing "Which fields should Alan write?" choice follows as one more screen in the same layout (default: everything Alan normally writes is ticked; the student's own fields such as lesson title stay unticked, as today). Then generation starts. While it runs, big Alan shows his loading pose on the right and the existing progress list sits on the left. When it finishes, the page switches to the existing document view.
- **Guided:** the page switches straight to the existing Guided document view with the Ask Alan chat, as today.

The big-Alan split is for the question flow (and the generation wait). The document view keeps today's layout, where Alan is the chat panel, because the document needs the width.

### Changing an answer later

The document view gets a **Lesson details** button (where the Setup tab used to be). It opens a summary screen in the flow layout listing every answer. Clicking an answer jumps to that step, and **Back to my plan** returns to the document. Changed answers apply to the next generation or Guided suggestion; nothing already written is rewritten automatically. The same button is there when a saved plan is reopened with `?plan_id=`.

### Unfinished plans

**Create Lesson Plan** starts a new run. If the student has an unfinished run (answers given but no plan generated yet), step 1 first offers **Continue where you left off** (showing its topic and format) or **Start a new plan**. Picking a format in step 1 of a new run never silently restores an older draft of the same format. The browser draft key becomes per run instead of per format, and old drafts stay in the List of Lesson Plans as today.

### Teacher accounts

Teachers (non-admin, non-student) use the same flow with two changes. Step 3 asks "What's your name?" and fills the same "Teacher" blanks. Step 4 (cooperating teacher) is skipped, so the flow has 11 steps for them.

## Grounding the recap and the assignment

New answers travel with the rest of the setup:

- `previous_topic` (empty string when "This is the first lesson")
- `next_topic` (empty string when "Not sure yet")
- `duration_minutes` (number)
- `school`, `student_teacher` (plus the existing `teacher_name` for the cooperating teacher)

They go into the generation request's `context` (`getAdvancedContext()` in `generator.js`) and are saved in `setup_context.setup` so a reopened draft keeps them. The backend already turns every `context` key into a "key: value" line in the prompt (`_context_block` in `backend/services/ai_service.py`), so the AI sees them with no route changes.

That alone is not enough, so add explicit instructions when a field is written:

- **Recap fields** (label contains review, recap, previous lesson, "reviewing previous lesson", checking of assignment): "The class's previous lesson was: {previous_topic}. Base this recap on that lesson and connect it to today's topic, {topic}." If `previous_topic` is empty: "This is the first lesson on this topic; open with what learners already know from daily life or earlier grades instead of a recap of a previous lesson."
- **Assignment fields** (label contains assignment, agreement, extended learning, additional activities, enrichment, remediation): "The next lesson is: {next_topic}. Write the assignment so it prepares learners for that next lesson while building on today's topic, {topic}." If `next_topic` is empty: "Base the assignment on today's topic."
- **Timing:** "The whole discussion lasts {duration_minutes} minutes. Where the procedure gives times, they must add up to that."

Keyword lists: the recap list also includes **Pre-Lesson** (ILAW, PAL3), and the assignment list includes **Extended Learning Opportunities** (ILAW, PAL3).

**Weekly formats (ILAW's day columns):** `duration_minutes` is per session (per day). `previous_topic` grounds the recap on **day 1** only; each later day recaps the day before it. `next_topic` grounds the assignment on the **last day** only; earlier days' assignments lead into the following day.

The same instructions apply in Guided mode, when Alan suggests text for one of those fields in the chat.

## Prefilling the format's own blanks

When a format is chosen and the plan starts, fill the format's fields from the answers by matching labels (case-insensitive):

- **School** → field labelled "School".
- **Student teacher's name** → "Student Teacher", "Teacher", "Name of Teacher", "Name of Teachers".
- **Subject** → "Learning Area", "Learning Area(s)" (only when empty).
- **Grade and section** → "Grade Level", "Grade Level & Section".

The student can still change any of these in the document. Fields that match nothing (date, quarter, teaching time…) stay blank for the student, as today.

## Remembering answers

School, the student's name and the cooperating teacher are remembered per signed-in user in browser storage (keyed by user id). On the next plan these steps come up already filled, and the student just confirms with Next. A draft in progress keeps all its answers through the existing draft save (`setup_context`), so Back, refresh and leave-and-return don't lose anything.

## Layout and feel

- Desktop: two halves. **Left:** the question, one at a time, vertically centred, comfortable measure. **Right:** big 3D Alan on the soft green stage from `alan-3d.html`, filling most of the height, with a short speech line above him. Alan has no rotate or zoom controls; he moves on his own (see memory: big fixed camera, self-animating).
- **Poses:** Saying hi on step 1; Thinking on the topic questions (8–10); Reading on the course guide; Idea on the mode pick; Loading while a file is read or the plan is written; Celebrating when generation finishes. Other steps use Idle or Presenting.
- Phones: Alan becomes a band across the top (roughly a third of the height) with his line beside or under him, and the question below. One question per screen still.
- Stays in AlignED's existing theme: the tokens in `css/style.css` (greens, Space Grotesk headings, system body font), the existing topbar and sidebar. The design direction is soft and premium (taste-skill soft-skill), supervised with impeccable; the step screens should feel calm, roomy and quiet, not like a form.
- Reduced motion: Alan holds still and the step transitions are instant.
- If WebGL or the three.js CDN fails, the matching 2D PNG pose from `img/owl/` stands in.

## Constraints

- Vanilla HTML/CSS/JS like the rest of `frontend/`; no build step, no framework. three.js stays on the pinned CDN version already used by `alan-3d.html`.
- Backend is the existing Flask app. Changes: prompt instructions, accepting the new context keys, refusing format writes from student accounts, and listing a student's teachers' formats.
- The sidebar's **Create Lesson Plan** link opens step 1 of the flow. Reopening a saved plan (`?plan_id=`) goes straight to the document view as today.
- Deployment follows the AlignED VPS routine (the VPS can be ahead of local; diff and back up first).

## Calls I made (check these)

1. "The teacher's upload" means formats owned by the teacher of any class the student joined, shared or not. Public formats from other teachers are not shown to students. A student in no class sees only the built-in formats.
2. The tidy-up editor is out of the flow. The old format page becomes a teacher-only Formats page. Formats students uploaded before the change stop appearing for new plans, but existing plans that use them still work.
3. Order: previous topic before today's topic, then next topic.
4. Duration quick picks are 30 / 45 / 60 / 90 with 45 preselected.
5. The "which fields should Alan write" choice becomes one screen after Building Proficiency.
6. The document view keeps today's layout; the big Alan is only for the questions and the generation wait.
7. The student's name fills "Teacher"-type blanks; the cooperating teacher only goes to the AI context.
8. School, name and cooperating teacher are remembered in the browser per user.
9. No extra questions for date, quarter or teaching time; those blanks stay in the document.
10. A **Lesson details** button in the document reopens the answers; changes apply to the next generation only.
11. Create Lesson Plan offers **Continue where you left off** or **Start a new plan** when an unfinished run exists; drafts are keyed per run, not per format.
12. Teachers get the same flow without the cooperating-teacher step.
13. "Pre-Lesson" counts as a recap field and "Extended Learning Opportunities" as an assignment field. On weekly formats, the previous topic grounds day 1, the next topic grounds the last day, and duration is per session.

## Left to the builder

- Exact copy for each of Alan's lines and the help text under each question, in AlignED's plain voice.
- How the flow is split between files: a new page versus reworking `generator.html` in place, provided the URLs `generator.html?format_id=` and `?plan_id=` keep working for existing links.
- Transition motion between steps, within the "one authored moment" rule.
- Backend tests for the new prompt instructions, following the existing `backend/test_*.py` style.
