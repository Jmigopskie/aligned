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
const videoInput = document.getElementById("announcement-video");
const videoCurrent = document.getElementById("announcement-video-current");
const videoName = document.getElementById("announcement-video-name");
const videoRemoveBtn = document.getElementById("announcement-video-remove");
const videoProgress = document.getElementById("announcement-video-progress");
const videoBar = document.getElementById("announcement-video-bar");
const videoPercent = document.getElementById("announcement-video-percent");
const MAX_VIDEO_MB = 500;

videoCurrent.querySelector("[data-icon]").innerHTML = Icons.video;

let allAnnouncements = [];
let uploading = false;

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
          ${a.has_video ? `<div class="video-tag">${Icons.video}<span>${escapeHtml(a.video_name || "Video")}</span></div>` : ""}
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

function showCurrentVideo(a) {
  const has = !!(a && a.has_video);
  videoCurrent.hidden = !has;
  videoName.textContent = has ? `${a.video_name || "Video"} (${Math.max(1, Math.round((a.video_size || 0) / 1048576))} MB)` : "";
}

function showProgress(fraction) {
  const pct = Math.round(fraction * 100);
  videoProgress.hidden = false;
  videoBar.style.transform = `scaleX(${fraction})`;
  videoPercent.textContent = `${pct}%`;
  submitBtn.textContent = `Uploading video ${pct}%`;
}

videoRemoveBtn.addEventListener("click", async () => {
  const id = idInput.value;
  if (!id || !confirm("Remove this video from the announcement?")) return;
  try {
    const data = await Api.adminDeleteAnnouncementVideo(id);
    showCurrentVideo(data.announcement);
    showToast("Video removed.");
    loadAnnouncements();
  } catch (err) {
    showToast(err.message, true);
  }
});

function openModal(a) {
  form.reset();
  videoProgress.hidden = true;
  showCurrentVideo(a);
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
  // Closing mid-upload would leave the video half sent with no sign of it.
  if (uploading) return;
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

  const video = videoInput.files[0] || null;
  if (video) {
    if (!/\.(mp4|webm)$/i.test(video.name)) {
      showToast("Choose an MP4 or WebM video.", true);
      return;
    }
    if (video.size > MAX_VIDEO_MB * 1024 * 1024) {
      showToast(`That video is over ${MAX_VIDEO_MB} MB. Use a shorter or smaller one.`, true);
      return;
    }
  }

  setButtonLoading(submitBtn, true, "Saving");
  let savedId = id;
  try {
    if (id) {
      await Api.adminUpdateAnnouncement(id, payload);
    } else {
      const data = await Api.adminCreateAnnouncement(payload);
      savedId = data.announcement.id;
      idInput.value = savedId;
    }
    if (video) {
      // Sent after the announcement exists, so a failed upload never loses
      // the text the admin wrote; they can attach the video again.
      uploading = true;
      showProgress(0);
      await Api.adminUploadAnnouncementVideo(savedId, video, showProgress);
    }
    showToast(video ? "Announcement and video saved." : "Announcement saved.");
    uploading = false;
    closeModal();
    loadAnnouncements();
  } catch (err) {
    uploading = false;
    showToast(video && savedId ? `The announcement was saved, but the video didn't upload: ${err.message}` : err.message, true);
    loadAnnouncements();
  } finally {
    uploading = false;
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
