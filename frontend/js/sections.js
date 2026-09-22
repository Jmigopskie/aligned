const errorBox = document.getElementById("error-box");
const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const sectionGrid = document.getElementById("section-grid");

const createOverlay = document.getElementById("create-overlay");
const createForm = document.getElementById("create-form");
const createSubmitBtn = document.getElementById("create-submit-btn");

const detailOverlay = document.getElementById("detail-overlay");
const detailTitle = document.getElementById("detail-title");
const detailCode = document.getElementById("detail-code");
const rosterList = document.getElementById("roster-list");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("sections");

let currentSectionId = null;

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function openCreateModal() {
  createForm.reset();
  createOverlay.hidden = false;
}
function closeCreateModal() {
  createOverlay.hidden = true;
}

function renderSections(sections) {
  loadingState.hidden = true;
  if (!sections.length) {
    emptyState.hidden = false;
    sectionGrid.hidden = true;
    return;
  }
  emptyState.hidden = true;
  sectionGrid.hidden = false;
  sectionGrid.innerHTML = sections
    .map(
      (s) => `
      <div class="class-card" data-section="${s.id}">
        <h3>${escapeHtml(s.name)}</h3>
        <div class="join-code-chip">${escapeHtml(s.join_code)}</div>
        <div class="class-stats" style="margin-top:14px;">
          <div><strong>${s.student_count}</strong>students</div>
          <div><strong>${s.pending_count}</strong>pending</div>
        </div>
      </div>`
    )
    .join("");

  sectionGrid.querySelectorAll(".class-card").forEach((card) => {
    card.addEventListener("click", () => openDetail(card.dataset.section));
  });
}

async function loadSections() {
  try {
    const data = await Api.listSections();
    renderSections(data.sections || []);
  } catch (err) {
    loadingState.hidden = true;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

async function openDetail(sectionId) {
  currentSectionId = sectionId;
  detailTitle.textContent = "Loading\u2026";
  detailCode.textContent = "\u2013";
  rosterList.innerHTML = "";
  detailOverlay.hidden = false;

  try {
    const data = await Api.getSection(sectionId);
    const section = data.section;
    detailTitle.textContent = section.name;
    detailCode.textContent = section.join_code;

    const students = section.students || [];
    if (!students.length) {
      rosterList.innerHTML = `<p class="text-sm">No students have joined yet.</p>`;
    } else {
      rosterList.innerHTML = students
        .map(
          (m) => `
          <div class="roster-row">
            <div class="roster-who">
              <strong>${escapeHtml(m.student_name || "")}</strong>
              <span>${escapeHtml(m.student_email || "")} &middot; joined ${fmtDate(m.joined_at)}</span>
            </div>
            <button class="row-action-btn danger" type="button" data-student="${m.student_id}" title="Remove student" aria-label="Remove student">${Icons.trash}</button>
          </div>`
        )
        .join("");

      rosterList.querySelectorAll("[data-student]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!confirm("Remove this student from the section?")) return;
          try {
            await Api.removeStudent(currentSectionId, btn.dataset.student);
            showToast("Student removed.");
            openDetail(currentSectionId);
            loadSections();
          } catch (err) {
            showToast(err.message, true);
          }
        });
      });
    }
  } catch (err) {
    detailTitle.textContent = "Section";
    rosterList.innerHTML = `<p class="text-sm">${escapeHtml(err.message)}</p>`;
  }
}

function closeDetail() {
  detailOverlay.hidden = true;
  currentSectionId = null;
}

document.getElementById("new-section-btn").addEventListener("click", openCreateModal);
document.getElementById("empty-new-section-btn").addEventListener("click", openCreateModal);
document.getElementById("create-close").addEventListener("click", closeCreateModal);
createOverlay.addEventListener("click", (e) => {
  if (e.target === createOverlay) closeCreateModal();
});

document.getElementById("detail-close").addEventListener("click", closeDetail);
detailOverlay.addEventListener("click", (e) => {
  if (e.target === detailOverlay) closeDetail();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!createOverlay.hidden) closeCreateModal();
  if (!detailOverlay.hidden) closeDetail();
});

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("section-name").value.trim(),
  };
  setButtonLoading(createSubmitBtn, true, "Creating");
  try {
    await Api.createSection(payload);
    showToast("Section created.");
    closeCreateModal();
    loadSections();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(createSubmitBtn, false);
  }
});

document.getElementById("regen-code-btn").addEventListener("click", async () => {
  if (!currentSectionId) return;
  try {
    const data = await Api.regenerateSectionCode(currentSectionId);
    detailCode.textContent = data.section.join_code;
    showToast("New join code generated.");
    loadSections();
  } catch (err) {
    showToast(err.message, true);
  }
});

document.getElementById("delete-section-btn").addEventListener("click", async () => {
  if (!currentSectionId) return;
  if (!confirm("Delete this section? Students will lose access and their submissions will be unlinked.")) return;
  try {
    await Api.deleteSection(currentSectionId);
    showToast("Section deleted.");
    closeDetail();
    loadSections();
  } catch (err) {
    showToast(err.message, true);
  }
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "teacher") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  loadSections();
}

init();
