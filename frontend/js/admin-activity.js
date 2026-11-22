// The admin's activity log: who did what and when (GET /api/admin/activity).
const params = new URLSearchParams(window.location.search);
document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-activity");

const errorBox = document.getElementById("error-box");
const body = document.getElementById("activity-body");
const searchInput = document.getElementById("search-input");
const pagerInfo = document.getElementById("pager-info");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
let page = 1;
let searchTimer = null;

function when(iso) {
  return iso ? new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit",
  }) : "–";
}

function who(e) {
  if (!e.user_id) return '<span class="text-sm">Not signed in</span>';
  return `<strong>${escapeHtml(e.user_name || "–")}</strong><br><span class="text-sm">${escapeHtml(e.user_email || "")}${
    e.role ? ` · ${escapeHtml(e.role)}` : ""}</span>`;
}

async function load() {
  errorBox.hidden = true;
  const query = new URLSearchParams({ page: String(page), per_page: "50" });
  if (searchInput.value.trim()) query.set("q", searchInput.value.trim());
  if (params.get("user_id")) query.set("user_id", params.get("user_id"));
  try {
    const data = await apiFetch(`/api/admin/activity?${query}`);
    body.innerHTML = data.entries.length ? data.entries.map((e) => `
      <tr>
        <td data-label="When">${escapeHtml(when(e.created_at))}</td>
        <td data-label="Who">${who(e)}</td>
        <td data-label="Action">${escapeHtml(e.action)}</td>
        <td data-label="Details">${escapeHtml(e.detail || "–")}</td>
        <td data-label="IP address">${escapeHtml(e.ip || "–")}</td>
      </tr>`).join("") : '<tr class="table-empty-row"><td colspan="5">No activity matches.</td></tr>';
    pagerInfo.textContent = `${data.total} entr${data.total === 1 ? "y" : "ies"} · page ${data.page} of ${data.pages}`;
    prevBtn.disabled = data.page <= 1;
    nextBtn.disabled = data.page >= data.pages;
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

prevBtn.addEventListener("click", () => { page -= 1; load(); });
nextBtn.addEventListener("click", () => { page += 1; load(); });
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { page = 1; load(); }, 300);
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  if (params.has("q")) searchInput.value = params.get("q");
  load();
}

init();
