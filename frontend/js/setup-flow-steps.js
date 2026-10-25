// Rules for the Create Lesson Plan flow, where Alan asks one question at a
// time: the step order, which answers are required, filling the format's own
// blanks from the answers, and which formats an account may pick. No DOM here,
// so frontend/js/setup-flow-steps.check.js can run it under node.

// Eight steps, a few fields each: format + school, people, class, subject +
// duration, the four topics, supplementary sources, a sample plan (optional),
// mode.
const FLOW_STEP_IDS = ["format", "people", "class", "subject", "topics", "sources", "sample", "mode"];

// Alan's pose for each step (keys from js/alan3d.js POSES).
const FLOW_POSES = {
  format: "hi", people: "present", class: "present", subject: "point",
  topics: "think", sources: "reading", sample: "check", mode: "idea",
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

function isStepAnswered(stepId, answers) {
  const a = answers || {};
  switch (stepId) {
    case "format": return filled(a.formatId); // the school is encouraged, not required
    case "people": return filled(a.studentTeacher) && filled(a.coop);
    case "class":
      return a.levelType === "college" ? filled(a.program) && filled(a.year) : filled(a.grade);
    case "subject":
      return filled(a.subject) && Number.isInteger(a.durationMinutes) && a.durationMinutes >= 5 && a.durationMinutes <= 240;
    case "topics": return filled(a.mainTopic) && filled(a.topic); // previous and next are encouraged
    case "sources": // at least one source of any kind, and the term and week
      return (a.guides || []).length + (a.sources || []).length > 0 && filled(a.term) && filled(a.week);
    case "sample": return true; // optional: a finished plan to learn the layout from
    case "mode": return a.mode === "full" || a.mode === "step";
    default: return true;
  }
}

function classLabel(a) {
  const parts = a.levelType === "college" ? [a.program, a.year, a.section] : [a.grade, a.section];
  return parts.map((p) => (p || "").trim()).filter(Boolean).join(" · ");
}

const PREFILL_LABELS = [
  [["school"], (a) => a.school],
  [["student teacher", "teacher", "name of teacher", "name of teachers"], (a) => a.studentTeacher],
  [["learning area", "learning area(s)"], (a) => a.subject],
  [["grade level", "grade level & section"], classLabel],
  [["term", "quarter", "term/quarter", "quarter/term", "grading period"], (a) => a.term],
  [["week", "week no.", "week number"], (a) => weekLabel(a.week)],
];

// The week is typed by hand: a bare number reads as "Week 3", anything else
// ("Week 4", "Weeks 3-4") stays as written.
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
