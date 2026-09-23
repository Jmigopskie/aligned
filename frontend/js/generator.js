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
let dirty = false;

// Guided mode: the flat, ordered list of every field on this format
// (document order via sort_order) and which one is currently unlocked.
let stepFieldKeys = [];
let stepIndex = 0;

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

let selectedCourseGuide = null;
let cgTab = "search";
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
const generateScope = document.getElementById("generate-scope");
const generateScopeAuto = document.getElementById("generate-scope-auto");
const generateScopeOptions = document.getElementById("generate-scope-options");
const generationProgressEl = document.getElementById("generation-progress");
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
const cgTabsEl = document.getElementById("cg-tabs");
const cgTabSearch = document.getElementById("cg-tab-search");
const cgTabUpload = document.getElementById("cg-tab-upload");
const cgSearchBtn = document.getElementById("cg-search-btn");
const cgSearchBtnLabel = document.getElementById("cg-search-btn-label");
const cgResultsEl = document.getElementById("cg-results");
const cgNoTopic = document.getElementById("cg-no-topic");
const cgDropzone = document.getElementById("cg-dropzone");
const cgFileInput = document.getElementById("cg-file-input");
const cgSelectedEl = document.getElementById("cg-selected");
const gateLock = document.getElementById("gate-lock");
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
// ready content that goes straight into the field, "ask" choices send a
// follow-up question. ----
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
const CHAT_TURNS_SENT = 8;

// One conversation per field, not one long stream. Switching field (or
// leaving guided mode and coming back) swaps the visible thread instead of
// starting over, and every thread is written to localStorage so it is still
// there after a reload — the History button reads them back.
const CHAT_STORE_PREFIX = "owlChat:v1:";
const CHAT_MAX_TURNS_PER_FIELD = 60;
const chat = { threads: {}, busy: false, fieldKey: null };

function chatStoreKey() {
  const formatId = new URLSearchParams(window.location.search).get("format_id") || "none";
  return `${CHAT_STORE_PREFIX}${formatId}`;
}

function loadChatThreads() {
  try {
    chat.threads = JSON.parse(localStorage.getItem(chatStoreKey()) || "{}") || {};
  } catch (err) {
    // Corrupt or unavailable storage must never stop the chat working.
    chat.threads = {};
  }
}

function saveChatThreads() {
  try {
    localStorage.setItem(chatStoreKey(), JSON.stringify(chat.threads));
  } catch (err) {
    /* private mode, or the quota is full — the in-memory threads still work */
  }
}

function threadFor(key) {
  if (!chat.threads[key]) chat.threads[key] = [];
  return chat.threads[key];
}

function recordTurn(key, role, text) {
  const thread = threadFor(key);
  thread.push({ role, text, at: Date.now() });
  // Keep a lid on it: a very long conversation about one field would
  // otherwise grow the stored blob without limit.
  if (thread.length > CHAT_MAX_TURNS_PER_FIELD) thread.splice(0, thread.length - CHAT_MAX_TURNS_PER_FIELD);
  saveChatThreads();
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
  body.innerHTML = '<div class="owl-bubble"><span class="owl-dots" aria-label="The owl is typing"><i></i><i></i><i></i></span></div>';
  owlChatLog.appendChild(row);
  scrollChatToEnd();
  return row;
}

function addOwlMessage(text, choices = [], { error = false } = {}) {
  // Only the latest set of choices stays tappable, so an old suggestion
  // isn't applied to a field it was never written for.
  owlChatLog.querySelectorAll(".owl-choice:not(.is-used)").forEach((b) => { b.disabled = true; });
  const { row, body } = owlRow(error ? "alert" : "guide");
  if (error) row.classList.add("is-error");
  const bubble = document.createElement("div");
  bubble.className = "owl-bubble";
  bubble.textContent = text;
  body.appendChild(bubble);

  if (choices.length) {
    const list = document.createElement("div");
    list.className = "owl-choices";
    choices.forEach((choice) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `owl-choice owl-choice-${choice.type}`;
      if (choice.type === "use") {
        const label = document.createElement("span");
        label.className = "owl-choice-label";
        label.textContent = choice.label;
        const preview = document.createElement("span");
        preview.className = "owl-choice-text";
        preview.textContent = choice.text;
        const action = document.createElement("span");
        action.className = "owl-choice-action";
        action.textContent = "Use this";
        btn.append(label, preview, action);
        btn.title = "Add this to the field";
      } else {
        btn.textContent = choice.label;
      }
      btn.addEventListener("click", () => pickOwlChoice(choice, btn));
      list.appendChild(btn);
    });
    body.appendChild(list);
  }
  owlChatLog.appendChild(row);
  scrollChatToEnd();
}

// Draw a saved thread back into the log. Restored owl turns carry no choice
// buttons: a "use this" suggestion was written for the field as it stood at
// the time, and re-offering it later would paste stale content.
function renderThread(key, note) {
  owlChatLog.innerHTML = "";
  const thread = chat.threads[key] || [];
  // The note introduces what follows, so it goes in before the messages.
  if (note && thread.length) addChatNote(note);
  thread.forEach((turn) => {
    if (turn.role === "teacher") addTeacherMessage(turn.text);
    else addOwlMessage(turn.text, []);
  });
  return thread.length;
}

