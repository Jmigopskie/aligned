// Create Lesson Plan: Alan asks one question at a time on the left while the
// big 3D Alan reacts on the right. The answers go to generator.js through
// window.Generator; the step order and rules come from setup-flow-steps.js.

const flow = document.getElementById("flow");
const G = window.Generator;
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

// The 2D picture that stands in for each pose when three.js can't load.
const PNG_FOR_POSE = {
  hi: "wave", wave: "wave", present: "idle", idle: "idle", point: "point", check: "check",
  think: "think", reading: "check", idea: "idea", loading: "loading", celebrate: "celebrate",
};

const COPY = {
  format: {
    q: "Which lesson plan format, and which school?",
    help: "Pick the format your school uses, then type the school's name.",
    say: "Hi! I'm Alan. Let's build your lesson plan together, a few questions at a time.",
  },
  people: {
    q: "Who's teaching this lesson?",
    help: "As the names should appear on the plan.",
    say: "I'll put these names wherever the format asks for them.",
  },
  class: {
    q: "Which class is this for?",
    help: "",
    say: "Knowing the class helps me pitch the activities right.",
  },
  subject: {
    q: "What subject, and how long is the discussion?",
    help: "Most discussions run 45 minutes.",
    say: "I'll make the times in your procedure add up to this.",
  },
  topics: {
    q: "What's the lesson about?",
    help: "The last and next topics help me connect the recap and the assignment.",
    say: "Tell me where this lesson sits, so the recap and the assignment line up.",
  },
  sources: {
    q: "Which Budget of Work should I follow?",
    help: "Add your own supplementary sources too, if you have any. Only you and I see them.",
    say: "I'll follow the Budget of Work closely, and read your sources too.",
  },
  mode: {
    q: "How do you want to write it?",
    help: "",
    say: "Last one! How do you want to write it?",
  },
};

let user = null;
let steps = [];
let index = 0;
let alan = { setPose() {} };
let refresh = () => {};

// ---- small builders ----
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  });
  children.flat().forEach((c) => c != null && node.append(c));
  return node;
}

function icon(name) {
  const span = el("span", { "aria-hidden": "true" });
  span.innerHTML = Icons[name] || "";
  return span;
}

// A one-line answer that saves as it is typed. `alt` adds a toggle such as
// "This is the first lesson" that clears and locks the box.
function textAnswer(key, { placeholder = "", label, alt } = {}) {
  const answers = G.getAnswers();
  const id = `flow-${key}`;
  const input = el("input", {
    id, type: "text", maxlength: "200", autocomplete: "off", placeholder,
    "aria-labelledby": label ? null : "flow-question",
  });
  input.value = answers[key] || "";
  input.addEventListener("input", () => {
    G.setAnswers({ [key]: input.value });
    refresh();
  });
  const parts = [];
  if (label) parts.push(el("label", { class: "flow-label", for: id }, label));
  parts.push(el("div", { class: "flow-field" }, input));
  if (alt) {
    const on = !!answers[alt.flag];
    const toggle = el("button", { type: "button", class: "flow-choice flow-alt", "aria-pressed": String(on) },
      el("span", {}, alt.label), tick());
    const sync = (pressed) => {
      toggle.setAttribute("aria-pressed", String(pressed));
      input.disabled = pressed;
    };
    sync(on);
    toggle.addEventListener("click", () => {
      const pressed = toggle.getAttribute("aria-pressed") !== "true";
      G.setAnswers(pressed ? { [alt.flag]: true, [key]: "" } : { [alt.flag]: false });
      if (pressed) input.value = "";
      sync(pressed);
      refresh();
      if (!pressed) input.focus();
    });
    parts.push(toggle);
  }
  return parts;
}

function tick() {
  const t = icon("check");
  t.className = "flow-choice-tick";
  return t;
}

// One-of-several answers. `options` are {value, label}.
function choiceAnswer(options, current, onPick, label) {
  const group = el("div", { class: "flow-choices", role: "group", "aria-label": label || null,
    "aria-labelledby": label ? null : "flow-question" });
  options.forEach((o) => {
    const btn = el("button", { type: "button", class: "flow-choice", "aria-pressed": String(String(o.value) === String(current)) },
      el("span", {}, o.label), tick());
    btn.addEventListener("click", () => {
      group.querySelectorAll(".flow-choice").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      onPick(o.value);
      refresh();
    });
    group.append(btn);
  });
  return group;
}

// The subject, grade and year lists live in generator.html's selects, so the
// flow offers exactly what the page always accepted.
function optionsOf(selectId) {
  return [...document.getElementById(selectId).options]
    .filter((o) => !o.disabled && o.value)
    .map((o) => ({ value: o.value, label: o.textContent.trim() }));
}

