// Guided mode: the plan is written one part at a time on the flow's own
// screens, with the big 3D Alan writing beside the student. Clicking Alan
// swaps him for the chat; hiding the chat brings him back. After the parts
// come the quick blanks, then a review, and only then the document.
// The answers live in generator.js (window.Generator), the same values the
// document, saving and exporting use.

export function createGuided(ui) {
  const { G, el, icon, twoLine, stageEl, alanHost, say } = ui;
  let active = false;
  let showing = null; // { key, sync() } for the part on screen
  let redraw = null; // shows the current screen again (after the preview closes)
  let celebrated = false;

  // Preview: the plan so far, in its real document, from any Guided screen.
  const previewBtn = el("button", { type: "button", class: "flow-preview-btn", title: "Preview your plan", "aria-label": "Preview your plan" },
    icon("eye"), el("span", {}, "Preview"));
  previewBtn.addEventListener("click", () => G.openPreview(() => redraw && redraw()));
  const touch = matchMedia("(hover: none)").matches;
  const ASK = touch ? "Tap me" : "Click me";

  // ---- Alan and the chat share the stage ----
  function openChat() {
    if (active) G.openChat();
  }
  alanHost.addEventListener("click", openChat);
  alanHost.addEventListener("keydown", (e) => {
    if (active && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openChat();
    }
  });

  G.generationEvents.addEventListener("chat", (e) => {
    if (!active) return;
    const { open, unread } = e.detail;
    stageEl.classList.toggle("is-chatting", open);
    if (!open && unread) say(`I answered in the chat. ${ASK} to read it.`, "point");
    else if (!open && showing) say(`${ASK} any time you want ideas.`, "write");
  });

  function enter() {
    if (active) return;
    active = true;
    G.mountChat(stageEl);
    stageEl.classList.add("is-guided");
    const top = document.querySelector(".flow-top");
    if (top) top.append(previewBtn);
    alanHost.setAttribute("role", "button");
    alanHost.setAttribute("tabindex", "0");
    alanHost.setAttribute("aria-label", "Ask Alan for help with this part");
  }

  function leave() {
    if (!active) return;
    active = false;
    showing = null;
    G.unmountChat();
    previewBtn.remove();
    stageEl.classList.remove("is-guided", "is-chatting");
    ["role", "tabindex", "aria-label"].forEach((a) => alanHost.removeAttribute(a));
  }

  // ---- the answer boxes ----
  const asText = (v) => (Array.isArray(v) ? v.join("\n") : v == null ? "" : String(v));
  const dayText = (v, i) => (Array.isArray(v) ? (v[i] == null ? "" : String(v[i])) : i === 0 ? asText(v) : "");

  // A box that grows with what is typed, so a long answer never hides in a
  // scrolling sliver.
  function grow(box) {
    box.style.height = "auto";
    box.style.height = `${box.scrollHeight + 2}px`;
  }

  // ---- the formatting toolbox ----
  // Bold, italic, underline, lists, highlight and clear on a part's answer.
  // The styled HTML is stored like a styled document slot (G.setGuidedRich),
  // so it shows in the document, the preview, the saved plan and the export.
  const TOOLS = [
    { cmd: "bold", label: "Bold (Ctrl+B)", mark: () => el("strong", {}, "B") },
    { cmd: "italic", label: "Italic (Ctrl+I)", mark: () => el("em", {}, "I") },
    { cmd: "underline", label: "Underline (Ctrl+U)", mark: () => el("u", {}, "U") },
    { cmd: "insertUnorderedList", label: "Bulleted list", mark: () => icon("list") },
    { cmd: "insertOrderedList", label: "Numbered list", mark: () => el("span", { class: "flow-format-num" }, "1.") },
    { cmd: "highlight", label: "Highlight", mark: () => icon("highlight") },
    { cmd: "clear", label: "Clear formatting", mark: () => icon("clearFormat") },
  ];

  // A contenteditable answer with its toolbar (editor.toolbar). `partOf` says
  // which day it shows (null for a plain part); `onChange` stores it.
  function richEditor(p, partOf, onChange, rows) {
    const editor = el("div", { class: "flow-textarea flow-rich", contenteditable: "true", role: "textbox",
      "aria-multiline": "true", spellcheck: "true", style: `min-height: ${rows * 27 + 28}px` });
    const buttons = TOOLS.map((t) => el("button", { type: "button", class: "flow-format-btn", "data-cmd": t.cmd,
      title: t.label, "aria-label": t.label, "aria-pressed": "false" }, t.mark()));
    editor.toolbar = el("div", { class: "flow-format", role: "toolbar", "aria-label": "Format this answer" }, buttons);

    const highlighted = () => {
      const node = (window.getSelection() || {}).anchorNode;
      const at = node && (node.nodeType === 1 ? node : node.parentElement);
      return !!(at && editor.contains(at) && at.closest(".hl-yellow"));
    };
    const states = () => buttons.forEach((b) => {
      const cmd = b.dataset.cmd;
      const on = cmd === "highlight" ? highlighted() : cmd === "clear" ? false : document.queryCommandState(cmd);
      b.setAttribute("aria-pressed", String(!!on));
    });
    const changed = () => { onChange(editor); states(); ui.refresh(); };

    // Text just pasted, as character offsets in the answer, so one click on a
    // list tool turns every pasted line into an item; any other key or click forgets it.
    let pasted = null;
    const caretOffset = () => {
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount || !editor.contains(sel.anchorNode)) return null;
      const r = document.createRange();
      r.selectNodeContents(editor);
      r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
      return r.toString().length;
    };
    // Offsets ignore line breaks, so `from` at a line's end is also the next
    // line's start: `startAfter` picks the next line (a paste's first line).
    const selectChars = (from, to, startAfter = false) => {
      const range = document.createRange();
      const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
      let seen = 0, started = false, node;
      while ((node = walker.nextNode())) {
        const len = node.textContent.length;
        if (!started && (startAfter ? seen + len > from : seen + len >= from)) { range.setStart(node, from - seen); started = true; }
        if (started && seen + len >= to) { range.setEnd(node, to - seen); break; }
        seen += len;
      }
      if (!started) return false;
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return true;
    };

    function run(cmd) {
      editor.focus();
      const sel = window.getSelection();
      if (cmd === "highlight") G.applySpanClass(["hl-"], highlighted() ? "hl-none" : "hl-yellow");
      else if (cmd === "clear") {
        if (sel && !sel.isCollapsed) G.applySpanClass(["hl-", "fc-", "fs-"], "");
        document.execCommand("removeFormat", false, null);
      } else {
        const list = cmd === "insertUnorderedList" || cmd === "insertOrderedList";
        if (list && pasted && sel && sel.isCollapsed && caretOffset() === pasted.to) selectChars(pasted.from, pasted.to, true);
        // Chrome leaves the caret at the start of the line after a list
        // command, so Enter would split it: the caret goes back where it was
        // (a line with text only; on an empty line Chrome's caret is right).
        const at = sel && sel.anchorNode;
        const keep = list && sel.isCollapsed && at && at.nodeType === 3 && at.textContent.trim() ? caretOffset() : null;
        document.execCommand(cmd, false, null);
        if (keep !== null) selectChars(keep, keep);
      }
      pasted = null;
      changed();
    }

    buttons.forEach((b) => {
      // Keep the selection in the answer when a tool is clicked.
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("click", () => run(b.dataset.cmd));
    });

    editor.addEventListener("keydown", (e) => {
      const mod = e.ctrlKey || e.metaKey;
      // Ctrl+Shift+8 bullets, Ctrl+Shift+7 numbers (as in Google Docs).
      if (mod && e.shiftKey && (e.code === "Digit8" || e.code === "Digit7")) {
        e.preventDefault();
        run(e.code === "Digit8" ? "insertUnorderedList" : "insertOrderedList");
        return;
      }
      if (!["Shift", "Control", "Meta", "Alt"].includes(e.key)) pasted = null;
      // Enter on an empty bullet ends the list (the browser alone keeps adding bullets).
      if (e.key === "Enter" && !e.shiftKey && !mod) {
        const sel = window.getSelection();
        const node = sel && sel.anchorNode;
        const li = node && (node.nodeType === 1 ? node : node.parentElement).closest("li");
        if (li && editor.contains(li) && !li.textContent.trim()) {
          e.preventDefault();
          run(li.parentElement.tagName === "OL" ? "insertOrderedList" : "insertUnorderedList");
        }
      }
    });
    editor.addEventListener("mousedown", () => { pasted = null; });

    // "- " or "* " at the start of a line starts a bulleted list, "1. " a numbered one.
    function autoList(e) {
      if (e.inputType !== "insertText" || e.data !== " ") return false;
      const sel = window.getSelection();
      const node = sel && sel.anchorNode;
      if (!node || node.nodeType !== 3 || !sel.isCollapsed || node.parentElement.closest("li")) return false;
      const before = node.textContent.slice(0, sel.anchorOffset).replace(/ /g, " ");
      const marker = { "- ": "insertUnorderedList", "* ": "insertUnorderedList", "1. ": "insertOrderedList" }[before];
      // Only at the start of a line: a line break, a list or a block (or the answer's edge) before it.
      const prev = node.previousSibling;
      if (!marker || (prev && !/^(BR|UL|OL|DIV|P)$/.test(prev.nodeName))) return false;
      const r = document.createRange();
      r.setStart(node, 0);
      r.setEnd(node, sel.anchorOffset);
      sel.removeAllRanges();
      sel.addRange(r);
      document.execCommand("delete", false, null);
      document.execCommand(marker, false, null);
      return true;
    }

    editor.addEventListener("input", (e) => {
      autoList(e);
      changed();
    });
    editor.addEventListener("keyup", states);
    editor.addEventListener("mouseup", states);
    // Pasted text comes in plain (styling from other sites wouldn't survive export anyway).
    editor.addEventListener("paste", (e) => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text/plain").replace(/\r\n?/g, "\n");
      const from = caretOffset();
      document.execCommand("insertText", false, text);
      const to = caretOffset();
      pasted = from !== null && to !== null && text.includes("\n") ? { from, to } : null;
    });

    // Shows the stored answer: its formatting if it has any, else its lines.
    editor.fill = () => {
      const part = partOf();
      const rich = G.guidedRich(p.key, part);
      if (rich) {
        editor.innerHTML = rich;
        return;
      }
      const text = part === null ? asText(G.fieldValue(p.key)) : dayText(G.fieldValue(p.key), part);
      editor.textContent = "";
      text.split("\n").forEach((line, i) => editor.append(...(i ? [el("br"), line] : [line])));
    };
    editor.fill();
    return editor;
  }

  // The box(es) as placed on the screen: a formatted answer brings its toolbar.
  const fieldNode = (input) => [input.toolbar || "", el("div", { class: "flow-field" }, input)];

  function box(p, part, { compact = false } = {}) {
    const multi = p.type !== "text" || part !== null;
    // A part's own screen gets the formatting toolbox; the quick blanks stay plain.
    if (multi && !compact) {
      const editor = richEditor(p, () => part, (ed) => G.setGuidedRich(p.key, ed, part), part !== null ? 3 : 6);
      editor.addEventListener("focus", () => G.setGuidedDay(part));
      return editor;
    }
    const input = multi
      ? el("textarea", { class: "flow-textarea", rows: compact ? "2" : part !== null ? "3" : "6", maxlength: "6000" })
      : el("input", { type: "text", maxlength: "500", autocomplete: "off" });
    input.value = part === null ? asText(G.fieldValue(p.key)) : dayText(G.fieldValue(p.key), part);
    input.addEventListener("focus", () => G.setGuidedDay(part));
    input.addEventListener("input", () => {
      G.setGuidedValue(p.key, input.value, part);
      if (multi) grow(input);
      ui.refresh();
    });
    if (multi) requestAnimationFrame(() => grow(input));
    return input;
  }

  // A weekly part (one answer per day) gets one box and a day picker instead
  // of a box per day. "From … to …" lets one answer cover several days, for a
  // part that repeats across the week.
  function dayEditor(p, opts = {}) {
    const days = p.days;
    const filled = (d) => !!dayText(G.fieldValue(p.key), d).trim();
    let from = Math.max(0, days.findIndex((_, d) => !filled(d)));
    let to = from;
    const id = `guided-${p.key}`;
    const options = () => days.map((d, i) => el("option", { value: String(i) }, d));
    const fromSel = el("select", { id: `${id}-from` }, options());
    const toSel = el("select", { id: `${id}-to`, "aria-label": "Through" }, options());
    // On a part's own screen the day's answer is formatted, written to every day in the range.
    const rich = !opts.compact;
    const input = rich
      ? richEditor(p, () => from, (ed) => { for (let d = from; d <= to; d++) G.setGuidedRich(p.key, ed, d); }, 5)
      : el("textarea", { class: "flow-textarea", rows: "2", maxlength: "6000" });
    input.id = id;
    if (rich) input.setAttribute("aria-label", `${p.label}: answer for the chosen day`);

    function paint() {
      fromSel.value = String(from);
      toSel.value = String(to);
      if (rich) {
        if (document.activeElement !== input) input.fill();
        return;
      }
      const text = dayText(G.fieldValue(p.key), from);
      if (input.value !== text) input.value = text;
      grow(input);
    }
    fromSel.addEventListener("change", () => {
      from = parseInt(fromSel.value, 10);
      if (to < from) to = from;
      G.setGuidedDay(from);
      paint();
    });
    toSel.addEventListener("change", () => {
      to = Math.max(from, parseInt(toSel.value, 10));
      paint();
    });
    input.addEventListener("focus", () => G.setGuidedDay(from));
    // The formatted editor stores itself (richEditor's onChange).
    if (!rich) {
      input.addEventListener("input", () => {
        for (let d = from; d <= to; d++) G.setGuidedValue(p.key, input.value, d);
        grow(input);
        paint();
        ui.refresh();
      });
    }
    G.setGuidedDay(from);
    requestAnimationFrame(paint);
    const picker = el("div", { class: "flow-day-picker" },
      el("label", { class: "flow-label", for: fromSel.id }, opts.label ? `${p.label}: day` : "Day"),
      el("div", { class: "flow-field flow-select" }, fromSel),
      el("span", { class: "flow-day-to" }, "to"),
      el("div", { class: "flow-field flow-select" }, toSel));
    return { node: [picker, ...fieldNode(input)], sync: paint };
  }

  // Every box for one part: one, or the day editor for a weekly part.
  function editors(p, opts = {}) {
    if (p.days && p.days.length > 1) return dayEditor(p, opts);
    const boxes = [];
    const id = (i) => `guided-${p.key}${i === null ? "" : `-${i}`}`;
    let node;
    if (p.days) {
      const input = box(p, 0, opts);
      input.id = id(0);
      boxes.push([input, 0]);
      node = [opts.label ? el("label", { class: "flow-label", for: input.id }, p.label) : "", ...fieldNode(input)];
    } else {
      const input = box(p, null, opts);
      input.id = id(null);
      if (!opts.label) input.setAttribute("aria-labelledby", "flow-question");
      boxes.push([input, null]);
      node = [opts.label ? el("label", { class: "flow-label", for: input.id }, p.label) : "", ...fieldNode(input)];
    }
    const sync = () => boxes.forEach(([input, part]) => {
      // A formatted answer repaints from the stored HTML (after "Clear this part", say).
      if (input.fill) {
        if (document.activeElement !== input) input.fill();
        return;
      }
      const v = G.fieldValue(p.key);
      const text = part === null ? asText(v) : dayText(v, part);
      if (input.value !== text) {
        input.value = text;
        if (input.tagName === "TEXTAREA") grow(input);
      }
    });
    return { node, sync };
  }

  // The lesson proper is taught from the plan's references: they show under
  // the box, each link opening in a new tab.
  function referencesBox(refs) {
    const box = el("section", { class: "flow-refs", "aria-label": "Your references" },
      el("p", { class: "flow-label" }, "Your references"));
    if (!refs.length) {
      box.append(el("p", { class: "flow-help" },
        "None yet. Add them in the References part, so your discussion comes from real sources."));
      return box;
    }
    const list = el("ul", { class: "flow-refs-list" });
    refs.forEach((ref) => {
      const url = (ref.match(/https?:\/\/[^\s<>"')\]]+/) || [""])[0].replace(/[.,;]+$/, "");
      const item = el("li", {}, url ? ref.slice(0, ref.indexOf(url)) : ref);
      if (url) item.append(el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, url));
      list.append(item);
    });
    box.append(list, el("p", { class: "flow-help" }, "Your discussion should come from these sources."));
    return box;
  }

  // ---- screens ----
  function part(i) {
    const parts = G.guidedParts();
    if (!parts.length) return quick();
    enter();
    i = Math.max(0, Math.min(i, parts.length - 1));
    const p = parts[i];
    redraw = () => part(i);
    G.setGuidedIndex(i);
    G.setAnswers({ guidedAt: "part" });
    const last = i === parts.length - 1;
    ui.screen({
      count: `Part ${i + 1} of ${parts.length}`,
      at: (i + 1) / (parts.length + 2),
      q: p.label,
      help: p.locked
        ? `Your teacher locked this part, so it's yours to write. ${ASK} if you'd like help thinking it through.`
        : `${p.type === "list" ? "One item per line. " : ""}Write it in your own words, or ${ASK.toLowerCase()} for ideas.`,
      body: (answer) => {
        const ed = editors(p);
        showing = { key: p.key, sync: ed.sync };
        const tools = el("div", { class: "flow-part-tools" });
        const clear = el("button", { type: "button", class: "flow-back flow-more flow-clear" }, icon("eraser"), "Clear this part");
        clear.addEventListener("click", () => {
          if (p.days) p.days.forEach((_, d) => G.setGuidedValue(p.key, "", d));
          else G.setGuidedValue(p.key, "");
          ed.sync();
          ui.refresh();
        });
        tools.append(clear);
        answer.append(...[].concat(ed.node), tools);
        const refs = G.lessonReferences(p.key);
        if (refs) answer.append(referencesBox(refs));
      },
      next: last ? "Done with the parts" : "Next part",
      canNext: () => G.isFieldComplete(p.key),
      onNext: () => (last ? quick() : part(i + 1)),
      onBack: () => (i > 0 ? part(i - 1) : backToSetup()),
      sayText: p.locked
        ? `${p.label} is yours to write. I'll help you think it through.`
        : `Your turn: ${p.label}. ${ASK} if you'd like ideas.`,
      pose: p.locked ? "think" : "write",
    });
  }

  function quick() {
    const blanks = G.quickParts();
    const parts = G.guidedParts();
    if (!blanks.length) return review();
    enter();
    showing = null;
    redraw = quick;
    G.setAnswers({ guidedAt: "quick" });
    ui.screen({
      count: "Quick details",
      at: (parts.length + 1) / (parts.length + 2),
      q: "A few quick blanks",
      help: "Short details I couldn't fill in from your answers. Fill in the ones your plan needs.",
      body: (answer) => {
        const cells = blanks.map((p) => el("div", { class: "flow-cell" }, editors(p, { compact: true, label: true }).node));
        answer.append(el("div", { class: "flow-row" }, cells));
      },
      next: "Review my plan",
      onNext: review,
      onBack: () => part(parts.length - 1),
      sayText: "Nearly there. Just these short ones.",
      pose: "check",
    });
  }

  function preview(p) {
    const v = G.fieldValue(p.key);
    const text = p.days
      ? p.days.map((d, i) => (dayText(v, i).trim() ? `${d}: ${dayText(v, i)}` : "")).filter(Boolean).join(" · ")
      : asText(v);
    return text.trim().replace(/\s+/g, " ") || "Not written yet";
  }

  function review() {
    const parts = G.guidedParts();
    enter();
    showing = null;
    redraw = review;
    G.setAnswers({ guidedAt: "review" });
    const done = parts.every((p) => G.isFieldComplete(p.key));
    // Every part written: the plan is made, so celebrate (once per visit).
    if (done && !celebrated) {
      celebrated = true;
      G.celebrate();
    }
    ui.screen({
      count: "Review",
      at: 1,
      q: done ? "Your plan is written" : "Almost there",
      help: done
        ? "Click a part to change it. Then open the document to check the layout, save and export."
        : "A part is still empty. Click it to finish it, or open the document as it is.",
      body: (answer) => {
        const list = el("div", { class: "flow-details" });
        parts.forEach((p, i) => {
          const row = el("button", { type: "button", class: `flow-detail${G.isFieldComplete(p.key) ? "" : " is-missing"}` },
            twoLine(p.label, preview(p)), icon("edit"));
          row.addEventListener("click", () => part(i));
          list.append(row);
        });
        answer.append(list);
      },
      next: "Open the document",
      onNext: () => {
        leave();
        G.showDocument();
      },
      onBack: () => (G.quickParts().length ? quick() : part(parts.length - 1)),
      sayText: done ? "Great work! Have a look before you save it." : "So close. One part still needs you.",
      pose: done ? "celebrate" : "point",
    });
  }

  function backToSetup() {
    leave();
    ui.backToMode();
  }

  // Where the student left off: a part, the quick blanks, or the review.
  function resume() {
    const at = G.getAnswers().guidedAt;
    if (at === "review") return review();
    if (at === "quick") return quick();
    return part(G.guidedIndex());
  }

  return { start: () => part(G.guidedIndex()), resume, leave, isActive: () => active };
}
