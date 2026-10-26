let fmt = null;
let sections = [];
let mode = "full";
let fieldValues = {};
// Sanitized rich-text HTML (bold/italic/underline/lists) for any field
// styled via the live document's toolbar, keyed by field_key — only set for
// fields the teacher has actually touched with the toolbar; everything else
// stays plain text.
let fieldRichValues = {};
let planId = null;
// The plan's server revision this page last loaded or saved. Every PATCH sends
// it, and the server refuses the save if another device has written since.
let planRevision = null;
let dirty = false;
// Bumped on every edit, so a save can tell whether something changed while
// its request was in flight (a boolean can't: it is already true then).
let editSeq = 0;
// True while what is on screen is exactly the server's copy at planRevision,
// which is the only time it's safe to swap in a newer copy silently.
let syncedWithServer = false;

// True for the duration of a Building Proficiency generation stream. Guards
// the mode-switch buttons: section_done handlers keep assigning into
// fieldValues as chunks arrive, so switching mode mid-stream would bank a
// partial generation into the outgoing slot and then let the still-running
// stream write the rest into what is now the OTHER mode's slot, splitting
// the plan across both and overwriting whatever the teacher had typed there.
let generating = false;
// Tells the setup flow when Alan starts, finishes or fails writing the plan,
// so the big Alan can show it (start / done / error with detail.message).
const generationEvents = new EventTarget();
function emitGeneration(type, detail = {}) {
  generationEvents.dispatchEvent(new CustomEvent(type, { detail }));
}

// Confetti when a lesson plan is finished: a short burst from the top of the
// screen in Alan's colours, drawn on a canvas that never takes a click.
// Reduced motion skips it.
function celebrate() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = Object.assign(document.createElement("canvas"), { className: "confetti" });
  cv.setAttribute("aria-hidden", "true");
  document.body.append(cv);
  const ctx = cv.getContext("2d");
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const W = innerWidth, H = innerHeight;
  cv.width = W * dpr;
  cv.height = H * dpr;
  ctx.scale(dpr, dpr);
  const colors = ["#1C5C4E", "#2E8B6F", "#FFE200", "#ED1C24", "#F7B32B", "#FFFFFF"];
  const bits = Array.from({ length: 150 }, () => ({
    x: W * (0.15 + Math.random() * 0.7),
    y: -20 - Math.random() * H * 0.25,
    vx: (Math.random() - 0.5) * 7,
    vy: 2 + Math.random() * 4,
    size: 6 + Math.random() * 7,
    spin: Math.random() * Math.PI,
    turn: (Math.random() - 0.5) * 0.3,
    color: colors[Math.floor(Math.random() * colors.length)],
  }));
  const start = performance.now();
  const frame = (now) => {
    const t = now - start;
    ctx.clearRect(0, 0, W, H);
    ctx.globalAlpha = Math.max(0, Math.min(1, (2600 - t) / 600));
    bits.forEach((b) => {
      b.vy += 0.12;
      b.vx *= 0.99;
      b.x += b.vx;
      b.y += b.vy;
      b.spin += b.turn;
      ctx.save();
      ctx.translate(b.x, b.y);
      ctx.rotate(b.spin);
      ctx.fillStyle = b.color;
      ctx.fillRect(-b.size / 2, -b.size / 4, b.size, b.size / 2);
      ctx.restore();
    });
    if (t < 2600) requestAnimationFrame(frame);
    else cv.remove();
  };
  requestAnimationFrame(frame);
}

// Guided mode: the flat, ordered list of every field on this format
// (document order via sort_order) and which one is currently unlocked.
let stepFieldKeys = [];
let stepIndex = 0;
// The day box last typed in on the Guided screens, so Alan's suggestion for a
// weekly field lands in that day; null when the part has one box.
let guidedPart = null;

// One slot per mode. The two modes have different purposes, so work in one is
// not work in the other: Building Proficiency's draft and Guided's walkthrough
// are two drafts of the same plan. fieldValues/fieldRichValues always hold the
// ACTIVE mode; the other mode's copy waits here and in the plan's mode_values.
let modeSlots = {
  full: { fieldValues: {}, fieldRichValues: {} },
  step: { fieldValues: {}, fieldRichValues: {}, stepIndex: 0 },
};

// Writes whatever is on screen into the active mode's slot.
function captureModeSlot() {
  modeSlots[mode] = {
    fieldValues: JSON.parse(JSON.stringify(fieldValues || {})),
    fieldRichValues: JSON.parse(JSON.stringify(fieldRichValues || {})),
    stepIndex: mode === "step" ? stepIndex : undefined,
  };
}

// Loads a mode's slot into the live values and repaints the editor.
function loadModeSlot(name) {
  const slot = modeSlots[name] || {};
  fieldValues = JSON.parse(JSON.stringify(slot.fieldValues || {}));
  fieldRichValues = JSON.parse(JSON.stringify(slot.fieldRichValues || {}));
  if (name === "step" && typeof slot.stepIndex === "number") stepIndex = slot.stepIndex;

  // Repainting fires the same input handlers a teacher typing would, which
  // would otherwise mark the page dirty and autosave the mode just left.
  // Restore the previous value rather than hardcoding false, in case this
  // ever runs nested inside a larger restore that is still in progress.
  const wasRestoring = restoringDraft;
  restoringDraft = true;
  try {
    // blankMissing=true: unlike a page restore, a mode switch must also clear
    // fields the incoming mode has nothing for, or the outgoing mode's text
    // stays on screen.
    paintRestoredValues(true);
  } finally {
    restoringDraft = wasRestoring;
  }
}

// The slot to persist alongside the active mode's values.
function inactiveModeSlot() {
  const other = mode === "full" ? "step" : "full";
  const slot = modeSlots[other] || {};
  return {
    field_values: slot.fieldValues || {},
    rich_field_values: slot.fieldRichValues || {},
    step_index: typeof slot.stepIndex === "number" ? slot.stepIndex : 0,
  };
}

// Whether the mode NOT currently on screen has anything written in it, so a
// switch can say so instead of just going blank — nothing is actually lost,
// but an empty editor with no explanation reads as a vanished lesson plan.
function inactiveModeHasWork() {
  const values = inactiveModeSlot().field_values || {};
  return Object.values(values).some((v) => (Array.isArray(v) ? v.length > 0 : !!(v && String(v).trim())));
}

// The two curriculum documents a plan is based on, picked separately: the
// Budget of Work (week-by-week competencies) and the Curriculum Guide (the
// standards above them). Either may be empty, not both.
const selectedGuides = { budget_of_work: null, curriculum_guide: null };

function hasGuide() {
  return !!(selectedGuides.budget_of_work || selectedGuides.curriculum_guide
    || flowFlags.guides.length || flowFlags.sources.length);
}
let currentUser = null;

// The format's real reference document, rendered with an empty editable slot
// per field ({html, matched_fields, unmatched_fields} from the template-html
// endpoint) — null when this format has no usable reference file, in which
// case the plain field-by-field editor (#results) is used instead.
let docTemplateData = null;

const errorBox = document.getElementById("error-box");
const loadingState = document.getElementById("loading-state");
const content = document.getElementById("content");
const modeSwitchBtns = [...document.querySelectorAll("#mode-switch button")];
const fullControls = document.getElementById("full-controls");
const stepControls = document.getElementById("step-controls");
const sectionNav = document.getElementById("section-nav");
const stepProgressLabel = document.getElementById("step-progress-label");
const generateFullBtn = document.getElementById("generate-full-btn");
const generationProgressEl = document.getElementById("generation-progress");
const ownFieldsNote = document.getElementById("own-fields-note");
const ownFieldsNoteText = document.getElementById("own-fields-note-text");
const ownFieldsGenerateBtn = document.getElementById("own-fields-generate-btn");
const generationProgressList = document.getElementById("generation-progress-list");
const stepContinueBtn = document.getElementById("step-continue-btn");
const stepClearBtn = document.getElementById("step-clear-btn");
const resultsEl = document.getElementById("results");
const liveDocHint = document.getElementById("live-doc-hint");
const liveDocToolbar = document.getElementById("live-doc-toolbar");
const liveDocWrap = document.getElementById("live-doc-wrap");
const liveDocStage = document.getElementById("live-doc-stage");
const footer = document.getElementById("footer");
const saveStatus = document.getElementById("save-status");
const previewBtn = document.getElementById("preview-btn");
const saveBtn = document.getElementById("save-btn");
const exportBtn = document.getElementById("export-btn");
const visibilityCheckbox = document.getElementById("visibility-checkbox");
const pageSizeSelect = document.getElementById("page-size-select");
const submitSectionSelect = document.getElementById("submit-section-select");
const submitBtn = document.getElementById("submit-btn");
const previewOverlay = document.getElementById("preview-overlay");
const previewBody = document.getElementById("preview-body");
const previewTitle = document.getElementById("preview-title");
const previewClose = document.getElementById("preview-close");

const teacherNameInput = document.getElementById("ctx-teacher-name");
const subjectInput = document.getElementById("ctx-subject");
const topicInput = document.getElementById("ctx-topic");
const levelTypeSelect = document.getElementById("ctx-level-type");
const collegeFieldsWrap = document.getElementById("ctx-college-fields-wrap");
const collegeProgramInput = document.getElementById("ctx-college-program");
const collegeYearSelect = document.getElementById("ctx-college-year");
const k12GradeWrap = document.getElementById("ctx-k12-grade-wrap");
const k12GradeSelect = document.getElementById("ctx-k12-grade");
const sectionInput = document.getElementById("ctx-section");
// Answers the Create Lesson Plan flow asks for (js/setup-flow.js).
const schoolInput = document.getElementById("ctx-school");
const studentTeacherInput = document.getElementById("ctx-student-teacher");
const durationInput = document.getElementById("ctx-duration");
const prevTopicInput = document.getElementById("ctx-prev-topic");
const nextTopicInput = document.getElementById("ctx-next-topic");
const mainTopicInput = document.getElementById("ctx-main-topic");
// The flow's own state, saved with the setup so a refresh lands on the same step.
// guides: the library documents picked in step 6, any number of either kind;
// sources: the student's own private uploads.
let flowFlags = { firstLesson: false, nextUnsure: false, flowStep: null, stage: "flow", formatName: "", mode: null, sources: [], guides: [], term: "", week: "", sample: null, assessment: null, quizItems: 5, guidedAt: "part" };
// One run = one pass through the flow; its draft is keyed by run, not by
// format, so picking a format never silently brings back an older draft.
let currentRunId = new URLSearchParams(window.location.search).get("run");
const gateLock = document.getElementById("gate-lock");
// The setup answers are changed in the flow's Lesson details (js/setup-flow.js),
// from the header button or from the locked gate's way out.
const openLessonDetails = () => window.dispatchEvent(new CustomEvent("aligned:lesson-details"));
document.getElementById("gate-setup-btn").addEventListener("click", openLessonDetails);
document.getElementById("lesson-details-btn").addEventListener("click", openLessonDetails);
const unlockedContent = document.getElementById("unlocked-content");

const genTabsEl = document.getElementById("gen-tabs");
const tabPanelSetup = document.getElementById("tab-panel-setup");
const tabPanelGenerate = document.getElementById("tab-panel-generate");
const setupContinueBtn = document.getElementById("setup-continue-btn");

// ---- Guide owl ----
// The owl himself lives in api.js (OwlGuide) and is shared with the format
// builder. These are the poses the old per-state calls below map onto.
const OWL_POSES = {
  idle: "wave",
  guide: "point",
  thinking: "think",
  alert: "think",
  celebrate: "celebrate",
};

function owlPoseSrc(state) {
  return `img/owl/alan-${OWL_POSES[state] || "point"}.png`;
}

// ---- Guided mode: a chat with the owl about the field being written. The
// owl answers in a sentence or two and offers choices: "use" choices are
// example content with a line on why it fits, to read (never inserted), and
// "ask" choices send a follow-up question. ----
const owlChat = document.getElementById("owl-chat");
const owlChatLog = document.getElementById("owl-chat-log");
const owlChatForm = document.getElementById("owl-chat-form");
const owlChatInput = document.getElementById("owl-chat-input");
const owlChatSend = document.getElementById("owl-chat-send");
const owlChatField = document.getElementById("owl-chat-field");
const owlChatToggle = document.getElementById("owl-chat-toggle");

const OWL_STARTERS = [
  { type: "ask", label: "Suggest content for this field", text: "Suggest content for this field." },
  { type: "ask", label: "What should this field include?", text: "What should this field include?" },
  { type: "ask", label: "Show me an example", text: "Show me an example for this field." },
];
const OWL_COACH_STARTERS = [
  { type: "ask", label: "What should this part include?", text: "What should this part include?" },
  { type: "ask", label: "Ask me questions to get started", text: "Ask me a few questions to help me start writing this part." },
  { type: "ask", label: "Check what I wrote", text: "Read what I wrote so far and tell me how to improve it, without rewriting it." },
];
const CHAT_TURNS_SENT = 8;

// One conversation per lesson plan, like a chat app's conversation list: moving
// to the next part never clears the log, Alan just opens the new part with a
// message of his own. Each turn remembers its part, so only that part's turns
// are sent to the AI. All of them are kept in localStorage (the History button
// lists them, one per plan). The old per-field threads (owlChat:v1:) are left
// where they are and not shown.
const CHAT_STORE_KEY = "owlChat:v2";
const CHAT_MAX_TURNS = 300;
const CHAT_MAX_CONVERSATIONS = 30;
const chat = { store: {}, busy: false, fieldKey: null, shown: null };

// The run id while a plan is being made; a plan opened from the list has none.
function chatConvKey() {
  return currentRunId ? `run:${currentRunId}` : planId ? `plan:${planId}` : "run:none";
}

function loadChatThreads() {
  try {
    const store = JSON.parse(localStorage.getItem(CHAT_STORE_KEY) || "{}");
    chat.store = store && typeof store === "object" && !Array.isArray(store) ? store : {};
  } catch (err) {
    // Corrupt or unavailable storage must never stop the chat working.
    chat.store = {};
  }
}

function saveChatThreads() {
  try {
    // The oldest conversations go first once there are too many.
    const keys = Object.keys(chat.store).sort((a, b) => (chat.store[b].updatedAt || 0) - (chat.store[a].updatedAt || 0));
    keys.slice(CHAT_MAX_CONVERSATIONS).forEach((k) => delete chat.store[k]);
    localStorage.setItem(CHAT_STORE_KEY, JSON.stringify(chat.store));
  } catch (err) {
    /* private mode, or the quota is full — the in-memory chat still works */
  }
}

function currentConversation() {
  const key = chatConvKey();
  const conv = chat.store[key];
  if (conv && Array.isArray(conv.turns)) return conv;
  chat.store[key] = { turns: [], startedAt: Date.now() };
  return chat.store[key];
}

// role: "teacher" | "owl" | "part" (the divider naming the part). intro marks
// Alan's built-in opening for a part, which is never sent to the AI.
function recordTurn(key, role, text, options = [], intro = false) {
  const conv = currentConversation();
  conv.turns.push({ role, text, field: key, at: Date.now(), ...(options.length ? { options } : {}), ...(intro ? { intro } : {}) });
  if (conv.turns.length > CHAT_MAX_TURNS) conv.turns.splice(0, conv.turns.length - CHAT_MAX_TURNS);
  conv.updatedAt = Date.now();
  conv.title = topicInput.value.trim() || mainTopicInput.value.trim() || conv.title || "";
  conv.format = (fmt && fmt.name) || conv.format || "";
  saveChatThreads();
}

// Text with several lines: lines starting with "- " or "• " (or every line,
// for an option's text) become a bulleted list, the rest paragraphs.
// Alan's replies and options, organised: "- " or "•" lines become a bulleted
// list and "1." lines a numbered one, a list run together on one line is
// split into its items, and **bold** shows as bold, not as asterisks.
function fillLines(el, text, listAll = false) {
  let raw = String(text || "").replace(/\r/g, "");
  if (/(^|\s)1[.)]\s.+\s2[.)]\s/.test(raw)) raw = raw.replace(/\s+(?=\d{1,2}[.)]\s+\S)/g, "\n");
  raw = raw.replace(/\s+•\s+/g, "\n• ");
  const lines = raw.split("\n").map((l) => l.trim()).filter(Boolean);
  el.textContent = "";
  if (lines.length < 2 && !listAll) {
    appendBold(el, lines[0] || "");
    return;
  }
  let list = null;
  lines.forEach((line) => {
    const numbered = /^\d{1,2}[.)]\s+/.test(line);
    const bulleted = /^[-•*]\s+/.test(line);
    if (listAll || numbered || bulleted) {
      const tag = numbered ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) list = el.appendChild(document.createElement(tag));
      appendBold(list.appendChild(document.createElement("li")), line.replace(/^([-•*]|\d{1,2}[.)])\s+/, ""));
    } else {
      list = null;
      appendBold(el.appendChild(document.createElement("p")), line);
    }
  });
}

function appendBold(el, text) {
  String(text).split(/\*\*(.+?)\*\*/).forEach((piece, i) => {
    if (!piece) return;
    el.appendChild(i % 2 ? document.createElement("strong") : document.createTextNode(piece)).textContent = piece;
  });
}

function scrollChatToEnd() {
  owlChatLog.scrollTop = owlChatLog.scrollHeight;
}

function addChatNote(text) {
  const note = document.createElement("div");
  note.className = "owl-chat-note";
  note.textContent = text;
  owlChatLog.appendChild(note);
  scrollChatToEnd();
}

function addTeacherMessage(text) {
  const row = document.createElement("div");
  row.className = "owl-msg owl-msg-teacher";
  const bubble = document.createElement("div");
  bubble.className = "owl-bubble";
  bubble.textContent = text;
  row.appendChild(bubble);
  owlChatLog.appendChild(row);
  scrollChatToEnd();
}

function owlRow(avatarState) {
  const row = document.createElement("div");
  row.className = "owl-msg owl-msg-owl";
  const avatar = document.createElement("img");
  avatar.className = "owl-msg-avatar";
  avatar.src = owlPoseSrc(avatarState);
  avatar.alt = "";
  const body = document.createElement("div");
  body.className = "owl-msg-body";
  row.append(avatar, body);
  return { row, body };
}

function addOwlTyping() {
  const { row, body } = owlRow("thinking");
  row.classList.add("is-typing");
  body.innerHTML = '<div class="owl-bubble"><span class="owl-dots" aria-label="Alan is typing"><i></i><i></i><i></i></span></div>';
  owlChatLog.appendChild(row);
  scrollChatToEnd();
  return row;
}