// A dropdown in the same tray as the text fields. `options` are {value, label},
// or {group, items: [{value, label}]} for an optgroup.
function selectAnswer(id, label, options, current, onChange, { placeholder = "Choose…", disabled = false } = {}) {
  const select = el("select", { id, disabled });
  select.append(el("option", { value: "", disabled: true }, placeholder));
  const option = (o) => el("option", { value: String(o.value) }, o.label);
  options.forEach((o) => {
    if (o.group) select.append(el("optgroup", { label: o.group }, o.items.map(option)));
    else select.append(option(o));
  });
  select.value = current == null ? "" : String(current);
  if (select.selectedIndex < 0) select.selectedIndex = 0;
  select.addEventListener("change", () => {
    onChange(select.value);
    refresh();
  });
  return [el("label", { class: "flow-label", for: id }, label), el("div", { class: "flow-field flow-select" }, select)];
}

// ---- step 1: the format ----
// A card is only chosen here; Next opens it (G.loadFormat).
let pendingFormatId = null;
// An earlier run that never reached the document. Checked before a new run is
// started, which would otherwise replace it as "the current run".
let resumeOffer = null;

function startNewRun() {
  G.newRun();
  const memory = recall();
  G.setAnswers({
    school: memory.school || "",
    studentTeacher: memory.studentTeacher || user.full_name || "",
    coop: memory.coop || "",
    durationMinutes: 45,
    levelType: "k12",
  });
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function twoLine(title, sub) {
  return el("span", { class: "flow-format-text" }, el("strong", {}, title), sub ? el("small", {}, sub) : "");
}

function formatStep() {
  const wrap = el("div", { class: "flow-answer" });
  const answers = G.getAnswers();
  pendingFormatId = answers.formatId;
  const run = !answers.formatId && resumeOffer;
  if (run) paintResume(wrap, run);
  else paintFormats(wrap);
  return wrap;
}

function paintResume(wrap, run) {
  const carryOn = el("button", { type: "button", class: "flow-choice flow-format" },
    twoLine("Continue where you left off", [run.topic, run.formatName].filter(Boolean).join(" · ") || "Your unfinished plan"),
    icon("arrowRight"));
  carryOn.addEventListener("click", () => {
    location.href = `generator.html?run=${encodeURIComponent(run.runId)}&format_id=${encodeURIComponent(run.formatId)}`;
  });
  const fresh = el("button", { type: "button", class: "flow-choice flow-format" },
    twoLine("Start a new plan", "Pick a format next"), icon("arrowRight"));
  fresh.addEventListener("click", () => {
    resumeOffer = null;
    startNewRun();
    paintFormats(wrap);
  });
  wrap.replaceChildren(el("div", { class: "flow-choices flow-choices-stack" }, carryOn, fresh));
  carryOn.focus();
}

async function paintFormats(wrap) {
  actions.hidden = false;
  wrap.replaceChildren(el("p", { class: "flow-help" }, "Loading formats…"));
  let formats;
  try {
    formats = (await Api.listFormats()).formats || [];
  } catch (err) {
    wrap.replaceChildren(el("p", { class: "flow-error" }, err.message));
    return;
  }
  const groups = formatGroups(formats, user);
  const item = (f, by) => ({ value: f.id, label: by && f.owner_name ? `${f.name} (${f.owner_name})` : f.name });
  const options = [{ group: "Built-in", items: groups.builtin.map((f) => item(f)) }];
  if (user.role === "student") {
    if (groups.teacher.length) options.push({ group: "From your teacher", items: groups.teacher.map((f) => item(f, true)) });
    else say("Join your teacher's class to see the formats they uploaded.", "hi");
  } else if (groups.mine.length) {
    options.push({ group: "Uploaded by you", items: groups.mine.map((f) => item(f)) });
  }
  // In Lesson details the format stays as it is: changing it would reload
  // the plan onto another template.
  const parts = selectAnswer("flow-format", "Lesson plan format", options, pendingFormatId, (v) => {
    pendingFormatId = Number(v);
  }, { placeholder: "Choose a format…", disabled: detailsMode });
  if (user.role !== "student" && !detailsMode) {
    const upload = el("button", { type: "button", class: "flow-back flow-more flow-upload-link" }, icon("upload"), "Upload my school's format");
    upload.addEventListener("click", () => paintUpload(wrap));
    parts.push(upload);
  }
  parts.push(...textAnswer("school", { label: "School", placeholder: "e.g. San Isidro National High School" }));
  wrap.replaceChildren(...parts);
  refresh();
}

// Teachers only: upload a blank format right here, name it, save, carry on.
function paintUpload(wrap) {
  actions.hidden = true;
  errorEl.hidden = true;
  const input = el("input", { type: "file", accept: ".docx,.dotx,.pdf", hidden: true });
  const drop = el("button", { type: "button", class: "flow-drop" }, icon("upload"),
    twoLine("Choose your school's blank format", "or drop it here · .docx, .dotx or .pdf"));
  const back = el("button", { type: "button", class: "flow-back" }, icon("arrowLeft"), "Back to formats");
  back.addEventListener("click", () => {
    say(COPY.format.say, FLOW_POSES.format);
    paintFormats(wrap);
  });
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("is-over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("is-over");
    if (e.dataTransfer.files.length) scan(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => input.files.length && scan(input.files[0]));
  wrap.replaceChildren(drop, input, back);
  drop.focus();

  async function scan(file) {
    errorEl.hidden = true;
    if (!/\.(docx|dotx|pdf)$/i.test(file.name)) {
      showError("Only .docx, .dotx or .pdf files work here.");
      return;
    }
    drop.disabled = true;
    say("I'm reading your format…", "loading");
    try {
      const data = await Api.scanFormat(file);
      if (data.scan_error) throw new Error(data.scan_error);
      paintSave(wrap, data, file.name);
    } catch (err) {
      showError(err.message);
      say(COPY.format.say, FLOW_POSES.format);
      drop.disabled = false;
    }
  }
}

function paintSave(wrap, scanned, filename) {
  say("Got it. Give it a name your students will recognise.", "present");
  const name = el("input", { id: "flow-format-name", type: "text", maxlength: "120", autocomplete: "off" });
  name.value = filename.replace(/\.[^.]+$/, "");
  let share = false;
  const shareBtn = el("button", { type: "button", class: "flow-choice flow-alt", "aria-pressed": "false" },
    el("span", {}, "Share with other teachers"), tick());
  shareBtn.addEventListener("click", () => {
    share = !share;
    shareBtn.setAttribute("aria-pressed", String(share));
  });
  const saveIcon = icon("arrowRight");
  saveIcon.className = "flow-next-icon";
  const save = el("button", { type: "button", class: "flow-next" }, el("span", {}, "Save format"), saveIcon);
  const back = el("button", { type: "button", class: "flow-back" }, icon("arrowLeft"), "Back to formats");
  back.addEventListener("click", () => {
    say(COPY.format.say, FLOW_POSES.format);
    paintFormats(wrap);
  });
  save.addEventListener("click", async () => {
    errorEl.hidden = true;
    if (!name.value.trim()) {
      showError("Give this format a name.");
      name.focus();
      return;
    }
    save.disabled = true;
    say("Finding the fields in your format. This can take a minute.", "loading");
    try {
      const data = await Api.createFormat({
        name: name.value.trim(),
        is_public: share,
        source_temp_token: scanned.source_temp_token,
        source_filename: scanned.source_filename,
      });
      pendingFormatId = data.format.id;
      actions.hidden = false;
      go(1);
    } catch (err) {
      // The server's wording points at the full format editor, which isn't
      // here, so say what to do from this screen instead.
      showError("I couldn't find the fillable fields in this file. Try saving again, or set it up on the Formats page.");
      say("That didn't work. You can try again, or pick a built-in format.", "unsure");
      save.disabled = false;
    }
  });
  wrap.replaceChildren(
    el("label", { class: "flow-label", for: "flow-format-name" }, "Format name"),
    el("div", { class: "flow-field" }, name),
    shareBtn,
    el("div", { class: "flow-actions" }, back, save),
  );
  name.focus();
}

// ---- answers per step ----
const STEPS = {
  format: formatStep,
  people: () => [
    ...textAnswer("studentTeacher", { label: "Your name", placeholder: "e.g. Ana Cruz" }),
    ...(user.role === "student"
      ? textAnswer("coop", { label: "Cooperating Teacher / Subject Teacher (optional)", placeholder: "e.g. Juan Dela Cruz" })
      : []),
  ],
  class: () => {
    const wrap = el("div", { class: "flow-answer" });
    const paint = () => {
      const a = G.getAnswers();
      const parts = selectAnswer("flow-grade", "Grade level", gradeOptions(), gradeValue(a), (v) => {
        const wasCollege = G.getAnswers().levelType === "college";
        G.setAnswers(answersForGrade(v));
        // Only college asks for a program, so repaint when that changes.
        if (wasCollege !== (G.getAnswers().levelType === "college")) {
          paint();
          wrap.querySelector("#flow-grade").focus();
        }
      }, { placeholder: "Choose a grade level…" });
      if (a.levelType === "college") parts.push(...textAnswer("program", { label: "Program", placeholder: "e.g. BS Information Technology" }));
      parts.push(...textAnswer("section", { label: "Section (optional)", placeholder: "e.g. Sampaguita" }));
      wrap.replaceChildren(...parts);
    };
    paint();
    return wrap;
  },
  subject: () => {
    const a = G.getAnswers();
    const custom = a.durationMinutes && !DURATION_CHOICES.includes(a.durationMinutes);
    const other = el("div", { class: "flow-field", hidden: !custom });
    const input = el("input", { type: "number", min: "5", max: "240", step: "1", inputmode: "numeric",
      placeholder: "Minutes, e.g. 50", "aria-label": "Minutes" });
    if (custom) input.value = a.durationMinutes;
    input.addEventListener("input", () => {
      G.setAnswers({ durationMinutes: input.value });
      refresh();
    });
    other.append(input);
    const durations = [...DURATION_CHOICES.map((m) => ({ value: m, label: `${m} minutes` })), { value: "other", label: "Other" }];
    return [
      ...selectAnswer("flow-subject", "Subject", optionsOf("ctx-subject"), a.subject,
        (v) => G.setAnswers({ subject: v }), { placeholder: "Choose a subject…" }),
      ...selectAnswer("flow-duration", "Duration", durations, custom ? "other" : a.durationMinutes, (v) => {
        other.hidden = v !== "other";
        if (v === "other") {
          G.setAnswers({ durationMinutes: input.value });
          input.focus();
        } else {
          G.setAnswers({ durationMinutes: v });
        }
      }, { placeholder: "Choose a length…" }),
      other,
    ];
  },
  topics: () => [
    ...textAnswer("mainTopic", { label: "Main topic", placeholder: "e.g. Spreadsheets" }),
    ...textAnswer("topic", { label: "Specific topic for today", placeholder: "e.g. Cell formulas" }),
    ...textAnswer("previousTopic", {
      label: "Last topic (previous meeting)", placeholder: "e.g. Basic cell formatting",
      alt: { flag: "firstLesson", label: "This is the first lesson" },
    }),
    ...textAnswer("nextTopic", {
      label: "Next topic", placeholder: "e.g. Making charts",
      alt: { flag: "nextUnsure", label: "Not sure yet" },
    }),
  ],
  sources: () => {
    const bow = el("div", { class: "flow-guide-kind" });
    paintGuideKind(bow, "budget_of_work", "Budget of Work", "budgetOfWork");
    const own = el("div", { class: "flow-guide-kind" });
    paintSources(own);
    return el("div", { class: "flow-answer" }, bow, own);
  },
  mode: () => {
    const wrap = el("div", { class: "flow-choices flow-choices-stack", role: "group", "aria-labelledby": "flow-question" });
    const current = G.getAnswers().mode;
    [
      { value: "full", title: "Building Proficiency", sub: "I write the whole plan; you review and edit it." },
      { value: "step", title: "Guided", sub: "You write each part, with me helping beside you." },
    ].forEach((m) => {
      const btn = el("button", { type: "button", class: "flow-choice flow-format flow-mode", "aria-pressed": String(m.value === current) },
        twoLine(m.title, m.sub), tick());
      btn.addEventListener("click", () => {
        wrap.querySelectorAll(".flow-mode").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        G.setAnswers({ mode: m.value });
        refresh();
      });
      wrap.append(btn);
    });
    return wrap;
  },
};

// ---- the Budget of Work ----
// Tapping the picked card again takes it back.
const GUIDES_SHOWN = 6;

function guideCard(g, pressed, onPick) {
  const meta = g.is_builtin
    ? `${g.curriculum || "DepEd"}${g.grades ? ` · Grade ${g.grades}` : ""}`
    : `${g.subject} · uploaded by ${g.uploaded_by || "a teacher"}`;
  const text = twoLine(g.title, meta);
  if (g.is_builtin) {
    const badge = el("span", { class: "flow-badge" }, icon("shieldCheck"), "Official DepEd");
    text.prepend(badge);
  }
  const btn = el("button", { type: "button", class: "flow-choice flow-format", "aria-pressed": String(pressed) }, text, tick());
  btn.addEventListener("click", () => onPick(btn));
  return btn;
}

async function paintGuideKind(box, kind, label, answerKey, showAll = false) {
  const a = G.getAnswers();
  const heading = el("p", { class: "flow-label" }, label);
  box.replaceChildren(heading, el("p", { class: "flow-help" }, `Looking for ${a.subject || "your subject"} ${label.toLowerCase()}s…`));
  let guides = [];
  try {
    guides = await G.searchCourseGuides(kind);
  } catch (err) {
    showError(err.message);
  }
  const current = G.getAnswers()[answerKey];
  if (current && !guides.some((g) => g.id === current.id)) guides.unshift(current);

  const list = el("div", { class: "flow-choices flow-choices-stack flow-scroll", role: "group", "aria-label": label });
  (showAll ? guides : guides.slice(0, GUIDES_SHOWN)).forEach((g) => {
    list.append(guideCard(g, !!current && g.id === current.id, (btn) => {
      const picking = btn.getAttribute("aria-pressed") !== "true";
      list.querySelectorAll(".flow-format").forEach((b) => b.setAttribute("aria-pressed", String(picking && b === btn)));
      G.selectCourseGuide(picking ? g : null, kind);
      refresh();
    }));
  });
  const parts = [heading];
  parts.push(guides.length ? list : el("p", { class: "flow-help" }, `No ${label} for this subject yet. Upload yours and I'll add it to the shared library.`));
  if (!showAll && guides.length > GUIDES_SHOWN) {
    const more = el("button", { type: "button", class: "flow-back flow-more" }, `Show all ${guides.length}`);
    more.addEventListener("click", () => paintGuideKind(box, kind, label, answerKey, true));
    parts.push(more);
  }

  const input = el("input", { type: "file", accept: ".docx,.dotx,.pdf", hidden: true });
  const upload = el("button", { type: "button", class: "flow-back flow-more flow-upload-link" }, icon("upload"), `Upload my own ${label}`);
  upload.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    if (!/\.(docx|dotx|pdf)$/i.test(file.name)) {
      showError("Only .docx, .dotx or .pdf files work here.");
      return;
    }
    errorEl.hidden = true;
    upload.disabled = true;
    say("Adding it to the library…", "loading");
    try {
      await G.uploadCourseGuide(file, kind);
      say(COPY.guide.say, FLOW_POSES.guide);
      paintGuideKind(box, kind, label, answerKey, showAll);
    } catch (err) {
      showError(err.message);
      say(COPY.guide.say, FLOW_POSES.guide);
      upload.disabled = false;
    }
  });
  parts.push(upload, input);
  box.replaceChildren(...parts);
  refresh();
}

