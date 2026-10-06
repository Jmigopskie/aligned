const errorBox = document.getElementById("error-box");
const plansBody = document.getElementById("plans-body");
const searchInput = document.getElementById("search-input");
const sortSelect = document.getElementById("sort-select");
const previewOverlay = document.getElementById("preview-overlay");
const previewBody = document.getElementById("preview-body");
const previewClose = document.getElementById("preview-close");
const tabSwitch = document.getElementById("plans-tab-switch");
const statusFilter = document.getElementById("status-filter");
const statusFilterField = document.getElementById("status-filter-field");

const submitOverlay = document.getElementById("submit-overlay");
const submitForm = document.getElementById("submit-form");
const submitSectionSelect = document.getElementById("submit-section-select");
const submitConfirmBtn = document.getElementById("submit-confirm-btn");
const submitClose = document.getElementById("submit-close");
const submitPreviewLink = document.getElementById("submit-preview-link");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("lesson-plan-list");

let allPlans = [];
let currentUser = null;
let mySections = [];
let submitPlanId = null;
let activeTab = "mine";
const formatCache = {};

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function statusLabel(status) {
  if (status === "submitted") return "Pending review";
  if (status === "reviewed") return "Reviewed";
  return "Draft";
}

function scoreTone(score) {
  if (score >= 90) return "score-great";
  if (score >= 75) return "score-good";
  if (score >= 50) return "score-ok";
  return "score-low";
}

// How much of a draft is filled in, so its row says what is left to do rather
// than only when it was last touched.
function draftProgress(plan) {
  const values = plan.field_values || {};
  const filled = Object.values(values).filter((v) => {
    if (Array.isArray(v)) return v.some((item) => String(item).trim());
    return String(v == null ? "" : v).trim();
  }).length;
  const total = Object.keys(values).length;
  // Editing the document body is real work on the plan, so a row must not
  // report "nothing filled in yet" over it. It counts separately from the AI
  // fields because the two are different kinds of progress.
  const edits = (plan.doc_edits || []).length;
  const editNote = edits ? `${edits} document edit${edits === 1 ? "" : "s"}` : "";

  if (!total) return editNote || "Nothing filled in yet";
  const fieldNote = filled === total
    ? `All ${total} fields filled in`
    : `${filled} of ${total} fields filled in`;
  return editNote ? `${fieldNote}, ${editNote}` : fieldNote;
}

function sortPlans(plans, sortBy) {
  const sorted = plans.slice();
  if (sortBy === "name") {
    sorted.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  } else if (sortBy === "score") {
    // Higher score first; plans with no score yet sink to the bottom.
    sorted.sort((a, b) => {
      const aScore = a.score == null ? -1 : a.score;
      const bScore = b.score == null ? -1 : b.score;
      return bScore - aScore;
    });
  } else {
    sorted.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  }
  return sorted;
}

