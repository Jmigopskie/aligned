// Rules for the Create Lesson Plan flow, where Alan asks one question at a
// time: the step order, which answers are required, filling the format's own
// blanks from the answers, and which formats an account may pick. No DOM here,
// so frontend/js/setup-flow-steps.check.js can run it under node.

const FLOW_STEP_IDS = ["format", "school", "name", "coop", "subject", "duration", "class",
  "prevTopic", "topic", "nextTopic", "guide", "mode"];

// Alan's pose for each question (keys from js/alan3d.js POSES).
const FLOW_POSES = {
  format: "hi", school: "present", name: "present", coop: "present", subject: "point",
  duration: "check", class: "present", prevTopic: "think", topic: "think", nextTopic: "think",
  guide: "reading", mode: "idea",
};

// A teacher writing their own plan has no cooperating teacher to name.
function flowSteps(role) {
  return role === "teacher" ? FLOW_STEP_IDS.filter((id) => id !== "coop") : FLOW_STEP_IDS.slice();
}

function filled(value) {
  return typeof value === "string" ? value.trim().length > 0 : value != null && value !== "";
}

function isStepAnswered(stepId, answers) {
  const a = answers || {};
  switch (stepId) {
    case "format": return filled(a.formatId);
    case "name": return filled(a.studentTeacher);
    case "subject": return filled(a.subject);
    case "duration":
      return Number.isInteger(a.durationMinutes) && a.durationMinutes >= 5 && a.durationMinutes <= 240;
    case "class":
      return a.levelType === "college" ? filled(a.program) && filled(a.year) : filled(a.grade);
    case "topic": return filled(a.topic);
    case "guide": return filled(a.courseGuideId);
    case "mode": return a.mode === "full" || a.mode === "step";
    default: return true; // school, coop, prevTopic, nextTopic are encouraged, not required
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
];

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