// ---- supplementary sources: the student's own files, read by Alan ----
function paintSources(box) {
  const sources = G.getAnswers().sources || [];
  const list = el("div", { class: "flow-sources" });
  sources.forEach((s) => {
    const remove = el("button", { type: "button", class: "flow-source-remove", "aria-label": `Remove ${s.name}` }, icon("x"));
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try {
        await G.removeSource(s.id);
        paintSources(box);
      } catch (err) {
        showError(err.message);
        remove.disabled = false;
      }
    });
    list.append(el("div", { class: "flow-source" }, icon("file"), el("span", {}, s.name), remove));
  });
  const input = el("input", { type: "file", accept: ".docx,.dotx,.pdf", hidden: true });
  const upload = el("button", { type: "button", class: "flow-back flow-more flow-upload-link" }, icon("upload"),
    sources.length ? "Add another source" : "Upload a supplementary source");
  upload.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    if (!/\.(docx|dotx|pdf)$/i.test(file.name)) {
      showError("Only .docx, .dotx or .pdf files work here.");
      return;
    }
    errorEl.hidden = true;
    upload.disabled = true;
    say("Reading your source…", "loading");
    try {
      await G.uploadSource(file);
      say(COPY.sources.say, FLOW_POSES.sources);
      paintSources(box);
    } catch (err) {
      showError(err.message);
      say(COPY.sources.say, FLOW_POSES.sources);
      upload.disabled = false;
    }
  });
  box.replaceChildren(
    el("p", { class: "flow-label" }, "Supplementary sources (optional)"),
    ...(sources.length ? [list] : [el("p", { class: "flow-help" }, "Notes, readings or worksheets you want me to use. .docx, .dotx or .pdf.")]),
    upload,
    input,
  );
}

