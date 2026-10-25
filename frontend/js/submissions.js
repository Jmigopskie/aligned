const errorBox = document.getElementById("error-box");
const sectionSelect = document.getElementById("section-select");
const statusSelect = document.getElementById("status-select");
const sortSelect = document.getElementById("sort-select");
const noSectionsState = document.getElementById("no-sections-state");
const submissionsList = document.getElementById("submissions-list");

const reviewOverlay = document.getElementById("review-overlay");
const reviewTitle = document.getElementById("review-title");
const reviewBody = document.getElementById("review-body");
const reviewClose = document.getElementById("review-close");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("submissions");

const formatCache = {};

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
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

function sortPlans(plans, sortBy) {
  const sorted = plans.slice();
  if (sortBy === "name") {
    sorted.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  } else if (sortBy === "score") {
    // Higher score first; ungraded submissions (no score yet) sink to the bottom.
    sorted.sort((a, b) => {
      const aScore = a.score == null ? -1 : a.score;
      const bScore = b.score == null ? -1 : b.score;
      return bScore - aScore;
    });
  } else {
    sorted.sort((a, b) => new Date(b.submitted_at || b.updated_at) - new Date(a.submitted_at || a.updated_at));
  }
  return sorted;
}

async function getFormatCached(formatId) {
  if (!formatCache[formatId]) {
    formatCache[formatId] = Api.getFormat(formatId).then((data) => data.format);
  }
  return formatCache[formatId];
}

function renderPreviewValue(value) {
  if (Array.isArray(value)) {
    const items = value.filter((v) => String(v).trim());
    if (!items.length) return `<div class="preview-field-value">\u2013</div>`;
    return `<ul class="preview-field-value">${items
      .map((v) => `<li>${escapeHtml(String(v))}</li>`)
      .join("")}</ul>`;
  }
  const text = value == null ? "" : String(value).trim();
  return `<div class="preview-field-value">${escapeHtml(text) || "\u2013"}</div>`;
}

async function loadSectionOptions() {
  const data = await Api.listSections();
  const sections = data.sections || [];

  if (!sections.length) {
    noSectionsState.hidden = false;
    sectionSelect.parentElement.parentElement.hidden = true;
    submissionsList.innerHTML = "";
    return null;
  }

  sectionSelect.innerHTML = sections
    .map((s) => `<option value="${s.id}">${escapeHtml(s.name)} (${s.pending_count} pending)</option>`)
    .join("");
  return sections;
}

let currentPlans = [];