function addOwlMessage(text, choices = [], { error = false, unread = true } = {}) {
  // Only the latest follow-up questions stay tappable, so an old one isn't
  // asked about a field it was never written for.
  owlChatLog.querySelectorAll("button.owl-choice").forEach((b) => { b.disabled = true; });
  const { row, body } = owlRow(error ? "alert" : "guide");
  if (error) row.classList.add("is-error");
  const bubble = document.createElement("div");
  bubble.className = "owl-bubble";
  fillLines(bubble, text);
  body.appendChild(bubble);

  if (choices.length) {
    const list = document.createElement("div");
    list.className = "owl-choices";
    choices.forEach((choice) => {
      // An option is something to read and learn from: its content and why
      // it fits. The student writes the part themselves, so it fills nothing.
      if (choice.type === "use") {
        const card = document.createElement("div");
        card.className = "owl-choice owl-choice-use";
        const label = document.createElement("span");
        label.className = "owl-choice-label";
        label.textContent = choice.label;
        // Several lines (objectives, say) read as a bulleted list, not one run.
        const text = document.createElement("div");
        text.className = "owl-choice-text";
        fillLines(text, choice.text, true);
        card.append(label, text);
        if (choice.why) {
          const why = document.createElement("span");
          why.className = "owl-choice-why";
          why.textContent = choice.why;
          card.append(why);
        }
        list.appendChild(card);
        return;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `owl-choice owl-choice-${choice.type}`;
      btn.textContent = choice.label;
      btn.addEventListener("click", () => pickOwlChoice(choice));
      list.appendChild(btn);
    });
    body.appendChild(list);
  }
  owlChatLog.appendChild(row);
  scrollChatToEnd();
  // A reply the teacher can't see yet shows as a dot on the owl.
  if (unread && !owlChat.hidden && owlChat.classList.contains("is-collapsed")) setChatUnread(true);
}

// The part divider in the log: which part the messages below are about.
function addPartNote(text) {
  addChatNote(text);
  owlChatLog.lastElementChild.classList.add("owl-chat-part");
}

// Draw a conversation's turns into the log. Owl turns keep their options
// (read-only); follow-up questions are only ever offered live.
function drawTurns(turns) {
  turns.forEach((turn) => {
    if (turn.role === "part") addPartNote(turn.text);
    else if (turn.role === "teacher") addTeacherMessage(turn.text);
    else addOwlMessage(turn.text, turn.options || [], { unread: false });
  });
}

const startersFor = (field) => (field.locked ? OWL_COACH_STARTERS : OWL_STARTERS);

// Alan's built-in opening for a part (js/part-guides.js): no AI call.
function partIntro(field) {
  return partGuide(field) + (field.locked
    ? "\n\nYour teacher wants this part in your own words, so I won't write it for you, but I can help you think it through."
    : "");
}

function introduceFieldInChat() {
  if (mode !== "step") return;
  const key = stepFieldKeys[stepIndex];
  const field = fieldByKey(key);
  if (!field || chat.fieldKey === key) return;
  chat.fieldKey = key;
  owlChatField.textContent = `Helping with: ${field.label}`;
  if (!owlChatHistory.hidden) showChatHistory(false);

  // The whole plan is one conversation, drawn once; a new part is added below.
  const conv = currentConversation();
  if (chat.shown !== chatConvKey()) {
    chat.shown = chatConvKey();
    owlChatLog.innerHTML = "";
    drawTurns(conv.turns);
  }
  const lastPart = [...conv.turns].reverse().find((t) => t.role === "part");
  if (!lastPart || lastPart.field !== key) {
    const note = `${field.label}`;
    const intro = partIntro(field);
    recordTurn(key, "part", note);
    recordTurn(key, "owl", intro, [], true);
    addPartNote(note);
    addOwlMessage(intro, startersFor(field), { unread: false });
  } else if (!owlChatLog.querySelector("button.owl-choice:not(:disabled)")) {
    // Back on the same part (a reload): offer its questions again.
    addOwlMessage("Ask me anything about this part.", startersFor(field), { unread: false });
  }
  scrollChatToEnd();
}

async function sendToOwl(text) {
  text = (text || "").trim();
  if (!text || chat.busy) return;
  const key = stepFieldKeys[stepIndex];
  const field = fieldByKey(key);
  if (!field) return;

  syncActiveStepValue();
  chat.busy = true;
  owlChatSend.disabled = true;
  owlChatInput.value = "";
  addTeacherMessage(text);
  const typing = addOwlTyping();
  try {
    // Only this part's exchange is sent: the AI answers about the part on screen.
    const history = currentConversation().turns
      .filter((t) => t.field === key && (t.role === "teacher" || t.role === "owl") && !t.intro)
      .slice(-CHAT_TURNS_SENT)
      .map(({ role, text: turnText }) => ({ role, text: turnText }));
    const data = await Api.owlChat({
      ...baseGenerationPayload(),
      field_key: key,
      prior_values: { ...fieldValues },
      history,
      message: text,
    });
    typing.remove();
    recordTurn(key, "teacher", text);
    recordTurn(key, "owl", data.reply, (data.choices || []).filter((c) => c.type === "use"));
    addOwlMessage(data.reply, data.choices || []);
  } catch (err) {
    typing.remove();
    addOwlMessage(err.message || "I could not answer just now. Please try again.",
      [{ type: "ask", label: "Try again", text }], { error: true });
  } finally {
    chat.busy = false;
    owlChatSend.disabled = false;
    owlChatInput.focus();
  }
}

// Only follow-up questions are tappable; options are read, not inserted.
function pickOwlChoice(choice) {
  sendToOwl(choice.text);
}

function updateChatRoom() {
  // On wide screens the page makes room for the open chat, so it never
  // covers the document the teacher is writing in.
  // Even collapsed, the bar and the owl float over the bottom of the page,
  // so the page gets room to scroll its last buttons clear of them.
  document.body.classList.toggle("owl-chat-shown", !owlChat.hidden);
}

// Collapsed means the panel is gone and only the owl is left, as the button
// that brings it back (clicking him toggles the chat; see OwlGuide.dock).
// Guided mode always starts that way, every time: the chat only ever appears
// because the teacher clicked him, never because it was open last time.

// Minimized, nothing of the chat is left on screen but Alan, so a reply that
// arrives meanwhile puts its dot on him.
let chatUnread = false;

function setChatUnread(unread) {
  chatUnread = !!unread;
  const state = { open: !owlChat.classList.contains("is-collapsed"), unread: chatUnread };
  // On the Guided screens the stage swaps Alan and the chat itself.
  if (owlChat.classList.contains("is-staged")) generationEvents.dispatchEvent(new CustomEvent("chat", { detail: state }));
  else OwlGuide.setChatState(state);
}

function setOwlChatCollapsed(collapsed) {
  owlChat.classList.toggle("is-collapsed", collapsed);
  owlChatToggle.setAttribute("aria-expanded", String(!collapsed));
  owlChatToggle.textContent = collapsed ? "Open" : "Hide";
  setChatUnread(collapsed && chatUnread);
  updateChatRoom();
  if (!collapsed) {
    scrollChatToEnd();
    if (owlChat.classList.contains("is-staged")) owlChatInput.focus({ preventScroll: true });
    // Stacked under the plan on a narrow screen, it may open out of view.
    else owlChat.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}


// ---- Chat panel width ----
const CHAT_W_KEY = "owlChatWidth";
const CHAT_W_MIN = 340;
const chatResizer = document.getElementById("owl-chat-resizer");

// The document beside it keeps at least DOC_MIN_W, so the chat can't squeeze
// the plan into a sliver.
const DOC_MIN_W = 480;

function chatMaxWidth() {
  const row = owlChat.parentElement.getBoundingClientRect().width || window.innerWidth;
  return Math.max(CHAT_W_MIN, Math.min(820, row - DOC_MIN_W - 20));
}

function setChatWidth(px, persist = true) {
  const w = Math.round(Math.min(Math.max(px, CHAT_W_MIN), chatMaxWidth()));
  document.documentElement.style.setProperty("--owl-chat-w", `${w}px`);
  chatResizer.setAttribute("aria-valuenow", String(w));
  chatResizer.setAttribute("aria-valuemin", String(CHAT_W_MIN));
  chatResizer.setAttribute("aria-valuemax", String(chatMaxWidth()));
  if (persist) {
    try {
      localStorage.setItem(CHAT_W_KEY, String(w));
    } catch (err) {
      /* not fatal: the width just won't be remembered next time */
    }
  }
  return w;
}

function currentChatWidth() {
  return owlChat.getBoundingClientRect().width;
}

(function wireChatResize() {
  let stored = null;
  try {
    stored = parseInt(localStorage.getItem(CHAT_W_KEY), 10);
  } catch (err) {
    /* ignore */
  }
  setChatWidth(stored || 460, false);

  let startX = 0;
  let startW = 0;

  chatResizer.addEventListener("pointerdown", (e) => {
    startX = e.clientX;
    startW = currentChatWidth();
    owlChat.classList.add("is-resizing");
    try {
      chatResizer.setPointerCapture(e.pointerId);
    } catch (err) {
      /* no capture available */
    }
    e.preventDefault();
  });

  chatResizer.addEventListener("pointermove", (e) => {
    if (!owlChat.classList.contains("is-resizing")) return;
    // The panel is pinned to the right, so dragging the left edge leftwards
    // (a falling clientX) makes it wider.
    setChatWidth(startW + (startX - e.clientX));
  });

  const stop = (e) => {
    if (!owlChat.classList.contains("is-resizing")) return;
    owlChat.classList.remove("is-resizing");
    try {
      if (chatResizer.hasPointerCapture(e.pointerId)) chatResizer.releasePointerCapture(e.pointerId);
    } catch (err) {
      /* already released */
    }
  };
  chatResizer.addEventListener("pointerup", stop);
  chatResizer.addEventListener("pointercancel", stop);

  // Dragging an edge is a pointer gesture, so it needs a keyboard equivalent.
  chatResizer.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 60 : 20;
    if (e.key === "ArrowLeft") setChatWidth(currentChatWidth() + step);
    else if (e.key === "ArrowRight") setChatWidth(currentChatWidth() - step);
    else if (e.key === "Home") setChatWidth(chatMaxWidth());
    else if (e.key === "End") setChatWidth(CHAT_W_MIN);
    else return;
    e.preventDefault();
  });

  // A remembered width can be too wide for a smaller window.
  window.addEventListener("resize", () => setChatWidth(currentChatWidth(), false));
})();

// ---- Saved conversations ----
const owlChatHistory = document.getElementById("owl-chat-history");
const owlChatHistoryBtn = document.getElementById("owl-chat-history-btn");
const owlChatHistoryList = document.getElementById("owl-chat-history-list");
const owlChatHistoryTitle = document.getElementById("owl-chat-history-title");
const owlChatHistoryBack = document.getElementById("owl-chat-history-back");

function showChatHistory(visible) {
  owlChatHistory.hidden = !visible;
  owlChatLog.hidden = visible;
  owlChatForm.hidden = visible;
  owlChatHistoryBtn.setAttribute("aria-pressed", String(visible));
  owlChatHistoryBtn.textContent = visible ? "Back to chat" : "History";
  if (visible) renderHistoryList();
}

function renderHistoryList() {
  owlChatHistoryBack.hidden = true;
  owlChatHistoryTitle.textContent = "Your conversations";
  owlChatHistoryList.innerHTML = "";

  // One conversation per lesson plan, newest first, like a chat app's list.
  const talked = (c) => (c.turns || []).filter((t) => t.role === "teacher").length;
  const entries = Object.entries(chat.store)
    .filter(([, c]) => c && Array.isArray(c.turns) && c.turns.length)
    .sort(([, a], [, b]) => (b.updatedAt || 0) - (a.updatedAt || 0));
  if (!entries.length) {
    owlChatHistoryList.innerHTML =
      '<p class="owl-chat-history-empty">Nothing saved yet. Each lesson plan you write with Alan keeps its conversation here, so you can read it back.</p>';
    return;
  }

  entries.forEach(([key, conv]) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "owl-chat-thread-btn";
    const title = document.createElement("strong");
    const when = new Date(conv.updatedAt || conv.startedAt || Date.now())
      .toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    title.textContent = `${conv.title || conv.format || "Lesson plan"}${key === chatConvKey() ? " (this plan)" : ""}`;
    const meta = document.createElement("span");
    const asked = talked(conv);
    meta.textContent = `${when} · ${asked ? `${asked} question${asked === 1 ? "" : "s"}` : "no questions yet"}${conv.format ? ` · ${conv.format}` : ""}`;
    btn.append(title, meta);
    btn.addEventListener("click", () => renderHistoryThread(key));
    owlChatHistoryList.appendChild(btn);
  });
}

// One saved conversation, read-only: its parts, questions, answers and options.
function renderHistoryThread(key) {
  const conv = chat.store[key];
  owlChatHistoryBack.hidden = false;
  owlChatHistoryTitle.textContent = (conv && (conv.title || conv.format)) || "Lesson plan";
  owlChatHistoryList.innerHTML = "";
  ((conv && conv.turns) || []).forEach((turn) => {
    if (turn.role === "part") {
      const note = document.createElement("div");
      note.className = "owl-chat-note owl-chat-part";
      note.textContent = turn.text;
      owlChatHistoryList.appendChild(note);
      return;
    }
    const row = document.createElement("div");
    row.className = `owl-msg owl-msg-${turn.role === "teacher" ? "teacher" : "owl"}`;
    if (turn.role !== "teacher") {
      const avatar = document.createElement("img");
      avatar.className = "owl-msg-avatar";
      avatar.src = owlPoseSrc("guide");
      avatar.alt = "";
      row.appendChild(avatar);
    }
    const body = document.createElement("div");
    body.className = "owl-msg-body";
    const bubble = document.createElement("div");
    bubble.className = "owl-bubble";
    fillLines(bubble, turn.text);
    body.appendChild(bubble);
    (turn.options || []).forEach((o) => {
      const card = document.createElement("div");
      card.className = "owl-choice owl-choice-use";
      const label = document.createElement("span");
      label.className = "owl-choice-label";
      label.textContent = o.label;
      const text = document.createElement("div");
      text.className = "owl-choice-text";
      fillLines(text, o.text, true);
      card.append(label, text);
      if (o.why) {
        const why = document.createElement("span");
        why.className = "owl-choice-why";
        why.textContent = o.why;
        card.append(why);
      }
      body.appendChild(card);
    });
    row.appendChild(body);
    owlChatHistoryList.appendChild(row);
  });
}

owlChatHistoryBtn.addEventListener("click", () => showChatHistory(owlChatHistory.hidden));
owlChatHistoryBack.addEventListener("click", renderHistoryList);

function toggleOwlChat() {
  setOwlChatCollapsed(!owlChat.classList.contains("is-collapsed"));
}

function showOwlChat(visible) {
  const opening = visible && owlChat.hidden;
  owlChat.hidden = !visible;
  if (visible) {
    // The owl stays through Guided mode beside the chat, rather than stepping
    // aside for a panel that then covered his corner.
    OwlGuide.dock(toggleOwlChat);
    if (opening) setOwlChatCollapsed(true);
    showChatHistory(false);
    introduceFieldInChat();
  } else {
    OwlGuide.undock();
  }
  updateChatRoom();
}

owlChatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendToOwl(owlChatInput.value);
});
owlChatToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleOwlChat();
});

function setOwlState(state, message) {
  // The flow's big Alan does the talking while its screens are up.
  if (!flowEl.hidden) return;
  OwlGuide.show({ pose: OWL_POSES[state] || "idle", text: message });
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function updateLevelFields() {
  const isCollege = levelTypeSelect.value === "college";
  collegeFieldsWrap.hidden = !isCollege;
  k12GradeWrap.hidden = isCollege;
}

levelTypeSelect.addEventListener("change", updateLevelFields);

function getClassLabel() {
  if (levelTypeSelect.value === "college") {
    const parts = [collegeProgramInput.value.trim(), collegeYearSelect.value.trim(), sectionInput.value.trim()].filter(Boolean);
    return parts.join(" · ");
  }
  const parts = [k12GradeSelect.value.trim(), sectionInput.value.trim()].filter(Boolean);
  return parts.join(" · ");
}

function assessmentText(a) {
  if (a.assessment === "quiz") return `a ${a.quizItems || 5}-item multiple-choice quiz`;
  if (a.assessment === "task") return "a performance task with a rubric";
  return "";
}

function getAdvancedContext() {
  const isCollege = levelTypeSelect.value === "college";
  const context = {
    topic: topicInput.value.trim(),
    level_type: isCollege ? "College" : "K-12",
    program: isCollege ? collegeProgramInput.value.trim() : "",
    year: isCollege ? collegeYearSelect.value.trim() : "",
    grade_level: isCollege ? "" : k12GradeSelect.value.trim(),
    section: sectionInput.value.trim(),
    school: schoolInput.value.trim(),
    student_teacher: studentTeacherInput.value.trim(),
    duration_minutes: parseInt(durationInput.value, 10) || "",
    // The broader topic today's lesson sits under (the flow's step 5).
    main_topic: mainTopicInput.value.trim(),
    // Step 6: which term and week of the Budget of Work this lesson is.
    term: flowFlags.term || "",
    week: flowFlags.week || "",
    // Step 2: how the lesson is assessed, in words, as the prompt reads it.
    assessment_type: assessmentText(flowFlags),
  };
  // Only when Alan actually asked (the plan went through the flow): then an
  // empty value means "first lesson" / "not sure yet" and the server grounds
  // the recap and assignment on it. A plan from before the flow sends neither.
  if (flowFlags.flowStep) {
    context.previous_topic = flowFlags.firstLesson ? "" : prevTopicInput.value.trim();
    context.next_topic = flowFlags.nextUnsure ? "" : nextTopicInput.value.trim();
  }
  return context;
}

let gateWasReady = false;

// Whether the teacher is past "Before we start" and actually editing.
function isEditorUnlocked() {
  return !unlockedContent.hidden;
}

// The owl belongs on screen only while the teacher is actually being guided
// through fields: Guided mode, past the setup gate, and on the tab that shows
// the document. Keying it off the mode alone left it floating over the setup
// form, and keying it off the gate as well still left it on the Setup tab,
// because the tabs live inside the gated content and switching them does not
// change that flag. One predicate now answers the question, and everything
// that can change the answer calls syncOwlVisibility().
// Guided writing now happens on its own screens beside the big 3D Alan, with
// the chat taking his place on the stage (setup-flow.js / guided-flow.js), so
// the document never gets the docked corner chat any more.
function shouldShowOwlChat() {
  return false;
}

function syncOwlVisibility() {
  if (owlChat.classList.contains("is-staged")) {
    OwlGuide.undock();
    return;
  }
  showOwlChat(shouldShowOwlChat());
}

function updateGate() {
  // The name step is required for everyone; teachers have no cooperating teacher.
  // Plans saved before the flow existed only have the old teacher field.
  const teacherOk = (studentTeacherInput.value || teacherNameInput.value).trim().length > 0;
  const subjectOk = subjectInput.value.trim().length > 0;
  const guideOk = hasGuide();
  const ready = teacherOk && subjectOk && guideOk;

  gateLock.hidden = ready;
  unlockedContent.hidden = !ready;

  // The owl's visibility depends on this gate, so it has to be re-checked
  // whenever the gate moves rather than only when the mode changes.
  syncOwlVisibility();

  if (ready && !gateWasReady) {
    setOwlState("guide", "Nice, you're all set. Head to “Generate & review” when you're ready.");
  }
  gateWasReady = ready;

  return ready;
}

teacherNameInput.addEventListener("input", updateGate);
// The pickers' search buttons name the subject they will search for.
function syncGuideSearchLabels() {
  document.querySelectorAll(".cg-search-btn-label").forEach((el) => {
    el.textContent = `Search for "${subjectInput.value.trim() || "this subject"}"`;
  });
}

subjectInput.addEventListener("change", () => {
  syncGuideSearchLabels();
  updateGate();
});

// The setup answers are part of the plan in progress, so they are saved the
// same way the fields are. markDirty() covers everything in the generate tab.
[teacherNameInput, subjectInput, topicInput, levelTypeSelect, collegeProgramInput,
 collegeYearSelect, k12GradeSelect, sectionInput, schoolInput, studentTeacherInput,
 durationInput, prevTopicInput, nextTopicInput, mainTopicInput].forEach((el) => {
  el.addEventListener("input", saveDraft);
  el.addEventListener("change", saveDraft);
});

function goToTab(tabName) {
  genTabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabName));
  tabPanelSetup.hidden = tabName !== "setup";
  tabPanelGenerate.hidden = tabName !== "generate";
  // The document lives on the generate tab, so the owl leaves with it.
  syncOwlVisibility();
  if (tabName === "generate") {
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (!hasAnyValue()) {
      setOwlState("guide", "Pick “Building Proficiency” or “Guided mode,” then click Generate. I'll help write it.");
    }
  } else if (tabName === "setup") {
    setOwlState("idle", "Let's set up your lesson plan. Tell me who's teaching and what subject.");
  }
}

