document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-documents");

const errorBox = document.getElementById("error-box");
const plansBody = document.getElementById("plans-body");
const guidesBody = document.getElementById("guides-body");
const sectionsBody = document.getElementById("sections-body");
const planStatusFilter = document.getElementById("plan-status-filter");
const planSortSelect = document.getElementById("plan-sort-select");
const guideSubjectFilter = document.getElementById("guide-subject-filter");

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

function sortPlans(plans, sortBy) {
  const sorted = plans.slice();
  if (sortBy === "name") {
    sorted.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  } else if (sortBy === "score") {
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

let allPlans = [];

async function loadPlans() {
  plansBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Loading&hellip;</td></tr>`;
  try {
    const data = await Api.adminListLessonPlans(planStatusFilter.value || undefined);
    allPlans = data.lesson_plans || [];
    renderPlans();
  } catch (err) {
    plansBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Couldn't load lesson plans.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

function renderPlans() {
  const plans = sortPlans(allPlans, planSortSelect.value);
  if (!plans.length) {
    plansBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">No lesson plans found.</td></tr>`;
    return;
  }
  plansBody.innerHTML = plans
    .map(
      (p) => `
      <tr>
        <td>${escapeHtml(p.title)}</td>
        <td>${escapeHtml(p.author_name || "\u2013")}</td>
        <td>${escapeHtml(p.section_name || "\u2013")}</td>
        <td><span class="status-pill ${p.status}">${statusLabel(p.status)}</span></td>
        <td>${p.score != null ? `<span class="score-pill ${scoreTone(p.score)}">${p.score}/100</span>` : "\u2013"}</td>
        <td>${fmtDate(p.updated_at)}</td>
        <td>
          <div class="row-actions">
            <button class="row-action-btn danger" type="button" data-action="delete" data-id="${p.id}" title="Delete" aria-label="Delete">${Icons.trash}</button>
          </div>
        </td>
      </tr>`
    )
    .join("");

  plansBody.querySelectorAll('[data-action="delete"]').forEach((btn) => {
    btn.addEventListener("click", () => deletePlan(btn.dataset.id));
  });
}

async function deletePlan(id) {
  if (!confirm("Delete this lesson plan permanently? This can't be undone.")) return;
  try {
    await Api.adminDeleteLessonPlan(id);
    showToast("Lesson plan deleted.");
    loadPlans();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadGuides() {
  guidesBody.innerHTML = `<tr class="table-empty-row"><td colspan="4">Loading&hellip;</td></tr>`;
  try {
    const data = await Api.adminListCourseGuides(guideSubjectFilter.value.trim());
    const guides = data.course_guides || [];
    if (!guides.length) {
      guidesBody.innerHTML = `<tr class="table-empty-row"><td colspan="4">No course guides found.</td></tr>`;
      return;
    }
    guidesBody.innerHTML = guides
      .map(
        (g) => `
        <tr>
          <td>${escapeHtml(g.title)}</td>
          <td>${escapeHtml(g.subject)}</td>
          <td>${escapeHtml(g.uploaded_by || "\u2013")}</td>
          <td>${fmtDate(g.created_at)}</td>
        </tr>`
      )
      .join("");
  } catch (err) {
    guidesBody.innerHTML = `<tr class="table-empty-row"><td colspan="4">Couldn't load course guides.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

async function loadSections() {
  sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Loading&hellip;</td></tr>`;
  try {
    const data = await Api.adminListSections();
    const sections = data.sections || [];
    if (!sections.length) {
      sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">No sections found.</td></tr>`;
      return;
    }
    sectionsBody.innerHTML = sections
      .map(
        (s) => `
        <tr>
          <td>${escapeHtml(s.name)}</td>
          <td>${escapeHtml(s.teacher_name || "\u2013")}</td>
          <td>${escapeHtml(s.subject || "\u2013")}</td>
          <td>${s.student_count}</td>
          <td><span class="join-code-chip">${escapeHtml(s.join_code)}</span></td>
          <td>${fmtDate(s.created_at)}</td>
        </tr>`
      )
      .join("");
  } catch (err) {
    sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Couldn't load sections.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

// ---- Tabs ----

const tabButtons = document.querySelectorAll("#doc-tabs button");
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach((panel) => (panel.hidden = true));
    document.getElementById(`tab-panel-${btn.dataset.tab}`).hidden = false;
  });
});

planStatusFilter.addEventListener("change", loadPlans);
planSortSelect.addEventListener("change", renderPlans);
let guideSearchTimer = null;
guideSubjectFilter.addEventListener("input", () => {
  clearTimeout(guideSearchTimer);
  guideSearchTimer = setTimeout(loadGuides, 300);
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);

  try {
    await Promise.all([loadPlans(), loadGuides(), loadSections()]);
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

init();