// ---- the shell ----
const askEl = el("div", { class: "flow-ask" });
const bar = el("span");
const progress = el("div", { class: "flow-progress", role: "progressbar", "aria-label": "Progress", "aria-valuemin": "1" }, bar);
const countEl = el("p", { class: "flow-count" });
const backBtn = el("button", { type: "button", class: "flow-back" }, icon("arrowLeft"), "Back");
const nextIcon = icon("arrowRight");
nextIcon.className = "flow-next-icon";
const nextLabel = el("span", {}, "Next");
const nextBtn = el("button", { type: "submit", class: "flow-next" }, nextLabel, nextIcon);
const errorEl = el("p", { class: "flow-error", role: "alert", hidden: true });
const form = el("form", { class: "flow-step", novalidate: true });
const actions = el("div", { class: "flow-actions" }, backBtn, nextBtn, el("span", { class: "flow-hint" }, "or press Enter"));
askEl.append(el("div", { class: "flow-top" }, progress, countEl),
  el("div", { class: "flow-body" }, form, errorEl, actions));

const sayEl = el("p", { class: "flow-say", role: "status", "aria-live": "polite" });
const alanHost = el("div", { class: "flow-alan" }, el("img", { src: "img/owl/alan-wave.png", alt: "" }));
const stageEl = el("div", { class: "flow-stage" }, sayEl, alanHost);