genTabsEl.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => goToTab(btn.dataset.tab));
});

setupContinueBtn.addEventListener("click", () => {
  if (!updateGate()) {
    showError("Fill in the cooperating teacher and subject, and choose a Budget of Work or Curriculum Guide first.");
    return;
  }
  goToTab("generate");
});

// The course guide library groups grades the way DepEd's documents do.
function gradeBandFor() {
  if (levelTypeSelect.value !== "k12") return "";
  const grade = parseInt((k12GradeSelect.value || "").replace(/\D/g, ""), 10);
  if (grade >= 4 && grade <= 6) return "4-6";
  if (grade >= 7 && grade <= 8) return "7-8";
  if (grade >= 9 && grade <= 10) return "9-10";
  if (grade >= 11) return "SHS";
  return "";
}

const GUIDE_KIND_LABEL = { budget_of_work: "Budget of Work", curriculum_guide: "Curriculum Guide" };

// One picker per document kind, built from the same markup in generator.html.
// Each searches only its own kind (plus untyped uploads from before the split),
// shows what is chosen by highlighting its card and a summary under the list,
// and files an upload as its own kind.
const guidePickers = {};

function makeGuidePicker(root) {
  const kind = root.dataset.guideKind;
  const label = GUIDE_KIND_LABEL[kind];
  const tabs = [...root.querySelectorAll(".cg-tabs button")];
  const panes = [...root.querySelectorAll(".cg-tab-content")];
  const searchBtn = root.querySelector(".cg-search-btn");
  const resultsEl = root.querySelector(".cg-results");
  const noneEl = root.querySelector(".cg-none");
  const dropzone = root.querySelector(".cg-dropzone");
  const fileInput = root.querySelector(".cg-file-input");
  const selectedEl = root.querySelector(".cg-selected");

  tabs.forEach((btn) => btn.addEventListener("click", () => {
    tabs.forEach((b) => b.classList.toggle("active", b === btn));
    panes.forEach((p) => { p.hidden = p.dataset.pane !== btn.dataset.tab; });
  }));

  // The chosen card is marked in the list itself, not only in the summary
  // below it, so a teacher scanning the results sees at once which one is in use.
  function markResults() {
    const chosen = selectedGuides[kind];
    resultsEl.querySelectorAll(".cg-result-card").forEach((card) => {
      const on = !!chosen && Number(card.dataset.guideId) === chosen.id;
      card.classList.toggle("selected", on);
      card.setAttribute("aria-pressed", String(on));
      card.querySelector(".cg-pick").innerHTML = on ? `${Icons.check}Selected` : "Select";
    });
  }

  function renderSelected() {
    const g = selectedGuides[kind];
    root.classList.toggle("has-selection", !!g);
    selectedEl.hidden = !g;
    if (!g) {
      selectedEl.innerHTML = "";
    } else {
      selectedEl.innerHTML = `
        <span class="cg-selected-chip">
          ${Icons.checkSquare}
          <span>Using <strong>${escapeHtml(g.title)}</strong></span>
          <button type="button" class="btn btn-ghost btn-sm cg-clear-btn">Remove</button>
        </span>`;
      selectedEl.querySelector(".cg-clear-btn").addEventListener("click", () => select(null));
    }
    markResults();
  }

  function select(guide) {
    selectedGuides[kind] = guide;
    renderSelected();
    if (noneEl) noneEl.hidden = true;
    updateGate();
    saveDraft();
  }

  function renderResults(guides) {
    resultsEl.innerHTML = "";
    guides.forEach((g) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "cg-result-card";
      card.dataset.guideId = g.id;
      card.setAttribute("role", "listitem");
      const meta = g.is_builtin
        ? `${escapeHtml(g.curriculum || "DepEd")}${g.grades ? ` &middot; Grade ${escapeHtml(g.grades)}` : ""}`
        : `${escapeHtml(g.subject)} &middot; uploaded by ${escapeHtml(g.uploaded_by || "a teacher")}`;
      card.innerHTML = `
        <span>
          <span class="cg-title">${escapeHtml(g.title)}</span>
          <span class="cg-meta">${g.is_builtin ? `<span class="badge badge-official">${Icons.shieldCheck}Official DepEd</span> ` : ""}${meta}</span>
        </span>
        <span class="cg-pick text-sm">Select</span>`;
      card.addEventListener("click", () => select(g));
      resultsEl.appendChild(card);
    });
    markResults();
  }

  searchBtn.addEventListener("click", async () => {
    const subject = subjectInput.value.trim();
    if (!subject) {
      showError(`Select a subject first, then search for a ${label}.`);
      return;
    }
    errorBox.hidden = true;
    noneEl.hidden = true;
    setButtonLoading(searchBtn, true, "Searching");
    try {
      // The grade only ranks results, it never hides any: a document for the
      // next band up can still be the right reference.
      const data = await Api.searchCourseGuides({ subject, doc_type: kind, prefer_grade_band: gradeBandFor() });
      const guides = data.course_guides || [];
      if (!guides.length) {
        resultsEl.innerHTML = "";
        noneEl.hidden = false;
        return;
      }
      renderResults(guides);
    } catch (err) {
      showError(err.message);
    } finally {
      setButtonLoading(searchBtn, false);
    }
  });

  async function upload(file) {
    if (!/\.(docx|dotx|pdf)$/i.test(file.name)) {
      showError("Only .docx, .dotx, or .pdf files are allowed.");
      return;
    }
    const subject = subjectInput.value.trim();
    if (!subject) {
      showError(`Select a subject first, so this ${label} can be filed correctly.`);
      return;
    }
    errorBox.hidden = true;
    dropzone.style.opacity = "0.5";
    dropzone.style.pointerEvents = "none";
    try {
      const data = await Api.uploadCourseGuide(file, subject, file.name, kind);
      const g = data.course_guide;
      // The same file may already be in the library as the other kind (an
      // official Curriculum Guide dropped on the Budget of Work picker, say);
      // it goes where its own type says.
      const target = guidePickers[g.doc_type] || guidePickers[kind];
      target.select(g);
      showToast(
        data.duplicate
          ? `This file is already in the shared library, so the existing ${GUIDE_KIND_LABEL[g.doc_type] || label} is used.`
          : `${label} added to the shared library.`
      );
    } catch (err) {
      showError(err.message);
    } finally {
      dropzone.style.opacity = "1";
      dropzone.style.pointerEvents = "auto";
    }
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) upload(fileInput.files[0]);
  });

  return { select };
}

document.querySelectorAll("[data-guide-kind]").forEach((root) => {
  guidePickers[root.dataset.guideKind] = makeGuidePicker(root);
});

function buildSections(fields) {
  const map = new Map();
  const order = [];
  fields.forEach((f) => {
    const name = f.section_group && f.section_group.trim() ? f.section_group.trim() : "General";
    if (!map.has(name)) {
      map.set(name, []);
      order.push(name);
    }
    map.get(name).push(f);
  });
  return order.map((name) => ({ name, fields: map.get(name) }));
}

// ---- Guided mode: the teacher writes every field themselves, one at
// a time. Every field starts locked except the current one; submitting a
// non-empty answer unlocks the next. A completed field can be revisited by
// clicking its pill (which re-locks anything after it), but an upcoming
// field can't be skipped to. ----

// Which fields each mode is for. The role is resolved server-side and arrives on
// the field, so the keyword list lives in exactly one place (see
// backend/services/field_roles.py).
function fieldsInDocumentOrder() {
  return (fmt.fields || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
}

function heavyFieldKeys() {
  return fieldsInDocumentOrder().filter((f) => f.role === "heavy").map((f) => f.field_key);
}

function easyFieldKeys() {
  return fieldsInDocumentOrder().filter((f) => f.role !== "heavy" && f.role !== "self").map((f) => f.field_key);
}

// The student's own to write (lesson title, session number): never filled in
// automatically, only when they tick them in the checklist.
function selfFieldKeys() {
  return fieldsInDocumentOrder().filter((f) => f.role === "self").map((f) => f.field_key);
}

function fieldByKey(key) {
  return (fmt.fields || []).find((f) => f.field_key === key);
}

// ---- Weekly fields: one answer per day, each in its own slot ----
// A weekly field (ILAW's day columns) is one field whose value is a list with
// one entry per day, rendered as one slot per day carrying data-part. Every
// place that reads or writes a slot goes through these, so a plain field keeps
// working exactly as before.

function partCount(key) {
  const field = fieldByKey(key);
  return field && field.field_type === "weekly" && field.parts ? field.parts.length : 0;
}

function weeklyArray(value, count) {
  let parts;
  if (Array.isArray(value)) parts = value.slice();
  else if (value == null || String(value) === "") parts = [];
  else parts = [String(value)];
  parts = parts.slice(0, count).map((v) => (v == null ? "" : String(v)));
  while (parts.length < count) parts.push("");
  return parts;
}

function slotPart(el) {
  return el.dataset.part === undefined ? null : parseInt(el.dataset.part, 10);
}

// The text one slot shows: its day's entry for a weekly field, the whole value
// otherwise.
function valueForSlot(el) {
  const key = el.dataset.fieldKey;
  const value = fieldValues[key];
  const part = slotPart(el);
  if (part !== null) return weeklyArray(value, partCount(key))[part] || "";
  return Array.isArray(value) ? value.join("\n") : (value || "");
}

function richForSlot(el) {
  const rich = fieldRichValues[el.dataset.fieldKey];
  const part = slotPart(el);
  if (part !== null) return Array.isArray(rich) ? (rich[part] || "") : "";
  return Array.isArray(rich) ? "" : (rich || "");
}

// Writes one slot's text (and, when given, its styled HTML) back into the
// value maps, touching only that day's entry for a weekly field.
function storeSlot(el, text, html) {
  const key = el.dataset.fieldKey;
  const part = slotPart(el);
  if (part === null) {
    fieldValues[key] = text;
    if (html !== undefined) fieldRichValues[key] = html;
    return;
  }
  const count = partCount(key);
  const parts = weeklyArray(fieldValues[key], count);
  parts[part] = text;
  fieldValues[key] = parts;
  if (html !== undefined) {
    const rich = weeklyArray(Array.isArray(fieldRichValues[key]) ? fieldRichValues[key] : [], count);
    rich[part] = html;
    fieldRichValues[key] = rich;
  }
}

function slotsFor(key, root) {
  return root ? Array.from(root.querySelectorAll(`[data-field-key="${CSS.escape(key)}"]`)) : [];
}

// A value as the plain preview lists it: a weekly field reads "Monday: ..."
// line by line, leaving out days with nothing in them.
function previewValue(key) {
  const count = partCount(key);
  if (!count) return fieldValues[key];
  const names = fieldByKey(key).parts;
  return weeklyArray(fieldValues[key], count)
    .map((text, i) => (String(text).trim() ? `${names[i]}: ${text}` : ""))
    .filter(Boolean);
}

function hasValue(value) {
  return Array.isArray(value) ? value.some((v) => String(v == null ? "" : v).trim()) : !!String(value == null ? "" : value).trim();
}

// Which fields Alan must leave alone ("static"), remembered per format so a
// teacher who always writes their own Flow says so once. The student's own
// fields (role "self": lesson title, session number) start static, as they
// always have; every other field starts as Generate.
const SCOPE_V1 = "alignedGenScope:v1:";      // old checklist: heavy fields unticked
const SELF_SCOPE_PREFIX = "alignedGenSelf:v1:"; // old checklist: own fields ticked
const SCOPE_V2 = "alignedGenScope:v2:";      // { static: [...], seen: [...] }
let staticKeys = new Set();

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) {
    return fallback;
  }
}

function loadStaticKeys() {
  const all = fieldsInDocumentOrder().map((f) => f.field_key);
  const own = new Set(selfFieldKeys());
  const saved = readJson(SCOPE_V2 + fmt.id, null);
  let stat;
  let seen;
  if (saved && Array.isArray(saved.static)) {
    stat = new Set(saved.static);
    seen = new Set(saved.seen || []);
  } else {
    // First visit since the popup: carry the old checklist's choices over.
    const ownTicked = new Set(readJson(SELF_SCOPE_PREFIX + fmt.id, []));
    stat = new Set(readJson(SCOPE_V1 + fmt.id, []));
    selfFieldKeys().forEach((k) => {
      if (!ownTicked.has(k)) stat.add(k);
    });
    seen = new Set(all);
  }
  // A field added to the format since the last visit gets its role's default.
  all.forEach((k) => {
    if (!seen.has(k) && own.has(k)) stat.add(k);
  });
  staticKeys = new Set(all.filter((k) => stat.has(k)).concat(lockedKeys()));
}

// Fields the format's teacher locked: never generated, whatever is chosen here.
// The reflection, written after the lesson, is never generated either.
function lockedKeys() {
  return fieldsInDocumentOrder().filter((f) => f.locked || f.reflection).map((f) => f.field_key);
}

function saveStaticKeys() {
  try {
    localStorage.setItem(SCOPE_V2 + fmt.id, JSON.stringify({
      static: [...staticKeys],
      seen: fieldsInDocumentOrder().map((f) => f.field_key),
    }));
  } catch (err) {
    /* private mode or quota: the choice just won't persist */
  }
}

// "Lesson Title and Session No." / "A, B and C".
function joinLabels(labels) {
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

// Every field not kept static, in document order. The page sends the full list
// rather than letting the server decide, so "generate exactly what was asked
// for" is the only rule in play.
function selectedGenerateKeys() {
  return fieldsInDocumentOrder().map((f) => f.field_key).filter((k) => !staticKeys.has(k));
}

// Empty static fields keep a hatched "static" look after the popup closes, so
// the teacher can see which blanks are theirs to write.
// The placeholder says so too, instead of a tag that would sit on top of it.
function setStaticLook(el, isStatic) {
  const f = fieldByKey(el.dataset.fieldKey) || {};
  el.setAttribute("data-placeholder", f.reflection ? "Reflection: write it after the lesson"
    : f.locked ? "Locked by your teacher: yours to write" : isStatic ? "Static: yours to fill in" : "Not generated yet");
}

function paintStaticMarks() {
  liveDocWrap.querySelectorAll("[data-field-key]").forEach((el) => {
    setStaticLook(el, staticKeys.has(el.dataset.fieldKey));
    el.classList.toggle("lp-field-static", staticKeys.has(el.dataset.fieldKey));
  });
}

function isFieldComplete(key) {
  return hasValue(fieldValues[key]);
}

// stepFieldKeys is heavy-only, so finishing the walkthrough does not mean the
// plan is done - the easy fields outside it can still be blank. Any message
// that announces "done" or "complete" off the guided check alone is a
// false-completeness claim, the same bug the field-role split was meant to
// fix. Every place that needs to say so calls this one check, so the messages
// can't drift apart and start disagreeing about what "done" means.
function incompleteEasyFieldKeys() {
  return easyFieldKeys().concat(selfFieldKeys()).filter((k) => !isFieldComplete(k) && !stepFieldKeys.includes(k));
}

// The guided side of the same problem: Task 7 left already-stepped-past
// fields editable, and the Clear button acts on whatever field the caret is
// in regardless of stepIndex, so a field the walkthrough already passed can
// go blank again after the fact. Position (stepIndex) is no longer proof a
// guided field is answered, so anything claiming the walkthrough is "done"
// has to re-check every guided field, not just trust that reaching the last
// step means all the earlier ones are still filled in.
function incompleteGuidedFieldKeys() {
  return stepFieldKeys.filter((k) => !isFieldComplete(k));
}

function goToStep(i) {
  stepIndex = Math.max(0, Math.min(i, stepFieldKeys.length - 1));
  applyStepLocks();
}

// A dropdown instead of a row of pills — with 15-20+ fields on a real
// format, pills wrap into a wall of buttons at the top of the panel. The
// dropdown only ever lets you jump to a field you've already reached
// (options for anything still locked are disabled), same as clicking a
// "done" pill used to.
function renderStepFieldNav() {
  sectionNav.innerHTML = "";
  stepFieldKeys.forEach((key, i) => {
    const field = fieldByKey(key);
    const label = field ? field.label : key;
    const opt = document.createElement("option");
    opt.value = String(i);
    // The checkmark is a completeness claim, not a position marker, so it has
    // to ask isFieldComplete rather than just "did we step past this one" -
    // the Clear button can empty a field the teacher already stepped past.
    // Disabled (locked) still goes purely by position: staying reachable and
    // unlocked when it's before the cursor is what lets the teacher go back
    // and fix it, whether or not it's currently complete.
    // Words, not symbols: an <option> can't hold an icon, and emoji or
    // geometric glyphs render differently on every OS.
    opt.textContent =
      i === stepIndex
        ? `${label} (current)`
        : i > stepIndex
        ? `${label} (locked)`
        : isFieldComplete(key)
        ? `${label} (done)`
        : label;
    opt.disabled = i > stepIndex;
    sectionNav.appendChild(opt);
  });
  sectionNav.value = String(stepIndex);
  stepProgressLabel.textContent = `Field ${stepIndex + 1} of ${stepFieldKeys.length}`;

  const isLast = stepIndex >= stepFieldKeys.length - 1;
  stepContinueBtn.textContent = isLast ? "Finish" : "Submit & continue";
}

sectionNav.addEventListener("change", () => goToStep(parseInt(sectionNav.value, 10)));

// Locks every field except the one currently being written, in both the
// live document view and the plain field-list fallback (a blank-start
// format with no reference file).
function applyStepLocks() {
  if (docTemplateData) {
    const canvas = liveDocWrap.querySelector(".lp-doc");
    if (canvas) {
      let activeEl = null;
      // Only the walkthrough's own fields are locked or unlocked here. Anything
      // outside it keeps the editability the document was rendered with.
      stepFieldKeys.forEach((key, i) => {
        // Every slot of the field: a weekly field has one per day.
        slotsFor(key, canvas).forEach((el) => {
          el.classList.remove("step-locked", "step-active");
          if (i === stepIndex) {
            el.contentEditable = "true";
            el.classList.add("step-active");
            if (!activeEl) activeEl = el;
          } else if (i > stepIndex) {
            el.contentEditable = "false";
            el.classList.add("step-locked");
          } else {
            // A field the teacher has already answered stays theirs to correct.
            // It used to be set read-only with no lock styling at all, so it
            // looked perfectly editable and silently swallowed typing, which is
            // what "I can't edit the fields" was.
            el.contentEditable = "true";
          }
        });
      });
      if (activeEl) {
        activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
        activeEl.focus();
      }
    }
  } else {
    if (resultsEl.hidden || !resultsEl.querySelector("[data-field-key]")) renderResults();
    resultsEl.querySelectorAll("[data-field-key]").forEach((el) => {
      const i = stepFieldKeys.indexOf(el.dataset.fieldKey);
      // A field that is not part of the walkthrough at all (indexOf -> -1) stays
      // enabled, which is exactly right: the quick fields are always editable.
      el.disabled = i > stepIndex;
      el.classList.toggle("step-locked", i > stepIndex);
      el.classList.toggle("step-active", i === stepIndex);
      if (i === stepIndex) el.focus();
    });
  }
  renderStepFieldNav();
  introduceFieldInChat();
  saveDraft();
}

// Back to "everything editable" for Building Proficiency mode.
function clearStepLocks() {
  if (docTemplateData) {
    const canvas = liveDocWrap.querySelector(".lp-doc");
    if (canvas) {
      canvas.querySelectorAll("[data-field-key]").forEach((el) => {
        el.contentEditable = "true";
        el.classList.remove("step-locked", "step-active");
      });
    }
  } else {
    resultsEl.querySelectorAll("[data-field-key]").forEach((el) => {
      el.disabled = false;
      el.classList.remove("step-locked", "step-active");
    });
  }
}

function syncActiveStepValue() {
  const key = stepFieldKeys[stepIndex];
  if (!key) return;
  if (docTemplateData) {
    const canvas = liveDocWrap.querySelector(".lp-doc");
    slotsFor(key, canvas).forEach((el) => storeSlot(el, el.textContent));
  } else {
    slotsFor(key, resultsEl).forEach((el) => storeSlot(el, el.value));
  }
}

// Strips any bullet/dash/number the model (or a prior pass) may already have
// put on a line, so we can re-apply a single consistent marker.
function stripExistingBullet(line) {
  return line.replace(/^[•\-*]\s+/, "").replace(/^\d+[.)]\s+/, "").trim();
}