function introduceFieldInChat() {
  if (mode !== "step") return;
  const key = stepFieldKeys[stepIndex];
  const field = fieldByKey(key);
  if (!field || chat.fieldKey === key) return;
  chat.fieldKey = key;
  owlChatField.textContent = `Helping with: ${field.label}`;
  if (!owlChatHistory.hidden) showChatHistory(false);

  // Show this field's own conversation. Coming back to a field you already
  // discussed picks up where you left off rather than wiping the log.
  const hadTurns = renderThread(key, `Earlier conversation about "${field.label}".`);
  if (hadTurns) {
    scrollChatToEnd();
  } else {
    addOwlMessage(`I can help with "${field.label}". Ask a question or tap an option.`, OWL_STARTERS);
  }
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
    const history = (chat.threads[key] || [])
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
    recordTurn(key, "owl", data.reply);
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

function insertIntoActiveField(text) {
  const key = stepFieldKeys[stepIndex];
  const field = fieldByKey(key);
  if (!field) return;
  syncActiveStepValue();
  const addition = field.field_type === "text" ? text.replace(/\s*\n\s*/g, " ").trim() : formatGeneratedValue(text);
  const current = String(fieldValues[key] || "").trim();
  // A short text field is replaced; a multi-line field keeps what the
  // teacher already wrote and gains the new lines below it.
  const value = field.field_type !== "text" && current ? `${current}\n${addition}` : addition;
  fieldValues[key] = value;

  if (docTemplateData) {
    const canvas = liveDocWrap.querySelector(".lp-doc");
    const el = canvas && canvas.querySelector(`[data-field-key="${key}"]`);
    if (el) {
      el.textContent = value;
      delete fieldRichValues[key];
      el.classList.add("lp-filled");
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } else {
    const el = resultsEl.querySelector(`[data-field-key="${key}"]`);
    if (el) el.value = value;
  }
  markDirty();
  renderStepFieldNav();
  return field.label;
}

function pickOwlChoice(choice, btn) {
  if (choice.type === "ask") {
    sendToOwl(choice.text);
    return;
  }
  const label = insertIntoActiveField(choice.text);
  if (!label) return;
  btn.classList.add("is-used");
  btn.disabled = true;
  const action = btn.querySelector(".owl-choice-action");
  if (action) action.textContent = "Added";
  addChatNote(`Added to "${label}". You can still edit it in the document.`);
}

function updateChatRoom() {
  // On wide screens the page makes room for the open chat, so it never
  // covers the document the teacher is writing in.
  document.body.classList.toggle("owl-chat-open", !owlChat.hidden && !owlChat.classList.contains("is-collapsed"));
}

function setOwlChatCollapsed(collapsed) {
  owlChat.classList.toggle("is-collapsed", collapsed);
  updateChatRoom();
  owlChatToggle.setAttribute("aria-expanded", String(!collapsed));
  owlChatToggle.textContent = collapsed ? "Open" : "Hide";
  if (!collapsed) scrollChatToEnd();
}

// ---- Chat panel width ----
const CHAT_W_KEY = "owlChatWidth";
const CHAT_W_MIN = 340;
const chatResizer = document.getElementById("owl-chat-resizer");

function chatMaxWidth() {
  return Math.max(CHAT_W_MIN, Math.min(820, window.innerWidth - 120));
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
  owlChatHistoryTitle.textContent = "Saved conversations";
  owlChatHistoryList.innerHTML = "";

  const entries = Object.entries(chat.threads).filter(([, turns]) => turns.length);
  if (!entries.length) {
    owlChatHistoryList.innerHTML =
      '<p class="owl-chat-history-empty">Nothing saved yet. Conversations you have with the owl about each field are kept here so you can read them back.</p>';
    return;
  }

  entries.forEach(([key, turns]) => {
    const field = fieldByKey(key);
    const last = turns[turns.length - 1];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "owl-chat-thread-btn";
    const title = document.createElement("strong");
    const when = last.at ? ` · ${new Date(last.at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : "";
    title.textContent = `${field ? field.label : key} (${turns.length} messages)${when}`;
    const preview = document.createElement("span");
    preview.textContent = last.text;
    btn.append(title, preview);
    btn.addEventListener("click", () => renderHistoryThread(key));
    owlChatHistoryList.appendChild(btn);
  });
}

function renderHistoryThread(key) {
  const field = fieldByKey(key);
  owlChatHistoryBack.hidden = false;
  owlChatHistoryTitle.textContent = field ? field.label : key;
  owlChatHistoryList.innerHTML = "";
  (chat.threads[key] || []).forEach((turn) => {
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
    bubble.textContent = turn.text;
    body.appendChild(bubble);
    row.appendChild(body);
    owlChatHistoryList.appendChild(row);
  });
}

owlChatHistoryBtn.addEventListener("click", () => showChatHistory(owlChatHistory.hidden));
owlChatHistoryBack.addEventListener("click", renderHistoryList);

function showOwlChat(visible) {
  owlChat.hidden = !visible;
  // The chat is the voice during guided mode; the guide owl steps aside.
  if (visible) OwlGuide.hide();
  updateChatRoom();
  if (visible) {
    showChatHistory(false);
    introduceFieldInChat();
  }
}

owlChatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendToOwl(owlChatInput.value);
});
owlChatToggle.addEventListener("click", () => setOwlChatCollapsed(!owlChat.classList.contains("is-collapsed")));
owlChat.querySelector(".owl-chat-head").addEventListener("click", (e) => {
  if (owlChat.classList.contains("is-collapsed") && e.target !== owlChatToggle) setOwlChatCollapsed(false);
});
if (window.matchMedia("(max-width: 640px)").matches) setOwlChatCollapsed(true);

function setOwlState(state, message) {
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
    return parts.join(" — ");
  }
  const parts = [k12GradeSelect.value.trim(), sectionInput.value.trim()].filter(Boolean);
  return parts.join(" — ");
}

function getAdvancedContext() {
  const isCollege = levelTypeSelect.value === "college";
  return {
    topic: topicInput.value.trim(),
    level_type: isCollege ? "College" : "K-12",
    program: isCollege ? collegeProgramInput.value.trim() : "",
    year: isCollege ? collegeYearSelect.value.trim() : "",
    grade_level: isCollege ? "" : k12GradeSelect.value.trim(),
    section: sectionInput.value.trim(),
  };
}

let gateWasReady = false;

function updateGate() {
  const teacherOk = teacherNameInput.value.trim().length > 0;
  const subjectOk = subjectInput.value.trim().length > 0;
  const guideOk = !!selectedCourseGuide;
  const ready = teacherOk && subjectOk && guideOk;

  gateLock.hidden = ready;
  unlockedContent.hidden = !ready;

  if (ready && !gateWasReady) {
    setOwlState("guide", "Nice — you're all set. Head to “Generate & review” when you're ready.");
  }
  gateWasReady = ready;

  return ready;
}

teacherNameInput.addEventListener("input", updateGate);
subjectInput.addEventListener("change", () => {
  cgSearchBtnLabel.textContent = `Search for "${subjectInput.value.trim() || "this subject"}"`;
  updateGate();
});

// The setup answers are part of the plan in progress, so they are saved the
// same way the fields are. markDirty() covers everything in the generate tab.
[teacherNameInput, subjectInput, topicInput, levelTypeSelect, collegeProgramInput,
 collegeYearSelect, k12GradeSelect, sectionInput].forEach((el) => {
  el.addEventListener("input", saveDraft);
  el.addEventListener("change", saveDraft);
});

function goToTab(tabName) {
  genTabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabName));
  tabPanelSetup.hidden = tabName !== "setup";
  tabPanelGenerate.hidden = tabName !== "generate";
  if (tabName === "generate") {
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (!hasAnyValue()) {
      setOwlState("guide", "Pick “Building Proficiency” or “Guided mode,” then click Generate — I'll help write it.");
    }
  } else if (tabName === "setup") {
    setOwlState("idle", "Let's set up your lesson plan — tell me who's teaching and what subject.");
  }
}

genTabsEl.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => goToTab(btn.dataset.tab));
});

setupContinueBtn.addEventListener("click", () => {
  if (!updateGate()) {
    showError("Fill in the cooperating teacher, subject, and course guide first.");
    return;
  }
  goToTab("generate");
});

cgTabsEl.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    cgTab = btn.dataset.tab;
    cgTabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    cgTabSearch.hidden = cgTab !== "search";
    cgTabUpload.hidden = cgTab !== "upload";
  });
});

function renderCourseGuideResults(guides) {
  cgResultsEl.innerHTML = "";
  guides.forEach((g) => {
    const card = document.createElement("div");
    card.className = "cg-result-card";
    card.innerHTML = `
      <div>
        <div class="cg-title">${escapeHtml(g.title)}</div>
        <div class="cg-meta">${escapeHtml(g.subject)} &middot; uploaded by ${escapeHtml(g.uploaded_by || "a teacher")}</div>
      </div>
      <span class="text-sm">Select</span>
    `;
    card.addEventListener("click", () => {
      selectCourseGuide(g);
    });
    cgResultsEl.appendChild(card);
  });
}

function selectCourseGuide(guide) {
  selectedCourseGuide = guide;
  cgSelectedEl.hidden = false;
  cgSelectedEl.innerHTML = `
    <span class="cg-selected-chip">
      ${Icons.checkSquare}
      <span>Using "${escapeHtml(guide.title)}" (${escapeHtml(guide.subject)})</span>
      <button type="button" id="cg-clear-btn" class="btn btn-ghost btn-sm" style="padding:2px 6px;">Change</button>
    </span>
  `;
  document.getElementById("cg-clear-btn").addEventListener("click", () => {
    selectedCourseGuide = null;
    cgSelectedEl.hidden = true;
    updateGate();
    saveDraft();
  });
  cgNoTopic.hidden = true;
  updateGate();
  saveDraft();
}

cgSearchBtn.addEventListener("click", async () => {
  const subject = subjectInput.value.trim();
  if (!subject) {
    showError("Select a subject first, then search the course guide library.");
    return;
  }
  errorBox.hidden = true;
  cgNoTopic.hidden = true;

  setButtonLoading(cgSearchBtn, true, "Searching");
  try {
    const data = await Api.searchCourseGuides(subject);
    const guides = data.course_guides || [];
    if (!guides.length) {
      cgResultsEl.innerHTML = "";
      cgNoTopic.hidden = false;
      return;
    }
    renderCourseGuideResults(guides);
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(cgSearchBtn, false);
  }
});

cgDropzone.addEventListener("click", () => cgFileInput.click());
cgDropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  cgDropzone.classList.add("dragover");
});
cgDropzone.addEventListener("dragleave", () => cgDropzone.classList.remove("dragover"));
cgDropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  cgDropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleCourseGuideUpload(e.dataTransfer.files[0]);
});
cgFileInput.addEventListener("change", () => {
  if (cgFileInput.files.length) handleCourseGuideUpload(cgFileInput.files[0]);
});

async function handleCourseGuideUpload(file) {
  const allowed = /\.(docx|dotx|pdf)$/i;
  if (!allowed.test(file.name)) {
    showError("Only .docx, .dotx, or .pdf files are allowed.");
    return;
  }
  const subject = subjectInput.value.trim();
  if (!subject) {
    showError("Select a subject first, so this course guide can be filed correctly.");
    return;
  }

  errorBox.hidden = true;
  cgDropzone.style.opacity = "0.5";
  cgDropzone.style.pointerEvents = "none";
  try {
    const data = await Api.uploadCourseGuide(file, subject, file.name);
    selectCourseGuide(data.course_guide);
    showToast(
      data.duplicate
        ? "This course guide is already in the shared library — using the existing copy."
        : "Course guide added to the shared library."
    );
  } catch (err) {
    showError(err.message);
  } finally {
    cgDropzone.style.opacity = "1";
    cgDropzone.style.pointerEvents = "auto";
  }
}

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
  return fieldsInDocumentOrder().filter((f) => f.role !== "heavy").map((f) => f.field_key);
}

function fieldByKey(key) {
  return (fmt.fields || []).find((f) => f.field_key === key);
}

// Which thinking-heavy fields the teacher wants written for them. Remembered per
// format, because a teacher who always writes their own Flow should only have to
// say so once. Ticked by default so a teacher who never opens this panel gets
// what they got before the panel existed.
const SCOPE_PREFIX = "alignedGenScope:v1:";

function scopeStorageKey() {
  return `${SCOPE_PREFIX}${fmt.id}`;
}

function readScopeChoice() {
  try {
    const raw = localStorage.getItem(scopeStorageKey());
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function writeScopeChoice(excluded) {
  try {
    localStorage.setItem(scopeStorageKey(), JSON.stringify(excluded));
  } catch (err) {
    /* private mode or quota: the choice just won't persist */
  }
}

function renderGenerateScope() {
  const heavy = heavyFieldKeys();
  const easy = easyFieldKeys();

  // Nothing to choose between: no heavy fields means the old all-or-nothing
  // behaviour, so the panel stays out of the way.
  if (!heavy.length) {
    generateScope.hidden = true;
    return;
  }

  generateScope.hidden = false;
  generateScopeAuto.textContent = easy.length
    ? `${easy.length} straightforward ${easy.length === 1 ? "field" : "fields"} will be filled in automatically.`
    : "";

  // Previously excluded keys stay excluded; anything new to this format starts
  // ticked.
  const excluded = new Set(readScopeChoice() || []);

  generateScopeOptions.innerHTML = heavy
    .map((key) => {
      const field = fieldByKey(key);
      return `
        <label class="generate-scope-option">
          <input type="checkbox" data-scope-key="${escapeHtml(key)}" ${excluded.has(key) ? "" : "checked"} />
          <span>${escapeHtml(field ? field.label : key)}</span>
        </label>`;
    })
    .join("");

  generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((box) => {
    box.addEventListener("change", () => {
      const next = [];
      generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((b) => {
        if (!b.checked) next.push(b.dataset.scopeKey);
      });
      writeScopeChoice(next);
    });
  });
}

// The keys to generate: every quick field, plus the heavy ones still ticked.
// The page sends the full list rather than letting the server add the easy
// fields, so "generate exactly what was asked for" is the only rule in play.
function selectedGenerateKeys() {
  const ticked = [];
  generateScopeOptions.querySelectorAll("[data-scope-key]").forEach((box) => {
    if (box.checked) ticked.push(box.dataset.scopeKey);
  });
  return easyFieldKeys().concat(ticked);
}

function isFieldComplete(key) {
  const v = fieldValues[key];
  return Array.isArray(v) ? v.length > 0 : !!(v && String(v).trim());
}

// stepFieldKeys is heavy-only, so finishing the walkthrough does not mean the
// plan is done - the easy fields outside it can still be blank. Any message
// that announces "done" or "complete" off the guided check alone is a
// false-completeness claim, the same bug the field-role split was meant to
// fix. Every place that needs to say so calls this one check, so the messages
// can't drift apart and start disagreeing about what "done" means.
function incompleteEasyFieldKeys() {
  return easyFieldKeys().filter((k) => !isFieldComplete(k));
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
    opt.textContent =
      i === stepIndex
        ? `▸ ${label} (current)`
        : i > stepIndex
        ? `🔒 ${label}`
        : isFieldComplete(key)
        ? `✓ ${label}`
        : `○ ${label}`;
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
        const el = canvas.querySelector(`[data-field-key="${key}"]`);
        if (!el) return;
        el.classList.remove("step-locked", "step-active");
        if (i === stepIndex) {
          el.contentEditable = "true";
          el.classList.add("step-active");
          activeEl = el;
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
    const el = canvas && canvas.querySelector(`[data-field-key="${key}"]`);
    if (el) fieldValues[key] = el.textContent;
  } else {
    const el = resultsEl.querySelector(`[data-field-key="${key}"]`);
    if (el) fieldValues[key] = el.value;
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

  return items.map((item) => `• ${stripExistingBullet(item)}`).join("\n");
}

// Runs formatGeneratedValue over a whole field_key -> value map returned by
// the AI, so every list-like field gets a consistent bulleted structure
// before it lands in fieldValues.
function formatGeneratedValues(values) {
  const out = {};
  Object.entries(values || {}).forEach(([key, val]) => {
    out[key] = formatGeneratedValue(val);
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
  const value = fieldValues[field.field_key] || "";
  const requiredMark = field.is_required ? " *" : "";
  const hint = field.ai_hint ? `<p class="hint">${escapeHtml(field.ai_hint)}</p>` : "";
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
      fieldValues[el.dataset.fieldKey] = el.value;
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
  fieldValues[el.dataset.fieldKey] = el.textContent;
  fieldRichValues[el.dataset.fieldKey] = sanitizeRichValueHtml(el);
  el.classList.toggle("lp-filled", !!el.textContent.trim());
}

// The value-map half of clearing a field: shared by clearField() below and by
// the Guided fallback field-list branch (an input/textarea, not a DOM slot,
// so it can't go through clearField() itself). Also re-renders the step nav,
// since its checkmark now reflects real completeness rather than position,
// and clearing a field the teacher already stepped past has to un-tick it.
function clearFieldState(key) {
  fieldValues[key] = "";
  delete fieldRichValues[key];
  markDirty();
  if (mode === "step") renderStepFieldNav();
}

// Empties one field so the teacher can write their own answer or ask for a
// different suggestion. Clears the rich value as well as the plain text,
// otherwise the old styled HTML would come back on the next render.
function clearField(el) {
  const key = el.dataset.fieldKey;
  el.innerHTML = "";
  el.classList.remove("lp-filled", "field-needs-answer");
  clearFieldState(key);
}

function wireLiveDocEditing() {
  const canvas = liveDocWrap.querySelector(".lp-doc");
  if (!canvas) return;
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
    const el = canvas.querySelector(`[data-field-key="${key}"]`);
    if (el) {
      const value = fieldValues[key];
      el.textContent = Array.isArray(value) ? value.join("\n") : (value || "");
      delete fieldRichValues[key]; // fresh AI text replaces any earlier manual styling
      el.classList.add("lp-filled");
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    await sleep(220);
  }
}

function hasAnyValue() {
  return Object.values(fieldValues).some((v) => v && v.trim());
}

// The live document view always shows every field already (there's no
// per-section re-render needed); only the plain field-list fallback
// (formats with no reference file) needs re-rendering on nav/mode changes.
function maybeRenderResults() {
  if (!docTemplateData && hasAnyValue()) renderResults();
}

function markDirty() {
  dirty = true;
  saveStatus.textContent = "Unsaved changes — save to export the latest version.";
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
    generation_mode: mode,
    is_public: visibilityCheckbox.checked,
  };
}

function planTitle() {
  const subject = subjectInput.value.trim();
  const topic = topicInput.value.trim();
  // Topic first when there is one: a teacher's drafts are nearly all the same
  // subject and format, so "Subject — Format" would give every card in the
  // "continue where you left off" strip an identical name.
  if (topic) return `${topic}${subject ? ` — ${subject}` : ""}`;
  if (subject) return `${subject} — ${fmt.name}`;
  return `Untitled ${fmt.name}`;
}

// A plan is only worth a row once it holds something a teacher would want
// back. Without this, merely opening the generator would leave an empty draft
// behind every time.
function worthSaving() {
  return hasAnyValue() || !!subjectInput.value.trim() || !!topicInput.value.trim();
}

async function persistPlan() {
  if (!fmt) return null;
  const payload = planPayload();
  if (planId) {
    const data = await Api.updateLessonPlan(planId, payload);
    return data.lesson_plan;
  }
  const data = await Api.saveLessonPlan(payload);
  planId = data.lesson_plan.id;
  return data.lesson_plan;
}

function scheduleServerSave() {
  if (serverSaveLocked || restoringDraft) return;
  clearTimeout(serverSaveTimer);
  serverSaveTimer = setTimeout(runServerSave, SERVER_SAVE_DELAY_MS);
}

async function runServerSave() {
  if (serverSaveLocked || serverSaveInFlight || !fmt || !worthSaving()) return;

  serverSaveInFlight = true;
  const wasDirty = dirty;
  try {
    await persistPlan();
    // Only claim saved if nothing changed while the request was in flight —
    // otherwise the newer edit is still unsaved and saying otherwise would
    // lie about it.
    if (dirty === wasDirty) {
      dirty = false;
      saveStatus.textContent = `Draft saved ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`;
      enableExport();
    }
  } catch (err) {
    // 409 means the plan was submitted or graded elsewhere, so it will never
    // accept another edit — stop autosaving and say so once.
    if (/submitted/i.test(err.message || "")) {
      serverSaveLocked = true;
      saveStatus.textContent = "This plan has been submitted and can no longer be edited.";
      showToast("This plan has been submitted, so your latest changes weren't saved.", true);
    } else {
      // A transient failure (offline, server restart) leaves the localStorage
      // draft as the safety net and the page still marked unsaved.
      saveStatus.textContent = "Couldn't save the draft automatically — use Save lesson plan.";
    }
  } finally {
    serverSaveInFlight = false;
  }
}

function enableExport() {
  if (!planId) return;
  exportBtn.href = Api.exportUrl(planId);
  exportBtn.target = "_blank";
  exportBtn.rel = "noopener";
  exportBtn.style.pointerEvents = "auto";
  exportBtn.style.opacity = "1";
}

// Nothing is sent on pagehide: the debounce window is short and the
// localStorage draft below already survives navigation, so an unload-time
// request would add a failure path without covering anything new.

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
  return `${DRAFT_PREFIX}${params.get("format_id") || "none"}`;
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
  draftTimer = setTimeout(() => {
    try {
      localStorage.setItem(draftKey(), JSON.stringify({
        at: Date.now(),
        planId,
        mode,
        stepIndex,
        fieldValues,
        fieldRichValues,
        modeSlots,
        courseGuide: selectedCourseGuide,
        setup: {
          teacher: teacherNameInput.value,
          subject: subjectInput.value,
          topic: topicInput.value,
          levelType: levelTypeSelect.value,
          collegeProgram: collegeProgramInput.value,
          collegeYear: collegeYearSelect.value,
          k12Grade: k12GradeSelect.value,
          section: sectionInput.value,
        },
      }));
    } catch (err) {
      /* private mode or quota — the page still works, it just won't persist */
    }
  }, 400);
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
      const key = el.dataset.fieldKey;
      const rich = fieldRichValues[key];
      const value = fieldValues[key];
      const text = Array.isArray(value) ? value.join("\n") : (value || "");
      if (rich) {
        el.innerHTML = rich;
        el.classList.add("lp-filled");
      } else if (text.trim()) {
        el.textContent = text;
        el.classList.add("lp-filled");
      } else if (blankMissing) {
        el.textContent = "";
        el.classList.remove("lp-filled");
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
    if (plan.subject) subjectInput.value = plan.subject;
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
      saveStatus.textContent = "You're viewing someone else's plan. Save to keep your own copy.";
    } else if (plan.status === "submitted" || plan.status === "reviewed") {
      // A plan already submitted or graded can't take further edits, so the
      // page says so rather than letting the teacher type into a dead end.
      serverSaveLocked = true;
      saveStatus.textContent =
        plan.status === "reviewed"
          ? "This plan has been reviewed, so it can no longer be edited."
          : "This plan has been submitted, so it can no longer be edited.";
    }

    paintRestoredValues();
    enableExport();
  } finally {
    restoringDraft = false;
  }


  updateGate();
  return true;
}

function restoreDraft() {
  const draft = readDraft();
  if (!draft) return false;

  restoringDraft = true;
  try {
    const setup = draft.setup || {};
    if (setup.teacher) teacherNameInput.value = setup.teacher;
    if (setup.subject) subjectInput.value = setup.subject;
    if (setup.topic) topicInput.value = setup.topic;
    if (setup.levelType) levelTypeSelect.value = setup.levelType;
    if (setup.collegeProgram) collegeProgramInput.value = setup.collegeProgram;
    if (setup.collegeYear) collegeYearSelect.value = setup.collegeYear;
    if (setup.k12Grade) k12GradeSelect.value = setup.k12Grade;
    if (setup.section) sectionInput.value = setup.section;
    updateLevelFields();

    fieldValues = draft.fieldValues || {};
    fieldRichValues = draft.fieldRichValues || {};
    // Both modes' work comes back, not just the one that happened to be active.
    if (draft.modeSlots) modeSlots = draft.modeSlots;
    planId = draft.planId || null;
    stepIndex = draft.stepIndex || 0;

    if (draft.courseGuide) selectCourseGuide(draft.courseGuide);

    paintRestoredValues();

    if (draft.mode === "step") {
      const stepBtn = modeSwitchBtns.find((b) => b.dataset.mode === "step");
      if (stepBtn) stepBtn.click();
      // Entering guided mode jumps to the first unfinished field, which is
      // right when you switch modes but wrong when resuming: it would drop
      // the teacher somewhere other than where they actually stopped. Put
      // the saved position back and re-lock around it.
      if (typeof draft.stepIndex === "number" && draft.stepIndex < stepFieldKeys.length) {
        stepIndex = draft.stepIndex;
        applyStepLocks();
      }
    }
  } finally {
    restoringDraft = false;
  }

  updateGate();
  return hasAnyValue() || !!draft.courseGuide;
}

modeSwitchBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.mode === mode) return;   // already here, nothing to swap
    // restoreDraft() clicks this button purely to trigger the UI refresh
    // below, after it has already set fieldValues/modeSlots itself for the
    // mode being resumed into. Capturing here would run before `mode` has
    // caught up to what's on screen and stamp that mode's data over a slot
    // that restoreDraft already got right, so skip capture/load in that case.
    if (!restoringDraft) {
      // Put the current mode's work away before picking up the other's.
      captureModeSlot();
      mode = btn.dataset.mode;
      loadModeSlot(mode);
    } else {
      mode = btn.dataset.mode;
    }
    saveDraft();
    modeSwitchBtns.forEach((b) => b.classList.toggle("active", b === btn));
    fullControls.hidden = mode !== "full";
    stepControls.hidden = mode !== "step";
    showOwlChat(mode === "step");
    if (mode === "step") {
      // Shares incompleteGuidedFieldKeys() with the Finish branch below, so
      // the two places that decide whether the walkthrough is actually done
      // can't quietly start disagreeing about what "done" means.
      const incompleteGuided = incompleteGuidedFieldKeys();
      stepIndex = incompleteGuided.length === 0
        ? stepFieldKeys.length - 1
        : stepFieldKeys.indexOf(incompleteGuided[0]);
      applyStepLocks();
      let guideMessage;
      if (incompleteGuided.length === 0) {
        const outsideIncomplete = incompleteEasyFieldKeys();
        if (outsideIncomplete.length === 0) {
          guideMessage = "Every field already has an answer. Review them below, or click a pill to revise one.";
        } else {
          const n = outsideIncomplete.length;
          guideMessage = `The guided fields are done. ${n} quick field${n === 1 ? "" : "s"} outside the walkthrough ${n === 1 ? "is" : "are"} still blank. Fill ${n === 1 ? "it" : "them"} in directly below.`;
        }
      } else {
        guideMessage = `Let's start with "${fieldByKey(stepFieldKeys[stepIndex]).label}." Type your answer, then Submit & continue.`;
      }
      setOwlState("guide", guideMessage);
    } else {
      clearStepLocks();
      maybeRenderResults();
    }
  });
});

