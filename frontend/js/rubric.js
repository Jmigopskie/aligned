// A performance task's rubric is stored as rows of cells separated by " | "
// (the assessment prompt asks for that; a teacher can type it). Every place a
// plan is shown draws two or more such rows as a table, and the editable
// document reads a table back into rows, so the stored value stays text and
// the Word export (docx_service.pipe_rows_to_tables) makes the same table.
// No DOM at load, so rubric.check.js can run the rules under node.

const RUBRIC_RULE = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$/;

// The cells of a table row, or [] for a line that isn't one (fewer than three
// cells, or a markdown |---| rule). Same rule as docx_service.pipe_cells.
function rubricCells(line) {
  let s = String(line || "").replace(/^\s*[•·▪-]\s+/, "").trim();
  if (RUBRIC_RULE.test(s)) return [];
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  const cells = s.split("|").map((c) => c.trim());
  return cells.length >= 3 ? cells : [];
}

// The text as blocks: {rows: [[cell, ...], ...]} for 2+ consecutive table rows
// (|---| rules inside dropped), {line} for everything else.
function rubricBlocks(text) {
  const out = [];
  const lines = String(text || "").split("\n");
  if (lines.length === 1 && !lines[0]) return out;
  let i = 0;
  while (i < lines.length) {
    const rows = [];
    let j = i;
    while (j < lines.length && (rubricCells(lines[j]).length || (rows.length && RUBRIC_RULE.test(lines[j])))) {
      const cells = rubricCells(lines[j]);
      if (cells.length) rows.push(cells);
      j += 1;
    }
    if (rows.length >= 2) {
      out.push({ rows });
      i = j;
    } else {
      out.push({ line: lines[i] });
      i += 1;
    }
  }
  return out;
}

// For the read-only previews, which build HTML strings: the text with its
// rubric rows as a table (each other line a <div>), escaped; null when the
// text has no rubric, so the caller renders it as it always did.
function rubricHtml(text) {
  const blocks = rubricBlocks(text);
  if (!blocks.some((b) => b.rows)) return null;
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  return blocks.map((b) => {
    if (!b.rows) return `<div>${esc(b.line)}</div>`;
    const width = Math.max(...b.rows.map((r) => r.length));
    const rows = b.rows.map((cells, r) => {
      const tag = r === 0 ? "th" : "td";
      return `<tr>${Array.from({ length: width }, (_, c) => `<${tag}>${esc(cells[c] || "")}</${tag}>`).join("")}</tr>`;
    });
    return `<table class="lp-rubric">${rows.join("")}</table>`;
  }).join("");
}

// Writes text into a slot: rubric rows as a table, everything else exactly as
// el.textContent = text would (the slots are white-space: pre-wrap).
function setSlotText(el, text) {
  const blocks = rubricBlocks(text);
  if (!blocks.some((b) => b.rows)) {
    el.textContent = text;
    return;
  }
  el.textContent = "";
  let pending = [];
  const flush = () => {
    if (pending.length) el.append(document.createTextNode(pending.join("\n")));
    pending = [];
  };
  blocks.forEach((b) => {
    if (!b.rows) {
      pending.push(b.line);
      return;
    }
    flush();
    const table = document.createElement("table");
    table.className = "lp-rubric";
    const width = Math.max(...b.rows.map((r) => r.length));
    b.rows.forEach((cells, r) => {
      const tr = table.insertRow();
      for (let c = 0; c < width; c += 1) {
        const cell = document.createElement(r === 0 ? "th" : "td");
        cell.textContent = cells[c] || "";
        tr.append(cell);
      }
    });
    el.append(table);
  });
  flush();
}

// The inverse: a slot's text with any table read back as one " | " row per
// line. Without a table it is exactly el.textContent.
function slotText(el) {
  if (!el.querySelector || !el.querySelector("table")) return el.textContent;
  const parts = [];
  const walk = (node) => {
    node.childNodes.forEach((child) => {
      if (child.nodeType === 3) parts.push(child.data);
      else if (child.nodeType === 1 && child.tagName === "TABLE") {
        const rows = Array.from(child.rows).map((tr) => Array.from(tr.cells).map((c) => c.textContent.trim()).join(" | "));
        parts.push(`\n${rows.join("\n")}\n`);
      } else if (child.nodeType === 1) walk(child);
    });
  };
  walk(el);
  return parts.join("").replace(/\n{2,}/g, "\n").replace(/^\n|\n$/g, "");
}
