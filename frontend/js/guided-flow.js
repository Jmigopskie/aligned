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

  // A suggestion from the chat landed in this part: show it in the boxes.
  G.generationEvents.addEventListener("field", (e) => {
    if (!active || !showing || e.detail.key !== showing.key) return;
    showing.sync();
    ui.refresh();
  });

  function enter() {
    if (active) return;
    active = true;
    G.mountChat(stageEl);
    stageEl.classList.add("is-guided");
    alanHost.setAttribute("role", "button");
    alanHost.setAttribute("tabindex", "0");
    alanHost.setAttribute("aria-label", "Ask Alan for help with this part");
  }

  function leave() {
    if (!active) return;
    active = false;
    showing = null;
    G.unmountChat();
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

  function box(p, part, { compact = false } = {}) {
    const multi = p.type !== "text" || part !== null;
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

  // Every box for one part: one, or one per day for a weekly part.
  function editors(p, opts = {}) {
    const boxes = [];
    const id = (i) => `guided-${p.key}${i === null ? "" : `-${i}`}`;
    let node;
    if (p.days) {
      node = el("div", { class: "flow-row flow-days" }, p.days.map((day, i) => {
        const input = box(p, i, opts);
        input.id = id(i);
        boxes.push([input, i]);
        return el("div", { class: "flow-cell" }, el("label", { class: "flow-label", for: input.id }, day), el("div", { class: "flow-field" }, input));
      }));
    } else {
      const input = box(p, null, opts);
      input.id = id(null);
      if (!opts.label) input.setAttribute("aria-labelledby", "flow-question");
      boxes.push([input, null]);
      node = [opts.label ? el("label", { class: "flow-label", for: input.id }, p.label) : "", el("div", { class: "flow-field" }, input)];
    }
    const sync = () => boxes.forEach(([input, part]) => {
      const v = G.fieldValue(p.key);
      const text = part === null ? asText(v) : dayText(v, part);
      if (input.value !== text) {
        input.value = text;
        if (input.tagName === "TEXTAREA") grow(input);
      }
    });
    return { node, sync };
  }

  // ---- screens ----
  function part(i) {
    const parts = G.guidedParts();
    if (!parts.length) return quick();
    enter();
    i = Math.max(0, Math.min(i, parts.length - 1));
    const p = parts[i];
    G.setGuidedIndex(i);
    G.setAnswers({ guidedAt: "part" });
    const last = i === parts.length - 1;
    ui.screen({
      count: `Part ${i + 1} of ${parts.length}`,
      at: (i + 1) / (parts.length + 2),
      q: p.label,
      help: `${p.type === "list" ? "One item per line. " : ""}Write it in your own words, or ${ASK.toLowerCase()} for ideas.`,
      body: (answer) => {
        const ed = editors(p);
        showing = { key: p.key, sync: ed.sync };
        const clear = el("button", { type: "button", class: "flow-back flow-more flow-clear" }, icon("eraser"), "Clear this part");
        clear.addEventListener("click", () => {
          if (p.days) p.days.forEach((_, d) => G.setGuidedValue(p.key, "", d));
          else G.setGuidedValue(p.key, "");
          ed.sync();
          ui.refresh();
        });
        answer.append(...[].concat(ed.node), clear);
      },
      next: last ? "Done with the parts" : "Next part",
      canNext: () => G.isFieldComplete(p.key),
      onNext: () => (last ? quick() : part(i + 1)),
      onBack: () => (i > 0 ? part(i - 1) : backToSetup()),
      sayText: `Your turn: ${p.label}. ${ASK} if you'd like ideas.`,
      pose: "write",
    });
  }

  function quick() {
    const blanks = G.quickParts();
    const parts = G.guidedParts();
    if (!blanks.length) return review();
    enter();
    showing = null;
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
    G.setAnswers({ guidedAt: "review" });
    const done = parts.every((p) => G.isFieldComplete(p.key));
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
