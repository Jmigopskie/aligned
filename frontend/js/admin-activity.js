// The admin's activity page: everyone with a summary of what they did, then
// one person's activity day by day (GET /api/admin/activity/people and
// /api/admin/activity?user_id=). ?user_id= in the address opens that person.
document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-activity");

const errorBox = document.getElementById("error-box");
const peopleView = document.getElementById("people-view");
const personView = document.getElementById("person-view");
const peopleBody = document.getElementById("people-body");
const searchInput = document.getElementById("search-input");
const roleFilter = document.getElementById("role-filter");
const timeline = document.getElementById("timeline");
let peoplePage = 1;
let timelinePage = 1;
let person = null; // the row from the people list, when one is open
let searchTimer = null;

const ROLE_LABEL = { student: "Student", teacher: "Teacher", admin: "Admin" };
const STATS = [["sign-in", "Sign-ins"], ["plan", "Lesson plans"], ["submit", "Submitted"],
  ["review", "Reviewed / rated"], ["download", "Downloads"]];

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function ago(iso) {
  if (!iso) return "Never";
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// ---- Everyone ----
async function loadPeople() {
  errorBox.hidden = true;
  const query = new URLSearchParams({ page: String(peoplePage) });
  if (searchInput.value.trim()) query.set("q", searchInput.value.trim());
  if (roleFilter.value) query.set("role", roleFilter.value);
  try {
    const data = await apiFetch(`/api/admin/activity/people?${query}`);
    peopleBody.innerHTML = data.people.length ? data.people.map((p) => `
      <tr class="activity-person-row" data-user="${p.user_id}" tabindex="0">
        <td data-label="Person"><strong>${escapeHtml(p.name || "–")}</strong><br>
          <span class="text-sm">${escapeHtml(p.email || "")} · ${ROLE_LABEL[p.role] || escapeHtml(p.role || "")}</span></td>
        <td data-label="Last active">${escapeHtml(ago(p.last_active))}</td>
        ${STATS.map(([kind, label]) => `<td class="num" data-label="${label}">${p.counts[kind] || "–"}</td>`).join("")}
        <td><button type="button" class="btn btn-secondary btn-sm" data-user="${p.user_id}">View activity</button></td>
      </tr>`).join("") : '<tr class="table-empty-row"><td colspan="8">No one matches.</td></tr>';
    peopleBody._people = data.people;
    document.getElementById("people-pager-info").textContent =
      `${data.total} ${data.total === 1 ? "person" : "people"} · page ${data.page} of ${data.pages}`;
    document.getElementById("people-prev").disabled = data.page <= 1;
    document.getElementById("people-next").disabled = data.page >= data.pages;
  } catch (err) {
    showError(err.message);
  }
}

function openFromRow(target) {
  const el = target.closest("[data-user]");
  if (!el) return;
  const row = (peopleBody._people || []).find((p) => String(p.user_id) === el.dataset.user);
  openPerson(Number(el.dataset.user), row, true);
}
peopleBody.addEventListener("click", (e) => openFromRow(e.target));
peopleBody.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches("tr[data-user]")) openFromRow(e.target);
});

// ---- One person ----
function dayLabel(iso) {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86400000);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

async function loadTimeline() {
  errorBox.hidden = true;
  const query = new URLSearchParams({ user_id: String(person.user_id), page: String(timelinePage), per_page: "50" });
  try {
    const data = await apiFetch(`/api/admin/activity?${query}`);
    const days = [];
    data.entries.forEach((e) => {
      const label = dayLabel(e.created_at);
      if (!days.length || days[days.length - 1].label !== label) days.push({ label, entries: [] });
      days[days.length - 1].entries.push(e);
    });
    timeline.innerHTML = days.length ? days.map((day) => `
      <section class="activity-day">
        <h3>${escapeHtml(day.label)}</h3>
        <ol>${day.entries.map((e) => `
          <li class="activity-item kind-${escapeHtml(e.kind || "account")}">
            <time datetime="${escapeHtml(e.created_at || "")}">${escapeHtml(new Date(e.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))}</time>
            <span class="activity-dot" aria-hidden="true"></span>
            <span class="activity-what"><strong>${escapeHtml(e.action)}</strong>${
              e.detail && !/@/.test(e.detail) ? `<span class="text-sm">${escapeHtml(e.detail)}</span>` : ""}${
              e.ip ? `<span class="activity-ip">IP ${escapeHtml(e.ip)}</span>` : ""}</span>
          </li>`).join("")}</ol>
      </section>`).join("") : '<p class="activity-empty">No activity yet.</p>';
    document.getElementById("pager-info").textContent =
      `${data.total} activit${data.total === 1 ? "y" : "ies"} · page ${data.page} of ${data.pages}`;
    document.getElementById("prev-btn").disabled = data.page <= 1;
    document.getElementById("next-btn").disabled = data.page >= data.pages;
  } catch (err) {
    showError(err.message);
  }
}

async function openPerson(userId, row, push) {
  if (!row) {
    // Opened from the address: find them in the people list.
    try {
      row = (await apiFetch(`/api/admin/activity/people?user_id=${userId}`)).people[0];
    } catch (err) { /* shown below as unknown */ }
  }
  person = row || { user_id: userId, name: "Unknown account", email: "", role: "", counts: {} };
  if (push) history.pushState({ userId }, "", `?user_id=${userId}`);
  document.getElementById("person-name").textContent = person.name || "–";
  document.getElementById("person-sub").textContent =
    [person.email, ROLE_LABEL[person.role], person.last_active ? `last active ${ago(person.last_active).toLowerCase()}` : ""]
      .filter(Boolean).join(" · ");
  document.getElementById("person-stats").innerHTML = STATS.map(([kind, label]) =>
    `<span class="person-stat"><strong>${(person.counts || {})[kind] || 0}</strong>${escapeHtml(label)}</span>`).join("");
  peopleView.hidden = true;
  personView.hidden = false;
  timelinePage = 1;
  loadTimeline();
  document.getElementById("back-btn").focus();
}

function showPeople(push) {
  person = null;
  if (push) history.pushState({}, "", location.pathname);
  personView.hidden = true;
  peopleView.hidden = false;
  loadPeople();
}

document.getElementById("back-btn").addEventListener("click", () => showPeople(true));
window.addEventListener("popstate", () => {
  const id = Number(new URLSearchParams(location.search).get("user_id"));
  if (id) openPerson(id, null, false);
  else showPeople(false);
});
document.getElementById("prev-btn").addEventListener("click", () => { timelinePage -= 1; loadTimeline(); });
document.getElementById("next-btn").addEventListener("click", () => { timelinePage += 1; loadTimeline(); });
document.getElementById("people-prev").addEventListener("click", () => { peoplePage -= 1; loadPeople(); });
document.getElementById("people-next").addEventListener("click", () => { peoplePage += 1; loadPeople(); });
roleFilter.addEventListener("change", () => { peoplePage = 1; loadPeople(); });
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { peoplePage = 1; loadPeople(); }, 300);
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  hydrateIcons();
  const id = Number(new URLSearchParams(location.search).get("user_id"));
  if (id) openPerson(id, null, false);
  else loadPeople();
}

init();