async function loadSubmissions() {
  const sectionId = sectionSelect.value;
  if (!sectionId) return;
  const status = statusSelect.value;

  submissionsList.innerHTML = `<p class="text-sm">Loading&hellip;</p>`;
  try {
    const data = await Api.sectionSubmissions(sectionId, status);
    currentPlans = data.lesson_plans || [];
    renderSubmissions(sortPlans(currentPlans, sortSelect.value));
  } catch (err) {
    submissionsList.innerHTML = "";
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

function renderSubmissions(plans) {
  if (!plans.length) {
    submissionsList.innerHTML = `<div class="empty-state"><h2>Nothing here yet</h2><p>Submitted lesson plans for this section will show up here.</p></div>`;
    return;
  }

  submissionsList.innerHTML = plans
    .map(
      (p) => `
      <div class="submission-card">
        <div class="submission-card-header">
          <div>
            <h3>${escapeHtml(p.title)}</h3>
            <div class="submission-meta">By ${escapeHtml(p.author_name || "\u2013")} &middot; ${escapeHtml(p.subject || "\u2013")} &middot; submitted ${fmtDate(p.submitted_at)}</div>
          </div>
          <span class="status-pill ${p.status}">${statusLabel(p.status)}</span>
        </div>
        ${p.score != null ? `<div class="score-row"><span class="score-pill ${scoreTone(p.score)}">${p.score}/100</span></div>` : ""}
        ${p.teacher_feedback ? `<div class="feedback-box"><strong>Your feedback:</strong> ${escapeHtml(p.teacher_feedback)}</div>` : ""}
        <div class="row-actions" style="margin-top:12px;">
          <button class="btn btn-secondary" type="button" data-action="review" data-plan="${p.id}">Open &amp; review</button>
          <button class="btn btn-secondary" type="button" data-action="export" data-plan="${p.id}" data-title="${escapeHtml(p.title || "")}">Download</button>
        </div>
      </div>`
    )
    .join("");

  submissionsList.querySelectorAll("[data-action='review']").forEach((btn) => {
    btn.addEventListener("click", () => openReview(btn.dataset.plan));
  });
  submissionsList.querySelectorAll("[data-action='export']").forEach((btn) => {
    btn.addEventListener("click", () => {
      exportPlan(btn.dataset.plan, btn.dataset.title);
    });
  });
}

async function openReview(planId) {
  reviewTitle.textContent = "Loading\u2026";
  reviewBody.innerHTML = `<div class="preview-loading">Loading&hellip;</div>`;
  reviewOverlay.hidden = false;

  try {
    const data = await Api.getLessonPlan(planId);
    const plan = data.lesson_plan;
    const fmt = await getFormatCached(plan.format_id);

    reviewTitle.textContent = plan.title || "Lesson plan";

    const meta = `
      <div class="preview-meta">
        <span><strong>By:</strong> ${escapeHtml(plan.author_name || "\u2013")}</span>
        <span><strong>Grade:</strong> ${escapeHtml(plan.grade_level || "\u2013")}</span>
        <span><strong>Quarter:</strong> ${escapeHtml(plan.quarter || "\u2013")}</span>
        <span><strong>Date:</strong> ${escapeHtml(plan.date || "\u2013")}</span>
        <span><strong>Status:</strong> ${statusLabel(plan.status)}</span>
      </div>`;

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

    const feedbackForm = `
      <div style="margin-top:22px; padding-top:18px; border-top:1px solid var(--border);">
        <div class="field" style="max-width:160px;">
          <label for="score-input">Score (1&ndash;100)</label>
          <input type="number" id="score-input" min="1" max="100" step="1" placeholder="e.g. 92" value="${plan.score != null ? plan.score : ""}" />
        </div>
        <div class="field">
          <label for="feedback-input">Feedback for the student</label>
          <textarea id="feedback-input" rows="4" placeholder="What should they revise or improve?">${escapeHtml(plan.teacher_feedback || "")}</textarea>
        </div>
        <button class="btn btn-primary" type="button" id="mark-reviewed-btn" data-plan="${plan.id}">Mark as reviewed</button>
      </div>`;

    reviewBody.innerHTML = meta + (sectionsHtml || `<p>This format has no fields defined.</p>`) + feedbackForm;

    document.getElementById("mark-reviewed-btn").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const feedback = document.getElementById("feedback-input").value.trim();
      const scoreValue = document.getElementById("score-input").value;

      if (scoreValue === "") {
        showToast("Give this lesson plan a score from 1 to 100.", true);
        return;
      }
      const score = Number(scoreValue);
      if (!Number.isInteger(score) || score < 1 || score > 100) {
        showToast("Score must be a whole number from 1 to 100.", true);
        return;
      }

      setButtonLoading(btn, true, "Saving");
      try {
        await Api.reviewLessonPlan(plan.id, feedback, score);
        showToast("Feedback sent to student.");
        closeReview();
        loadSubmissions();
      } catch (err) {
        showToast(err.message, true);
      } finally {
        setButtonLoading(btn, false);
      }
    });
  } catch (err) {
    reviewBody.innerHTML = `<div class="preview-error">${escapeHtml(err.message)}</div>`;
  }
}

function closeReview() {
  reviewOverlay.hidden = true;
}

reviewClose.addEventListener("click", closeReview);
reviewOverlay.addEventListener("click", (e) => {
  if (e.target === reviewOverlay) closeReview();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !reviewOverlay.hidden) closeReview();
});

sectionSelect.addEventListener("change", loadSubmissions);
statusSelect.addEventListener("change", loadSubmissions);
sortSelect.addEventListener("change", () => renderSubmissions(sortPlans(currentPlans, sortSelect.value)));

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "teacher") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);

  try {
    const sections = await loadSectionOptions();
    if (sections) loadSubmissions();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

init();
