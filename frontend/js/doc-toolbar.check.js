// Self-check for the document zoom ladder. Run: node frontend/js/doc-toolbar.check.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "doc-toolbar.js"), "utf8"), ctx);
const step = ctx.docZoomStepIndex;
const steps = vm.runInContext("DOC_ZOOM_STEPS", ctx);
const at = (scale) => steps.indexOf(scale);

// From Fit, + and − move to the nearest ladder step past the current scale.
assert.strictEqual(step(0.82, 1), at(0.9));
assert.strictEqual(step(0.82, -1), at(0.8));
// A phone's Fit (19%) is below the smallest step: − must not enlarge the page.
assert.strictEqual(step(0.19, -1), null);
assert.strictEqual(step(0.19, 1), at(0.5));
// At either end of the ladder there is nowhere further to go.
assert.strictEqual(step(2, 1), null);
assert.strictEqual(step(0.5, -1), null);
console.log("zoom ladder OK");