// AI responses for list-style fields (objectives, references, materials, etc.)
// can come back either as a JSON array or as a newline-separated string. This
// normalizes both into a single "• " bulleted string per line so the field
// reads as a real list instead of one run-on paragraph, while staying inside
// a plain, editable textarea. Single-line/paragraph values are left as-is.
function formatGeneratedValue(raw) {
  if (raw == null) return "";

  let items;
  if (Array.isArray(raw)) {
    items = raw.map((v) => String(v).trim()).filter(Boolean);
  } else {
    items = String(raw)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  if (items.length <= 1) return items[0] || "";

  // A numbered answer is an ordered procedure and keeps its numbering: turning
  // "1. 2. 3." into bullets would throw away the one thing the numbers carry,
  // which is that the steps happen in that order. The server already re-numbers
  // these cleanly, so they arrive as "1. ", "2. ", and so on.
  if (items.filter((item) => /^\(?\d{1,2}[.)]\s/.test(item)).length >= 2) {
    return items.join("\n");
  }

  // A lead-in line ("At the end of the lesson, the learners are expected to:")
  // introduces the list, so it stays a plain line above the bullets.
  return items.map((item) => (/:\s*$/.test(item) ? stripExistingBullet(item) : `• ${stripExistingBullet(item)}`)).join("\n");
}

// Runs formatGeneratedValue over a whole field_key -> value map returned by
// the AI, so every list-like field gets a consistent bulleted structure
// before it lands in fieldValues.
function formatGeneratedValues(values) {
  const out = {};
  Object.entries(values || {}).forEach(([key, val]) => {
    // A weekly field stays one entry per day, each formatted on its own.
    const count = partCount(key);
    out[key] = count ? weeklyArray(val, count).map(formatGeneratedValue) : formatGeneratedValue(val);
  });
  return out;
}

function isBulletedValue(value) {
  // Either list shape the app produces: bulleted, or a numbered procedure
  // whose numbering the server preserved.
  return typeof value === "string"
    && (/(^|\n)•\s/.test(value)
      || /(^|\n)\(?\d{1,2}[.)]\s/.test(value));
}

function fieldInputMarkup(field) {
  const requiredMark = field.is_required ? " *" : "";
  const hint = field.ai_hint ? `<p class="hint">${escapeHtml(field.ai_hint)}</p>` : "";

  // A weekly field: one labelled box per day.
  if (field.field_type === "weekly" && field.parts && field.parts.length) {
    const parts = weeklyArray(fieldValues[field.field_key], field.parts.length);
    return `
      <div class="field">
        <label>${escapeHtml(field.label)}${requiredMark}</label>
        <div class="weekly-parts">
          ${field.parts.map((name, i) => `
            <label class="weekly-part">
              <span class="weekly-part-name">${escapeHtml(name)}</span>
              <textarea data-field-key="${field.field_key}" data-part="${i}" rows="3" placeholder="Not generated yet">${escapeHtml(parts[i])}</textarea>
            </label>`).join("")}
        </div>
        ${hint}
      </div>
    `;
  }

  const value = fieldValues[field.field_key] || "";
  const bulleted = isBulletedValue(value) || field.field_type === "list" || field.field_type === "table";

  const lineCount = String(value).split("\n").length;
  const baseRows = field.field_type === "table" ? 5 : 4;
  const rows = value ? Math.min(14, Math.max(baseRows, lineCount + 1)) : baseRows;

  const control =
    field.field_type === "text"
      ? `<input type="text" data-field-key="${field.field_key}" value="${escapeHtml(value)}" placeholder="Not generated yet" />`
      : `<textarea data-field-key="${field.field_key}" rows="${rows}" class="${bulleted ? "textarea-list" : ""}" placeholder="Not generated yet">${escapeHtml(value)}</textarea>`;

  return `
    <div class="field">
      <label>${escapeHtml(field.label)}${requiredMark}</label>
      ${control}
      ${hint}
    </div>
  `;
}

function sectionBlockMarkup(section) {
  return `
    <div class="section-group">
      <h2>${escapeHtml(section.name)}</h2>
      ${section.fields.map(fieldInputMarkup).join("")}
    </div>
  `;
}

function renderResults() {
  resultsEl.innerHTML = sections.map(sectionBlockMarkup).join("");

  resultsEl.querySelectorAll("[data-field-key]").forEach((el) => {
    el.addEventListener("input", () => {
      storeSlot(el, el.value);
      markDirty();
      if (mode === "step") renderStepFieldNav();
    });
  });

  footer.hidden = false;
}

// ---- Live document view: the format's real reference file, shown up front
// (empty) and filled in as generation happens, instead of a plain list of
// form fields. Used whenever this format has a real reference document;
// falls back to renderResults() otherwise (a blank-start format has no
// document to render at all). ----

async function initLiveDocView() {
  try {
    const data = await Api.getFormatTemplateHtml(fmt.id);
    if (!data.html) return;
    docTemplateData = data;
  } catch (err) {
    docTemplateData = null;
    return;
  }

  liveDocWrap.innerHTML = docTemplateData.html;
  liveDocStage.hidden = false;
  liveDocHint.hidden = false;
  resultsEl.hidden = true;
  footer.hidden = false;
  wireLiveDocEditing();
  wireLiveDocToolbar();
}

// Only these tags survive out of a field's contenteditable innerHTML — a
// browser's rich-text commands (execCommand) can produce other wrapper
// elements (span, div) depending on browser, which this flattens down to
// their text/line-break content instead of storing arbitrary markup.
const RICH_VALUE_TAGS = new Set(["B", "STRONG", "I", "EM", "U", "UL", "OL", "LI", "BR"]);
const RICH_VALUE_BLOCK_TAGS = new Set(["DIV", "P"]);

// The closed set of classes a <span> may carry through the sanitizer. These are
// the only styles the Word export knows how to reproduce, so allowing anything
// else would let a teacher apply formatting on screen that silently disappeared
// on export. A span whose classes are all rejected is unwrapped to its text.
const RICH_VALUE_SPAN_CLASSES = new Set([
  "fs-sm", "fs-md", "fs-lg", "fs-xl",
  "fc-default", "fc-red", "fc-amber", "fc-green", "fc-blue",
  "hl-none", "hl-yellow", "hl-green", "hl-cyan",
]);

function allowedSpanClasses(el) {
  return Array.from(el.classList).filter((cls) => RICH_VALUE_SPAN_CLASSES.has(cls));
}

function sanitizeRichValueHtml(node) {
  let out = "";
  node.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      out += escapeHtml(child.textContent);
      return;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) return;
    const tag = child.tagName;
    if (tag === "BR") {
      out += "<br>";
    } else if (tag === "SPAN" && child.classList.contains("lp-img")) {
      // Only pictures a student uploaded (an id of the exact shape the server
      // issues). Rebuilt from the vocabulary rather than copied, so the resize
      // handle, inline styles and any src never get stored.
      const id = child.dataset.imgId || "";
      if (!/^[0-9a-f]{32}$/.test(id)) return;
      const s = readDocImage(child);
      const cap = child.querySelector(".lp-img-cap");
      const capHtml = cap && cap.textContent.trim() ? `<span class="lp-img-cap">${sanitizeRichValueHtml(cap)}</span>` : "";
      out += `<span class="lp-img img-align-${s.align} img-wrap-${s.wrap}${s.border ? " img-border" : ""}" data-img-id="${id}" data-width-pct="${s.width_pct}" contenteditable="false"><img src="${docImageUrl(id)}" alt="">${capHtml}</span>`;
    } else if (tag === "SPAN" && child.classList.contains("lp-img-handle")) {
      return;
    } else if (tag === "SPAN") {
      // Kept only for the vocabulary classes, and only those: the class
      // attribute is rebuilt from the allowlist rather than copied, so nothing
      // arbitrary can ride along in it.
      const classes = allowedSpanClasses(child);
      const inner = sanitizeRichValueHtml(child);
      out += classes.length ? `<span class="${classes.join(" ")}">${inner}</span>` : inner;
    } else if (RICH_VALUE_TAGS.has(tag)) {
      out += `<${tag.toLowerCase()}>${sanitizeRichValueHtml(child)}</${tag.toLowerCase()}>`;
    } else {
      out += sanitizeRichValueHtml(child) + (RICH_VALUE_BLOCK_TAGS.has(tag) ? "<br>" : "");
    }
  });
  return out;
}

function syncFieldFromEl(el) {
  storeSlot(el, el.textContent, sanitizeRichValueHtml(el));
  el.classList.toggle("lp-filled", !!el.textContent.trim() || !!el.querySelector(".lp-img"));
}

// The value-map half of clearing a field: shared by clearField() below and by
// the Guided fallback field-list branch (an input/textarea, not a DOM slot,
// so it can't go through clearField() itself). Also re-renders the step nav,
// since its checkmark now reflects real completeness rather than position,
// and clearing a field the teacher already stepped past has to un-tick it.
function clearFieldState(key) {
  fieldValues[key] = partCount(key) ? weeklyArray([], partCount(key)) : "";
  delete fieldRichValues[key];
  markDirty();
  if (mode === "step") renderStepFieldNav();
}

// Empties one field so the teacher can write their own answer or ask for a
// different suggestion. Clears the rich value as well as the plain text,
// otherwise the old styled HTML would come back on the next render.
function clearField(el) {
  const key = el.dataset.fieldKey;
  // Every slot of the field: a weekly field is cleared for the whole week.
  const root = el.closest(".lp-doc") || el.parentElement;
  (slotsFor(key, root).length ? slotsFor(key, root) : [el]).forEach((slot) => {
    slot.innerHTML = "";
    slot.classList.remove("lp-filled", "field-needs-answer");
  });
  clearFieldState(key);
}

// The document body, keyed by the position each line occupies in the real .docx
// (the same anchor_index the format builder addresses). Captured as rendered so
// an edit can be recognised by comparing against it, and so only what actually
// changed is ever sent.
let docBaseline = {};

function captureDocBaseline(canvas) {
  docBaseline = {};
  canvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    docBaseline[el.dataset.anchorIndex] = anchorText(el);
  });
}

// A line's own text, excluding any field slot sitting inside it. The slot's
// content belongs to the AI field, not to the document body, and folding it in
// here would make every generated value look like a hand edit to the label.
function anchorText(el) {
  let out = "";
  el.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += node.textContent;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.hasAttribute && node.hasAttribute("data-field-key")) return;
    out += anchorText(node);
  });
  return out.replace(/ /g, " ").trim();
}

// Only the lines the teacher actually changed, in the shape the export replays.
// Put saved edits back on screen. The baseline stays as the untouched template
// text on purpose: a restored edit is still a difference from the reference
// file, so it keeps being sent on the next save rather than being mistaken for
// the original wording and quietly dropped.
function applyDocEdits(edits) {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (!canvas || !Array.isArray(edits) || !edits.length) return;
  edits.forEach((edit) => {
    if (!edit || typeof edit.text !== "string") return;
    const el = canvas.querySelector(`[data-anchor-index="${CSS.escape(String(edit.anchor_index))}"]`);
    if (!el) return;
    // Write only the line's own text, keeping any field slot that lives inside
    // it: the slot belongs to the AI field, not to the body text being replaced.
    const slot = el.querySelector("[data-field-key]");
    el.textContent = edit.text;
    if (slot) el.appendChild(slot);
  });
}

function collectDocEdits() {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (!canvas) return [];
  const edits = [];
  canvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    if (Number.isNaN(idx)) return;
    const now = anchorText(el);
    if (docBaseline[el.dataset.anchorIndex] === undefined) return;
    if (now === docBaseline[el.dataset.anchorIndex]) return;
    edits.push({ anchor_index: idx, text: now });
  });
  return edits;
}

function wireLiveDocEditing() {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (!canvas) return;

  captureDocBaseline(canvas);

  // The whole document is the teacher's to edit, not only the AI's slots. The
  // slots stay marked so it is obvious which parts regenerating will overwrite,
  // but every label, heading and cell around them takes typing too.
  canvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    el.contentEditable = "true";
    el.addEventListener("input", () => markDirty());
  });
  canvas.querySelectorAll("[data-field-key]").forEach((el) => {
    el.setAttribute("data-placeholder", "Not generated yet");
    el.addEventListener("input", () => {
      syncFieldFromEl(el);
      markDirty();
      if (mode === "step") renderStepFieldNav();
    });
  });
}

function updateLiveDocToolbarStates() {
  ["bold", "italic", "underline", "justifyLeft", "justifyCenter", "justifyRight", "justifyFull"].forEach((cmd) => {
    const btn = liveDocToolbar.querySelector(`[data-cmd="${cmd}"]`);
    if (!btn) return;
    let active = false;
    try { active = document.queryCommandState(cmd); } catch (e) { /* unsupported in this browser */ }
    btn.classList.toggle("active", active);
  });
}

// The field slot the caret is currently in, or null. Every text tool needs one:
// applying a style with the caret outside the document would either do nothing
// or edit the page around it.
function activeFieldEl() {
  const el = document.activeElement;
  if (el && el.dataset && el.dataset.fieldKey) return el;
  // A click straight onto a toolbar button can move focus off the slot even
  // with mousedown suppressed, so fall back to whatever the selection is in.
  const selection = window.getSelection();
  if (!selection || !selection.anchorNode) return null;
  const node = selection.anchorNode.nodeType === Node.ELEMENT_NODE
    ? selection.anchorNode
    : selection.anchorNode.parentElement;
  const slot = node && node.closest ? node.closest("[data-field-key]") : null;
  return slot && liveDocWrap.contains(slot) ? slot : null;
}

// Wraps the current selection in a span carrying one class out of the fixed
// vocabulary, replacing any previous class of the same kind. execCommand has no
// command for this, and its styleWithCSS output is inline CSS the sanitizer
// deliberately drops, so the span is built here instead.
function applyDocSpanClass(prefixes, className) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    showToast("Select some text first, then choose a style.", true);
    return false;
  }

  const range = selection.getRangeAt(0);
  const contents = range.extractContents();

  // Strip any existing class of the same kind from the selected fragment, so
  // picking red over blue replaces it rather than nesting the two.
  contents.querySelectorAll("span").forEach((span) => {
    prefixes.forEach((prefix) => {
      Array.from(span.classList)
        .filter((cls) => cls.startsWith(prefix))
        .forEach((cls) => span.classList.remove(cls));
    });
    // A span left with no classes is noise; unwrap it.
    if (!span.classList.length) span.replaceWith(...span.childNodes);
  });

  // "Default" and "None" mean "remove the styling", so no new span is added.
  const isReset = className === "fc-default" || className === "hl-none" || className === "";
  if (isReset) {
    range.insertNode(contents);
  } else {
    const wrapper = document.createElement("span");
    wrapper.className = className;
    wrapper.appendChild(contents);
    range.insertNode(wrapper);
  }

  selection.removeAllRanges();
  return true;
}

