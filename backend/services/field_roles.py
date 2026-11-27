"""Which fields need a teacher's pedagogical thinking, and which are quick facts.

The two generation modes have opposite purposes, so they should target opposite
halves of a format. Guided walks the teacher through the thinking-heavy fields
one at a time with the owl's help; Building Proficiency fills in the quick facts
without asking and offers the heavy ones as an opt-in checklist.

The classification is keyword-based because it has to work on formats that
already exist, with no setup and no per-field curation. A field may override it
outright (FormatField.role), which is what a school whose wording this module
does not recognise should reach for.

The keywords deliberately cover DepEd lesson-plan vocabulary rather than only
the obvious six words: a real format in use calls its procedures section "Flow"
and its objectives "Learning Competency", neither of which contains "procedure"
or "objective".
"""

HEAVY = "heavy"
EASY = "easy"
# The student's own to write (which session of the term it is, which only
# their schedule knows): never filled in automatically, offered to the AI only
# if they tick it. The lesson title used to be here too, but it follows from
# the topic, so the AI fills it like any other quick field.
SELF = "self"

_SELF_KEYWORDS = ("session no", "session number", "no. of sessions", "no of sessions")

# Matched as plain substrings against "<field_key> <label>", lowercased with
# underscores turned into spaces. Substrings rather than whole words so
# "learning_objectives", "Objectives:" and "objective" all match one entry.
_HEAVY_KEYWORDS = (
    # Standards, objectives and content
    "standard", "objective", "competency", "competencies", "content", "subject matter",
    "topic outline",
    # References and learning resources: Guided walks them before the lesson
    # parts that draw on them (testers found them skipped to the end).
    "reference", "resource", "material",
    # The DepEd DLP's procedure parts, worded as SNHS words them
    "discussion", "review", "purpose", "mastery", "evaluat", "presentation",
    "engage", "explore", "explain", "elaborate", "elicit",
    # The TUP SDLP: objectives under their own lead-in, values, activity mechanics
    "at the end of the lesson", "should be able to", "values", "mechanic",
    # Procedures
    "procedure", "flow", "learning task", "lesson proper", "sequence", "steps",
    # Activity and motivation
    "activity", "activities", "motivation", "pre-lesson", "pre lesson",
    "energizer", "warm-up", "warm up", "icebreaker", "routine", "drill",
    # Application, analysis, abstraction (the DepEd 4A's)
    "application", "integration", "abstraction", "analysis", "generalization",
    "generalisation", "valuing",
    # Assessment and assignment
    "assignment", "assessment", "evaluation", "extended learning",
    "enrichment", "agreement", "remediation",
    # Learner context
    "learner context",
)

# The reflection the teacher writes after teaching the lesson: the DepEd DLP's
# Remarks and its reflection questions (A to G). No one can write it before the
# lesson, so it is never generated, never walked in Guided, and starts static.
_REFLECTION_KEYWORDS = (
    "reflection", "remarks", "no. of learners", "no of learners", "remedial lessons",
    "teaching strategies worked", "difficulties did i encounter", "innovation or locali",
    "localized materials",
)


import re

# Labels that are plain facts (who, where, when): known even though no part
# keyword matches them, so their context is never read as a lesson part.
_FACT_WORDS = ("school", "teacher", "name", "date", "time", "week", "day", "grade", "section", "quarter",
               "term", "semester", "subject", "learning area", "modality", "title", "topic", "session",
               "pages", "prepared by", "checked by", "noted by", "approved by", "duration")