function renderPlans(plans) {
  const isMineTab = activeTab === "mine";
  const isStudent = currentUser && currentUser.role === "student";
  const showStatusScore = isMineTab && isStudent;
  document.querySelectorAll(".js-status-col").forEach((el) => (el.hidden = !showStatusScore));
  document.querySelectorAll(".js-score-col").forEach((el) => (el.hidden = !showStatusScore));
  document.querySelectorAll(".js-author-col").forEach((el) => (el.hidden = isMineTab));

  const visibleCols = 5 + (isMineTab ? 0 : 1) + (showStatusScore ? 2 : 0);

  if (!plans.length) {
    plansBody.innerHTML = `
      <tr class="table-empty-row">
        <td colspan="${visibleCols}">${
          isMineTab
            ? `No lesson plans match yet. <a href="lesson-plan.html">Create your first one</a>.`
            : `No public lesson plans yet.`
        }</td>
      </tr>`;
    return;
  }

  plansBody.innerHTML = plans
    .map(
      (p) => `
      <tr>
        <td>
          <div class="plan-title-cell">
            <span class="file-ico">${Icons.file}</span>
            <span class="plan-title-text">
              <span>${escapeHtml(p.title)}</span>
              ${isMineTab && p.status === "draft" ? `<span class="plan-progress">${escapeHtml(draftProgress(p))}</span>` : ""}
            </span>
            ${isMineTab && p.is_public ? `<span class="badge">Public</span>` : ""}
          </div>
        </td>
        <td>${escapeHtml(p.subject || "\u2013")}</td>
        <td>${escapeHtml(p.grade_level || "\u2013")}</td>
        ${!isMineTab ? `<td>${escapeHtml(p.author_name || "\u2013")}</td>` : ""}
        ${showStatusScore ? `<td><span class="status-pill ${p.status}">${statusLabel(p.status)}</span></td>` : ""}
        ${showStatusScore ? `<td>${p.score != null ? `<span class="score-pill ${scoreTone(p.score)}">${p.score}/100</span>` : "\u2013"}</td>` : ""}
        <td>${fmtDate(p.updated_at)}</td>
        <td>
          <div class="row-actions">
            ${
              // Only a draft can still be changed: the server locks a plan once
              // it is submitted, so those get Preview instead.
              isMineTab && p.status === "draft"
                ? `<a class="btn btn-secondary btn-sm row-continue" href="generator.html?plan_id=${p.id}"><span data-icon="edit"></span>Continue</a>`
                : ""
            }
            <button class="row-action-btn" type="button" data-action="preview" data-plan="${p.id}" title="Preview" aria-label="Preview">${Icons.eye}</button>
            <button class="row-action-btn" type="button" data-action="export" data-plan="${p.id}" title="Download" aria-label="Download">${Icons.download}</button>
            ${
              isMineTab
                ? `<button class="row-action-btn" type="button" data-action="visibility" data-plan="${p.id}" data-public="${p.is_public ? "1" : "0"}" title="${p.is_public ? "Make private" : "Make public"}" aria-label="${p.is_public ? "Make private" : "Make public"}">${p.is_public ? Icons.globe : Icons.lock}</button>`
                : ""
            }
            ${isMineTab && isStudent ? `<button class="row-action-btn" type="button" data-action="submit" data-plan="${p.id}" title="Submit to class" aria-label="Submit to class">${Icons.inbox}</button>` : ""}
            ${isMineTab ? `<button class="row-action-btn danger" type="button" data-action="delete" data-plan="${p.id}" title="Delete" aria-label="Delete">${Icons.trash}</button>` : ""}
          </div>
        </td>
      </tr>`
    )
    .join("");

  hydrateIcons(plansBody);
  wireRowActions();
}

function wireRowActions() {
  plansBody.querySelectorAll(".row-action-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const planId = btn.dataset.plan;
      if (btn.dataset.action === "preview") {
        openPreview(planId);
      } else if (btn.dataset.action === "export") {
        window.open(Api.exportUrl(planId), "_blank", "noopener");
      } else if (btn.dataset.action === "submit") {
        openSubmitModal(planId);
      } else if (btn.dataset.action === "visibility") {
        const makePublic = btn.dataset.public !== "1";
        try {
          const data = await Api.setLessonPlanVisibility(planId, makePublic);
          const idx = allPlans.findIndex((p) => String(p.id) === String(planId));
          if (idx !== -1) allPlans[idx] = data.lesson_plan;
          showToast(makePublic ? "Lesson plan is now public." : "Lesson plan is now private.");
          applyFilter();
        } catch (err) {
          showToast(err.message, true);
        }
      } else if (btn.dataset.action === "delete") {
        if (!confirm("Delete this lesson plan? This can't be undone.")) return;
        try {
          await Api.deleteLessonPlan(planId);
          showToast("Lesson plan deleted.");
          allPlans = allPlans.filter((p) => String(p.id) !== String(planId));
          applyFilter();
        } catch (err) {
          showToast(err.message, true);
        }
      }
    });
  });
}

async function openSubmitModal(planId) {
  submitPlanId = planId;
  submitSectionSelect.innerHTML = `<option>Loading&hellip;</option>`;
  submitOverlay.hidden = false;

  try {
    if (!mySections.length) {
      const data = await Api.listSections();
      mySections = data.sections || [];
    }
    if (!mySections.length) {
      submitSectionSelect.innerHTML = "";
      submitForm.hidden = true;
      showToast("Join a class first from My Classes.", true);
      closeSubmitModal();
      return;
    }
    submitForm.hidden = false;
    submitSectionSelect.innerHTML = mySections
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
      .join("");
  } catch (err) {
    showToast(err.message, true);
    closeSubmitModal();
  }
}

function closeSubmitModal() {
  submitOverlay.hidden = true;
  submitPlanId = null;
}

