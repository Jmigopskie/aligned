// Self-check for the Create Lesson Plan flow's step rules. Run: node frontend/js/setup-flow-steps.check.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "setup-flow-steps.js"), "utf8"), ctx);
const get = (name) => vm.runInContext(name, ctx);

// Seven steps, several fields each; teachers get the same steps.
const ids = ["format", "people", "class", "subject", "topics", "sources", "mode"];
assert.deepStrictEqual(Array.from(ctx.flowSteps("student")), ids);
assert.deepStrictEqual(Array.from(ctx.flowSteps("teacher")), ids);
assert.deepStrictEqual(Array.from(get("FLOW_STEP_IDS")), ids);
assert.strictEqual(get("FLOW_POSES").topics, "think");
assert.strictEqual(get("FLOW_POSES").format, "hi");

// Grade dropdown: Grade 4-12 then the four college years, mapped onto the
// K-12 / college answers the page already keeps.
const grades = Array.from(ctx.gradeOptions()).map((o) => o.value);
assert.strictEqual(grades.length, 13);
assert.strictEqual(grades[0], "Grade 4");
assert.strictEqual(grades[12], "4th Year College");
assert.deepStrictEqual({ ...ctx.answersForGrade("Grade 7") }, { levelType: "k12", grade: "Grade 7" });
assert.deepStrictEqual({ ...ctx.answersForGrade("2nd Year College") }, { levelType: "college", year: "2nd Year" });
assert.strictEqual(ctx.gradeValue({ levelType: "college", year: "2nd Year" }), "2nd Year College");
assert.strictEqual(ctx.gradeValue({ levelType: "k12", grade: "Grade 9" }), "Grade 9");
assert.strictEqual(ctx.gradeValue({}), "");
assert.deepStrictEqual(Array.from(get("DURATION_CHOICES")), [30, 45, 60, 90]);

// Required answers per step.
const answered = ctx.isStepAnswered;
assert.strictEqual(answered("format", { formatId: 3 }), true);
assert.strictEqual(answered("format", { school: "SNHS" }), false);
assert.strictEqual(answered("people", { studentTeacher: "Ana", coop: "Juan" }), true);
assert.strictEqual(answered("people", { studentTeacher: "Ana", coop: " " }), false, "the subject teacher is required");
assert.strictEqual(answered("people", { coop: "Juan" }), false);
assert.strictEqual(answered("class", { levelType: "k12", grade: "Grade 7" }), true);
assert.strictEqual(answered("class", { levelType: "college", year: "2nd Year" }), false, "college needs a program");
assert.strictEqual(answered("class", { levelType: "college", year: "2nd Year", program: "BSIT" }), true);
assert.strictEqual(answered("subject", { subject: "ICT", durationMinutes: 45 }), true);
assert.strictEqual(answered("subject", { subject: "ICT", durationMinutes: 4 }), false);
assert.strictEqual(answered("subject", { subject: "ICT", durationMinutes: "45" }), false);
assert.strictEqual(answered("subject", { durationMinutes: 45 }), false);
assert.strictEqual(answered("topics", { mainTopic: "Spreadsheets", topic: "Cell formulas" }), true);
assert.strictEqual(answered("topics", { topic: "Cell formulas" }), false, "main topic is required");
assert.strictEqual(answered("topics", { mainTopic: "Spreadsheets", topic: "  " }), false);
assert.strictEqual(answered("sources", { guides: [{ id: 4 }, { id: 5 }] }), true);
assert.strictEqual(answered("sources", { sources: [{ id: 9 }] }), true, "an own upload is enough");
assert.strictEqual(answered("sources", { guides: [], sources: [] }), false, "at least one source");
assert.strictEqual(answered("mode", { mode: "step" }), true);
assert.strictEqual(answered("mode", {}), false);

// Prefill the format's own blanks, never over something already written.
const fields = ["School", "Student Teacher", "Learning Area", "Grade Level"].map((label, i) => ({ field_key: `f${i}`, label }));
const answers = { school: "SNHS", studentTeacher: "Ana Cruz", subject: "ICT", levelType: "k12", grade: "Grade 7", section: "Section A" };
const filled = ctx.prefillFieldValues(fields, answers, {});
assert.deepStrictEqual({ ...filled }, { f0: "SNHS", f1: "Ana Cruz", f2: "ICT", f3: "Grade 7 · Section A" });
const kept = ctx.prefillFieldValues(fields, answers, { f0: "Kept" });
assert.ok(!("f0" in kept));
const college = ctx.prefillFieldValues([{ field_key: "g", label: "Grade Level & Section" }],
  { levelType: "college", program: "BSIT", year: "2nd Year", section: "A" }, {});
assert.strictEqual(college.g, "BSIT · 2nd Year · A");

// Format groups: students see built-ins and their teachers' formats.
const formats = [{ id: 1, is_builtin: true, owner_id: 9 }, { id: 2, is_builtin: false, owner_id: 5 }, { id: 3, is_builtin: false, owner_id: 7 }];
const g = ctx.formatGroups(formats, { id: 7, role: "student" });
assert.deepStrictEqual([g.builtin.length, g.teacher.length, g.mine.length], [1, 2, 0]);
assert.strictEqual(ctx.formatGroups([formats[0]], { id: 7, role: "student" }).teacher.length, 0);
const t = ctx.formatGroups(formats, { id: 5, role: "teacher" });
assert.deepStrictEqual([t.builtin.length, t.teacher.length, t.mine.length], [1, 0, 1]);

assert.strictEqual(ctx.runDraftKey("abc"), "alignedDraft:v2:run:abc");
assert.strictEqual(ctx.rememberKey(12), "alignedFlowMemory:v1:12");
console.log("flow steps OK");
