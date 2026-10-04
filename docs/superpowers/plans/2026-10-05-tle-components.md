# TLE components Implementation Plan

> Executed inline (the user said "approved and start now"; same native execution as the last plan).

**Goal:** AFA, HE (FCS), IA and Electrical (EES) subjects with their 24 official DepEd Budgets of Work as built-in guides.
**Spec:** `docs/superpowers/specs/2026-10-05-tle-components-design.md`

## Global constraints
- No AI calls in testing (the user's OpenRouter credits are limited).
- No new dependencies. PDFs and their `.txt` go in `backend/builtin/course_guides/`.
- Python: `C:/tle/rel-Aligned/aligned/backend/venv/Scripts/python.exe`; run tests from `backend/`.

### Task 1: Test first (`backend/test_builtins.py`)
Add `check_new_subject_search(app, student)`: GET `/api/course-guides?subject=<v>` for `IA`, `Electrical (EES)`,
`HE (FCS)`, `AFA`, `ICT`. Asserts:
- IA returns the EES and SMAW files and a combined `AFA / FCS / IA` file, and no ICT title;
- Electrical (EES)'s first result is the Electrical and Electronics Servicing file;
- HE (FCS) returns Beauty Care Services and no ICT title;
- AFA returns Fish Capture;
- every one of the five returns the MATATAG curriculum guide.

Run it and watch it fail (subjects unknown, files missing).

### Task 2: Guides
One-off script `$JOB/tmp/fetch_tle.py` (not committed):
1. Download the 24 Drive files (ids paired from the LR Portal grade pages, validated against the known G7 ICT id).
2. Check each PDF's first page or title matches its listing.
3. Extract text with `services.text_extract.extract_text` into `<name>.txt`.
4. Append the manifest entries to `guides.json`: subject `AFA / FCS / IA` for the five combined files; `IA`,
   `HE (FCS)`, `AFA` for G9-10; `Electrical (EES)` for EES. The curriculum guide's subject becomes `ICT / CP / AFA / FCS / IA`.

Update `SOURCES.md` (scope line plus a table of the 24 files with their Drive links).

### Task 3: Subjects and aliases
- `SUBJECT_ALIASES` in `course_guide_routes.py` as in the spec; ICT and CP gain `ICT / CP / AFA / FCS / IA`.
- The subject `<option>`s in `generator.html` and the Course Guides filter get the four new values; bump the asset version.

Run `test_builtins.py`, then the full suite once. Commit.

### Task 4: Deploy
Backup, archive deploy, then verify on the server: built-in guide count 34 (10 + 24), and one search per new subject.
