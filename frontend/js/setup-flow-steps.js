// Rules for the Create Lesson Plan flow, where Alan asks one question at a
// time: the step order, which answers are required, filling the format's own
// blanks from the answers, and which formats an account may pick. No DOM here,
// so frontend/js/setup-flow-steps.check.js can run it under node.

// Ten steps, a few fields each: format + school + modality, how the lesson is
// assessed, people, class, subject + duration, the four topics, supplementary
// sources, what kind of lesson it is, a sample plan (optional), mode.
const FLOW_STEP_IDS = ["format", "assessment", "people", "class", "subject", "topics", "sources", "level", "sample", "mode"];

// Step 8, after the documents: what kind of lesson this is, so its depth,
// objectives and assessment fit where it sits in the unit (user, 2026-11-28).
const LESSON_LEVELS = [
  { value: "introductory", title: "Introductory lesson", sub: "Learners meet this topic for the first time." },
  { value: "developing", title: "Developing lesson", sub: "Learners know the basics; this lesson goes deeper." },
  { value: "application", title: "Application / practice", sub: "Learners already understand it; they use the skill." },
  { value: "review", title: "Review / mastery", sub: "Consolidate before the unit assessment, with remediation." },
];


// Alan's pose for each step (keys from js/alan3d.js POSES).
const FLOW_POSES = {
  format: "hi", assessment: "think", people: "present", class: "present", subject: "point",
  topics: "think", sources: "reading", level: "think", sample: "check", mode: "idea",
};

const DURATION_CHOICES = [30, 45, 60, 90];

// Teachers get the same steps.
function flowSteps(role) {
  return FLOW_STEP_IDS.slice();
}

// One grade dropdown: Grade 4-12, then the four college years, kept on the
// page as the K-12 grade or the college year it always stored.
const COLLEGE_YEARS = ["1st Year", "2nd Year", "3rd Year", "4th Year"];

function gradeOptions() {
  const k12 = [4, 5, 6, 7, 8, 9, 10, 11, 12].map((n) => `Grade ${n}`);
  return [...k12, ...COLLEGE_YEARS.map((y) => `${y} College`)].map((v) => ({ value: v, label: v }));
}

function answersForGrade(value) {
  return /College$/.test(value)
    ? { levelType: "college", year: value.replace(/ College$/, "") }
    : { levelType: "k12", grade: value };
}

function gradeValue(a) {
  if (a.levelType === "college") return a.year ? `${a.year} College` : "";
  return a.grade || "";
}

function filled(value) {
  return typeof value === "string" ? value.trim().length > 0 : value != null && value !== "";
}

// The quiz sizes the setup offers.
const QUIZ_SIZES = [5, 10, 15, 20];

function isStepAnswered(stepId, answers) {
  return stepProblem(stepId, answers) === null;
}

// Text that says something: at least two letters, not only symbols or digits.
function wordy(value) {
  return (String(value || "").match(/\p{L}/gu) || []).length >= 2;
}

// Reads as real words, not a number, a keyboard mash or a placeholder (user,
// 2026-11-28: "topic input is number or a word that doesn't make any sense").
// Kept in step with backend/services/text_sense.py. Acronyms in capitals
// (HTML, CSS, LAN) and words with digits (IPv4, Excel 2019) are fine.
const PLACEHOLDERS = new Set(["test", "testing", "sample", "topic", "none", "na", "n/a", "nothing", "idk", "blah",
  "abc", "xyz", "asdf", "qwerty", "lorem ipsum", "lorem", "aaa", "xxx", "etc", "something", "anything", "wala"]);
const MASHES = ["qwer", "wert", "asdf", "sdfg", "dfgh", "fghj", "ghjk", "hjkl", "zxcv", "xcvb", "cvbn", "vbnm"];
function sensible(value) {
  const text = String(value || "").trim();
  const letters = (text.match(/\p{L}/gu) || []).length;
  if (letters < 3 || letters * 2 < (text.match(/\d/g) || []).length) return false;
  if (PLACEHOLDERS.has(text.toLowerCase().replace(/[.!?]+$/, ""))) return false;
  return (text.match(/\p{L}+/gu) || []).every((word) => {
    if (/^\p{Lu}{2,6}s?$/u.test(word)) return true; // an acronym
    const w = word.toLowerCase();
    if (/(.)\1\1/.test(w)) return false; // "aaaa", "zzz"
    if (MASHES.some((m) => w.includes(m))) return false;
    if (w.length < 4) return !["asd", "qwe", "zxc", "sdf", "jkl", "hjk", "dfg"].includes(w);
    if (!/[aeiouy]/.test(w)) return false; // no vowel at all
    return !/[bcdfghjklmnpqrstvwxz]{6,}/.test(w); // "bcdfgh" ("strengths" has 5)
  });
}

