// Self-check for the rubric table rules. Run: node frontend/js/rubric.check.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "rubric.js"), "utf8"), ctx);
const blocks = (text) => JSON.parse(JSON.stringify(ctx.rubricBlocks(text)));

const HEAD = "Criteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)";
assert.deepStrictEqual(blocks(`Rubric:\n${HEAD}\nAccuracy | a | b | c | d\nTotal: 8 points`), [
  { line: "Rubric:" },
  { rows: [["Criteria", "Excellent (4)", "Good (3)", "Fair (2)", "Needs Improvement (1)"], ["Accuracy", "a", "b", "c", "d"]] },
  { line: "Total: 8 points" },
]);

// markdown_rule_dropped: a pasted |---| rule doesn't split or show in the table.
assert.deepStrictEqual(blocks("A | B | C\n|---|---|---|\nx | y | z"), [{ rows: [["A", "B", "C"], ["x", "y", "z"]] }]);
assert.deepStrictEqual(blocks("| A | B | C |\n| x | y | z |"), [{ rows: [["A", "B", "C"], ["x", "y", "z"]] }]);

// A lone row, or lines of two cells, stay text.
assert.deepStrictEqual(blocks("Only | one | row"), [{ line: "Only | one | row" }]);
assert.deepStrictEqual(blocks("Name | Section\nA | B"), [{ line: "Name | Section" }, { line: "A | B" }]);
assert.deepStrictEqual(blocks(""), []);

// The shared cell rule matches the Word export's: 3+ cells, bullets ignored.
assert.deepStrictEqual(Array.from(ctx.rubricCells("• a | b | c")), ["a", "b", "c"]);
console.log("rubric OK");
