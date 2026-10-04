document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("announcements");

const errorBox = document.getElementById("error-box");
const announcementsBody = document.getElementById("announcements-body");
const newAnnouncementBtn = document.getElementById("new-announcement-btn");
const actionsColHead = document.getElementById("actions-col-head");
const pageSubtitle = document.getElementById("page-subtitle");

const overlay = document.getElementById("announcement-overlay");
const modalTitle = document.getElementById("announcement-modal-title");
const form = document.getElementById("announcement-form");
const idInput = document.getElementById("announcement-id");
const titleInput = document.getElementById("announcement-title");
const messageInput = document.getElementById("announcement-message");
const audienceSelect = document.getElementById("announcement-audience");
const sectionWrap = document.getElementById("announcement-section-wrap");
const sectionSelect = document.getElementById("announcement-section");
const typeSelect = document.getElementById("announcement-type");
const startsInput = document.getElementById("announcement-starts");
const endsInput = document.getElementById("announcement-ends");
const activeCheckbox = document.getElementById("announcement-active");
const submitBtn = document.getElementById("announcement-submit-btn");
const modalClose = document.getElementById("announcement-modal-close");

let currentUser = null;
let allAnnouncements = [];
let mySections = [];

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
  if (start && end) return `${start} → ${end}`;
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

function audienceLabel(a) {
  return a.section_id ? escapeHtml(a.section_name || "A section") : "All";
}

function renderAnnouncements() {
  if (!allAnnouncements.length) {
    announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">No announcements yet.</td></tr>`;
    return;
  }

  announcementsBody.innerHTML = allAnnouncements
    .map((a) => {
      const canManage = currentUser && a.author_id === currentUser.id;
      return `
      <tr id="announcement-${a.id}">
        <td>
          <strong>${escapeHtml(a.title)}</strong>
          <div class="text-sm" style="margin-top:2px;">${escapeHtml(a.message)}</div>
          ${
            a.has_video
              ? `<video class="announcement-video" controls preload="none" playsinline src="${escapeHtml(a.video_url)}" aria-label="${escapeHtml(a.title)} video"></video>`
              : ""
          }
        </td>
        <td><span class="badge">${typeLabel(a.type)}</span></td>
        <td>${audienceLabel(a)}</td>
        <td>${windowLabel(a)}</td>
        <td>${statusPill(a)}</td>
        <td>${escapeHtml(a.author_name || "–")}</td>
        <td${actionsColHead.hidden ? " hidden" : ""}>
          ${
            canManage
              ? `<div class="row-actions">
                  <button class="row-action-btn" type="button" data-action="edit" data-id="${a.id}" title="Edit" aria-label="Edit">${Icons.edit}</button>
                  <button class="row-action-btn" type="button" data-action="toggle" data-id="${a.id}" data-active="${a.is_active}" title="${a.is_active ? "Turn off" : "Turn on"}" aria-label="Toggle active">${Icons.shield}</button>
                  <button class="row-action-btn danger" type="button" data-action="delete" data-id="${a.id}" title="Delete" aria-label="Delete">${Icons.trash}</button>
                </div>`
              : ""
          }
        </td>
      </tr>`;
    })
    .join("");

  announcementsBody.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleAction(btn));
  });
}

async function loadAnnouncements() {
  announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Loading&hellip;</td></tr>`;
  try {
    const data = await Api.myAnnouncements();
    allAnnouncements = data.announcements || [];
    renderAnnouncements();
    // Arriving from a banner's "Watch the video": the row only exists now.
    const target = location.hash && document.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView({ block: "center" });
  } catch (err) {
    announcementsBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Couldn't load announcements.</td></tr>`;
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
      await Api.updateAnnouncement(id, { is_active: !isActive });
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
      await Api.deleteAnnouncement(id);
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

function renderSectionOptions() {
  sectionSelect.innerHTML = mySections
    .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
    .join("");
}

function updateAudienceVisibility() {
  sectionWrap.hidden = audienceSelect.value !== "section";
}

audienceSelect.addEventListener("change", updateAudienceVisibility);

function openModal(a) {
  form.reset();
  if (a) {
    modalTitle.textContent = "Edit announcement";
    idInput.value = a.id;
    titleInput.value = a.title;
    messageInput.value = a.message;
    typeSelect.value = a.type;
    audienceSelect.value = a.section_id ? "section" : "all";
    if (a.section_id) sectionSelect.value = String(a.section_id);
    startsInput.value = toLocalInputValue(a.starts_at);
    endsInput.value = toLocalInputValue(a.ends_at);
    activeCheckbox.checked = a.is_active;
  } else {
    modalTitle.textContent = "New announcement";
    idInput.value = "";
    typeSelect.value = "info";
    audienceSelect.value = "all";
    activeCheckbox.checked = true;
  }
  updateAudienceVisibility();
  overlay.hidden = false;
}

function closeModal() {
  overlay.hidden = true;
}

newAnnouncementBtn.addEventListener("click", () => openModal(null));
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

  if (audienceSelect.value === "section" && !sectionSelect.value) {
    showToast("Create a section first, or choose \"All\" instead.", true);
    return;
  }

  const payload = {
    title: titleInput.value.trim(),
    message: messageInput.value.trim(),
    type: typeSelect.value,
    section_id: audienceSelect.value === "section" ? Number(sectionSelect.value) : null,
    is_active: activeCheckbox.checked,
    starts_at: startsInput.value ? new Date(startsInput.value).toISOString() : null,
    ends_at: endsInput.value ? new Date(endsInput.value).toISOString() : null,
  };

  setButtonLoading(submitBtn, true, "Saving");
  try {
    if (id) {
      await Api.updateAnnouncement(id, payload);
    } else {
      await Api.createAnnouncement(payload);
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
  currentUser = user;
  wireTopbar(user);

  if (user.role === "teacher") {
    newAnnouncementBtn.hidden = false;
    actionsColHead.hidden = false;
    pageSubtitle.textContent = "Notices from your school admin and other teachers, and a place to post your own.";
    try {
      const data = await Api.listSections();
      mySections = data.sections || [];
      renderSectionOptions();
      if (!mySections.length) {
        audienceSelect.querySelector('option[value="section"]').textContent = "My section only (create a section first)";
      }
    } catch (err) {
      mySections = [];
    }
  } else if (user.role === "student") {
    pageSubtitle.textContent = "Notices from your school admin and your teachers.";
  }

  loadAnnouncements();
}

init();
