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
    q: "Which lesson plan format does your school use?",
    help: "Pick a built-in format, or one your teacher uploaded.",
    say: "Hi! I'm Alan. Let's build your lesson plan together, one question at a time.",
  },
  school: {
    q: "What school are you teaching in?",
    help: "It goes into your plan's header. Leave it blank if your format doesn't ask for it.",
    say: "First, the basics. I'll fill these into your plan for you.",
  },
  name: {
    q: "What's your name?",
    help: "As it should appear on the plan.",
    say: "I'll put your name wherever the format asks for the teacher.",
  },
  coop: {
    q: "Who is your cooperating teacher?",
    help: "You can leave this blank.",
    say: "Good to know who's guiding you.",
  },
  subject: {
    q: "What subject is this for?",
    help: "",
    say: "Pick the subject, and I'll look for its course guide later.",
  },
  duration: {
    q: "How long is the discussion?",
    help: "Most discussions run 45 minutes.",
    say: "I'll make the times in your procedure add up to this.",
  },
  class: {
    q: "Which class is this for?",
    help: "",
    say: "Knowing the class helps me pitch the activities right.",
  },
  prevTopic: {
    q: "What did your class learn last meeting?",
    help: "I'll use it to write the review of the previous lesson.",
    say: "Tell me what came before, so the recap connects to it.",
  },
  topic: {
    q: "What's today's topic?",
    help: "Be specific: “Cell formulas” tells me more than “Spreadsheets”.",
    say: "Now the main event. What are you teaching?",
  },
  nextTopic: {
    q: "What comes next after this lesson?",
    help: "I'll point the assignment toward it.",
    say: "Last topic question. What comes after?",
  },
  guide: {
    q: "Which curriculum or course guide should I follow?",
    help: "",
    say: "I'll follow this guide's scope and words closely.",
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
  const card = (f, sub) => {
    const btn = el("button", { type: "button", class: "flow-choice flow-format", "aria-pressed": String(f.id === pendingFormatId) },
      twoLine(f.name, sub), tick());
    btn.addEventListener("click", () => {
      wrap.querySelectorAll(".flow-format").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      pendingFormatId = f.id;
      refresh();
    });
    return btn;
  };
  const group = (title, items) => [
    el("p", { class: "flow-label" }, title),
    el("div", { class: "flow-choices flow-choices-formats", role: "group", "aria-label": title }, items),
  ];
  const parts = group("Built-in", groups.builtin.map((f) => card(f, f.description)));
  if (user.role === "student") {
    if (groups.teacher.length) {
      parts.push(...group("From your teacher", groups.teacher.map((f) => card(f, f.owner_name ? `From ${f.owner_name}` : ""))));
    } else {
      say("Join your teacher's class to see the formats they uploaded.", "hi");
    }
  } else {
    const upload = el("button", { type: "button", class: "flow-choice flow-format flow-upload" },
      twoLine("Upload my school's format", ".docx, .dotx or .pdf"), icon("upload"));
    upload.addEventListener("click", () => paintUpload(wrap));
    parts.push(...group("Uploaded by you", [...groups.mine.map((f) => card(f, "")), upload]));
  }
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
  school: () => textAnswer("school", { placeholder: "e.g. San Isidro National High School" }),
  name: () => textAnswer("studentTeacher", { placeholder: "e.g. Ana Cruz" }),
  coop: () => textAnswer("coop", { placeholder: "e.g. Juan Dela Cruz" }),
  subject: () => choiceAnswer(optionsOf("ctx-subject"), G.getAnswers().subject, (v) => G.setAnswers({ subject: v })),
  duration: () => {
    const minutes = G.getAnswers().durationMinutes;
    const quick = [30, 45, 60, 90];
    const custom = minutes && !quick.includes(minutes);
    const other = el("div", { class: "flow-field", hidden: !custom });
    const input = el("input", { type: "number", min: "5", max: "240", step: "1", inputmode: "numeric",
      placeholder: "Minutes, e.g. 50", "aria-label": "Minutes" });
    if (custom) input.value = minutes;
    input.addEventListener("input", () => {
      G.setAnswers({ durationMinutes: input.value });
      refresh();
    });
    other.append(input);
    const options = [...quick.map((m) => ({ value: m, label: `${m} minutes` })), { value: "other", label: "Other" }];
    const group = choiceAnswer(options, custom ? "other" : minutes, (v) => {
      other.hidden = v !== "other";
      if (v === "other") {
        G.setAnswers({ durationMinutes: input.value });
        input.focus();
      } else {
        G.setAnswers({ durationMinutes: v });
      }
    });
    return [group, other];
  },
  class: () => {
    const a = G.getAnswers();
    const wrap = el("div", { class: "flow-answer" });
    const paint = () => {
      const now = G.getAnswers();
      const detail = now.levelType === "college"
        ? [
          ...textAnswer("program", { label: "Program", placeholder: "e.g. BS Information Technology" }),
          el("p", { class: "flow-label", id: "flow-year-label" }, "Year"),
          choiceAnswer(optionsOf("ctx-college-year"), now.year, (v) => G.setAnswers({ year: v }), "Year"),
        ]
        : [
          el("p", { class: "flow-label" }, "Grade"),
          choiceAnswer(optionsOf("ctx-k12-grade"), now.grade, (v) => G.setAnswers({ grade: v }), "Grade"),
        ];
      wrap.replaceChildren(...detail, ...textAnswer("section", { label: "Section (optional)", placeholder: "e.g. Sampaguita" }));
    };
    const level = choiceAnswer([{ value: "k12", label: "K-12" }, { value: "college", label: "College" }],
      a.levelType || "k12", (v) => {
        G.setAnswers({ levelType: v });
        paint();
      }, "Level");
    paint();
    return [level, wrap];
  },
  prevTopic: () => textAnswer("previousTopic", {
    placeholder: "e.g. Basic cell formatting",
    alt: { flag: "firstLesson", label: "This is the first lesson" },
  }),
  topic: () => textAnswer("topic", { placeholder: "e.g. Cell formulas" }),
  nextTopic: () => textAnswer("nextTopic", {
    placeholder: "e.g. Making charts",
    alt: { flag: "nextUnsure", label: "Not sure yet" },
  }),
};

