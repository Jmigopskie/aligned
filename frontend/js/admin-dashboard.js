document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-dashboard");

const errorBox = document.getElementById("error-box");

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function statusLabel(status) {
  if (status === "submitted") return "Pending review";
  if (status === "reviewed") return "Reviewed";
  return "Draft";
}

async function loadStats() {
  const data = await Api.adminStats();
  const s = data.stats;
  document.getElementById("stat-teachers").textContent = s.teachers;
  document.getElementById("stat-students").textContent = s.students;
  document.getElementById("stat-sections").textContent = s.sections;
  document.getElementById("stat-plans").textContent = s.lesson_plans;
  document.getElementById("stat-guides").textContent = s.course_guides;
  document.getElementById("stat-submitted").textContent = s.submitted;
}

async function loadSections() {
  const el = document.getElementById("sections-list");
  const data = await Api.adminListSections();
  const sections = data.sections || [];
  if (!sections.length) {
    el.innerHTML = `<p class="text-sm">No sections have been created yet.</p>`;
    return;
  }
  el.innerHTML = sections
    .slice(0, 8)
    .map(
      (s) => `
      <div class="roster-row">
        <div class="roster-who">
          <strong>${escapeHtml(s.name)}</strong>
          <span>${escapeHtml(s.teacher_name || "\u2013")} &middot; ${s.student_count} students</span>
        </div>
        <span class="join-code-chip">${escapeHtml(s.join_code)}</span>
      </div>`
    )
    .join("");
}

async function loadPlans() {
  const el = document.getElementById("plans-list");
  const data = await Api.adminListLessonPlans();
  const plans = (data.lesson_plans || []).slice(0, 8);
  if (!plans.length) {
    el.innerHTML = `<p class="text-sm">No lesson plans yet.</p>`;
    return;
  }
  el.innerHTML = plans
    .map(
      (p) => `
      <div class="roster-row">
        <div class="roster-who">
          <strong>${escapeHtml(p.title)}</strong>
          <span>${escapeHtml(p.author_name || "\u2013")} &middot; ${fmtDate(p.updated_at)}</span>
        </div>
        <span class="status-pill ${p.status}">${statusLabel(p.status)}</span>
      </div>`
    )
    .join("");
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);

  try {
    await Promise.all([loadStats(), loadSections(), loadPlans()]);
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

init();
