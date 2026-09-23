# Generator modes: field roles, per-mode progress, and editable fields

Date: 2026-09-23
Status: approved, ready for implementation planning

## Why

Five problems in the lesson-plan generator, reported together because they share
a cause: the two generation modes were built as one shared state machine with one
shared notion of which fields matter.

1. **Fields cannot be edited.** Reproduced: in Guided mode a field the teacher
   has already answered is set `contentEditable = false` and given *no* lock
   styling, so it looks ordinary and silently swallows typing. Because mode and
   progress are stored as one shared thing, returning to a saved draft drops the
   teacher back into Guided, where this then bites them even though they wanted
   Building Proficiency.
2. **The document toolbar disappears in fullscreen.** `requestFullscreen()` is
   called on the document wrapper, but the toolbar is its sibling, so it falls
   outside the fullscreened subtree.
3. **Inaccurate AI content is awkward to replace.** There is no way to clear a
   field and try again.
4. **Both modes target every field.** Guided walks the teacher through trivia
   like "No. of Sessions"; Building Proficiency writes high-level pedagogy the
   teacher may want to write themselves. The two modes have opposite purposes and
   should target opposite halves of the format.
5. **The modes share one set of values.** Work done in one mode is the work shown
   in the other, so the modes cannot be used for different drafts of the plan.

## Decisions taken

Confirmed with the user before this spec was written:

- Field roles come from **keyword matching, with a per-field override** in the
  format builder.
- Building Proficiency offers a **checklist** of the thinking-heavy fields before
  generating; the easy ones are always written.
- "Deletable" means **clear the field's content so it can be redone**, not remove
  the field from the format.
- Per-mode progress is stored with the **active mode in `field_values` and the
  other mode in a new `mode_values` column**, so export, submission and every
  existing saved plan keep working untouched.

## 1. Field roles

### The classification

A field is `heavy` (needs real pedagogical thinking) or `easy` (the teacher can
answer it in seconds). New module `backend/services/field_roles.py`:

```
role_for(field) -> "heavy" | "easy"
```

It matches the lowercased `field_key` and `label` against a keyword list, and
returns `easy` when nothing matches.

### The keyword list must cover DepEd vocabulary, not just six words

The user named six field types: content, procedures, assignment, objectives,
application, activity. Their own live format (`ILAW`, 17 fields) shows why
matching only those words is not enough — its labels are:

| Label | Intended role | Matched by the six words? |
|---|---|---|
| Name of Lesson | easy | – |
| Learning Area/s | easy | – |
| Designed by Teacher/s | easy | – |
| Designed for which Grade Level & Section | easy | – |
| No. of Sessions | easy | – |
| References | easy | – |
| Declaration of AI use | easy | – |
| Learning Competency | **heavy** | no |
| Learning Objectives | **heavy** | yes (objectives) |
| Learner Context | **heavy** | no |
| Pre-lesson | **heavy** | no |
| Flow | **heavy** (this format's "procedures") | no |
| Learning Resources | easy | – |
| Opportunities for integration | **heavy** | no |
| Formative Assessment | **heavy** | yes (assessment) |
| Extended learning opportunities | **heavy** | no |
| Reflections | **heavy** | no |

Two of nine heavy fields would be caught. So the default keyword list covers the
vocabulary DepEd formats actually use:

- **Objectives / content:** objective, competency, content, subject matter, topic
  outline
- **Procedures:** procedure, flow, learning task, lesson proper, sequence, steps
- **Activity / motivation:** activity, activities, motivation, pre-lesson,
  pre lesson, energizer, warm-up, routine, drill
- **Application / analysis:** application, integration, abstraction, analysis,
  generalization, valuing
- **Assessment / assignment:** assignment, assessment, evaluation, extended
  learning, enrichment, agreement
- **Reflection and context:** reflection, learner context

`Reflections` is classified heavy deliberately. A teacher writes it after
teaching and may well not want it generated — but heavy means *opt-in* in
Building Proficiency, which gives them that choice, whereas easy would mean it is
silently written every time.

### The override

New column `format_fields.role`, nullable:

- `NULL` — decide by keyword (the default for every existing field)
- `"heavy"` / `"easy"` — explicit, set by the teacher in the format builder

Added through the existing `_add_column()` helper in `app.py`.

### One definition, not two

The frontend needs the role to render the checklist and to drive Guided's step
list. Rather than re-implement the keyword list in JavaScript, the resolved role
is returned by the API: `FormatField.to_dict()` gains `"role"`. The keyword list
exists in exactly one place.

## 2. Building Proficiency: easy fields always, heavy fields opt-in

### Behaviour

Before generating, the generate panel shows:

- a summary line naming how many easy fields will be filled in automatically
- a checklist of the heavy fields, each ticked by default

Ticked by default because that reproduces today's behaviour — a teacher who
never looks at the checklist gets what they get now. The choice is remembered
per format in `localStorage`, so a teacher who always writes their own Flow
only unticks it once.

### API

`POST /api/generate/full-stream` gains an optional `include_keys: [field_key]`.

- Absent — generate every field (current behaviour, so nothing else breaks)
- Present — generate exactly those keys, and nothing else

The page sends the **full** list: every easy field plus the heavy ones still
ticked. The server does not add the easy fields itself. One rule — "generate
exactly what was asked for" — is easier to reason about than a server that
silently extends the request, and it keeps the missing-field accounting below
honest, since the requested set is then exactly the set that should come back
answered.

The server validates the keys against the format and ignores unknown ones.

### Missing-field accounting

The `complete` event's `missing` list must only mention fields that were
*supposed* to be generated. Reporting a deliberately-skipped Flow as "couldn't
be generated" would train the teacher to ignore the warning, which is the thing
that warning exists to avoid. `generate_full_streaming()` therefore computes
`missing` against the requested fields, not against the whole format.

## 3. Guided: the thinking-heavy fields only

Guided's step sequence becomes the heavy fields in document order.

Easy fields are not part of the walkthrough and are **never locked** — the
teacher types their name and section whenever they like. This is also most of
the fix for problem 1: far fewer fields are ever locked at all.

If a format has no heavy fields (an unusual format, or every field overridden to
easy), Guided falls back to walking every field, so the mode is never empty.

## 4. Editing: the root-cause fix

A completed field stays editable. Only fields *ahead* of the current step are
locked, which is what "unlocks as you go" was for; a field already answered
belongs to the teacher.

Concretely, in `applyStepLocks()` the third branch (`i < stepIndex`) stops
setting `contentEditable = "false"`. Editing a completed field writes straight
back to that mode's values through the existing input handler.

This is smaller than adding an unlock affordance, and it removes the class of bug
entirely: there is no longer any state in which a field looks editable and is
not. The locked-ahead fields keep their existing hatched styling and lock
message, so the one remaining read-only state still announces itself.

## 5. Clear and redo

Two controls, neither of them inside the document:

- **Clear field** in the document toolbar, acting on the focused field. Clears
  the plain value and any rich value, marks the plan dirty.
- **Clear & ask again** beside Guided's *Submit & continue*. Clears the current
  field and re-asks the owl about it, for when the suggestion was wrong.

Deliberately not buttons injected into the document canvas: that would disturb
the printed-document layout and the `anchor_index` model the format builder
depends on.

## 6. Per-mode progress

### Storage

New column `lesson_plans.mode_values` (TEXT, JSON), holding the **inactive**
mode's state:

```json
{ "field_values": {...}, "rich_field_values": {...}, "step_index": 0 }
```

`field_values` and `rich_field_values` keep holding the **active** mode's
content, and `generation_mode` keeps recording which mode that is. Export,
submission, the plan list and every existing saved row therefore need no change
at all.

An older plan with no `mode_values` loads its single set of values as the active
mode's, with the other mode starting empty. Nothing to migrate.

### Frontend

The generator holds:

```js
modeState = {
  full: { fieldValues, fieldRichValues },
  step: { fieldValues, fieldRichValues, stepIndex },
}
```

Switching mode writes the live values into the outgoing mode's slot, loads the
incoming mode's slot, and repaints. The `localStorage` draft stores both slots so
leaving the page keeps both modes' work.

### What export uses

The active mode's values, unchanged. A teacher exports what they are looking at.

## 7. Fullscreen keeps the toolbar

Toolbar and canvas are wrapped in one stage element per screen
(`#live-doc-stage` in the generator, the equivalent in the format builder), and
the stage is what goes fullscreen, with the toolbar sticky at its top.

`initDocViewControls()` gains a `stageEl` — what to fullscreen — kept separate
from `wrapEl`, which is what zooms and scrolls. When `stageEl` is not given it
falls back to `wrapEl`, so the call sites stay simple.

## Testing

| Check | What it pins down |
|---|---|
| `test_field_roles.py` | The six named types resolve heavy; the 17 ILAW labels, hard-coded as fixtures rather than read from the database, resolve to the table above; overrides win over keywords; unknown labels default to easy |
| `test_generate_selection.py` | `include_keys` restricts what is generated; `missing` counts only requested fields; an unknown key is ignored rather than erroring |
| `test_lesson_plan_drafts.py` (extended) | `mode_values` round-trips through PATCH; a plan saved before this change still loads; switching modes does not lose either side |
| Browser pass | A completed field is editable in both modes; locked-ahead fields still announce themselves; the toolbar is visible in fullscreen; the checklist drives what gets written |

## Out of scope

- Removing a field from a plan entirely (the user chose clear-and-redo instead).
- A third role between heavy and easy.
- Changing what Guided's owl chat says, beyond re-asking on *Clear & ask again*.