# What an admin's context ("What goes here") says a part is, for a format
# whose own word for it is new to the app (PAL3's "Self-Check", a school's
# "Lesson Development"). Each maps to the standard name every recogniser
# already knows. The part named EARLIEST in the context wins: admins open
# with what the part is ("A short quiz on...") before what it relates to.
_HINT_KINDS = (
    (r"content standard", "content standard"),
    (r"performance standard", "performance standard"),
    (r"objective|at the end of the lesson|(?:learners|students) (?:should|will|are expected to) be able",
     "learning objectives"),
    (r"competenc|melc", "learning competency"),
    (r"reflection|after (?:the )?(?:session|teaching|class)|what to change next time", "reflection"),
    (r"learner context|observations? of (?:the|these) learners", "learner context"),
    (r"\bai\b|artificial intelligence", "declaration of ai use"),
    (r"reference|bibliograph|sources? (?:cited|used)", "references"),
    (r"materials?|learning resources?|instructional|equipment|tools? (?:and|&) supplies", "learning resources materials"),
    (r"routine|prayer|greeting|attendance|classroom rules", "pre-lesson routine"),
    (r"review|recap|previous lesson|past lesson", "review of the previous lesson"),
    (r"motivat|hook|energi[sz]er|warm.?up|icebreaker|arouse", "motivation"),
    (r"lesson proper|the lesson itself|discussion|lecture|(?:teach|present|explain|introduce)(?:es|s|ing)? the "
     r"(?:new |day's |lesson's )?(?:topic|lesson|concepts?|content)|key concepts|definitions", "lesson proper"),
    (r"flow|procedure|steps? of the lesson|activities in order|sequence of (?:the )?(?:activities|lesson)|"
     r"whole (?:session|lesson|period)", "lesson flow procedure"),
    (r"analy[sz]", "analysis"),
    (r"generali[sz]|abstraction|key idea|sum(?:s|ming)? up|summar", "generalization"),
    (r"application|apply|real.life|daily life", "application"),
    (r"quiz|evaluat|assess|\btest\b|self.check|check (?:of |for )?(?:learning|understanding|mastery)", "evaluation"),
    (r"assignment|homework|at home|outside (?:of )?class|extended learning|enrichment|remediation",
     "assignment extended learning"),
    (r"integration|contextuali|other learning areas|other subjects", "integration"),
    (r"values?\b|attitude", "values"),
    (r"activit|group work|hands.on|practice|exercise", "activity"),
)


def hint_kind(hint) -> str:
    """The standard part an admin's context describes, or "" if none."""
    text = str(hint or "").lower()
    found = [(m.start(), kind) for pattern, kind in _HINT_KINDS for m in [re.search(pattern, text)] if m]
    return min(found)[1] if found else ""


def _label_text(field) -> str:
    key = getattr(field, "field_key", "") or ""
    label = getattr(field, "label", "") or ""
    return f"{key} {label}".replace("_", " ").lower()


def label_known(field) -> bool:
    """The field's own key or label already names a part or a plain fact."""
    text = _label_text(field)
    words = _HEAVY_KEYWORDS + _REFLECTION_KEYWORDS + _SELF_KEYWORDS + _FACT_WORDS
    return any(w in text for w in words) or bool(re.search(r"lesson.proper|presentation|explain|\bai\b", text))


def part_text(field) -> str:
    """What a field is, for every recogniser: its key and label, plus, when
    that label is a term the app doesn't know, the standard part its admin
    context describes. A known label is never overridden, so formats that
    already worked read exactly as before."""
    text = _label_text(field)
    if not label_known(field):
        kind = hint_kind(getattr(field, "ai_hint", None))
        if kind:
            text = f"{text} {kind}"
    return text


def _haystack(field) -> str:
    return part_text(field)


def role_for(field) -> str:
    """HEAVY or EASY for one field.

    An explicit field.role wins outright. Anything the keywords do not recognise
    is EASY: an unfamiliar short field is quicker for the teacher to type than to
    be walked through, and treating unknowns as heavy would drag every stray
    "Remarks" column into the Guided walkthrough.
    """
    override = (getattr(field, "role", None) or "").strip().lower()
    if override in (HEAVY, EASY):
        return override

    haystack = _haystack(field)
    # The reflection is the teacher's own to write after the lesson, like the session number.
    if any(word in haystack for word in _SELF_KEYWORDS) or is_reflection(field):
        return SELF
    return HEAVY if any(word in haystack for word in _HEAVY_KEYWORDS) else EASY


def is_reflection(field) -> bool:
    """Part of the reflection written after the lesson (see _REFLECTION_KEYWORDS)."""
    haystack = _haystack(field)
    return any(word in haystack for word in _REFLECTION_KEYWORDS)
