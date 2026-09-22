document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-announcements");

const errorBox = document.getElementById("error-box");
const announcementsBody = document.getElementById("announcements-body");

const overlay = document.getElementById("announcement-overlay");
const modalTitle = document.getElementById("announcement-modal-title");
const form = document.getElementById("announcement-form");
const idInput = document.getElementById("announcement-id");
const titleInput = document.getElementById("announcement-title");
const messageInput = document.getElementById("announcement-message");
const typeSelect = document.getElementById("announcement-type");
const startsInput = document.getElementById("announcement-starts");
const endsInput = document.getElementById("announcement-ends");
const activeCheckbox = document.getElementById("announcement-active");
const submitBtn = document.getElementById("announcement-submit-btn");
const modalClose = document.getElementById("announcement-modal-close");

let allAnnouncements = [];

function fmtDateTime(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function typeLabel(type) {
  if (type === "maintenance") return "Maintenance";
  if (type === "urgent") return "Urgent";
  return "Info";
}

function windowLabel(a) {
  const start = fmtDateTime(a.starts_at);
  const end = fmtDateTime(a.ends_at);
  if (!start && !end) return "Always on";
  if (start && end) return `${start} \u2192 ${end}`;
  if (start) return `From ${start}`;
  return `Until ${end}`;
}

function isCurrentlyActive(a) {
  if (!a.is_active) return false;
  const now = new Date();
  if (a.starts_at && now < new Date(a.starts_at)) return false;
  if (a.ends_at && now > new Date(a.ends_at)) return false;
  return true;
}

function statusPill(a) {
  if (!a.is_active) return `<span class="status-pill draft">Off</span>`;
  if (isCurrentlyActive(a)) return `<span class="status-pill reviewed">Live</span>`;
  return `<span class="status-pill submitted">Scheduled</span>`;
}

function renderAnnouncements() {
  if (!allAnnouncements.length) {
    announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">No announcements yet.</td></tr>`;
    return;
  }

  announcementsBody.innerHTML = allAnnouncements
    .map(
      (a) => `
      <tr>
        <td>
          <strong>${escapeHtml(a.title)}</strong>
          <div class="text-sm" style="margin-top:2px;">${escapeHtml(a.message)}</div>
        </td>
        <td><span class="badge">${typeLabel(a.type)}</span></td>
        <td>${windowLabel(a)}</td>
        <td>${statusPill(a)}</td>
        <td>${escapeHtml(a.author_name || "\u2013")}</td>
        <td>
          <div class="row-actions">
            <button class="row-action-btn" type="button" data-action="edit" data-id="${a.id}" title="Edit" aria-label="Edit">${Icons.edit}</button>
            <button class="row-action-btn" type="button" data-action="toggle" data-id="${a.id}" data-active="${a.is_active}" title="${a.is_active ? "Turn off" : "Turn on"}" aria-label="Toggle active">${Icons.shield}</button>
            <button class="row-action-btn danger" type="button" data-action="delete" data-id="${a.id}" title="Delete" aria-label="Delete">${Icons.trash}</button>
          </div>
        </td>
      </tr>`
    )
    .join("");

  announcementsBody.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleAction(btn));
  });
}

async function loadAnnouncements() {
  announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Loading&hellip;</td></tr>`;
  try {
    const data = await Api.adminListAnnouncements();
    allAnnouncements = data.announcements || [];
    renderAnnouncements();
  } catch (err) {
    announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="6">Couldn't load announcements.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

async function handleAction(btn) {
  const id = btn.dataset.id;
  const action = btn.dataset.action;

  if (action === "edit") {
    const a = allAnnouncements.find((x) => String(x.id) === id);
    if (a) openModal(a);
    return;
  }

  if (action === "toggle") {
    const isActive = btn.dataset.active === "true";
    try {
      await Api.adminUpdateAnnouncement(id, { is_active: !isActive });
      showToast(isActive ? "Announcement turned off." : "Announcement turned on.");
      loadAnnouncements();
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }

  if (action === "delete") {
    if (!confirm("Delete this announcement permanently?")) return;
    try {
      await Api.adminDeleteAnnouncement(id);
      showToast("Announcement deleted.");
      loadAnnouncements();
    } catch (err) {
      showToast(err.message, true);
    }
  }
}

function toLocalInputValue(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function openModal(a) {
  form.reset();
  if (a) {
    modalTitle.textContent = "Edit announcement";
    idInput.value = a.id;
    titleInput.value = a.title;
    messageInput.value = a.message;
    typeSelect.value = a.type;
    startsInput.value = toLocalInputValue(a.starts_at);
    endsInput.value = toLocalInputValue(a.ends_at);
    activeCheckbox.checked = a.is_active;
  } else {
    modalTitle.textContent = "New announcement";
    idInput.value = "";
    typeSelect.value = "info";
    activeCheckbox.checked = true;
  }
  overlay.hidden = false;
}

function closeModal() {
  overlay.hidden = true;
}

document.getElementById("new-announcement-btn").addEventListener("click", () => openModal(null));
modalClose.addEventListener("click", closeModal);
overlay.addEventListener("click", (e) => {
  if (e.target === overlay) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !overlay.hidden) closeModal();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = idInput.value;
  const payload = {
    title: titleInput.value.trim(),
    message: messageInput.value.trim(),
    type: typeSelect.value,
    is_active: activeCheckbox.checked,
    starts_at: startsInput.value ? new Date(startsInput.value).toISOString() : null,
    ends_at: endsInput.value ? new Date(endsInput.value).toISOString() : null,
  };

  setButtonLoading(submitBtn, true, "Saving");
  try {
    if (id) {
      await Api.adminUpdateAnnouncement(id, payload);
    } else {
      await Api.adminCreateAnnouncement(payload);
    }
    showToast("Announcement saved.");
    closeModal();
    loadAnnouncements();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(submitBtn, false);
  }
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  loadAnnouncements();
}

init();