let currentPose = "hi";

function say(text, pose) {
  sayEl.textContent = text;
  currentPose = pose;
  alan.setPose(pose);
}

function remember() {
  try {
    const a = G.getAnswers();
    localStorage.setItem(rememberKey(user.id), JSON.stringify({ school: a.school, studentTeacher: a.studentTeacher, coop: a.coop }));
  } catch (err) {
    /* private mode: they'll just be asked again next time */
  }
}

function recall() {
  try {
    return JSON.parse(localStorage.getItem(rememberKey(user.id)) || "{}") || {};
  } catch (err) {
    return {};
  }
}

// One screen of the flow. The question steps go through render(); the review,
// writing and lesson-details screens call screen() directly with their own
// Next/Back handlers.
let screenNext = null;
let screenBack = null;
let detailsMode = false;

function screen({ count, at, q, help, body, next = "Next", onNext = null, onBack = null, showActions = true, showBack = true, sayText, pose }) {
  errorEl.hidden = true;
  countEl.textContent = count;
  progress.setAttribute("aria-valuemax", String(steps.length));
  progress.setAttribute("aria-valuenow", String(Math.max(1, Math.round(at * steps.length))));
  bar.style.transform = `scaleX(${at})`;
  screenNext = onNext;
  screenBack = onBack;
  nextLabel.textContent = next;
  actions.hidden = !showActions;
  backBtn.hidden = !showBack;

  const heading = el("h1", { class: "flow-question", id: "flow-question", tabindex: "-1" }, q);
  const answer = el("div", { class: "flow-answer" });
  body(answer);
  form.replaceChildren(heading, help ? el("p", { class: "flow-help" }, help) : "", answer);
  if (!calm) {
    form.classList.add("is-entering");
    requestAnimationFrame(() => requestAnimationFrame(() => form.classList.remove("is-entering")));
  }
  say(sayText, pose);
  refresh();
  const first = answer.querySelector("input:not(:disabled):not([type=file])");
  (first || heading).focus({ preventScroll: true });
}