submitPreviewLink.addEventListener("click", () => {
  if (!submitPlanId) return;
  const planId = submitPlanId;
  closeSubmitModal();
  openPreview(planId);
});

submitClose.addEventListener("click", closeSubmitModal);
submitOverlay.addEventListener("click", (e) => {
  if (e.target === submitOverlay) closeSubmitModal();
});

submitForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!submitPlanId) return;
  setButtonLoading(submitConfirmBtn, true, "Submitting");
  try {
    await Api.submitLessonPlan(submitPlanId, submitSectionSelect.value);
    showToast("Lesson plan submitted to your teacher.");
    closeSubmitModal();
    const data = await Api.listLessonPlans();
    allPlans = data.lesson_plans || [];
    applyFilter();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(submitConfirmBtn, false);
  }
});

async function getFormatCached(formatId) {
  if (!formatCache[formatId]) {
    formatCache[formatId] = Api.getFormat(formatId).then((data) => data.format);
  }
  return formatCache[formatId];
}

// Cache of { html, matched_fields, unmatched_fields } per format id (or null
// when there's no usable reference file for it).
const templateHtmlCache = {};
let previewViewMode = "doc";

function planFieldListHtml(fmt, plan) {
  const fields = (fmt.fields || []).slice().sort((a, b) => a.sort_order - b.sort_order);
  let currentSection = undefined;
  let sectionsHtml = "";
  fields.forEach((field) => {
    if (field.section_group !== currentSection) {
      currentSection = field.section_group;
      if (currentSection) {
        sectionsHtml += `<div class="preview-section-title">${escapeHtml(currentSection)}</div>`;
      }
    }
    sectionsHtml += `
      <div class="preview-field">
        <div class="preview-field-label">${escapeHtml(field.label)}</div>
        ${renderPreviewValue(plan.field_values[field.field_key])}
      </div>`;
  });
  return sectionsHtml || `<p>This format has no fields defined.</p>`;
}

function planUnmatchedFieldListHtml(fmt, plan, keys) {
  if (!keys || !keys.length) return "";
  const items = keys
    .map((key) => {
      const field = (fmt.fields || []).find((f) => f.field_key === key);
      const label = field ? field.label : key;
      return `
        <div class="preview-field">
          <div class="preview-field-label">${escapeHtml(label)}</div>
          ${renderPreviewValue(plan.field_values[key])}
        </div>`;
    })
    .join("");
  return `<div class="preview-section-title">Not part of the printed template</div>${items}`;
}

// Fills a rendered document canvas with this plan's saved values and locks
// it read-only — this view is for reviewing a finished plan, not editing it.
function fillAndLockDocCanvas(plan) {
  const canvas = previewBody.querySelector(".lp-doc");
  if (!canvas) return;
  canvas.querySelectorAll("[data-field-key]").forEach((el) => {
    const value = plan.field_values[el.dataset.fieldKey];
    const text = Array.isArray(value) ? value.join("\n") : (value || "");
    if (text.trim()) {
      el.textContent = text;
      el.classList.add("lp-filled");
    }
    el.setAttribute("contenteditable", "false");
  });
}