// What is wrong with a step's answers, as { field, message } (field: the
// input's id, to mark and focus), or null when the step is answered. Next
// shows the message instead of greying out with no reason (user report
// 2026-11-24: the create-plan inputs gave no error when something was off).
function stepProblem(stepId, answers) {
  const a = answers || {};
  const problem = (field, message) => ({ field, message });
  // An optional box may stay empty, but what is typed in it must read as words.
  const optional = (key, field, what) =>
    (filled(a[key]) && !sensible(a[key]) ? problem(field, `${what} doesn't look like real words. Check it, or leave it empty.`) : null);
  const name = (key, field, who) =>
    (sensible(a[key]) ? null : problem(field, `${who} should be a real name, as it appears on the plan.`));
  switch (stepId) {
    case "format":
      if (!filled(a.formatId)) return problem(null, "Choose a lesson plan format.");
      return optional("school", "flow-school", "The school's name"); // the school is encouraged, not required
    // Whatever the objectives call for, a quiz, a performance task, or both;
    // any choice that may hold a quiz has its 5, 10, 15 or 20 items.
    case "assessment":
      if (!["objectives", "quiz", "task", "both"].includes(a.assessment)) return problem(null, "Choose how you'll assess this lesson.");
      if (a.assessment !== "task" && !QUIZ_SIZES.includes(a.quizItems)) return problem("flow-quiz-items", "Choose how many quiz items.");
      return null;
    case "people":
      if (!filled(a.studentTeacher)) return problem("flow-studentTeacher", "Type your name.");
      if (name("studentTeacher", "flow-studentTeacher", "Your name")) return name("studentTeacher", "flow-studentTeacher", "Your name");
      if (!filled(a.coop)) return problem("flow-coop", "Type the cooperating or subject teacher's name.");
      return name("coop", "flow-coop", "The teacher's name");
    case "class":
      if (a.levelType === "college") {
        if (!filled(a.year)) return problem("flow-grade", "Choose the year level.");
        if (!filled(a.program)) return problem("flow-program", "Type the program, e.g. BS Information Technology.");
        if (!sensible(a.program)) return problem("flow-program", "That doesn't look like a program name. Type it out, e.g. BS Information Technology.");
      } else if (!filled(a.grade)) {
        return problem("flow-grade", "Choose the grade level.");
      }
      return null;
    case "subject":
      if (!filled(a.subject)) return problem("flow-subject", "Choose the subject.");
      if (!Number.isInteger(a.durationMinutes)) return problem("flow-minutes", "Choose how long the discussion is, or type the minutes.");
      if (a.durationMinutes < 5 || a.durationMinutes > 240) {
        return problem("flow-minutes", "The discussion should be from 5 to 240 minutes long.");
      }
      return null;
    case "topics":
      if (!filled(a.mainTopic)) return problem("flow-mainTopic", "Type the main topic.");
      if (!sensible(a.mainTopic)) return problem("flow-mainTopic", "That doesn't look like a topic. Type what the unit is about in words, e.g. Spreadsheets.");
      if (!filled(a.topic)) return problem("flow-topic", "Type today's specific topic.");
      if (!sensible(a.topic)) return problem("flow-topic", "That doesn't look like a topic. Type what today's lesson teaches in words, e.g. Cell formulas.");
      // previous and next are encouraged, not required
      return optional("previousTopic", "flow-previousTopic", "The last topic")
        || optional("nextTopic", "flow-nextTopic", "The next topic");
    case "sources": // at least one source of any kind
      return (a.guides || []).length + (a.sources || []).length > 0
        ? null : problem(null, "Pick at least one Budget of Work, Curriculum Guide or file for me to read.");
    case "level":
      return LESSON_LEVELS.some((l) => l.value === a.lessonLevel) ? null : problem(null, "Choose what kind of lesson this is.");
    case "sample": return null; // optional: a finished plan to learn the layout from
    case "mode":
      return a.mode === "full" || a.mode === "step" ? null : problem(null, "Choose Building Proficiency or Guided.");
    default: return null;
  }
}

function classLabel(a) {
  const parts = a.levelType === "college" ? [a.program, a.year, a.section] : [a.grade, a.section];
  return parts.map((p) => (p || "").trim()).filter(Boolean).join(" · ");
}

const PREFILL_LABELS = [
  [["school"], (a) => a.school],
  [["learning delivery modality", "learning modality", "modality", "delivery modality", "mode of delivery"],
    (a) => (a.modality === "Online" ? "Online" : "Face to Face")],
  [["student teacher", "teacher", "name of teacher", "name of teachers"], (a) => a.studentTeacher],
  [["learning area", "learning area(s)"], (a) => a.subject],
  [["grade level", "grade level & section"], classLabel],
  [["week", "week no.", "week number"], (a) => (a.levelType === "college" ? weekLabel(a.week) : "")],
];

// College only: the syllabus week, typed by hand. A bare number reads as
// "Week 5"; anything else ("Weeks 3-4") stays as written.
function weekLabel(week) {
  const w = String(week || "").trim();
  return /^\d+$/.test(w) ? `Week ${w}` : w;
}

// Answers given once (school, name, subject, class) go straight into the
// format's matching blanks, but never over something already written.
function prefillFieldValues(fields, answers, current) {
  const out = {};
  (fields || []).forEach((f) => {
    const label = (f.label || "").trim().toLowerCase();
    const rule = PREFILL_LABELS.find(([labels]) => labels.includes(label));
    if (!rule || filled((current || {})[f.field_key])) return;
    const value = rule[1](answers || {});
    if (filled(value)) out[f.field_key] = value.trim();
  });
  return out;
}

// Students choose from the built-ins and their teachers' formats (the server
// only sends those); teachers from the built-ins and their own uploads.
function formatGroups(formats, user) {
  const groups = { builtin: [], teacher: [], mine: [] };
  (formats || []).forEach((f) => {
    if (f.is_builtin) groups.builtin.push(f);
    else if (user.role === "student") groups.teacher.push(f);
    else if (f.owner_id === user.id) groups.mine.push(f);
  });
  return groups;
}

function rememberKey(userId) {
  return `alignedFlowMemory:v1:${userId}`;
}

function runDraftKey(runId) {
  return `alignedDraft:v2:run:${runId}`;
}
