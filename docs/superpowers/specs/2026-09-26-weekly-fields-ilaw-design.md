# Weekly fields, a corrected ILAW format, and better field detection

Date: 2026-09-26
Status: approved in conversation (decisions below), ready to build

## Why

The built-in ILAW format had wrong and missing fields. Comparing it with a filled
ILAW plan (`T1W7-TLE8-AFA-ICT-LESSON-PLAN-ILAW.docx`) showed three causes:

1. **ILAW is a weekly plan.** Most rows have one answer per day, Monday to Friday,
   in five cells. The engine fills a field into one cell (the first blank to the
   right of its label), so a whole answer landed in Monday.
2. **Detection skipped long labels.** DepEd templates put the label and its
   instructions in one paragraph ("Flow: Describe the activities..."). Lines longer
   than the label limit were dropped, so Learning Objectives, Learner Context, Flow,
   Opportunities, Formative Assessment, Extended learning and Reflections were
   never offered as fields.
3. **PDF conversion split tables at page breaks.** The tail of an instruction
   ("guidance or support throughout each session...", "you like your instructional
   coach to help you with?") became its own row and was taken for a label.

## Decisions (confirmed with the user)

- Day columns are one **weekly field per row**: the answer has one part per day,
  each filled into its own column.
- The built-in ILAW keeps the **converted PDF template**; only its fields change.
- **Detection improves for every upload**, not only ILAW.

## Design

### Weekly field type

- `FormatField.field_type = "weekly"` with a new nullable column `parts` (JSON list
  of labels, e.g. `["Monday", ..., "Friday"]`), exposed in `to_dict()`.
- A weekly value is a list of strings, one per part, stored as-is in
  `field_values` (rich values: a list of HTML strings).
- **Export** (`docx_service`): the field claims every consecutive blank cell to the
  right of its label in that row and fills part *i* into cell *i*.
- **Live document**: the same cells render as separate editable slots carrying
  `data-field-key` and `data-part`.
- **AI**: the schema line says `weekly, N parts: Monday, Tuesday, ...` and asks for a
  JSON array of exactly N strings. `ai_limits` cleans each part on its own.
- **Generator**: every place that reads or writes a slot goes through part-aware
  helpers, so a weekly field is one field (one Guided step) with N slots.

### Detection

- A long line of the form `Label: instructions` yields the candidate `Label`, at the
  same position.
- A line that begins with a lowercase letter is a continuation, never a label.
- A label whose row has two or more consecutive blank cells becomes a weekly field
  deterministically (not left to the AI). Its parts are named from the document's
  day header row (a row of weekday names); without one, `Column 1..N`.

### ILAW fields

Grade Level & Section, Teacher, Learning Area, Week / Teaching Dates and Time, Term,
Name of Teachers (text); Lesson Title, Session No., References, Declaration of AI
use, Performance Standards, Content Standards, Learning Competencies, Learning
Objectives, Learner Context, Pre-Lesson, Flow, Learning Resources, Opportunities for
integration and contextualization, Formative Assessment, Extended learning
opportunities, Reflections (weekly). School is pre-printed in the template and is
not a field. Each weekly field's hint says what the sample shows belongs there.

## Testing

`backend/test_weekly_fields.py`: detection offers the long-label fields and skips the
fragments; weekly detection and part names; export fills each day cell; live-document
slots carry parts; AI limits keep a weekly value as a list; the seeded ILAW has the
expected fields. Browser check: ILAW in the generator shows five slots per weekly row,
typing in Tuesday updates only Tuesday, and saved values survive a reload.
