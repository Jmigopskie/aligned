// Self-check for the Create Lesson Plan flow's step rules. Run: node frontend/js/setup-flow-steps.check.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "setup-flow-steps.js"), "utf8"), ctx);
const get = (name) => vm.runInContext(name, ctx);

// Order: students get 12 steps; teachers skip the cooperating teacher.
const student = ctx.flowSteps("student");
assert.deepStrictEqual(Array.from(student), Array.from(get("FLOW_STEP_IDS")));
assert.strictEqual(student.length, 12);
const teacher = ctx.flowSteps("teacher");
assert.strictEqual(teacher.length, 11);
assert.ok(!teacher.includes("coop"));
assert.strictEqual(get("FLOW_POSES").prevTopic, "think");
assert.strictEqual(get("FLOW_POSES").format, "hi");

// Required answers.
const answered = ctx.isStepAnswered;
assert.strictEqual(answered("duration", { durationMinutes: 45 }), true);
assert.strictEqual(answered("duration", { durationMinutes: 4 }), false);
assert.strictEqual(answered("duration", { durationMinutes: 241 }), false);
assert.strictEqual(answered("duration", { durationMinutes: "45" }), false);
assert.strictEqual(answered("class", { levelType: "college", program: "BSIT" }), false);
assert.strictEqual(answered("class", { levelType: "college", program: "BSIT", year: "2nd Year" }), true);
assert.strictEqual(answered("class", { levelType: "k12", grade: "Grade 7" }), true);
assert.strictEqual(answered("prevTopic", {}), true);
assert.strictEqual(answered("topic", { topic: "  " }), false);
assert.strictEqual(answered("format", { formatId: 3 }), true);

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
