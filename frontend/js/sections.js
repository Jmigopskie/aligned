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

  pointsError.hidden = true;
  pointsBulk.hidden = true;
  try {
    // Balances load beside the roster; a roster still shows if they can't.
    const [data, points] = await Promise.all([
      Api.getSection(sectionId),
      Api.sectionPoints(sectionId).catch(() => null),
    ]);
    const section = data.section;
    detailTitle.textContent = section.name;
    detailCode.textContent = section.join_code;
    balances = new Map(((points && points.students) || []).map((s) => [String(s.id), s.points]));

    const students = section.students || [];
    if (!students.length) {
      rosterList.innerHTML = `<p class="text-sm">No students have joined yet.</p>`;
    } else {
      const withPoints = !!points;
      pointsBulk.hidden = !withPoints;
      rosterList.innerHTML = students
        .map((m) => {
          const id = escapeHtml(String(m.student_id));
          const name = escapeHtml(m.student_name || "this student");
          return `
          <div class="roster-row${withPoints ? " roster-row-points" : ""}">
            ${withPoints ? `<input type="checkbox" class="points-pick" data-pick="${id}" aria-label="Select ${name}" />` : ""}
            <div class="roster-who">
              <strong>${escapeHtml(m.student_name || "")}</strong>
              <span>${escapeHtml(m.student_email || "")} &middot; joined ${fmtDate(m.joined_at)}</span>
            </div>
            ${withPoints ? `
            <span class="points-count" data-balance="${id}"></span>
            <form class="points-give" data-give="${id}">
              <label class="sr-only" for="give-${id}">Points to give ${name}</label>
              <input type="number" id="give-${id}" class="points-amount" value="30" min="1" step="1" inputmode="numeric" />
              <button class="btn btn-secondary btn-sm" type="submit">Give</button>
            </form>` : ""}
            <button class="row-action-btn danger" type="button" data-student="${id}" title="Remove student" aria-label="Remove ${name} from the section">${Icons.trash}</button>
          </div>`;
        })
        .join("");
      paintBalances();
      syncPicks();

      rosterList.querySelectorAll("form[data-give]").forEach((form) => {
        form.addEventListener("submit", (e) => {
          e.preventDefault();
          give([form.dataset.give], amountOf(form.querySelector("input")), form.querySelector("button"));
        });
      });
      rosterList.querySelectorAll(".points-pick").forEach((box) => box.addEventListener("change", syncPicks));

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

// ---- Points: each lesson plan a student starts uses 30; the teacher gives them ----
const pointsBulk = document.getElementById("points-bulk");
const pointsError = document.getElementById("points-error");
const selectAll = document.getElementById("points-select-all");
const bulkAmount = document.getElementById("points-bulk-amount");
const giveSelectedBtn = document.getElementById("points-give-selected");
const removeSelectedBtn = document.getElementById("points-remove-selected");
let balances = new Map();

function paintBalances() {
  rosterList.querySelectorAll("[data-balance]").forEach((el) => {
    const n = balances.get(el.dataset.balance) || 0;
    el.innerHTML = `<strong>${n}</strong> pt${n === 1 ? "" : "s"}`;
    el.classList.toggle("is-short", n < POINTS_PER_PLAN);
    el.title = n < POINTS_PER_PLAN ? "Not enough for a Building Proficiency plan" : `Enough for ${Math.floor(n / POINTS_PER_PLAN)} Building Proficiency plan(s)`;
  });
}

function picked() {
  return [...rosterList.querySelectorAll(".points-pick:checked")].map((b) => b.dataset.pick);
}

function syncPicks() {
  const all = rosterList.querySelectorAll(".points-pick");
  const n = picked().length;
  selectAll.checked = n > 0 && n === all.length;
  selectAll.indeterminate = n > 0 && n < all.length;
  giveSelectedBtn.disabled = removeSelectedBtn.disabled = n === 0;
  giveSelectedBtn.textContent = n ? `Give to ${n} selected` : "Give to selected";
}

function amountOf(input) {
  const n = Math.floor(Number(input.value));
  return n > 0 ? n : 0;
}

async function give(ids, add, btn) {
  pointsError.hidden = true;
  if (!add) {
    pointsError.textContent = "Enter a number of points above 0.";
    pointsError.hidden = false;
    return;
  }
  if (btn) setButtonLoading(btn, true, add > 0 ? "Giving" : "Removing");
  try {
    const data = await Api.givePoints(currentSectionId, ids, add);
    balances = new Map((data.students || []).map((s) => [String(s.id), s.points]));
    paintBalances();
    const who = ids.length === 1 ? "1 student" : `${ids.length} students`;
    showToast(add > 0 ? `Gave ${add} points to ${who}.` : `Removed ${-add} points from ${who}.`);
  } catch (err) {
    pointsError.textContent = err.message;
    pointsError.hidden = false;
  } finally {
    if (btn) setButtonLoading(btn, false);
    syncPicks();
  }
}

selectAll.addEventListener("change", () => {
  rosterList.querySelectorAll(".points-pick").forEach((b) => { b.checked = selectAll.checked; });
  syncPicks();
});
giveSelectedBtn.addEventListener("click", () => give(picked(), amountOf(bulkAmount), giveSelectedBtn));
removeSelectedBtn.addEventListener("click", () => give(picked(), -amountOf(bulkAmount), removeSelectedBtn));

document.getElementById("new-section-btn").addEventListener("click", openCreateModal);
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