// ---- the shell ----
const askEl = el("div", { class: "flow-ask" });
const bar = el("span");
const progress = el("div", { class: "flow-progress", role: "progressbar", "aria-label": "Progress", "aria-valuemin": "1" }, bar);
const countEl = el("p", { class: "flow-count" });
const backBtn = el("button", { type: "button", class: "flow-back" }, icon("arrowLeft"), "Back");
const nextIcon = icon("arrowRight");
nextIcon.className = "flow-next-icon";
const nextBtn = el("button", { type: "submit", class: "flow-next" }, el("span", {}, "Next"), nextIcon);
const errorEl = el("p", { class: "flow-error", role: "alert", hidden: true });
const form = el("form", { class: "flow-step", novalidate: true });
const actions = el("div", { class: "flow-actions" }, backBtn, nextBtn, el("span", { class: "flow-hint" }, "or press Enter"));
askEl.append(el("div", { class: "flow-top" }, progress, countEl),
  el("div", { class: "flow-body" }, form, errorEl, actions));

const sayEl = el("p", { class: "flow-say", role: "status", "aria-live": "polite" });
const alanHost = el("div", { class: "flow-alan" }, el("img", { src: "img/owl/alan-wave.png", alt: "" }));
const stageEl = el("div", { class: "flow-stage" }, sayEl, alanHost);

function say(text, pose) {
  sayEl.textContent = text;
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

function render() {
  const id = steps[index];
  const copy = COPY[id];
  errorEl.hidden = true;
  countEl.textContent = `Step ${index + 1} of ${steps.length}`;
  progress.setAttribute("aria-valuemax", String(steps.length));
  progress.setAttribute("aria-valuenow", String(index + 1));
  bar.style.transform = `scaleX(${(index + 1) / steps.length})`;
  backBtn.hidden = index === 0;

  const heading = el("h1", { class: "flow-question", id: "flow-question", tabindex: "-1" }, copy.q);
  const help = id === "format" && user.role !== "student" ? "Pick a built-in format, or upload your school's own." : copy.help;
  const answer = el("div", { class: "flow-answer" });
  const builder = STEPS[id];
  answer.append(...[].concat(builder ? builder() : []));
  form.replaceChildren(heading, help ? el("p", { class: "flow-help" }, help) : "", answer);

  if (!calm) {
    form.classList.add("is-entering");
    requestAnimationFrame(() => requestAnimationFrame(() => form.classList.remove("is-entering")));
  }
  say(copy.say, FLOW_POSES[id]);
  G.setAnswers({ flowStep: id });
  refresh();
  const first = answer.querySelector("input:not(:disabled)");
  (first || heading).focus({ preventScroll: true });
}

refresh = () => {
  const id = steps[index];
  nextBtn.disabled = id === "format" ? !pendingFormatId : !isStepAnswered(id, G.getAnswers());
};

async function go(delta) {
  const id = steps[index];
  const next = index + delta;
  if (next < 0 || next >= steps.length) return;
  if (delta > 0 && id === "format") {
    if (!pendingFormatId) return;
    if (pendingFormatId !== G.getAnswers().formatId) {
      // A different format reloads the page on this run, so say where to land.
      G.setAnswers({ flowStep: steps[next] });
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
  if (delta > 0 && ["school", "name", "coop"].includes(id)) remember();
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
      const dist = Math.max(3.3 / 2 / t, width / 2 / (t * camera.aspect));
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
async function start() {
  const ready = await G.ready;
  if (ready.kind !== "flow" || ready.stage === "doc") return;
  user = ready.user;
  steps = flowSteps(user.role);

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

  flow.replaceChildren(askEl, stageEl);
  flow.hidden = false;
  render();
  mountAlan(alanHost).then((ctl) => {
    alan = ctl;
    alan.setPose(FLOW_POSES[steps[index]]);
  });
}

start();