function wireLiveDocToolbar() {
  // Built from the shared module, so this toolbar and the format builder's are
  // the same set of tools rather than two hand-kept copies.
  liveDocToolbar.innerHTML = renderDocToolbar({ variant: "generator" });
  paintDocToolbarIcons(liveDocToolbar);

  // Keep the field's selection alive when a toolbar control is clicked —
  // otherwise the button would steal focus and the command would have nothing
  // to act on.
  liveDocToolbar.querySelectorAll("button, select").forEach((el) => {
    el.addEventListener("mousedown", (e) => {
      // Selects must stay clickable, so only buttons suppress mousedown.
      if (el.tagName === "BUTTON") e.preventDefault();
    });
  });

  // Applies a change to the field the caret is in, then writes the result back
  // into fieldValues/fieldRichValues. Every tool below goes through here so
  // none of them can forget to persist what it just did.
  function withActiveField(warning, fn) {
    const el = activeFieldEl();
    if (!el) {
      showToast(warning, true);
      return;
    }
    // execCommand needs the slot focused, which it may not be after a click.
    if (document.activeElement !== el) el.focus();
    fn(el);
    updateLiveDocToolbarStates();
    syncFieldFromEl(el);
    markDirty();
  }

  liveDocToolbar.querySelectorAll(".doc-tool-btn[data-cmd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cmd = btn.dataset.cmd;
      // Undo and redo are document-wide and meaningful even with the caret
      // between fields, so they don't demand an active slot.
      if (cmd === "undo" || cmd === "redo") {
        document.execCommand(cmd, false, null);
        const el = activeFieldEl();
        if (el) syncFieldFromEl(el);
        markDirty();
        return;
      }
      withActiveField("Click into a field first, then choose a style.", () => {
        document.execCommand(cmd, false, null);
      });
    });
  });

  const clearFieldBtn = liveDocToolbar.querySelector("[data-clear-field]");
  if (clearFieldBtn) {
    clearFieldBtn.addEventListener("click", () => {
      const el = activeFieldEl();
      if (!el) {
        showToast("Click into the field you want to clear first.", true);
        return;
      }
      clearField(el);
      el.focus();
    });
  }

  liveDocToolbar.querySelectorAll(".doc-tool-btn[data-list]").forEach((btn) => {
    btn.addEventListener("click", () => {
      withActiveField("Click into a field first, then choose a list style.", () => {
        document.execCommand(
          btn.dataset.list === "bullet" ? "insertUnorderedList" : "insertOrderedList",
          false,
          null
        );
      });
    });
  });

  // Heading style inside a filled plan means emphasis on the selected text, not
  // a document heading: a field slot sits inside the template's own structure,
  // so wrapping it in an <h2> would fight the layout the format defines. The
  // sizes map onto the same fixed vocabulary as the size picker.
  const headingSelect = liveDocToolbar.querySelector("#doc-heading-select");
  if (headingSelect) {
    const HEADING_TO_SIZE = { p: "", h1: "fs-xl", h2: "fs-lg", h3: "fs-md" };
    headingSelect.addEventListener("change", () => {
      const cls = HEADING_TO_SIZE[headingSelect.value] || "";
      withActiveField("Click into a field first, then choose a style.", () => {
        if (applyDocSpanClass(["fs-"], cls) && headingSelect.value !== "p") {
          // A heading is bold as well as bigger, which is what makes it read
          // as a heading rather than just large text.
          document.execCommand("bold", false, null);
        }
      });
      headingSelect.value = "p";
    });
  }

  const sizeSelect = liveDocToolbar.querySelector("#doc-size-select");
  if (sizeSelect) {
    sizeSelect.addEventListener("change", () => {
      const cls = sizeSelect.value;
      withActiveField("Click into a field first, then choose a size.", () => {
        applyDocSpanClass(["fs-"], cls);
      });
      sizeSelect.value = "";
    });
  }

  initDocToolbarMenus({
    toolbarEl: liveDocToolbar,
    onPick: (kind, className) => {
      const prefix = kind === "color" ? "fc-" : "hl-";
      withActiveField("Select some text in a field first.", () => {
        applyDocSpanClass([prefix], className);
      });
    },
  });

  initDocViewControls({
    toolbarEl: liveDocToolbar,
    wrapEl: liveDocWrap,
    stageEl: liveDocStage,
    storageKey: "alignedDocZoom:generator",
  });

  liveDocWrap.addEventListener("keyup", updateLiveDocToolbarStates);
  liveDocWrap.addEventListener("mouseup", updateLiveDocToolbarStates);

  // Pictures a student adds while editing a field. The format's own pictures
  // belong to the template, so only pictures inside a field are theirs to change.
  const fieldOf = (fig) => fig.closest("[data-field-key]");
  initDocImageTools({
    rootEl: liveDocWrap,
    selectable: (fig) => !!fig.dataset.imgId && !!fieldOf(fig),
    onChange: (fig) => {
      const f = fieldOf(fig);
      if (f) {
        syncFieldFromEl(f);
        markDirty();
      }
    },
    onDelete: (fig) => {
      const f = fieldOf(fig);
      fig.remove();
      if (f) {
        syncFieldFromEl(f);
        markDirty();
      }
    },
  });

  let imageTargetRange = null;
  initDocImageInsert({
    toolbarEl: liveDocToolbar,
    beforePick: () => {
      if (!activeFieldEl()) {
        showToast("Click into a field first, then choose Insert image.", true);
        return false;
      }
      const sel = window.getSelection();
      imageTargetRange = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
      return true;
    },
    onUploaded: (res) => {
      const range = imageTargetRange;
      if (!range) return;
      const node = range.startContainer;
      const field = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement).closest("[data-field-key]");
      if (!field) return;
      const tpl = document.createElement("template");
      tpl.innerHTML = docImageMarkup({ id: res.id });
      range.collapse(false);
      range.insertNode(tpl.content.firstChild);
      hydrateDocImages(field);
      field.classList.add("lp-filled");
      syncFieldFromEl(field);
      markDirty();
    },
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Reveals a batch of freshly generated fields into the live document one at
// a time, with a short pause between each — so watching a plan generate
// looks like something is actually being written, instead of a wall of text
// appearing all at once.
async function revealFieldsInLiveDoc(keys) {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (!canvas) return;
  for (const key of keys) {
    const slots = slotsFor(key, canvas);
    if (slots.length) {
      delete fieldRichValues[key]; // fresh AI text replaces any earlier manual styling
      slots.forEach((el) => {
        el.textContent = valueForSlot(el);
        el.classList.toggle("lp-filled", !!el.textContent.trim());
      });
      slots[0].scrollIntoView({ behavior: "smooth", block: "center" });
    }
    await sleep(220);
  }
}

function hasAnyValue() {
  return Object.values(fieldValues).some(hasValue);
}

// The live document view always shows every field already (there's no
// per-section re-render needed); only the plain field-list fallback
// (formats with no reference file) needs re-rendering on nav/mode changes.
function maybeRenderResults() {
  if (!docTemplateData && hasAnyValue()) renderResults();
}

function markDirty() {
  dirty = true;
  editSeq++;
  syncedWithServer = false;
  saveStatus.textContent = "Unsaved changes. Save to export the latest version.";
  exportBtn.style.pointerEvents = "none";
  exportBtn.style.opacity = "0.5";
  saveDraft();
  scheduleServerSave();
}

// ---- Saving to the server -------------------------------------------------
// One path writes a plan, used by both the autosave below and the Save button:
// the first write POSTs and captures the new id, every write after it PATCHes
// that same row. Without this the generator could only ever create plans, so an
// unfinished plan either vanished or piled up a new row per save.

const SERVER_SAVE_DELAY_MS = 2000;
let serverSaveTimer = null;
let serverSaveInFlight = false;
// Set when the server refuses further edits (the plan was submitted or graded
// in another tab). Autosaving stops rather than retrying into a wall.
let serverSaveLocked = false;

// The "Before we start" answers, in one shape used by both the localStorage
// draft and the saved plan. They had no home on the plan row before, so
// reopening one dropped the teacher back into that form with the fields blank:
// grade_level only holds a display string that cannot be split back into the
// dropdowns it came from, and the course guide the gate insists on was never
// stored at all.
function setupContext() {
  return {
    setup: {
      teacher: teacherNameInput.value,
      subject: subjectInput.value,
      topic: topicInput.value,
      levelType: levelTypeSelect.value,
      collegeProgram: collegeProgramInput.value,
      collegeYear: collegeYearSelect.value,
      k12Grade: k12GradeSelect.value,
      section: sectionInput.value,
      school: schoolInput.value,
      studentTeacher: studentTeacherInput.value,
      durationMinutes: durationInput.value,
      previousTopic: prevTopicInput.value,
      nextTopic: nextTopicInput.value,
      mainTopic: mainTopicInput.value,
      runId: currentRunId,
      formatId: fmt ? fmt.id : null,
      flow: { ...flowFlags },
    },
    courseGuide: selectedGuides.curriculum_guide,
    budgetOfWork: selectedGuides.budget_of_work,
    // Rides along here rather than in its own column: export reads it from
    // the saved plan, so every device exports on the same paper.
    pageSize: pageSizeSelect.value,
  };
}

// Puts a saved setup block back on screen. Shared by the draft restore and the
// plan restore so the two can never drift into filling different fields.
function applySetupContext(ctx) {
  const setup = (ctx && ctx.setup) || {};
  if (setup.teacher) teacherNameInput.value = setup.teacher;
  if (setup.subject) subjectInput.value = setup.subject;
  // Set in code, so the change listener that renames the search buttons
  // never fired; a restored plan still said "this subject".
  syncGuideSearchLabels();
  if (setup.topic) topicInput.value = setup.topic;
  if (setup.levelType) levelTypeSelect.value = setup.levelType;
  if (setup.collegeProgram) collegeProgramInput.value = setup.collegeProgram;
  if (setup.collegeYear) collegeYearSelect.value = setup.collegeYear;
  if (setup.k12Grade) k12GradeSelect.value = setup.k12Grade;
  if (setup.section) sectionInput.value = setup.section;
  if (setup.school) schoolInput.value = setup.school;
  if (setup.studentTeacher) studentTeacherInput.value = setup.studentTeacher;
  if (setup.durationMinutes) durationInput.value = setup.durationMinutes;
  if (setup.previousTopic) prevTopicInput.value = setup.previousTopic;
  if (setup.nextTopic) nextTopicInput.value = setup.nextTopic;
  if (setup.mainTopic) mainTopicInput.value = setup.mainTopic;
  if (setup.flow) flowFlags = { ...flowFlags, ...setup.flow };
  // Saved before step 6 took several sources: its one guide of each kind
  // becomes the picked list.
  if (ctx && !(setup.flow && setup.flow.guides)) {
    flowFlags.guides = [ctx.budgetOfWork, ctx.courseGuide].filter(Boolean);
  }
  if (ctx && ctx.pageSize) pageSizeSelect.value = ctx.pageSize;
  updateLevelFields();
}

function planPayload() {
  // The active slot must be current before it (or the inactive one below) is
  // read, or a save right after typing could ship a stale mode_values.
  captureModeSlot();
  return {
    format_id: fmt.id,
    title: planTitle(),
    subject: subjectInput.value.trim(),
    grade_level: getClassLabel(),
    field_values: fieldValues,
    rich_field_values: fieldRichValues,
    mode_values: inactiveModeSlot(),
    setup_context: setupContext(),
    doc_edits: collectDocEdits(),
    generation_mode: mode,
    is_public: visibilityCheckbox.checked,
    // The paid build a student's new plan belongs to (see payForBuild).
    run_key: currentRunId,
  };
}

// The name the teacher gave the plan (asked on Save, or set by renaming it in
// the list). Until there is one, the title follows the topic.
let planName = "";

function planTitle() {
  if (planName) return planName;
  const subject = subjectInput.value.trim();
  const topic = topicInput.value.trim();
  // Topic first when there is one: a teacher's drafts are nearly all the same
  // subject and format, so "Subject — Format" would give every card in the
  // "continue where you left off" strip an identical name.
  if (topic) return `${topic}${subject ? ` · ${subject}` : ""}`;
  if (subject) return `${subject} · ${fmt.name}`;
  return `Untitled ${fmt.name}`;
}

// A plan is only worth a row once it holds something a teacher would want
// back. Without this, merely opening the generator would leave an empty draft
// behind every time.
function worthSaving() {
  return hasAnyValue() || !!subjectInput.value.trim() || !!topicInput.value.trim();
}

// Saves run one at a time. The autosave and the Save button used to be able to
// overlap, which now matters twice over: two PATCHes carrying the same
// base_revision would make the page conflict with itself, and two POSTs before
// the first returned an id would create the plan twice. The payload is built
// when a save's turn comes, so it always carries the latest revision.
let saveQueue = Promise.resolve();

function persistPlan() {
  const run = saveQueue.then(persistPlanNow);
  saveQueue = run.catch(() => {});
  return run;
}

async function persistPlanNow() {
  if (!fmt) return null;
  const payload = planPayload();
  let data;
  if (planId) {
    // Visibility is changed only through its own control (which saves it at
    // once), so an autosave never carries it: a stale tab would otherwise
    // quietly flip a plan back to private or public. And a revision this page
    // doesn't know is sent as -1, never left out, because a save without one
    // skips the check altogether.
    const { is_public: _visibility, ...changes } = payload;
    data = await Api.updateLessonPlan(planId, { ...changes, base_revision: planRevision ?? -1 });
  } else {
    data = await Api.saveLessonPlan(payload);
    planId = data.lesson_plan.id;
  }
  planRevision = data.lesson_plan.revision;
  // The local draft carries the revision too; without rewriting it here it
  // would still hold the one from before this save, and coming back to the
  // page later would conflict with this very save.
  saveDraft();
  return data.lesson_plan;
}

// Whether nothing was typed since edit number `seq`, i.e. the save that just
// finished covers everything on screen. Only then is the page clean.
function savedEverythingSince(seq) {
  if (editSeq !== seq) return false;
  dirty = false;
  syncedWithServer = true;
  return true;
}

function isStaleSave(err) {
  return err && err.status === 409 && err.data && err.data.code === "stale";
}

function scheduleServerSave() {
  if (serverSaveLocked || restoringDraft) return;
  clearTimeout(serverSaveTimer);
  serverSaveTimer = setTimeout(runServerSave, SERVER_SAVE_DELAY_MS);
}

async function runServerSave() {
  if (serverSaveLocked || !fmt || !worthSaving()) return;
  // Already saving: try again once it lands rather than dropping this edit,
  // which is what returning here used to do.
  if (serverSaveInFlight) {
    scheduleServerSave();
    return;
  }

  serverSaveInFlight = true;
  const seq = editSeq;
  try {
    await persistPlan();
    // Only claim saved if nothing changed while the request was in flight —
    // otherwise the newer edit is still unsaved and saying otherwise would
    // lie about it.
    if (savedEverythingSince(seq)) {
      saveStatus.textContent = `Draft saved ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`;
      enableExport();
    }
  } catch (err) {
    if (isStaleSave(err)) {
      showConflict(err.data.lesson_plan);
    // 409 means the plan was submitted or graded elsewhere, so it will never
    // accept another edit — stop autosaving and say so once.
    } else if (/submitted/i.test(err.message || "")) {
      serverSaveLocked = true;
      saveStatus.textContent = "This plan has been submitted and can no longer be edited.";
      showToast("This plan has been submitted, so your latest changes weren't saved.", true);
    } else {
      // A transient failure (offline, server restart) leaves the localStorage
      // draft as the safety net and the page still marked unsaved.
      saveStatus.textContent = "Couldn't save the draft automatically. Use Save lesson plan.";
    }
  } finally {
    serverSaveInFlight = false;
  }
}

function enableExport() {
  if (!planId) return;
  exportBtn.href = Api.exportUrl(planId);
  exportBtn.style.pointerEvents = "auto";
  exportBtn.style.opacity = "1";
}

// Export asks for the file name first (api.js exportPlan).
exportBtn.addEventListener("click", (e) => {
  e.preventDefault();
  if (!planId) return;
  const topic = topicInput.value.trim() || mainTopicInput.value.trim();
  exportPlan(planId, [topic, fmt && fmt.name].filter(Boolean).join(" - "));
});

// ---- Same plan on two devices ----------------------------------------------
// A stale save is refused by the server (see update_lesson_plan), and this is
// where the page catches up: switching back to a tab silently loads a newer
// copy when this one has nothing unsaved, and an unsaved edit that lost the
// race asks rather than overwriting either side.

const conflictOverlay = document.getElementById("conflict-overlay");
let conflictPlan = null;

function reopenFromServer(id) {
  // Nothing on this device is worth keeping by now (caller's decision), and a
  // leftover draft would be restored over the newer copy on the next visit.
  clearDraft();
  dirty = false;
  leavingConfirmed = true;
  window.location.replace(`generator.html?plan_id=${encodeURIComponent(id)}`);
}

function showConflict(newer) {
  serverSaveLocked = true;
  clearTimeout(serverSaveTimer);
  conflictPlan = newer;
  saveStatus.textContent = "Not saved: this plan was changed on another device.";
  const when = newer && newer.updated_at ? new Date(newer.updated_at) : null;
  document.getElementById("conflict-when").textContent = when
    ? `The other copy was saved ${when.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}.`
    : "";
  openDialog(conflictOverlay);
}

document.getElementById("conflict-load").addEventListener("click", () => {
  reopenFromServer(conflictPlan ? conflictPlan.id : planId);
});

document.getElementById("conflict-copy").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  setButtonLoading(btn, true, "Saving");
  // Detach from the row the other device owns, then save this device's work
  // as a new plan. Both versions survive; the teacher keeps whichever.
  planId = null;
  planRevision = null;
  try {
    const plan = await persistPlan();
    serverSaveLocked = false;
    dirty = false;
    syncedWithServer = true;
    clearDraft();
    // A reload should reopen this copy, not the plan it split from.
    history.replaceState(null, "", `generator.html?plan_id=${plan.id}`);
    closeDialog(conflictOverlay);
    saveStatus.textContent = "Saved as a separate copy.";
    enableExport();
    showToast("Saved your version as a separate plan. The other version is still in your list.");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(btn, false);
  }
});

// The usual laptop-to-phone-and-back case: when this tab comes back into view,
// check whether the plan moved on elsewhere. If nothing here is unsaved, load
// the newer copy now, before the next keystroke would conflict with it.
async function checkForNewerCopy() {
  if (!planId || serverSaveLocked || !syncedWithServer || serverSaveInFlight) return;
  try {
    const { lesson_plan: plan } = await Api.getLessonPlan(planId);
    if (syncedWithServer && plan.revision > planRevision) reopenFromServer(plan.id);
  } catch (err) {
    /* offline or signed out — the next save will find out */
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    checkForNewerCopy();
  } else if (dirty && !serverSaveLocked) {
    // Leaving for another app or device: don't wait out the debounce, or the
    // last few seconds of typing aren't there when the plan is opened next.
    clearTimeout(serverSaveTimer);
    runServerSave();
  }
});

// ---- Unsaved-changes warning -------------------------------------------------
// The localStorage draft survives a navigation on this device, but not a
// switch to another one, so leaving with changes the server doesn't have yet
// asks first. App links get the page's own dialog; closing or reloading the
// tab can only get the browser's.

const leaveOverlay = document.getElementById("leave-overlay");
let leaveHref = null;
let leavingConfirmed = false;

function hasUnsavedWork() {
  return dirty && worthSaving() && !leavingConfirmed;
}

function leaveTo(href) {
  leavingConfirmed = true;
  closeDialog(leaveOverlay);
  showPageTransition();
  window.location.href = href;
}

// Capture phase, so this runs before api.js's page-transition handler, which
// skips any click already default-prevented.
document.addEventListener("click", (e) => {
  if (!hasUnsavedWork() || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const link = e.target.closest("a[href]");
  if (!link || link.target === "_blank" || link === exportBtn) return;
  const href = link.getAttribute("href");
  if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
  e.preventDefault();
  leaveHref = link.href;
  openDialog(leaveOverlay);
}, true);

window.addEventListener("beforeunload", (e) => {
  if (!hasUnsavedWork()) return;
  e.preventDefault();
  e.returnValue = "";
});

wireDialog(leaveOverlay);
document.getElementById("leave-close").addEventListener("click", () => closeDialog(leaveOverlay));
document.getElementById("leave-stay").addEventListener("click", () => closeDialog(leaveOverlay));
document.getElementById("leave-discard").addEventListener("click", () => leaveTo(leaveHref));
document.getElementById("leave-save").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  clearTimeout(serverSaveTimer);
  setButtonLoading(btn, true, "Saving");
  try {
    await persistPlan();
    dirty = false;
    leaveTo(leaveHref);
  } catch (err) {
    closeDialog(leaveOverlay);
    if (isStaleSave(err)) showConflict(err.data.lesson_plan);
    else showToast(err.message, true);
  } finally {
    setButtonLoading(btn, false);
  }
});

// ---- Draft autosave -------------------------------------------------------
// This is a multi-page app: clicking a sidebar link, or opening the plan in
// another browser tab, is a full navigation that throws away every variable
// on this page. Everything a teacher had typed used to go with it. The draft
// below keeps the in-progress plan in localStorage, keyed by format, and
// restores it on the way back in, so leaving the page is no longer the same
// as discarding the work.
const DRAFT_PREFIX = "alignedDraft:v1:";
let draftTimer = null;
let restoringDraft = false;

