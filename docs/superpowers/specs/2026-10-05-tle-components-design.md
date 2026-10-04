# More TLE components: AFA, HE (FCS), IA and Electrical, with official guides

Date: 2026-10-05
Status: design approved in conversation; spec awaiting review
Part 1 of 4 (then: tutorial video in Announcements, FAQ, owl onboarding)

## Why

AlignED supports only ICT and Computer Programming. Teachers of the other TLE
components (Industrial Arts, Home Economics, Electrical, and Agri-Fishery Arts,
which the user's own ILAW sample teaches alongside ICT) can't pick their subject
or find their official guides.

## What DepEd publishes (LR Portal, Three-Term Budget of Work pages)

- MATATAG renamed Home Economics **FCS (Family and Consumer Science)**. Electrical
  is the IA specialization **Electrical and Electronics Servicing (EES)**.
- Grades 4 to 8: one combined Budget of Work per grade for **AFA / FCS / IA**
  (`[G4] EPP: AFA | FCS | IA` ... `[G8] TLE: AFA | FCS | IA`), 5 files.
- Grades 9 to 10: one file per specialization:
  - IA (6): Automotive and Small Engine Servicing, Electrical and Electronics
    Servicing, Residential Carpentry, Residential Masonry and Tile Setting,
    Residential Plumbing, Shielded Metal Arc Welding (SMAW).
  - FCS (8): Beauty Care Services, Food Preparation, Food Service, Garments,
    Handicraft, Health and Wellness Massage, Hotel Services, Tourism Services.
  - AFA (5): Agricultural Crop Production, Animal Production, Aquaculture (Fish
    Culture), Fish Capture, Food and Beverage Processing.
- The built-in MATATAG EPP/TLE Curriculum Guide (Grades 4 to 10) already covers
  every component.

## Decisions (confirmed with the user)

- Support **AFA, HE (FCS), IA and Electrical (EES)** in addition to ICT and CP.
- Add **all 24** files above as built-in, read-only guides.

## Design

### Subjects

The generator's subject dropdown and the Course Guides page's subject filter offer,
in curriculum order: `ICT`, `CP (ComProg)`, `AFA`, `HE (FCS)`, `IA`,
`Electrical (EES)`. Values are plain strings, as today; existing plans and guides
are unchanged.

### Search aliases (`backend/routes/course_guide_routes.py`)

Matching stays a case-insensitive substring match on a guide's subject and title.
Bare "IA" or "HE" would match unrelated words ("Social", "the"), so every alias is
specific:

| Subject value | Aliases |
|---|---|
| `AFA` | `AFA`, `Agri-Fishery`, `AFA / FCS / IA` |
| `HE (FCS)` | `FCS`, `Home Economics`, `Family and Consumer`, `AFA / FCS / IA` |
| `IA` | `TLE: IA`, `Industrial Arts`, `AFA / FCS / IA` |
| `Electrical (EES)` | `Electrical`, `Electronics Servicing`, `AFA / FCS / IA` |

The curriculum guide's subject becomes `ICT / CP / AFA / FCS / IA`; the existing
ICT and CP alias lists gain that string, and so do the four above via their
`AFA / FCS / IA` alias, so the curriculum guide is found for every TLE subject.

### Built-in guides (`backend/builtin/course_guides/`)

- 24 PDFs, each with its pre-extracted `<name>.txt` (as the ICT ones have), and an
  entry in `guides.json`: key, title as DepEd lists it, subject, `doc_type:
  budget_of_work`, `grade_band` (`4-6` for G4 to G6, `7-8` for G7 and G8, `9-10`),
  grades, `curriculum: MATATAG`, Drive `source_url`, `retrieved_at`.
- Subjects: the 5 combined files `AFA / FCS / IA`; G9-10 files `IA`, `HE (FCS)` or
  `AFA`; the EES file `Electrical (EES)` (it also matches IA through "TLE: IA" in its
  title).
- Downloaded once by a script that is not committed (as with the ICT guides); each
  PDF's embedded title is checked against its listing. `SOURCES.md` lists every file
  and its Drive link, and the "Scope" line is updated.
- The seeder needs no change: it already inserts new manifest entries and reads the
  `.txt` beside each PDF.

## Testing

- One new check in `backend/test_builtins.py`: after seeding, a search for each new
  subject returns its own guides (IA finds the EES and SMAW files and the combined
  files; Electrical finds the EES file first), and does not return unrelated ones
  (IA must not return ICT - Visual Arts; HE must not return ICT files).
- The existing guide-search checks keep passing.
- No AI calls in testing.

## Deploy

Backup, then the usual archive deploy; verify the guide counts and one search per
new subject on the server.

## Out of scope

- Grade 11 and 12 TLE (the LR Portal has no TLE Budget of Work for them).
- Formats or field roles specific to the new components.