function baseGenerationPayload() {
  return {
    format_id: fmt.id,
    teacher_name: teacherNameInput.value.trim(),
    subject: subjectInput.value.trim(),
    course_guide_id: selectedCourseGuide ? selectedCourseGuide.id : null,
    context: getAdvancedContext(),
    include_keys: selectedGenerateKeys(),
  };
}

function renderProgress(sectionStates) {
  generationProgressEl.hidden = false;
  generationProgressEl.innerHTML = sectionStates
    .map((s) => {
      const icon = s.status === "done" ? "✓" : s.status === "active" ? "…" : s.status === "retrying" ? "⟳" : "";
      return `
        <div class="progress-row progress-${s.status}">
          <span class="progress-icon">${icon}</span>
          <span class="progress-label">${escapeHtml(s.name)}</span>
          ${s.status === "retrying" ? '<span class="progress-note">model is busy, retrying…</span>' : ""}
        </div>`;
    })
    .join("");
}

generateFullBtn.addEventListener("click", async () => {
  if (!updateGate()) {
    showError("Fill in the cooperating teacher, subject, and course guide first.");
    return;
  }

  if (!selectedGenerateKeys().length) {
    showError("Tick at least one field for me to write, or fill the plan in yourself.");
    return;
  }

  errorBox.hidden = true;
  setButtonLoading(generateFullBtn, true, "Generating");
  setOwlState("thinking", "Thinking hard about your lesson...");

  // Built up live from the stream's own chunk names as they arrive — the
  // Building Proficiency mode batches fields for pacing/streaming purposes,
  // which doesn't line up with the (now largely nominal) section grouping
  // used by Guided mode's nav.
  const progressRows = [];
  renderProgress(progressRows);

  try {
    const finalEvent = await Api.generateFullStream(baseGenerationPayload(), (event) => {
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
    reportGenerationOutcome(finalEvent);
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(generateFullBtn, false);
    generationProgressEl.hidden = true;
    startGenerateCooldown();
  }
});

// What the owl says once generation stops. The server reports which fields it
// could not fill even after retrying them, so a plan with blanks in it is
// never announced as finished: that mismatch is exactly what made "All done!"
// untrustworthy.
function reportGenerationOutcome(finalEvent) {
  const missingLabels = (finalEvent && finalEvent.missing_labels) || [];

  if (!missingLabels.length) {
    setOwlState("celebrate", "All done! Review what I wrote below, then save when you're happy with it.");
    return;
  }

  // Named outright up to a few, counted beyond that, so the message stays
  // readable on a long format.
  const shown = missingLabels.slice(0, 3).join(", ");
  const extra = missingLabels.length - 3;
  const list = extra > 0 ? `${shown}, and ${extra} more` : shown;

  setOwlState(
    "guide",
    `I filled in everything except ${list}. Write ${missingLabels.length === 1 ? "that one" : "those"} in yourself, or ask me about ${missingLabels.length === 1 ? "it" : "them"} in the chat.`
  );
  showError(
    `${missingLabels.length} field${missingLabels.length === 1 ? "" : "s"} couldn't be generated and ${
      missingLabels.length === 1 ? "is" : "are"
    } still empty: ${missingLabels.join(", ")}.`
  );

  // Draw attention to the actual empty fields rather than only naming them.
  highlightEmptyFields(finalEvent.missing || []);
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

stepContinueBtn.addEventListener("click", () => {
  syncActiveStepValue();
  const key = stepFieldKeys[stepIndex];
  if (!isFieldComplete(key)) {
    showError(`Fill in "${fieldByKey(key).label}" before continuing — every field is required in Guided mode.`);
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
          ${renderPreviewValue(fieldValues[field.field_key])}
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
          ${renderPreviewValue(fieldValues[key])}
        </div>`;
    })
    .join("");
  return `<div class="preview-section-title">Not part of the printed template</div>${items}`;
}

// Copies the already-generated fieldValues into the document canvas's
// editable slots. Only fields the backend actually matched to a real anchor
// in the reference file have a slot to fill — everything else is simply not
// touched, so nothing invented ever appears in the canvas.
function fillDocCanvas() {
  const canvas = previewBody.querySelector(".lp-doc");
  if (!canvas) return;
  let filled = 0;
  canvas.querySelectorAll("[data-field-key]").forEach((el) => {
    const value = fieldValues[el.dataset.fieldKey];
    const text = Array.isArray(value) ? value.join("\n") : (value || "");
    if (!text.trim()) return;
    el.textContent = text;
    el.classList.add("lp-filled");
    filled += 1;
  });
  showToast(filled ? `Filled ${filled} field${filled === 1 ? "" : "s"} from your generated content.` : "Nothing generated yet to fill in.");
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
      fieldValues[el.dataset.fieldKey] = el.textContent;
      el.classList.toggle("lp-filled", !!el.textContent.trim());
      markDirty();
      renderResults();
      if (mode === "step") renderStepFieldNav();
    });
  });
}

function renderPreviewModal(templateData, docAvailable) {
  const dialogEl = previewOverlay.querySelector(".modal-dialog");
  dialogEl.classList.toggle("modal-dialog-doc", previewViewMode === "doc");

  const toolbar = `
    <div class="doc-toolbar">
      <div class="doc-toolbar-views">
        <button type="button" class="doc-view-btn ${previewViewMode === "doc" ? "active" : ""}"
          data-view="doc" ${docAvailable ? "" : "disabled title=\"No reference file to render for this format\""}>
          Document view
        </button>
        <button type="button" class="doc-view-btn ${previewViewMode === "list" ? "active" : ""}" data-view="list">
          Field list view
        </button>
      </div>
      ${previewViewMode === "doc" ? `<button type="button" class="btn btn-secondary btn-sm" id="preview-fill-btn">Fill in generated content</button>` : ""}
    </div>`;

  const warning =
    docAvailable && templateData.unmatched_fields.length
      ? `<div class="doc-warning"><strong>${templateData.unmatched_fields.length} field${templateData.unmatched_fields.length === 1 ? "" : "s"}</strong> couldn't be matched to a spot in the reference document, so they're shown separately below rather than guessed at.</div>`
      : "";

  let content;
  if (previewViewMode === "doc") {
    content = `<div class="doc-hint">This mirrors your uploaded reference file. Tap "Fill in generated content", or click into any highlighted spot to edit it directly.</div>`;
    content += `<div class="lp-doc-wrap">${templateData.html}</div>`;
    content += renderUnmatchedFieldList(templateData.unmatched_fields);
  } else {
    content = renderPlainFieldList();
  }

  previewBody.innerHTML = renderPreviewMeta() + toolbar + warning + content;

  previewBody.querySelectorAll(".doc-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.dataset.view === previewViewMode) return;
      previewViewMode = btn.dataset.view;
      renderPreviewModal(templateData, docAvailable);
    });
  });

  if (previewViewMode === "doc") {
    wireDocCanvasEditing();
    const fillBtn = document.getElementById("preview-fill-btn");
    if (fillBtn) fillBtn.addEventListener("click", fillDocCanvas);
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

function closeGeneratorPreview() {
  previewOverlay.hidden = true;
  previewOverlay.querySelector(".modal-dialog").classList.remove("modal-dialog-doc");
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

saveBtn.addEventListener("click", async () => {
  // A pending autosave would otherwise race this one and re-send the same
  // payload a moment later.
  clearTimeout(serverSaveTimer);
  setButtonLoading(saveBtn, true, "Saving");
  try {
    await persistPlan();
    dirty = false;
    // The plan is on the server now and listed under "List of Lesson Plan",
    // so the local draft has done its job. Editing on from here marks the
    // page dirty again and starts a fresh draft.
    clearDraft();
    saveStatus.textContent = "Saved.";
    enableExport();
    showToast("Lesson plan saved.");
    setOwlState("celebrate", "Saved! Export it as Word whenever you're ready.");
    revealSubmitControlsIfStudent();
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(saveBtn, false);
  }
});

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("lesson-plan");

async function init() {
  const user = await requireAuth();
  if (!user) return;
  currentUser = user;
  wireTopbar(user);
  // Bring back any conversations saved for this format before the chat can
  // render, so a reload reopens the thread instead of an empty log.
  loadChatThreads();
  teacherNameInput.value = user.full_name || "";

  updateLevelFields();
  updateGate();

  // Two ways in: ?format_id= starts a new plan, ?plan_id= reopens one already
  // saved (what the "continue where you left off" cards link to). A reopened
  // plan supplies its own format, so the format id doesn't have to be passed
  // alongside it.
  const params = new URLSearchParams(window.location.search);
  const requestedPlanId = params.get("plan_id");
  let formatId = params.get("format_id");
  let openedPlan = null;

  if (requestedPlanId) {
    try {
      const data = await Api.getLessonPlan(requestedPlanId);
      openedPlan = data.lesson_plan;
      formatId = openedPlan.format_id;
    } catch (err) {
      loadingState.hidden = true;
      showError(`That lesson plan couldn't be opened: ${err.message}`);
      return;
    }
  }

  if (!formatId) {
    loadingState.hidden = true;
    showError("No format selected. Go back to Lesson Plan and pick a format.");
    return;
  }

  try {
    const data = await Api.getFormat(formatId);
    fmt = data.format;

    if (!fmt.fields || !fmt.fields.length) {
      loadingState.hidden = true;
      showError("This format doesn't have any fields defined yet.");
      return;
    }

    sections = buildSections(fmt.fields);
    document.title = `${fmt.name} — AlignED`;
    document.getElementById("format-name").textContent = fmt.name;

    // Guided walks the fields that need real thinking. The quick ones are left
    // out of the walkthrough entirely: a teacher does not need to be guided
    // through their own name, and locking those behind a step was most of why
    // fields felt uneditable.
    const heavy = heavyFieldKeys();
    // A format with no heavy fields would leave Guided with nothing to do, so it
    // falls back to walking everything.
    stepFieldKeys = heavy.length ? heavy : fieldsInDocumentOrder().map((f) => f.field_key);
    stepIndex = 0;
    renderGenerateScope();

    await initLiveDocView();

    // Bring back anything left from a previous visit before the page is
    // shown, so the teacher never sees their work blank out and refill. A
    // plan opened by id loads from its own saved row instead: that is the
    // authoritative copy, and it may well have been written on another
    // device where no local draft exists.
    const resumed = openedPlan ? applyOpenedPlan(openedPlan) : restoreDraft();

    loadingState.hidden = true;
    content.hidden = false;

    if (resumed) {
      showToast(openedPlan ? "Draft reopened." : "Picked up where you left off.");
      setOwlState("guide", "I brought back what you had so far. Carry on where you left off.");
    }
  } catch (err) {
    loadingState.hidden = true;
    showError(err.message);
  }
}

init();