function draftKey() {
  const params = new URLSearchParams(window.location.search);
  // A plan opened by id gets its own slot: keying only by format would make
  // two drafts of the same format share one slot and overwrite each other.
  const planKey = params.get("plan_id");
  if (planKey) return `${DRAFT_PREFIX}plan:${planKey}`;
  return runDraftKey(currentRunId || "none");
}

function saveDraft() {
  // Never write while the restore is still populating the page, or a
  // half-applied draft would overwrite the complete one.
  if (restoringDraft) return;
  // The brief only has planPayload() do this, but saveDraft() also persists
  // modeSlots and runs far more often (every keystroke, debounced) — without
  // this, a draft written between mode switches would carry a stale inactive
  // slot instead of what is actually on screen right now.
  captureModeSlot();
  clearTimeout(draftTimer);
  draftTimer = setTimeout(writeDraft, 400);
}

function writeDraft() {
  clearTimeout(draftTimer);
  {
    try {
      localStorage.setItem(draftKey(), JSON.stringify({
        at: Date.now(),
        planId,
        planRevision,
        mode,
        stepIndex,
        fieldValues,
        fieldRichValues,
        modeSlots,
        planName,
        // Same shape the saved plan stores, from one definition.
        ...setupContext(),
        docEdits: collectDocEdits(),
      }));
    } catch (err) {
      /* private mode or quota — the page still works, it just won't persist */
    }
  }
}

function readDraft() {
  try {
    return JSON.parse(localStorage.getItem(draftKey()) || "null");
  } catch (err) {
    return null;
  }
}

function clearDraft() {
  clearTimeout(draftTimer);
  try {
    localStorage.removeItem(draftKey());
  } catch (err) {
    /* nothing to clear */
  }
}

// Paint restored values into whichever editor this format uses. blankMissing
// clears fields that have nothing in fieldValues/fieldRichValues instead of
// leaving them untouched — a page restore has nothing there to begin with, so
// it defaults off, but a mode switch does (loadModeSlot passes true), since
// the field may still show the outgoing mode's text.
function paintRestoredValues(blankMissing = false) {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (canvas) {
    canvas.querySelectorAll("[data-field-key]").forEach((el) => {
      const rich = richForSlot(el);
      const text = valueForSlot(el);
      if (rich) {
        el.innerHTML = rich;
        hydrateDocImages(el);
        el.querySelectorAll(".lp-img-cap").forEach((c) => { c.contentEditable = "true"; });
        el.classList.add("lp-filled");
      } else if (text.trim()) {
        el.textContent = text;
        el.classList.add("lp-filled");
      } else if (blankMissing) {
        el.textContent = "";
        el.classList.remove("lp-filled");
        // Otherwise a highlight from the mode just left (this field was
        // reported missing/kept-back there) survives onto a field that, in
        // the mode being entered, has never even been asked about yet.
        el.classList.remove("field-needs-answer");
      }
    });
  } else if (blankMissing || hasAnyValue()) {
    renderResults();
  }
}

// Populate the page from a plan row fetched by id, so reopening a draft shows
// exactly what was saved. Mirrors restoreDraft()'s shape, including the
// restoringDraft guard that stops the repaint from being written straight back
// out as a fresh autosave.
function applyOpenedPlan(plan) {
  restoringDraft = true;
  try {
    planId = plan.id;
    planRevision = plan.revision ?? null;
    fieldValues = plan.field_values || {};
    fieldRichValues = plan.rich_field_values || {};
    // The active mode's values are in field_values; the other mode's ride in
    // mode_values. An older plan has none, which leaves that slot empty.
    const other = (plan.generation_mode === "step" ? "full" : "step");
    const stored = plan.mode_values || {};
    modeSlots[other] = {
      fieldValues: stored.field_values || {},
      fieldRichValues: stored.rich_field_values || {},
      stepIndex: stored.step_index || 0,
    };
    if (plan.generation_mode) mode = plan.generation_mode;
    // Before anything reads the gate: without the course guide and the level
    // parts this restores, updateGate() stays locked and the teacher is sent
    // back through "Before we start" on a plan they already filled in.
    applySetupContext(plan.setup_context);
    if (plan.subject) subjectInput.value = plan.subject;
    // A title other than the one the topic gives was chosen (named on Save
    // or renamed in the list), so autosaves keep it.
    planName = "";
    if (plan.title && plan.title !== planTitle()) planName = plan.title;
    syncGuideSearchLabels();
    if (plan.is_public) visibilityCheckbox.checked = true;

    // Only the author can write to a plan. getLessonPlan also serves public
    // plans and the submissions of a teacher's own sections, so anything not
    // owned by the signed-in user opens read-only rather than autosaving into
    // a rejected request.
    const isOwner = currentUser && plan.user_id === currentUser.id;
    if (!isOwner) {
      serverSaveLocked = true;
      // Detached from the row so editing on can't overwrite the original;
      // Save then writes a new plan of the reader's own.
      planId = null;
      planRevision = null;
      saveStatus.textContent = "You're viewing someone else's plan. Save to keep your own copy.";
    } else if (plan.status === "submitted" || plan.status === "reviewed") {
      // A plan already submitted or graded can't take further edits, so the
      // page says so rather than letting the teacher type into a dead end.
      serverSaveLocked = true;
      saveStatus.textContent =
        plan.status === "reviewed"
          ? "This plan has been reviewed, so it can no longer be edited."
          : "This plan has been submitted, so it can no longer be edited.";
    } else {
      syncedWithServer = true;
    }

    paintRestoredValues();
    // After the values, so a slot re-parented by a replayed edit already holds
    // its content rather than being blanked by the replay.
    applyDocEdits(plan.doc_edits);
    // Make the visible mode (buttons, controls, owl chat, step locks) match
    // the mode this plan actually opened into — without this, a plan last
    // saved in Guided would show Building Proficiency's controls while
    // `mode` was internally "step", and any subsequent capture/switch would
    // then read/write the wrong slot. Safe inside this function's
    // restoringDraft=true window: syncModeUI() never touches
    // fieldValues/modeSlots itself, and the one thing it calls that does
    // write out (applyStepLocks() -> saveDraft()) already no-ops under the
    // same restoringDraft guard restoreDraft() relies on for the same reason.
    syncModeUI();
    enableExport();
  } finally {
    restoringDraft = false;
  }


  updateGate();
  return true;
}

// A draft written before plans had revisions knows its plan but not which
// version of it. If the server's copy is no newer than the draft, the draft is
// the latest and takes the server's revision; if another device saved since,
// the teacher chooses, exactly as with any other conflict.
async function adoptRevisionForOldDraft(draftAt) {
  try {
    const { lesson_plan: plan } = await Api.getLessonPlan(planId);
    if (planRevision != null) return;
    if (!draftAt || new Date(plan.updated_at).getTime() <= draftAt) planRevision = plan.revision;
    else showConflict(plan);
  } catch (err) {
    /* unreachable or gone: the next save reports it */
  }
}

function restoreDraft() {
  const draft = readDraft();
  if (!draft) return false;

  restoringDraft = true;
  try {
    applySetupContext(draft);

    fieldValues = draft.fieldValues || {};
    fieldRichValues = draft.fieldRichValues || {};
    // Both modes' work comes back, not just the one that happened to be active.
    if (draft.modeSlots) modeSlots = draft.modeSlots;
    planId = draft.planId || null;
    planName = draft.planName || "";
    // A draft from before revisions has none, and its first save goes through
    // unchecked, as every save did then.
    planRevision = draft.planRevision ?? null;
    if (planId && planRevision == null) adoptRevisionForOldDraft(draft.at);
    stepIndex = draft.stepIndex || 0;


    paintRestoredValues();
    applyDocEdits(draft.docEdits);

    if (draft.mode === "step") {
      const stepBtn = modeSwitchBtns.find((b) => b.dataset.mode === "step");
      if (stepBtn) stepBtn.click();
      // Entering guided mode jumps to the first unfinished field, which is
      // right when you switch modes but wrong when resuming: it would drop
      // the teacher somewhere other than where they actually stopped.
      if (typeof draft.stepIndex === "number" && draft.stepIndex < stepFieldKeys.length) {
        stepIndex = draft.stepIndex;
        renderStepFieldNav();
      }
    }
  } finally {
    restoringDraft = false;
  }

  updateGate();
  return hasAnyValue() || !!draft.courseGuide || !!draft.budgetOfWork;
}

// Makes the visible page (active mode button, controls, owl chat, step
// locks/message) match the `mode` variable. UI only: it never reads or
// writes fieldValues/fieldRichValues/modeSlots, so it is structurally safe to
// call after fieldValues has already been set directly by something else
// (applyOpenedPlan) as well as from the live mode-switch click below — there
// is no capture/load code path in here for a guard to have to remember to skip.
//
// When entering Guided, stepIndex is recomputed to the first incomplete
// field rather than trusted from wherever it happened to be, because that is
// the only position this function can know: there is no persisted step
// position for the ACTIVE mode (mode_values only carries one for the
// INACTIVE mode, and a plan row has no top-level step_index column at all).
// A live mode-switch click and an opened plan are therefore both "start
// Guided at the first thing left to do" rather than "resume exactly where
// last seen" — restoreDraft() is the one path that can do better, and it
// re-applies its own saved stepIndex right after calling this.
function syncModeUI() {
  modeSwitchBtns.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  fullControls.hidden = mode !== "full";
  stepControls.hidden = mode !== "step";
  // The owl is a fixed-position element outside the gated content, so nothing
  // about hiding the editor or switching tabs hides it on its own.
  syncOwlVisibility();

  // Named once so both branches below can append the same reassurance without
  // repeating the lookup.
  const otherModeLabel = mode === "step" ? "Building Proficiency" : "Guided";
  const otherHasWork = inactiveModeHasWork();
  const otherNote = otherHasWork ? ` Your ${otherModeLabel} work is still there if you switch back.` : "";

  if (mode === "step") {
    // Shares incompleteGuidedFieldKeys() with the Finish branch below, so
    // the two places that decide whether the walkthrough is actually done
    // can't quietly start disagreeing about what "done" means.
    const incompleteGuided = incompleteGuidedFieldKeys();
    stepIndex = incompleteGuided.length === 0
      ? stepFieldKeys.length - 1
      : stepFieldKeys.indexOf(incompleteGuided[0]);
    // Guided writing happens on its own screens with Alan; in the document
    // every field stays open for reviewing and editing.
    clearStepLocks();
    renderStepFieldNav();
    if (otherHasWork) setOwlState("guide", `Switched to Guided mode.${otherNote}`);
  } else {
    clearStepLocks();
    maybeRenderResults();
    // Building Proficiency has no chat panel of its own, so this is the only
    // place left to say it: the guide owl bubble, same as generation status.
    if (otherHasWork) setOwlState("guide", `Switched to Building Proficiency.${otherNote}`);
  }
}

modeSwitchBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.mode === mode) return;   // already here, nothing to swap
    if (generating) {
      // The generate button is disabled while a stream runs, but the mode
      // buttons aren't; switching here would bank a partial generation into
      // the outgoing slot while the stream keeps writing into the incoming
      // one. Block the switch rather than gate section_done on mode, which
      // would just silently drop output the teacher already paid for.
      showToast("Wait for the plan to finish generating first.", true);
      return;
    }
    // restoreDraft() clicks this button purely to trigger syncModeUI() below,
    // after it has already set fieldValues/modeSlots itself for the mode
    // being resumed into. Capturing here would run before `mode` has caught
    // up to what's on screen and stamp that mode's data over a slot that
    // restoreDraft already got right, so skip capture/load in that case.
    if (!restoringDraft) {
      // Put the current mode's work away before picking up the other's.
      captureModeSlot();
      mode = btn.dataset.mode;
      loadModeSlot(mode);
    } else {
      mode = btn.dataset.mode;
    }
    saveDraft();
    syncModeUI();
    // Picking Guided from the document goes back to writing it with Alan.
    if (mode === "step" && !restoringDraft && !content.hidden) window.dispatchEvent(new Event("aligned:guided"));
  });
});

function baseGenerationPayload() {
  return {
    format_id: fmt.id,
    // The cooperating teacher; a teacher writing their own plan has none.
    teacher_name: teacherNameInput.value.trim() || studentTeacherInput.value.trim(),
    subject: subjectInput.value.trim(),
    course_guide_id: selectedGuides.curriculum_guide ? selectedGuides.curriculum_guide.id : null,
    budget_of_work_id: selectedGuides.budget_of_work ? selectedGuides.budget_of_work.id : null,
    // Step 6's supplementary sources: library documents and the student's own files.
    guide_ids: flowFlags.guides.map((g) => g.id),
    context: getAdvancedContext(),
    include_keys: selectedGenerateKeys(),
    source_ids: (flowFlags.sources || []).map((s) => s.id),
    // A finished sample plan: shows Alan what goes in each part.
    sample_id: flowFlags.sample ? flowFlags.sample.id : null,
    // Which paid plan this is: its run, or the saved plan itself.
    run_key: currentRunId,
    plan_id: planId || null,
  };
}

function renderProgress(sectionStates) {
  generationProgressEl.hidden = false;
  generationProgressList.innerHTML = sectionStates
    .map((s) => {
      const icon = s.status === "done" ? Icons.check
        : s.status === "active" ? Icons.moreHorizontal
        : s.status === "retrying" ? Icons.refresh : "";
      return `
        <div class="progress-row progress-${s.status}">
          <span class="progress-icon">${icon}</span>
          <span class="progress-label">${escapeHtml(s.name)}</span>
          ${s.status === "retrying" ? '<span class="progress-note">model is busy, retrying…</span>' : ""}
        </div>`;
    })
    .join("");
}


// "Generate these too": only the student's own fields that are still blank,
// leaving everything already written untouched.
ownFieldsGenerateBtn.addEventListener("click", () => {
  const blank = selfFieldKeys().filter((key) => !isFieldComplete(key));
  if (blank.length) runGeneration(blank);
});

// Generates exactly `includeKeys`: the full plan's selection, or just the
// student's own fields when they ask for those after the fact.
async function runGeneration(includeKeys) {
  if (generating) return;
  if (!updateGate()) {
    const message = "Answer Alan's questions first: your name, the subject, and a Budget of Work or Curriculum Guide.";
    showError(message);
    emitGeneration("error", { message });
    return;
  }

  if (!includeKeys.length) {
    const message = "Tick at least one field for me to write, or fill the plan in yourself.";
    showError(message);
    emitGeneration("error", { message });
    return;
  }

  errorBox.hidden = true;
  ownFieldsNote.hidden = true;
  setButtonLoading(generateFullBtn, true, "Generating");
  setOwlState("thinking", "Thinking hard about your lesson...");
  generating = true;
  emitGeneration("start");

  // Built up live from the stream's own chunk names as they arrive — the
  // Building Proficiency mode batches fields for pacing/streaming purposes,
  // which doesn't line up with the (now largely nominal) section grouping
  // used by Guided mode's nav.
  const progressRows = [];
  renderProgress(progressRows);

  // Captured once so the outcome report checks exactly what was sent, not a
  // fresh read of the checklist that could have drifted (it can't change
  // mid-stream since the panel is part of the same disabled controls, but
  // recomputing it separately would be one more place for the two to disagree).
  const payload = { ...baseGenerationPayload(), include_keys: includeKeys };

  try {
    const finalEvent = await Api.generateFullStream(payload, (event) => {
      if (event.type === "section_start") {
        progressRows.push({ name: event.section, status: "active" });
        renderProgress(progressRows);
        setOwlState("thinking", `Writing "${event.section}"...`);
      } else if (event.type === "filling_gaps") {
        // The server found fields the model skipped and is re-asking for just
        // those, so the progress list says so rather than appearing stalled.
        progressRows.push({ name: "Filling in what was missed", status: "active" });
        renderProgress(progressRows);
        setOwlState("thinking", "A few fields came back empty. Filling those in...");
      } else if (event.type === "section_done") {
        const formatted = formatGeneratedValues(event.values);
        Object.assign(fieldValues, formatted);
        const row = progressRows.find((r) => r.name === event.section)
          || progressRows.find((r) => r.name === "Filling in what was missed");
        if (row) row.status = "done";
        renderProgress(progressRows);
        markDirty();
        if (docTemplateData) {
          revealFieldsInLiveDoc(Object.keys(formatted));
        } else {
          renderResults();
        }
      }
    });
    generateFullBtn.dataset.originalLabel = "Regenerate full plan";
    reportGenerationOutcome(finalEvent, payload.include_keys);
    emitGeneration("done");
    celebrate();
  } catch (err) {
    showError(err.message);
    emitGeneration("error", { message: err.message });
  } finally {
    generating = false;
    setButtonLoading(generateFullBtn, false);
    generationProgressEl.hidden = true;
    startGenerateCooldown();
  }
}

generateFullBtn.addEventListener("click", () => {
  if (!updateGate()) {
    showError("Fill in the cooperating teacher and subject, and choose a Budget of Work or Curriculum Guide first.");
    return;
  }
  openReview();
});

// ---- Field review: before generating, the teacher picks which fields Alan
// writes. The document behind the popup marks each field as it is chosen. ----
const reviewOverlay = document.getElementById("gen-review-overlay");
const reviewList = document.getElementById("gen-review-list");
const reviewConfirm = document.getElementById("gen-review-confirm");
const reviewHint = document.getElementById("gen-review-hint");

function reviewRowMarkup(f) {
  const key = escapeHtml(f.field_key);
  const label = escapeHtml(f.label || f.field_key);
  const isStatic = staticKeys.has(f.field_key);
  const filled = isFieldComplete(f.field_key) ? '<span class="gen-review-note">has content</span>' : "";
  if (f.reflection) {
    return `
    <div class="gen-review-row" data-review-key="${key}">
      <span class="gen-review-label">${label}${filled}</span>
      <span class="gen-review-locked">${Icons.edit}Write after the lesson</span>
    </div>`;
  }
  if (f.locked) {
    return `
    <div class="gen-review-row" data-review-key="${key}">
      <span class="gen-review-label">${label}${filled}</span>
      <span class="gen-review-locked">${Icons.lock}Locked by your teacher</span>
    </div>`;
  }
  return `
    <div class="gen-review-row" data-review-key="${key}">
      <span class="gen-review-label">${label}${filled}</span>
      <div class="seg" role="radiogroup" aria-label="${label}">
        <label><input type="radio" name="rv-${key}" value="gen" ${isStatic ? "" : "checked"}><span>Generate</span></label>
        <label><input type="radio" name="rv-${key}" value="static" ${isStatic ? "checked" : ""}><span>Keep static</span></label>
      </div>
    </div>`;
}

function renderReviewList() {
  const all = fieldsInDocumentOrder();
  const fields = all.filter((f) => !f.locked && !f.reflection);
  const groups = [
    ["Quick fields", fields.filter((f) => f.role !== "heavy" && f.role !== "self")],
    ["Needs real thinking", fields.filter((f) => f.role === "heavy")],
    ["Yours to fill in", fields.filter((f) => f.role === "self")],
    ["You write these (locked by your teacher)", all.filter((f) => f.locked && !f.reflection)],
    ["Your reflection, after the lesson", all.filter((f) => f.reflection)],
  ].filter(([, list]) => list.length);
  reviewList.innerHTML = groups
    .map(([title, list]) => `<fieldset class="gen-review-group"><legend>${title}</legend>${list.map(reviewRowMarkup).join("")}</fieldset>`)
    .join("");
  syncReview();
}