function render() {
  const id = steps[index];
  const copy = COPY[id];
  screen({
    count: detailsMode ? "Lesson details" : `Step ${index + 1} of ${steps.length}`,
    at: (index + 1) / steps.length,
    q: copy.q,
    help: id === "format" && user.role !== "student" ? "Pick a built-in format, or upload your school's own." : copy.help,
    next: detailsMode ? "Save" : "Next",
    showBack: index > 0 || detailsMode,
    body: (answer) => {
      const builder = STEPS[id];
      answer.append(...[].concat(builder ? builder() : []));
    },
    sayText: copy.say,
    pose: FLOW_POSES[id],
  });
  G.setAnswers({ flowStep: id });
}

refresh = () => {
  if (screenNext) {
    nextBtn.disabled = false;
    return;
  }
  const id = steps[index];
  nextBtn.disabled = id === "format" ? !pendingFormatId : !isStepAnswered(id, G.getAnswers());
};

async function go(delta) {
  if (delta > 0 && screenNext) return screenNext();
  if (delta < 0 && screenBack) return screenBack();
  const id = steps[index];
  if (delta > 0 && id === "format") {
    if (!pendingFormatId) return;
    if (pendingFormatId !== G.getAnswers().formatId) {
      // A different format reloads the page on this run, so say where to land.
      G.setAnswers({ flowStep: steps[index + 1] });
      nextBtn.disabled = true;
      say("Opening the format…", "loading");
      try {
        await G.loadFormat(pendingFormatId);
      } catch (err) {
        showError(err.message);
        say(COPY.format.say, FLOW_POSES.format);
        refresh();
        return;
      }
    }
  } else if (delta > 0 && !isStepAnswered(id, G.getAnswers())) {
    return;
  }
  if (delta > 0 && ["format", "people"].includes(id)) remember();
  if (detailsMode) return showDetails();
  if (delta > 0 && id === "mode") return finish();
  const next = index + delta;
  if (next < 0 || next >= steps.length) return;
  index = next;
  render();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  go(1);
});
nextBtn.addEventListener("click", (e) => {
  e.preventDefault();
  go(1);
});
backBtn.addEventListener("click", () => go(-1));

