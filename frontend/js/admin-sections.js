// Admin oversight of every class across all teachers, with bulk archive.
// Deliberately the same shape as admin-users.js — same filters, same checkbox
// selection through initBulkSelect(), same archive semantics (is_active on the
// row) — so the two admin tables behave identically.
const initialFilters = new URLSearchParams(window.location.search);

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-sections");

const errorBox = document.getElementById("error-box");
const sectionsBody = document.getElementById("sections-body");
const statusFilter = document.getElementById("status-filter");
const searchInput = document.getElementById("search-input");

let searchTimer = null;
let allSections = [];
// Assigned below, once the table body exists. Declared here because
// renderSections() guards on it and would otherwise hit the temporal dead zone
// of a later declaration instead of seeing undefined.
let bulk = null;

function fmtDate(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function renderSections(sections) {
  if (!sections.length) {
    sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="9">${
      statusFilter.value === "0" ? "No archived sections." : "No sections match."
    }</td></tr>`;
    if (bulk) bulk.sync();
    return;
  }

  sectionsBody.innerHTML = sections
    .map(
      (s) => `
      <tr>
        ${bulkCheckboxCell(s.id, s.name)}
        <td>${escapeHtml(s.name)}</td>
        <td>${escapeHtml(s.teacher_name || "–")}</td>
        <td>${escapeHtml(s.subject || "–")}</td>
        <td>${escapeHtml(s.grade_level || "–")}</td>
        <td>${s.student_count == null ? "–" : s.student_count}</td>
        <td>${
          s.is_active
            ? `<span class="status-pill reviewed">Active</span>`
            : `<span class="status-pill draft">Archived</span>`
        }</td>
        <td>${fmtDate(s.created_at)}</td>
        <td>
          <div class="row-actions">
            <button class="row-action-btn" type="button" data-action="toggle" data-id="${s.id}"
                    data-active="${s.is_active}" title="${s.is_active ? "Archive" : "Restore"}"
                    aria-label="${s.is_active ? "Archive" : "Restore"} ${escapeHtml(s.name)}">${
              s.is_active ? Icons.archive : Icons.upload
            }</button>
          </div>
        </td>
      </tr>`
    )
    .join("");

  sectionsBody.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleAction(btn));
  });

  // Rows were just replaced, so re-apply whatever is still selected.
  if (bulk) bulk.sync();
}

async function loadSections() {
  sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="9">Loading&hellip;</td></tr>`;
  try {
    const params = {};
    if (statusFilter.value) params.active = statusFilter.value;
    if (searchInput.value.trim()) params.q = searchInput.value.trim();

    // Mirror the filters into the address bar so the view can be linked and
    // reloaded. replaceState, not pushState: typing in the search box
    // shouldn't bury the previous page under a dozen history entries.
    const qs = new URLSearchParams(params).toString();
    history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);

    const data = await Api.adminListSections(params);
    allSections = data.sections || [];
    renderSections(allSections);
  } catch (err) {
    sectionsBody.innerHTML = `<tr class="table-empty-row"><td colspan="9">Couldn't load sections.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

// The single-row button goes through the same bulk endpoint as the batch, so
// there is only one path that changes a section's archived state.
async function handleAction(btn) {
  if (btn.dataset.action !== "toggle") return;
  const id = Number(btn.dataset.id);
  const isActive = btn.dataset.active === "true";

  const prompt = isActive
    ? "Archive this section? Students and submissions are kept, but it stops appearing in class lists and can no longer be joined."
    : "Restore this section? It will appear in class lists again and can be joined with its code.";
  if (!confirm(prompt)) return;

  try {
    const result = await Api.adminBulkArchive("sections", [id], !isActive);
    const skipped = (result.skipped || [])[0];
    if (skipped) showToast(skipped.reason, true);
    else showToast(isActive ? "Section archived." : "Section restored.");
    loadSections();
  } catch (err) {
    showToast(err.message, true);
  }
}

bulk = initBulkSelect({
  kind: "sections",
  tbody: sectionsBody,
  selectAllEl: document.getElementById("bulk-select-all"),
  barEl: document.getElementById("bulk-bar"),
  countEl: document.getElementById("bulk-count"),
  archiveBtn: document.getElementById("bulk-archive-btn"),
  restoreBtn: document.getElementById("bulk-restore-btn"),
  clearBtn: document.getElementById("bulk-clear-btn"),
  onApplied: () => loadSections(),
});

statusFilter.addEventListener("change", loadSections);
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadSections, 300);
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);

  if (initialFilters.has("active")) statusFilter.value = initialFilters.get("active");
  if (initialFilters.has("q")) searchInput.value = initialFilters.get("q");

  loadSections();
}

init();