function syncReview() {
  const n = selectedGenerateKeys().length;
  reviewConfirm.disabled = n === 0;
  reviewConfirm.textContent = n ? `Generate ${n} field${n === 1 ? "" : "s"}` : "Generate";
  reviewHint.textContent = n ? "" : "Set at least one field to Generate, or fill the plan in yourself.";
  liveDocWrap.querySelectorAll("[data-field-key]").forEach((el) => {
    const isStatic = staticKeys.has(el.dataset.fieldKey);
    setStaticLook(el, isStatic);
    el.classList.toggle("lp-field-review-gen", !isStatic);
    el.classList.toggle("lp-field-review-static", isStatic);
  });
}

reviewList.addEventListener("change", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (!row) return;
  if (e.target.value === "static") staticKeys.add(row.dataset.reviewKey);
  else staticKeys.delete(row.dataset.reviewKey);
  saveStaticKeys();
  syncReview();
});

// Pointing at a row shows where that field is in the document behind.
function pulseField(key) {
  const el = liveDocWrap.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("lp-field-review-pulse");
  void el.offsetWidth; // restart the animation
  el.classList.add("lp-field-review-pulse");
}

reviewList.addEventListener("mouseover", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (row && row.dataset.reviewKey !== reviewList.dataset.lastPulse) {
    reviewList.dataset.lastPulse = row.dataset.reviewKey;
    pulseField(row.dataset.reviewKey);
  }
});
reviewList.addEventListener("focusin", (e) => {
  const row = e.target.closest("[data-review-key]");
  if (row) pulseField(row.dataset.reviewKey);
});

document.querySelectorAll("[data-review-all]").forEach((btn) => {
  btn.addEventListener("click", () => {
    staticKeys = btn.dataset.reviewAll === "static"
      ? new Set(fieldsInDocumentOrder().map((f) => f.field_key))
      : new Set(lockedKeys());
    saveStaticKeys();
    renderReviewList();
  });
});

let reviewReturnFocus = null;
// Where each part of the review list lives in the popup, recorded before the
// flow ever moves it: [node, parent, next sibling].
const reviewHome = [".gen-review-intro", ".gen-review-bulk", "#gen-review-list", "#gen-review-hint"]
  .map((sel) => document.querySelector(sel))
  .filter(Boolean)
  .map((node) => [node, node.parentNode, node.nextSibling]);

function openReview() {
  // The setup flow borrows the list for its "Which parts should I write?"
  // screen (mountReview); bring it home before the popup shows it.
  reviewHome.forEach(([node, parent, before]) => parent.insertBefore(node, before));
  reviewReturnFocus = document.activeElement;
  delete reviewList.dataset.lastPulse;
  renderReviewList();
  reviewOverlay.hidden = false;
  const first = reviewOverlay.querySelector(".gen-review-row input:checked") || reviewConfirm;
  first.focus();
}

function closeReview() {
  reviewOverlay.hidden = true;
  liveDocWrap.querySelectorAll(".lp-field-review-gen, .lp-field-review-static, .lp-field-review-pulse")
    .forEach((el) => el.classList.remove("lp-field-review-gen", "lp-field-review-static", "lp-field-review-pulse"));
  paintStaticMarks();
  if (reviewReturnFocus && reviewReturnFocus.focus) reviewReturnFocus.focus();
}

document.getElementById("gen-review-close").addEventListener("click", closeReview);
document.getElementById("gen-review-cancel").addEventListener("click", closeReview);
reviewOverlay.addEventListener("click", (e) => {
  if (e.target === reviewOverlay) closeReview();
});
reviewOverlay.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeReview();
});
reviewConfirm.addEventListener("click", () => {
  closeReview();
  runGeneration(selectedGenerateKeys());
});

// What the owl says once generation stops. The server only reports on the
// fields it was asked for (`missing`/`missing_labels`), so an empty
// `missing_labels` no longer means the plan is finished by itself: fields the
// teacher unticked in the checklist are still blank and this is the one place
// that has to know it. The two buckets are kept apart in the wording because
// they mean different things — one is the AI failing at something, the other
// is the teacher choosing not to delegate it — but both leave a blank field,
// so both have to be said and both have to be highlighted.
function reportGenerationOutcome(finalEvent, requestedKeys) {
  const missingLabels = (finalEvent && finalEvent.missing_labels) || [];
  // Standards and competencies with no Budget of Work or Curriculum Guide to
  // copy them from: left blank rather than made up.
  const guideLabels = (finalEvent && finalEvent.needs_guide_labels) || [];
  const guideKeys = (finalEvent && finalEvent.needs_guide) || [];
  const missingKeys = ((finalEvent && finalEvent.missing) || []).concat(guideKeys);
  const asked = new Set(requestedKeys || []);
  // Fields the teacher deliberately unticked: not a generation failure, so
  // they get their own wording rather than being folded into "couldn't
  // generate" and implying the AI tried and failed at them.
  const blankUnasked = (fmt.fields || [])
    .filter((f) => !asked.has(f.field_key) && !isFieldComplete(f.field_key));
  // The student's own fields (lesson title, session number) are theirs to
  // write, so a blank one is expected, not a problem: a calm note with the
  // option to have them written after all.
  const ownFields = blankUnasked.filter((f) => f.role === "self");
  const yoursFields = blankUnasked.filter((f) => f.role !== "self");
  const yoursKeys = yoursFields.map((f) => f.field_key);
  const ownKeys = ownFields.map((f) => f.field_key);

  if (ownFields.length) {
    const labels = joinLabels(ownFields.map((f) => f.label || f.field_key));
    ownFieldsNoteText.textContent = `${labels} ${ownFields.length === 1 ? "is" : "are"} yours to fill in. Want me to write ${ownFields.length === 1 ? "it" : "them"} too?`;
    ownFieldsNote.hidden = false;
  } else {
    ownFieldsNote.hidden = true;
  }

  if (!missingLabels.length && !yoursKeys.length && !guideLabels.length) {
    if (ownKeys.length) {
      setOwlState("guide", `I wrote everything else. ${ownFieldsNoteText.textContent}`);
      highlightEmptyFields(ownKeys);
      return;
    }
    setOwlState("celebrate", "All done! Review what I wrote below, then save when you're happy with it.");
    highlightEmptyFields([]);
    return;
  }

  const messages = [];

  if (missingLabels.length) {
    // Named outright up to a few, counted beyond that, so the message stays
    // readable on a long format.
    const shown = missingLabels.slice(0, 3).join(", ");
    const extra = missingLabels.length - 3;
    const list = extra > 0 ? `${shown}, and ${extra} more` : shown;
    messages.push(
      `I filled in everything else, but couldn't generate ${list}. Write ${missingLabels.length === 1 ? "that one" : "those"} in yourself, or ask me about ${missingLabels.length === 1 ? "it" : "them"} in the chat.`
    );
    showError(
      `${missingLabels.length} field${missingLabels.length === 1 ? "" : "s"} couldn't be generated and ${
        missingLabels.length === 1 ? "is" : "are"
      } still empty: ${missingLabels.join(", ")}.`
    );
  }

  if (guideLabels.length) {
    const one = guideLabels.length === 1;
    messages.push(
      `${joinLabels(guideLabels)} ${one ? "is" : "are"} copied word for word from a Budget of Work or Curriculum Guide, and you didn't add one, so I left ${one ? "it" : "them"} blank instead of making ${one ? "it" : "them"} up. Add one in Supplementary sources and generate again, or copy ${one ? "it" : "them"} in yourself.`
    );
  }

  if (yoursKeys.length) {
    const yoursLabels = yoursFields.map((f) => f.label || f.field_key);
    const shown = yoursLabels.slice(0, 3).join(", ");
    const extra = yoursLabels.length - 3;
    const list = extra > 0 ? `${shown}, and ${extra} more` : shown;
    messages.push(
      `${list} ${yoursLabels.length === 1 ? "is" : "are"} still blank because you kept ${yoursLabels.length === 1 ? "it" : "them"} static. Fill ${yoursLabels.length === 1 ? "it" : "them"} in whenever you are ready.`
    );
  }

  setOwlState("guide", messages.join(" "));

  // Draw attention to the actual empty fields rather than only naming them,
  // whichever bucket (or both) they came from.
  highlightEmptyFields(missingKeys);
  paintStaticMarks();
}

// Marks the still-empty fields in whichever editor this format uses, so the
// teacher can see where the gaps are instead of hunting for them.
function highlightEmptyFields(keys) {
  document.querySelectorAll(".field-needs-answer").forEach((el) => {
    el.classList.remove("field-needs-answer");
  });
  keys.forEach((key) => {
    document
      .querySelectorAll(`[data-field-key="${CSS.escape(key)}"]`)
      .forEach((el) => el.classList.add("field-needs-answer"));
  });
}

// ---- Generate button buffer -----------------------------------------------
// setButtonLoading() already disables the button for the length of the run, so
// a second click mid-generation was never possible. This adds the part that
// was missing: a short cooldown afterwards, so the button can't be hammered
// into firing run after run, each one a real cost and a full rewrite of the
// teacher's fields.

const GENERATE_COOLDOWN_MS = 5000;
let cooldownTimer = null;

function startGenerateCooldown() {
  clearInterval(cooldownTimer);
  const label = generateFullBtn.dataset.originalLabel || generateFullBtn.innerHTML;
  let remaining = Math.ceil(GENERATE_COOLDOWN_MS / 1000);

  generateFullBtn.disabled = true;
  generateFullBtn.innerHTML = `${label} (${remaining})`;

  cooldownTimer = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) {
      generateFullBtn.innerHTML = `${label} (${remaining})`;
      return;
    }
    clearInterval(cooldownTimer);
    generateFullBtn.disabled = false;
    generateFullBtn.innerHTML = label;
  }, 1000);
}

document.getElementById("guided-return-btn").addEventListener("click", () => {
  window.dispatchEvent(new Event("aligned:guided"));
});

stepContinueBtn.addEventListener("click", () => {
  syncActiveStepValue();
  const key = stepFieldKeys[stepIndex];
  if (!isFieldComplete(key)) {
    showError(`Fill in "${fieldByKey(key).label}" before continuing. Every guided field is required.`);
    return;
  }
  errorBox.hidden = true;
  markDirty();

  if (stepIndex < stepFieldKeys.length - 1) {
    stepIndex += 1;
    applyStepLocks();
    setOwlState("guide", `Nice! Next up: "${fieldByKey(stepFieldKeys[stepIndex]).label}."`);
  } else {
    applyStepLocks();
    // Finishing used to only check the field just submitted, which was
    // enough when reaching the last step proved every earlier one was still
    // filled in. Task 7 left earlier guided fields editable and the Clear
    // button can empty any of them regardless of stepIndex, so a field the
    // nav already ticked can be blank again by now. Guided fields have to be
    // re-checked here too, not just the easy ones, or "All fields done"
    // would be the exact false-completeness lie the field-role split exists
    // to prevent.
    const incompleteGuided = incompleteGuidedFieldKeys();
    const outsideIncomplete = incompleteEasyFieldKeys();
    if (incompleteGuided.length > 0) {
      // Name the field rather than just counting: it was almost certainly
      // just cleared, so the label is what the teacher needs to act on it.
      const label = fieldByKey(incompleteGuided[0]).label;
      const rest = incompleteGuided.length - 1;
      setOwlState(
        "guide",
        `"${label}" is still blank${rest > 0 ? ` (and ${rest} more guided field${rest === 1 ? "" : "s"})` : ""}. Go back and answer it before finishing.`
      );
    } else if (outsideIncomplete.length === 0) {
      setOwlState("celebrate", "All fields done. Review everything, then save when you're happy.");
    } else {
      const n = outsideIncomplete.length;
      setOwlState(
        "guide",
        `The guided fields are done. ${n} quick field${n === 1 ? "" : "s"} outside the walkthrough ${n === 1 ? "is" : "are"} still blank. Fill ${n === 1 ? "it" : "them"} in directly below.`
      );
    }
  }
});

// The owl's suggestion for this field was wrong: wipe it and ask again, rather
// than making the teacher select the text and delete it by hand.
stepClearBtn.addEventListener("click", () => {
  const key = stepFieldKeys[stepIndex];
  if (!key) return;

  const canvas = liveDocWrap.querySelector(".lp-doc");
  const el = canvas && canvas.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
  if (el) {
    clearField(el);
  } else {
    // Fallback field list: the control is an input/textarea, not a slot.
    const input = resultsEl.querySelector(`[data-field-key="${CSS.escape(key)}"]`);
    if (input) {
      input.value = "";
      clearFieldState(key);
    }
  }

  const field = fieldByKey(key);
  setOwlState("guide", `Cleared "${field ? field.label : key}". Ask me for a different suggestion, or write your own.`);

  // introduceFieldInChat() returns early when chat.fieldKey already matches, so
  // clearing chat.fieldKey is what makes it re-open the field instead of doing
  // nothing. Reusing it keeps one path for "the owl is now on this field".
  chat.fieldKey = null;
  introduceFieldInChat();
});

// Cache of { html, matched_fields, unmatched_fields } per format id (or null
// when this format has no usable reference file), so reopening the preview
// doesn't re-render the document from scratch every time.
const templateHtmlCache = {};
let previewViewMode = "doc";

function findFieldByKey(key) {
  return (fmt.fields || []).find((f) => f.field_key === key);
}

function renderPreviewMeta() {
  return `
    <div class="preview-meta">
      <span><strong>Subject:</strong> ${escapeHtml(subjectInput.value.trim() || "\u2013")}</span>
      <span><strong>Class:</strong> ${escapeHtml(getClassLabel() || "\u2013")}</span>
      <span><strong>Cooperating teacher:</strong> ${escapeHtml(teacherNameInput.value.trim() || "\u2013")}</span>
      ${topicInput.value.trim() ? `<span><strong>Topic:</strong> ${escapeHtml(topicInput.value.trim())}</span>` : ""}
    </div>`;
}

function renderPlainFieldList() {
  let sectionsHtml = "";
  sections.forEach((section) => {
    sectionsHtml += `<div class="preview-section-title">${escapeHtml(section.name)}</div>`;
    section.fields.forEach((field) => {
      sectionsHtml += `
        <div class="preview-field">
          <div class="preview-field-label">${escapeHtml(field.label)}</div>
          ${renderPreviewValue(previewValue(field.field_key))}
        </div>`;
    });
  });
  return sectionsHtml || `<p>Nothing generated yet.</p>`;
}

// Fields that exist on the format but whose label couldn't be found in the
// real reference file — shown separately instead of ever being drawn into
// the document canvas, so the canvas never shows a slot that isn't real.
function renderUnmatchedFieldList(keys) {
  if (!keys || !keys.length) return "";
  const items = keys
    .map((key) => {
      const field = findFieldByKey(key);
      const label = field ? field.label : key;
      return `
        <div class="preview-field">
          <div class="preview-field-label">${escapeHtml(label)}</div>
          ${renderPreviewValue(previewValue(key))}
        </div>`;
    })
    .join("");
  return `<div class="preview-section-title">Not part of the printed template</div>${items}`;
}

// Copies the plan's current content into the preview's document slots, the
// same way the live document paints them (styled HTML and pictures when a
// field has them, plain text otherwise). Runs as soon as the preview opens:
// it used to wait for a "Fill in generated content" click, so a finished plan
// previewed as an empty form. Only fields matched to a real spot in the
// reference file have a slot, so nothing invented appears in the canvas.
function fillDocCanvas() {
  const canvas = previewBody.querySelector(".lp-doc");
  if (!canvas) return;
  canvas.querySelectorAll("[data-field-key]").forEach((el) => {
    const rich = richForSlot(el);
    const text = valueForSlot(el);
    if (rich) {
      el.innerHTML = rich;
      hydrateDocImages(el);
    } else if (text.trim()) {
      el.textContent = text;
    } else {
      return;
    }
    el.classList.add("lp-filled");
  });
}

// Lets a teacher tweak wording directly in the document canvas, syncing any
// edit straight back into fieldValues (the same data Save/Export use) so the
// canvas isn't a dead-end mockup — it's really editing the lesson plan.
function wireDocCanvasEditing() {
  const canvas = previewBody.querySelector(".lp-doc");
  if (!canvas) return;
  canvas.querySelectorAll("[data-field-key]").forEach((el) => {
    el.setAttribute("data-placeholder", "Not generated yet");
    el.addEventListener("input", () => {
      storeSlot(el, el.textContent);
      el.classList.toggle("lp-filled", !!el.textContent.trim() || !!el.querySelector(".lp-img"));
      markDirty();
      renderResults();
      if (mode === "step") renderStepFieldNav();
    });
  });
}

function renderPreviewModal(templateData, docAvailable) {
  const dialogEl = previewOverlay.querySelector(".modal-dialog");
  dialogEl.classList.toggle("modal-dialog-doc", previewViewMode === "doc");

  // Document view only; a format with no reference document falls back to the
  // plain list, since there is no page to show.
  const toolbar = "";

  const warning =
    docAvailable && templateData.unmatched_fields.length
      ? `<div class="doc-warning"><strong>${templateData.unmatched_fields.length} field${templateData.unmatched_fields.length === 1 ? "" : "s"}</strong> couldn't be matched to a spot in the reference document, so they're shown separately below rather than guessed at.</div>`
      : "";

  let content;
  if (previewViewMode === "doc") {
    content = `<div class="doc-hint">Your plan in its reference document. Click into any highlighted spot to edit it directly.</div>`;
    content += `<div class="lp-doc-wrap">${templateData.html}</div>`;
    content += renderUnmatchedFieldList(templateData.unmatched_fields);
  } else {
    content = renderPlainFieldList();
  }

  previewBody.innerHTML = renderPreviewMeta() + toolbar + warning + content;
  previewBody.querySelectorAll(".lp-doc-wrap").forEach(fitDocPage);

  if (previewViewMode === "doc") {
    fillDocCanvas();
    wireDocCanvasEditing();
  }
}

async function openGeneratorPreview() {
  previewTitle.textContent = `${subjectInput.value.trim() || fmt.name} \u2014 Preview`;
  previewOverlay.hidden = false;
  previewBody.innerHTML = `<div class="preview-loading">Loading preview\u2026</div>`;

  let templateData = templateHtmlCache[fmt.id];
  if (templateData === undefined) {
    try {
      const data = await Api.getFormatTemplateHtml(fmt.id);
      templateData = data.html ? data : null;
    } catch (err) {
      // No reference file on this format, or it couldn't be rendered — the
      // field-list view below still works fine without it.
      templateData = null;
    }
    templateHtmlCache[fmt.id] = templateData;
  }

  const docAvailable = !!templateData;
  previewViewMode = docAvailable ? "doc" : "list";
  renderPreviewModal(templateData, docAvailable);
}

let previewClosed = null; // what to do when the preview closes (the Guided screens redraw)
function closeGeneratorPreview() {
  previewOverlay.hidden = true;
  previewOverlay.querySelector(".modal-dialog").classList.remove("modal-dialog-doc");
  if (previewClosed) {
    const done = previewClosed;
    previewClosed = null;
    done();
  }
}

previewBtn.addEventListener("click", openGeneratorPreview);
previewClose.addEventListener("click", closeGeneratorPreview);
previewOverlay.addEventListener("click", (e) => {
  if (e.target === previewOverlay) closeGeneratorPreview();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !previewOverlay.hidden) closeGeneratorPreview();
});