// ---- after the last question ----
function finish() {
  if (G.getAnswers().mode === "step") {
    G.startGuided();
    return;
  }
  // Prefill now so the review already shows the answered blanks as kept.
  G.useMode("full");
  renderReview();
}

function renderReview() {
  screen({
    count: "Last check",
    at: 1,
    q: "Which parts should I write?",
    help: "I'll write everything set to Generate. Your lesson title and session number stay yours unless you change them.",
    body: (answer) => G.mountReview(answer),
    next: "Write my plan",
    onNext: () => {
      flowGenerating = true;
      G.startFull();
    },
    onBack: () => {
      index = steps.indexOf("mode");
      render();
    },
    sayText: "Pick what I write, then I'll get started.",
    pose: "check",
  });
}

// Generation runs in generator.js; while it does, the big Alan keeps the
// student company and the progress list moves over here.
let flowGenerating = false;
const progressEl = document.getElementById("generation-progress");
const progressHome = progressEl.parentNode;
const progressNext = progressEl.nextSibling;
const sendProgressHome = () => progressHome.insertBefore(progressEl, progressNext);

G.generationEvents.addEventListener("start", () => {
  if (!flowGenerating) return;
  G.hideDocument();
  screen({
    count: "Writing",
    at: 1,
    q: "Writing your plan…",
    help: "This usually takes a minute or two. Each part shows up here as it's written.",
    body: (answer) => answer.append(progressEl),
    showActions: false,
    sayText: "I'm on it. Writing each part of your plan now.",
    pose: "loading",
  });
});

G.generationEvents.addEventListener("done", () => {
  if (!flowGenerating) return;
  flowGenerating = false;
  sendProgressHome();
  say("Done! Here's your plan.", "celebrate");
  setTimeout(() => G.showDocument(), calm ? 0 : 1200);
});

G.generationEvents.addEventListener("error", (e) => {
  if (!flowGenerating) return;
  flowGenerating = false;
  sendProgressHome();
  screen({
    count: "Writing",
    at: 1,
    q: "That didn't work",
    help: e.detail.message || "Something went wrong while writing your plan.",
    body: () => {},
    next: "Try again",
    onNext: () => {
      flowGenerating = true;
      G.startFull();
    },
    onBack: renderReview,
    sayText: "Sorry, that one got away from me. Let's try again.",
    pose: "unsure",
  });
});

// ---- lesson details: change an answer from the document ----
function classText(a) {
  const parts = a.levelType === "college" ? [a.program, a.year, a.section] : [a.grade, a.section];
  return parts.filter((p) => p && String(p).trim()).join(" · ");
}

// [step that holds the answer, label, value, shown to students only?]
const DETAIL_ROWS = [
  ["format", "School", (a) => a.school],
  ["people", "Your name", (a) => a.studentTeacher],
  ["people", "Cooperating / Subject Teacher", (a) => a.coop, true],
  ["class", "Class", classText],
  ["subject", "Subject", (a) => a.subject],
  ["subject", "Discussion length", (a) => (a.durationMinutes ? `${a.durationMinutes} minutes` : "")],
  ["topics", "Main topic", (a) => a.mainTopic],
  ["topics", "Specific topic", (a) => a.topic],
  ["topics", "Last topic", (a) => (a.firstLesson ? "This is the first lesson" : a.previousTopic)],
  ["topics", "Next topic", (a) => (a.nextUnsure ? "Not sure yet" : a.nextTopic)],
  ["sources", "Budget of Work", (a) => (a.budgetOfWork ? a.budgetOfWork.title : "")],
  ["sources", "Supplementary sources", (a) => (a.sources || []).map((s) => s.name).join(", ")],
];

