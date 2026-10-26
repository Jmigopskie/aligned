const errorBox = document.getElementById("error-box");
const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const classGrid = document.getElementById("class-grid");
const joinForm = document.getElementById("join-form");
const joinCodeInput = document.getElementById("join-code");
const joinSubmitBtn = document.getElementById("join-submit-btn");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("my-classes");

function renderClasses(sections) {
  loadingState.hidden = true;
  if (!sections.length) {
    emptyState.hidden = false;
    classGrid.hidden = true;
    return;
  }
  emptyState.hidden = true;
  classGrid.hidden = false;
  classGrid.innerHTML = sections
    .map(
      (s) => `
      <div class="class-card" style="cursor:default;" data-section="${s.id}">
        <h3>${escapeHtml(s.name)}</h3>
        <div class="class-meta">Teacher: ${escapeHtml(s.teacher_name || "\u2013")}</div>
        <div style="margin-top:14px; display:flex; gap:8px;">
          <button class="btn btn-secondary" type="button" onclick="window.location.href='lesson-plan-list.html'">Submit a plan</button>
          <button class="btn btn-secondary danger" type="button" data-leave="${s.id}">Leave</button>
        </div>
      </div>`
    )
    .join("");

  classGrid.querySelectorAll("[data-leave]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Leave this class? You can rejoin later with the class code.")) return;
      try {
        await Api.leaveSection(btn.dataset.leave);
        showToast("You left the class.");
        loadClasses();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function loadClasses() {
  try {
    const data = await Api.listSections();
    renderClasses(data.sections || []);
  } catch (err) {
    loadingState.hidden = true;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

joinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = joinCodeInput.value.trim();
  if (!code) return;
  setButtonLoading(joinSubmitBtn, true, "Joining");
  try {
    const data = await Api.joinSection(code);
    showToast(`Joined ${data.section.name}!`);
    joinCodeInput.value = "";
    loadClasses();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(joinSubmitBtn, false);
  }
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "student") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  document.getElementById("points-balance").innerHTML = pointsBalanceHtml(user.points);
  document.getElementById("points-panel").hidden = false;
  loadClasses();
}

init();