let mySectionsForSubmit = null;

async function revealSubmitControlsIfStudent() {
  if (!currentUser || currentUser.role !== "student") return;
  try {
    if (!mySectionsForSubmit) {
      const data = await Api.listSections();
      mySectionsForSubmit = data.sections || [];
    }
    if (!mySectionsForSubmit.length) return;
    submitSectionSelect.innerHTML = mySectionsForSubmit
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
      .join("");
    submitSectionSelect.hidden = false;
    submitBtn.hidden = false;
  } catch (err) {
    // Not fatal — the student can still submit later from the lesson plan list.
  }
}

submitBtn.addEventListener("click", async () => {
  if (!planId) return;
  setButtonLoading(submitBtn, true, "Submitting");
  try {
    await Api.submitLessonPlan(planId, submitSectionSelect.value);
    showToast("Lesson plan submitted to your teacher.");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(submitBtn, false);
  }
});

visibilityCheckbox.addEventListener("change", async () => {
  if (!planId) return;
  try {
    await Api.setLessonPlanVisibility(planId, visibilityCheckbox.checked);
    showToast(visibilityCheckbox.checked ? "Lesson plan is now public." : "Lesson plan is now private.");
  } catch (err) {
    showToast(err.message, true);
    visibilityCheckbox.checked = !visibilityCheckbox.checked;
  }
});

// Export reads the paper size from the saved plan, so a change is an edit like
// any other: it autosaves, and Export waits for that save.
pageSizeSelect.addEventListener("change", markDirty);

// Saving asks what to call the plan first (its title in the list), prefilled
// with the name it has; cancelling saves nothing.
function askPlanName() {
  return new Promise((resolve) => askName({
    title: "Save lesson plan", label: "Lesson plan name", value: planTitle(),
    action: "Save", busy: "Saving…", empty: "Give the lesson plan a name.",
    onSubmit: async (name) => resolve(name), onCancel: () => resolve(null),
  }));
}

saveBtn.addEventListener("click", async () => {
  const name = await askPlanName();
  if (!name) return;
  planName = name;
  // A pending autosave would otherwise race this one and re-send the same
  // payload a moment later.
  clearTimeout(serverSaveTimer);
  setButtonLoading(saveBtn, true, "Saving");
  const seq = editSeq;
  try {
    await persistPlan();
    // A refresh now reopens the saved plan instead of an empty run.
    if (planId) history.replaceState(null, "", `${location.pathname}?plan_id=${planId}`);
    if (savedEverythingSince(seq)) {
      // The plan is on the server now and listed under "List of Lesson Plan",
      // so the local draft has done its job. Editing on from here marks the
      // page dirty again and starts a fresh draft.
      clearDraft();
      saveStatus.textContent = "Saved.";
      enableExport();
    } else {
      // Typing carried on while it saved: that newer text is not on the
      // server yet, so the page stays unsaved and the autosave picks it up.
      scheduleServerSave();
    }
    showToast("Lesson plan saved.");
    setOwlState("celebrate", "Saved! Export it as Word whenever you're ready.");
    revealSubmitControlsIfStudent();
  } catch (err) {
    if (isStaleSave(err)) showConflict(err.data.lesson_plan);
    else showError(err.message);
  } finally {
    setButtonLoading(saveBtn, false);
  }
});

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("lesson-plan");

// Page-level icon spans (the back link, the continue button). The toolbar
// paints its own via paintDocToolbarIcons; this covers the rest, matching how
// format-builder.js already does it, so no control ships a bare arrow glyph.
document.querySelectorAll("[data-icon]").forEach((el) => {
  if (el.closest(".doc-toolbar")) return;
  const icon = Icons[el.dataset.icon];
  if (icon) el.innerHTML = icon;
});

// ---- Bridge for the Create Lesson Plan flow (js/setup-flow.js) ----
// The flow asks the questions; this page keeps doing what it always did with
// the answers (drafts, the gate, generation, the document). The flow only
// talks to it through window.Generator below.

const flowEl = document.getElementById("flow");
let readyResolve;
const generatorReady = new Promise((resolve) => (readyResolve = resolve));

function setRunInUrl() {
  const params = new URLSearchParams();
  if (currentRunId) params.set("run", currentRunId);
  if (fmt) params.set("format_id", fmt.id);
  history.replaceState(null, "", `${location.pathname}?${params}`);
}

async function loadFormat(formatId) {
  if (fmt) {
    if (String(fmt.id) === String(formatId)) return fmt;
    // A different format mid-run: reload on the same run. The answers live in
    // the run's draft, so they come back; the new format's blanks start empty.
    writeDraft();
    location.replace(`${location.pathname}?run=${encodeURIComponent(currentRunId || "")}&format_id=${encodeURIComponent(formatId)}`);
    return new Promise(() => {});
  }
  const data = await Api.getFormat(formatId);
  if (!data.format.fields || !data.format.fields.length) {
    throw new Error("This format doesn't have any fields defined yet.");
  }
  fmt = data.format;
  sections = buildSections(fmt.fields);
  document.title = `${fmt.name} | AlignED`;
  document.getElementById("format-name").textContent = fmt.name;
  // Guided walks exactly the fields the format's teacher marked Guided, plus
  // the ones they locked (which Alan never writes, so the student does, with
  // his help), in document order. Quick facts stay out of the walkthrough.
  const walked = fieldsInDocumentOrder().filter((f) => f.role === "heavy" || f.locked).map((f) => f.field_key);
  // A format with none would leave Guided with nothing to do, so it falls
  // back to walking everything.
  stepFieldKeys = walked.length ? walked : fieldsInDocumentOrder().map((f) => f.field_key);
  stepIndex = 0;
  loadStaticKeys();
  await initLiveDocView();
  paintStaticMarks();
  flowFlags.formatName = fmt.name;
  if (!new URLSearchParams(location.search).get("plan_id")) setRunInUrl();
  // The chat history is kept per format, which is only known now.
  loadChatThreads();
  return fmt;
}

const ANSWER_INPUTS = {
  school: schoolInput, studentTeacher: studentTeacherInput, coop: teacherNameInput,
  subject: subjectInput, durationMinutes: durationInput, levelType: levelTypeSelect,
  grade: k12GradeSelect, program: collegeProgramInput, year: collegeYearSelect,
  section: sectionInput, previousTopic: prevTopicInput, topic: topicInput, nextTopic: nextTopicInput,
  mainTopic: mainTopicInput,
};
const ANSWER_FLAGS = ["firstLesson", "nextUnsure", "flowStep", "stage", "mode", "sources", "guides", "term", "week", "sample", "assessment", "quizItems", "guidedAt"];

function getAnswers() {
  const answers = {};
  Object.entries(ANSWER_INPUTS).forEach(([key, el]) => (answers[key] = el.value));
  ANSWER_FLAGS.forEach((key) => (answers[key] = flowFlags[key]));
  answers.durationMinutes = parseInt(durationInput.value, 10) || null;
  answers.formatId = fmt ? fmt.id : null;
  answers.formatName = flowFlags.formatName;
  answers.sources = flowFlags.sources || [];
  return answers;
}

function setAnswers(partial) {
  Object.entries(partial || {}).forEach(([key, value]) => {
    if (ANSWER_INPUTS[key]) ANSWER_INPUTS[key].value = value == null ? "" : String(value);
    else if (ANSWER_FLAGS.includes(key)) flowFlags[key] = value;
  });
  updateLevelFields();
  updateGate();
  saveDraft();
}

// Answers given once go straight into the format's matching blanks (school,
// your name, learning area, grade). Weekly fields hold one answer per day, so
// they are left alone.
function applyPrefill() {
  if (!fmt) return;
  const plain = (fmt.fields || []).filter((f) => f.field_type !== "weekly");
  const filled = prefillFieldValues(plain, getAnswers(), fieldValues);
  if (!Object.keys(filled).length) return;
  Object.assign(fieldValues, filled);
  // The student already answered these, so Alan keeps them as they are
  // instead of writing over them.
  Object.keys(filled).forEach((key) => staticKeys.add(key));
  saveStaticKeys();
  paintRestoredValues();
  paintStaticMarks();
  markDirty();
}

// "Which parts should I write?" becomes a screen in the flow instead of a popup:
// the same list (and its listeners) moves into the flow's answer area.
function mountReview(container) {
  renderReviewList();
  const intro = document.querySelector(".gen-review-intro");
  const bulk = document.querySelector(".gen-review-bulk");
  container.replaceChildren(...[intro, bulk, reviewList, reviewHint].filter(Boolean));
}

// Each mode keeps its own copy of the fields, so switch first and prefill
// after: prefilling first would land in the mode being left.
function useMode(name) {
  if (mode !== name) modeSwitchBtns.find((b) => b.dataset.mode === name).click();
  flowFlags.mode = name;
  applyPrefill();
}

// A student's lesson plan costs 30 points, once: the first start of a run
// pays; coming back to the same run or a saved plan is free (the server
// decides). Throws the reason when there aren't enough points.
async function payForBuild() {
  if (!currentUser || currentUser.role !== "student" || flowFlags.paid) return;
  const data = await Api.startBuild({ run_key: currentRunId, plan_id: planId || null });
  flowFlags.paid = true;
  if (typeof data.points === "number") {
    currentUser.points = data.points;
    cacheUser(currentUser);
  }
  saveDraft();
}

// What starting this plan costs a student, for the mode step; "" for teachers.
function pointsNote() {
  if (!currentUser || currentUser.role !== "student") return "";
  if (flowFlags.paid || planId) return "This lesson plan is already paid for, so carrying on is free.";
  const have = currentUser.points || 0;
  return have >= 30
    ? `Starting this lesson plan uses 30 of your ${have} points.`
    : `Starting a lesson plan uses 30 points and you have ${have}. Ask your teacher for more points.`;
}

function startFull() {
  useMode("full");
  runGeneration(selectedGenerateKeys());
}

// Guided mode is written on the flow's own screens (guided-flow.js), one part
// at a time beside Alan; the document only opens at the end, for review.
function startGuided() {
  useMode("step");
  flowFlags.stage = "guided";
  saveDraft();
}

// ---- for the Guided screens ----
function partInfo(key) {
  const f = fieldByKey(key);
  return {
    key, label: f.label, type: f.field_type, group: f.section_group || "",
    days: partCount(key) ? f.parts : null, locked: !!f.locked,
  };
}

// A formatted Guided answer (the part's toolbar box): its sanitized HTML goes
// to fieldRichValues, the same as a styled document slot, and its plain text
// to fieldValues, so completeness checks, Alan and the quick parts keep
// reading text while the document, preview, save and export get the styling.
function setGuidedRich(key, editorEl, part = null) {
  const html = sanitizeRichValueHtml(editorEl);
  const text = editorEl.innerText.replace(/\n+$/, "");
  const target = { dataset: part === null ? { fieldKey: key } : { fieldKey: key, part: String(part) } };
  storeSlot(target, text, html);
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (canvas) {
    slotsFor(key, canvas).forEach((el) => {
      if (part !== null && slotPart(el) !== part) return;
      el.innerHTML = html;
      el.classList.toggle("lp-filled", !!text.trim());
    });
  }
  markDirty();
}

// The formatted HTML of one Guided answer (one day of a weekly part), or "".
function guidedRich(key, part = null) {
  return richForSlot({ dataset: part === null ? { fieldKey: key } : { fieldKey: key, part: String(part) } });
}

// Writes one part's answer (or one day of a weekly part) and shows it in the
// hidden document too, so saving and exporting see exactly what was typed.
function setGuidedValue(key, text, part = null) {
  if (part === null) {
    fieldValues[key] = text;
    delete fieldRichValues[key];
  } else {
    const parts = weeklyArray(fieldValues[key], partCount(key));
    parts[part] = text;
    fieldValues[key] = parts;
    if (Array.isArray(fieldRichValues[key])) fieldRichValues[key][part] = "";
  }
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (canvas) {
    slotsFor(key, canvas).forEach((el) => {
      if (part !== null && slotPart(el) !== part) return;
      el.textContent = valueForSlot(el);
      el.classList.toggle("lp-filled", !!el.textContent.trim());
    });
  } else {
    slotsFor(key, resultsEl).forEach((el) => { el.value = valueForSlot(el); });
  }
  markDirty();
}

let chatHome = null;
function mountChat(host) {
  if (!chatHome) chatHome = { parent: owlChat.parentNode, next: owlChat.nextSibling };
  owlChat.classList.add("is-staged");
  host.append(owlChat);
  owlChat.hidden = false;
  OwlGuide.undock();
  setOwlChatCollapsed(true);
}

function unmountChat() {
  if (!chatHome || !owlChat.classList.contains("is-staged")) return;
  setOwlChatCollapsed(true);
  owlChat.classList.remove("is-staged");
  owlChat.hidden = true;
  chatHome.parent.insertBefore(owlChat, chatHome.next);
}

function showDocument() {
  flowEl.hidden = true;
  loadingState.hidden = true;
  content.hidden = false;
  flowFlags.stage = "doc";
  saveDraft();
  syncOwlVisibility();
  window.scrollTo({ top: 0 });
}

function hideDocument() {
  content.hidden = true;
  flowEl.hidden = false;
  syncOwlVisibility();
}

function runPointerKey() {
  return `alignedFlowRun:v1:${currentUser ? currentUser.id : "anon"}`;
}

// The last run that never reached the document, so step 1 can offer to carry on.
function unfinishedRun() {
  try {
    const runId = localStorage.getItem(runPointerKey());
    if (!runId || runId === currentRunId) return null;
    const draft = JSON.parse(localStorage.getItem(runDraftKey(runId)) || "null");
    const setup = draft && draft.setup;
    if (!setup || !setup.formatId || (setup.flow && setup.flow.stage === "doc")) return null;
    return { runId, formatId: setup.formatId, topic: setup.topic || "", formatName: (setup.flow || {}).formatName || "" };
  } catch (err) {
    return null;
  }
}

function newRun() {
  currentRunId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  try {
    localStorage.setItem(runPointerKey(), currentRunId);
  } catch (err) {
    /* private mode: the run still works, it just can't be resumed later */
  }
  setRunInUrl();
  return currentRunId;
}

window.Generator = {
  ready: generatorReady,
  loadFormat,
  getAnswers,
  setAnswers,
  // Both kinds of library document for the subject, official ones first.
  searchCourseGuides: async () => {
    const data = await Api.searchCourseGuides({ subject: subjectInput.value.trim(), prefer_grade_band: gradeBandFor() });
    return data.course_guides || [];
  },
  // Supplementary sources: private to the student, read by Alan.
  uploadSource: async (file) => {
    const { source } = await Api.uploadSource(file);
    setAnswers({ sources: [...(flowFlags.sources || []), source] });
    return source;
  },
  removeSource: async (id) => {
    await Api.deleteSource(id);
    setAnswers({ sources: (flowFlags.sources || []).filter((s) => s.id !== id) });
  },
  // The sample lesson plan: one private file, stored like a source but read
  // as an example of the layout, never as a source of content.
  uploadSample: async (file) => {
    const { source } = await Api.uploadSource(file);
    if (flowFlags.sample) Api.deleteSource(flowFlags.sample.id).catch(() => {});
    setAnswers({ sample: source });
    return source;
  },
  removeSample: async () => {
    if (flowFlags.sample) await Api.deleteSource(flowFlags.sample.id);
    setAnswers({ sample: null });
  },
  applyPrefill,
  useMode,
  mountReview,
  startFull,
  startGuided,
  payForBuild,
  pointsNote,
  // The Guided screens: the parts Alan walks through, the quick blanks left
  // over, and reading/writing their answers.
  guidedParts: () => stepFieldKeys.map(partInfo),
  quickParts: () => incompleteEasyFieldKeys().map(partInfo),
  fieldValue: (key) => fieldValues[key],
  isFieldComplete,
  setGuidedValue,
  // The part screens' formatting toolbox: the formatted answer, read and
  // written through the document's own rich-value machinery.
  setGuidedRich,
  guidedRich,
  applySpanClass: applyDocSpanClass,
  setGuidedDay: (i) => { guidedPart = i; },
  guidedIndex: () => stepIndex,
  setGuidedIndex: (i) => {
    stepIndex = Math.max(0, Math.min(i, stepFieldKeys.length - 1));
    guidedPart = null;
    renderStepFieldNav();
    introduceFieldInChat();
    saveDraft();
  },
  mountChat,
  unmountChat,
  celebrate,
  // The plan so far, in its document, from the Guided screens.
  openPreview: (onClose) => {
    previewClosed = onClose || null;
    openGeneratorPreview();
  },
  openChat: () => setOwlChatCollapsed(false),
  showDocument,
  hideDocument,
  unfinishedRun,
  newRun,
  generationEvents,
};

async function init() {
  const user = await requireAuth();
  if (!user) return;
  currentUser = user;
  wireTopbar(user);
  updateLevelFields();
  updateGate();

  // ?plan_id= reopens a saved plan straight into the document (what Continue
  // in the list of lesson plans links to). Anything else is a new plan, and
  // the flow asks the questions; ?run= (with ?format_id=) resumes a run after
  // a refresh.
  const params = new URLSearchParams(window.location.search);
  const requestedPlanId = params.get("plan_id");

  // Students make lesson plans for a class, so they join one first (the server
  // refuses too). A plan they already have still opens below.
  if (user.role === "student" && user.enrolled === false && !requestedPlanId) {
    loadingState.hidden = true;
    flowEl.hidden = false;
    flowEl.innerHTML = `
      <div class="enroll-gate">
        <img src="img/owl/alan-wave.png" alt="" />
        <h1>Join your class first</h1>
        <p>You can make lesson plans once you're in your teacher's class. Ask them for the class code, then join in My Classes.</p>
        <a class="btn btn-primary" href="my-classes.html">Go to My Classes</a>
      </div>`;
    readyResolve({ user, kind: "blocked" });
    return;
  }
  if (requestedPlanId) {
    // A reopened plan came from the list, so that is where Back goes.
    const back = document.querySelector(".back-link");
    back.href = "lesson-plan-list.html";
    back.lastChild.textContent = "Back to List of Lesson Plans";
    try {
      const data = await Api.getLessonPlan(requestedPlanId);
      await loadFormat(data.lesson_plan.format_id);
      applyOpenedPlan(data.lesson_plan);
      showDocument();
      showToast("Draft reopened.");
      setOwlState("guide", "I brought back what you had so far. Carry on where you left off.");
    } catch (err) {
      loadingState.hidden = true;
      showError(`That lesson plan couldn't be opened: ${err.message}`);
    }
    readyResolve({ user, kind: "plan" });
    return;
  }

  loadingState.hidden = true;
  const formatId = params.get("format_id");
  let resumed = false;
  if (currentRunId && formatId) {
    try {
      await loadFormat(formatId);
      resumed = restoreDraft();
    } catch (err) {
      showError(err.message);
    }
  }
  if (fmt && flowFlags.stage === "doc") showDocument();
  readyResolve({
    user,
    kind: "flow",
    runId: currentRunId,
    formatId: fmt ? fmt.id : formatId || null,
    stage: flowFlags.stage,
    flowStep: flowFlags.flowStep,
    resumed,
  });
}

init();