function showDetails() {
  ensureShell();
  detailsMode = true;
  G.hideDocument();
  const a = G.getAnswers();
  screen({
    count: "Lesson details",
    at: 1,
    q: "Lesson details",
    help: "Change an answer and I'll use it the next time I write. What's already written stays as it is.",
    body: (answer) => {
      const list = el("div", { class: "flow-details" });
      if (a.formatName) {
        list.append(el("div", { class: "flow-detail is-fixed" }, twoLine("Format", a.formatName)));
      }
      DETAIL_ROWS.filter(([, , , studentsOnly]) => !studentsOnly || user.role === "student").forEach(([id, label, value]) => {
        const row = el("button", { type: "button", class: "flow-detail" }, twoLine(label, value(a) || "Not answered"), icon("edit"));
        row.addEventListener("click", () => {
          index = steps.indexOf(id);
          render();
        });
        list.append(row);
      });
      answer.append(list);
    },
    next: "Back to my plan",
    showBack: false,
    onNext: () => {
      detailsMode = false;
      G.showDocument();
    },
    sayText: "Anything to change?",
    pose: "present",
  });
}

window.addEventListener("aligned:lesson-details", showDetails);

// ---- Alan ----
// Loaded on demand: if three.js or WebGL is unavailable the 2D picture stays
// and the questions still work.
async function mountAlan(host) {
  const img = host.querySelector("img");
  const usePng = { setPose: (pose) => (img.src = `img/owl/alan-${PNG_FOR_POSE[pose] || "idle"}.png`) };
  try {
    const THREE = await import("three");
    const { createAlan } = await import("./alan3d.js?v=2026-10-22a");
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    const scene = new THREE.Scene();
    // Lit side of the toon ramp lands exactly on the art's flat colours (0.55 + 0.45 = 1).
    scene.add(new THREE.AmbientLight(0xffffff, Math.PI * 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, Math.PI * 0.45);
    sun.position.set(-2, 4, 5);
    scene.add(sun);
    const model = createAlan();
    scene.add(model.root);

    const shadowCv = Object.assign(document.createElement("canvas"), { width: 256, height: 256 });
    const sg = shadowCv.getContext("2d");
    const grad = sg.createRadialGradient(128, 128, 0, 128, 128, 128);
    grad.addColorStop(0, "rgba(22,35,30,0.28)");
    grad.addColorStop(1, "rgba(22,35,30,0)");
    sg.fillStyle = grad;
    sg.fillRect(0, 0, 256, 256);
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.9, 1.1),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(shadowCv), transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.set(0, -0.08, 0.1);
    scene.add(shadow);

    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    const target = new THREE.Vector3(0, 1.2, 0);
    // Room above Alan for the speech line, and for his widest props.
    const fit = () => {
      const { clientWidth: w, clientHeight: h } = host;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      const t = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      // Phones favour Alan's size over the margin for a held-out clipboard.
      const width = innerWidth <= 860 ? 2.5 : 3.0;
      // 1.18: Alan a little smaller than edge-to-edge, still centred in his half.
      const dist = 1.18 * Math.max(3.3 / 2 / t, width / 2 / (t * camera.aspect));
      camera.position.set(target.x, target.y + 0.35, target.z + dist);
      camera.lookAt(target.x, target.y + 0.2, target.z);
      camera.updateProjectionMatrix();
    };
    img.remove();
    host.append(renderer.domElement);
    new ResizeObserver(fit).observe(host);
    fit();

    const clock = new THREE.Clock();
    renderer.setAnimationLoop(() => {
      const dt = Math.min(clock.getDelta(), 0.05);
      if (flow.hidden) return;
      model.update(dt, clock.elapsedTime, calm);
      renderer.render(scene, camera);
    });
    return { setPose: (pose) => model.setPose(pose) };
  } catch (err) {
    return usePng;
  }
}

// ---- start ----
// The shell and the 3D Alan are mounted on first use: right away for a new
// plan, or only when Lesson details is opened from a saved plan.
let shellMounted = false;

function ensureShell() {
  if (shellMounted) return;
  shellMounted = true;
  flow.replaceChildren(askEl, stageEl);
  mountAlan(alanHost).then((ctl) => {
    alan = ctl;
    alan.setPose(currentPose);
  });
}

async function start() {
  const ready = await G.ready;
  user = ready.user;
  steps = flowSteps(user.role);
  // A saved plan (or a run already in its document) only needs Lesson details.
  if (ready.kind !== "flow" || ready.stage === "doc") return;

  if (!ready.runId) {
    resumeOffer = ready.formatId ? null : G.unfinishedRun();
    if (!resumeOffer) startNewRun();
  }
  if (!G.getAnswers().formatId && ready.formatId) {
    try {
      await G.loadFormat(ready.formatId);
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  }

  const resumeAt = steps.indexOf(ready.flowStep);
  index = resumeAt >= 0 ? resumeAt : Math.max(0, steps.indexOf(G.getAnswers().formatId ? "school" : "format"));

  ensureShell();
  flow.hidden = false;
  render();
}

start();