function renderPlanPreviewModal(fmt, plan, templateData, docAvailable) {
  const dialogEl = previewOverlay.querySelector(".modal-dialog");
  dialogEl.classList.toggle("modal-dialog-doc", previewViewMode === "doc");

  const meta = `
    <div class="preview-meta">
      <span><strong>Lesson:</strong> ${escapeHtml(plan.subject || "\u2013")}</span>
      <span><strong>Grade:</strong> ${escapeHtml(plan.grade_level || "\u2013")}</span>
      <span><strong>Quarter:</strong> ${escapeHtml(plan.quarter || "\u2013")}</span>
      <span><strong>Date:</strong> ${escapeHtml(plan.date || "\u2013")}</span>
    </div>
    ${
      plan.status && plan.status !== "draft"
        ? `<div style="margin-bottom:14px; display:flex; gap:10px; align-items:center;"><span class="status-pill ${plan.status}">${statusLabel(plan.status)}</span>${plan.score != null ? `<span class="score-pill ${scoreTone(plan.score)}">${plan.score}/100</span>` : ""}</div>`
        : ""
    }
    ${plan.teacher_feedback ? `<div class="feedback-box"><strong>Teacher feedback:</strong> ${escapeHtml(plan.teacher_feedback)}</div>` : ""}`;

  const toolbar = docAvailable
    ? `<div class="doc-toolbar">
        <div class="doc-toolbar-views">
          <button type="button" class="doc-view-btn ${previewViewMode === "doc" ? "active" : ""}" data-view="doc">Document view</button>
          <button type="button" class="doc-view-btn ${previewViewMode === "list" ? "active" : ""}" data-view="list">Field list view</button>
        </div>
      </div>`
    : "";

  const warning =
    docAvailable && templateData.unmatched_fields.length
      ? `<div class="doc-warning"><strong>${templateData.unmatched_fields.length} field${templateData.unmatched_fields.length === 1 ? "" : "s"}</strong> couldn't be matched to a spot in the reference document, so they're shown separately below.</div>`
      : "";

  let content;
  if (previewViewMode === "doc") {
    content = `<div class="lp-doc-wrap">${templateData.html}</div>`;
    content += planUnmatchedFieldListHtml(fmt, plan, templateData.unmatched_fields);
  } else {
    content = planFieldListHtml(fmt, plan);
  }

  previewBody.innerHTML = meta + toolbar + warning + content;
  previewBody.querySelectorAll(".lp-doc-wrap").forEach(fitDocPage);

  previewBody.querySelectorAll(".doc-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.view === previewViewMode) return;
      previewViewMode = btn.dataset.view;
      renderPlanPreviewModal(fmt, plan, templateData, docAvailable);
    });
  });

  if (previewViewMode === "doc") fillAndLockDocCanvas(plan);
}

async function openPreview(planId) {
  document.getElementById("preview-title").textContent = "Lesson plan preview";
  previewBody.innerHTML = `<div class="preview-loading">Loading&hellip;</div>`;
  previewOverlay.hidden = false;

  try {
    const data = await Api.getLessonPlan(planId);
    const plan = data.lesson_plan;
    const fmt = await getFormatCached(plan.format_id);

    document.getElementById("preview-title").textContent = plan.title || "Lesson plan preview";

    let templateData = templateHtmlCache[fmt.id];
    if (templateData === undefined) {
      try {
        const tData = await Api.getFormatTemplateHtml(fmt.id);
        templateData = tData.html ? tData : null;
      } catch (err) {
        templateData = null;
      }
      templateHtmlCache[fmt.id] = templateData;
    }

    const docAvailable = !!templateData;
    previewViewMode = docAvailable ? "doc" : "list";
    renderPlanPreviewModal(fmt, plan, templateData, docAvailable);
  } catch (err) {
    previewBody.innerHTML = `<div class="preview-error">${escapeHtml(err.message)}</div>`;
  }
}

function closePreview() {
  previewOverlay.hidden = true;
  previewOverlay.querySelector(".modal-dialog").classList.remove("modal-dialog-doc");
}

previewClose.addEventListener("click", closePreview);
previewOverlay.addEventListener("click", (e) => {
  if (e.target === previewOverlay) closePreview();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !previewOverlay.hidden) closePreview();
});

// Status only means something on a student's own plans (a teacher's plans are
// never submitted), so that is the only place the filter shows.
function statusFilterApplies() {
  return activeTab === "mine" && currentUser && currentUser.role === "student";
}

function applyFilter() {
  const q = searchInput.value.trim().toLowerCase();
  statusFilterField.hidden = !statusFilterApplies();
  const status = statusFilterApplies() ? statusFilter.value : "";
  const filtered = allPlans.filter(
    (p) =>
      (!status || p.status === status) &&
      (!q || (p.title || "").toLowerCase().includes(q) || (p.subject || "").toLowerCase().includes(q))
  );
  renderPlans(sortPlans(filtered, sortSelect.value));
}

searchInput.addEventListener("input", applyFilter);
sortSelect.addEventListener("change", applyFilter);
statusFilter.addEventListener("change", applyFilter);

async function loadActiveTab() {
  errorBox.hidden = true;
  plansBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Loading&hellip;</td></tr>`;
  try {
    const data =
      activeTab === "mine" ? await Api.listLessonPlans() : await Api.publicLessonPlans();
    allPlans = data.lesson_plans || [];
    applyFilter();
  } catch (err) {
    plansBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Couldn't load lesson plans.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

tabSwitch.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === activeTab) return;
    activeTab = btn.dataset.tab;
    tabSwitch.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    loadActiveTab();
  });
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  currentUser = user;
  wireTopbar(user);
  await loadActiveTab();
}

init();
