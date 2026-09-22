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
const generationProgressEl = document.getElementById("generation-progress");
const stepContinueBtn = document.getElementById("step-continue-btn");
const resultsEl = document.getElementById("results");
const liveDocHint = document.getElementById("live-doc-hint");
const liveDocToolbar = document.getElementById("live-doc-toolbar");
const liveDocWrap = document.getElementById("live-doc-wrap");
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

function fieldByKey(key) {
  return (fmt.fields || []).find((f) => f.field_key === key);
}

function isFieldComplete(key) {
  const v = fieldValues[key];
  return Array.isArray(v) ? v.length > 0 : !!(v && String(v).trim());
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
    opt.textContent = i < stepIndex ? `✓ ${label}` : i === stepIndex ? `▸ ${label} (current)` : `🔒 ${label}`;
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
          el.contentEditable = "false";
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
  return typeof value === "string" && /(^|\n)•\s/.test(value);
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
  liveDocWrap.hidden = false;
  liveDocHint.hidden = false;
  liveDocToolbar.hidden = false;
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
  ["bold", "italic", "underline"].forEach((cmd) => {
    const btn = liveDocToolbar.querySelector(`[data-cmd="${cmd}"]`);
    if (!btn) return;
    let active = false;
    try { active = document.queryCommandState(cmd); } catch (e) { /* unsupported in this browser */ }
    btn.classList.toggle("active", active);
  });
}

function wireLiveDocToolbar() {
  // Keep the field's selection alive when a toolbar button is clicked —
  // otherwise the button would steal focus and execCommand would have
  // nothing to act on.
  liveDocToolbar.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  liveDocToolbar.querySelectorAll(".doc-tool-btn[data-cmd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = document.activeElement;
      if (!el || !el.dataset || !el.dataset.fieldKey) {
        showToast("Click into a field first, then choose a style.", true);
        return;
      }
      document.execCommand(btn.dataset.cmd, false, null);
      updateLiveDocToolbarStates();
      syncFieldFromEl(el);
      markDirty();
    });
  });

  liveDocToolbar.querySelectorAll(".doc-tool-btn[data-list]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = document.activeElement;
      if (!el || !el.dataset || !el.dataset.fieldKey) {
        showToast("Click into a field first, then choose a list style.", true);
        return;
      }
      document.execCommand(btn.dataset.list === "bullet" ? "insertUnorderedList" : "insertOrderedList", false, null);
      syncFieldFromEl(el);
      markDirty();
    });
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
}

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
  const formatId = new URLSearchParams(window.location.search).get("format_id") || "none";
  return `${DRAFT_PREFIX}${formatId}`;
}

function saveDraft() {
  // Never write while the restore is still populating the page, or a
  // half-applied draft would overwrite the complete one.
  if (restoringDraft) return;
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

// Paint restored values into whichever editor this format uses.
function paintRestoredValues() {
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
      }
    });
  } else if (hasAnyValue()) {
    renderResults();
  }
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
    mode = btn.dataset.mode;
    saveDraft();
    modeSwitchBtns.forEach((b) => b.classList.toggle("active", b === btn));
    fullControls.hidden = mode !== "full";
    stepControls.hidden = mode !== "step";
    showOwlChat(mode === "step");
    if (mode === "step") {
      const firstIncomplete = stepFieldKeys.findIndex((k) => !isFieldComplete(k));
      stepIndex = firstIncomplete === -1 ? stepFieldKeys.length - 1 : firstIncomplete;
      applyStepLocks();
      setOwlState(
        "guide",
        firstIncomplete === -1
          ? "Every field already has an answer — review them below, or click a pill to revise one."
          : `Let's start with "${fieldByKey(stepFieldKeys[stepIndex]).label}." Type your answer, then Submit & continue.`
      );
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
    await Api.generateFullStream(baseGenerationPayload(), (event) => {
      if (event.type === "section_start") {
        progressRows.push({ name: event.section, status: "active" });
        renderProgress(progressRows);
        setOwlState("thinking", `Writing "${event.section}"...`);
      } else if (event.type === "section_done") {
        const formatted = formatGeneratedValues(event.values);
        Object.assign(fieldValues, formatted);
        const row = progressRows.find((r) => r.name === event.section);
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
    setOwlState("celebrate", "All done! Review what I wrote below, then save when you're happy with it.");
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(generateFullBtn, false);
    generationProgressEl.hidden = true;
  }
});

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
    setOwlState("celebrate", "All fields done — review everything, then save when you're happy.");
  }
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
  setButtonLoading(saveBtn, true, "Saving");
  try {
    const data = await Api.saveLessonPlan({
      format_id: fmt.id,
      title: `${subjectInput.value.trim()} — ${fmt.name}`,
      subject: subjectInput.value.trim(),
      grade_level: getClassLabel(),
      field_values: fieldValues,
      rich_field_values: fieldRichValues,
      generation_mode: mode,
      is_public: visibilityCheckbox.checked,
    });
    planId = data.lesson_plan.id;
    dirty = false;
    // The plan is on the server now and listed under "List of Lesson Plan",
    // so the local draft has done its job. Editing on from here marks the
    // page dirty again and starts a fresh draft.
    clearDraft();
    saveStatus.textContent = "Saved.";
    exportBtn.href = Api.exportUrl(planId);
    exportBtn.target = "_blank";
    exportBtn.rel = "noopener";
    exportBtn.style.pointerEvents = "auto";
    exportBtn.style.opacity = "1";
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

  const formatId = new URLSearchParams(window.location.search).get("format_id");
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

    stepFieldKeys = fmt.fields.slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)).map((f) => f.field_key);
    stepIndex = 0;

    await initLiveDocView();

    // Bring back anything left from a previous visit before the page is
    // shown, so the teacher never sees their work blank out and refill.
    const resumed = restoreDraft();

    loadingState.hidden = true;
    content.hidden = false;

    if (resumed) {
      showToast("Picked up where you left off.");
      setOwlState("guide", "I brought back what you had so far. Carry on where you left off.");
    }
  } catch (err) {
    loadingState.hidden = true;
    showError(err.message);
  }
}

init();
