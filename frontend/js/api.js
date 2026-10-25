const API_URL = (() => {
  const { protocol, hostname, port } = window.location;
  if (protocol === "file:") return "http://127.0.0.1:5000";
  // Local dev convenience: a static file server (e.g. VS Code Live Server on
  // 5500) serving the frontend separately from the Flask backend on 5000.
  if (port === "5500") return `${protocol}//${hostname}:5000`;
  // Everywhere else the page is being served BY the Flask app itself —
  // whether that's direct access on :5000 or through a reverse proxy on the
  // standard 80/443 ports — so the API is always same-origin.
  return "";
})();

// Built from the id, never taken from stored markup, so a saved plan can't point
// an <img> anywhere else.
function docImageUrl(id) {
  return `${API_URL}/api/images/${encodeURIComponent(id)}`;
}

class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.status = status;
    // The parsed error body, for callers that need more than the message
    // (a stale-save 409 carries the newer plan).
    this.data = data;
  }
}

async function apiFetch(path, options = {}) {
  const opts = {
    credentials: "include",
    headers: {},
    ...options,
  };

  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
  }

  let response;
  try {
    response = await fetch(`${API_URL}${path}`, opts);
  } catch (err) {
    throw new ApiError(
      "Can't reach the server. Check that the backend is running.",
      0
    );
  }

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      data = null;
    }
  }

  if (!response.ok) {
    const message =
      (data && data.message) || `Request failed (${response.status}).`;
    throw new ApiError(message, response.status, data);
  }

  return data;
}

const Api = {

  signup: (payload) =>
    apiFetch("/api/signup", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload) =>
    apiFetch("/api/login", { method: "POST", body: JSON.stringify(payload) }),
  logout: () => apiFetch("/api/logout", { method: "POST" }),
  forgotPassword: (email) =>
    apiFetch("/api/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (payload) =>
    apiFetch("/api/reset-password", { method: "POST", body: JSON.stringify(payload) }),
  me: () => apiFetch("/api/me"),
  markOnboarded: () => apiFetch("/api/me/onboarded", { method: "POST" }),
  updateMe: (payload) =>
    apiFetch("/api/me", { method: "PATCH", body: JSON.stringify(payload) }),
  changePassword: (currentPassword, newPassword) =>
    apiFetch("/api/me/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  uploadAvatar: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/me/avatar", { method: "POST", body: form });
  },
  deleteAvatar: () => apiFetch("/api/me/avatar", { method: "DELETE" }),
  uploadBanner: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/me/banner", { method: "POST", body: form });
  },
  deleteBanner: () => apiFetch("/api/me/banner", { method: "DELETE" }),

  listFormats: () => apiFetch("/api/formats"),
  uploadImage: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/images", { method: "POST", body: form });
  },
  scanFormat: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/formats/scan", { method: "POST", body: form });
  },
  createFormat: (payload) =>
    apiFetch("/api/formats", { method: "POST", body: JSON.stringify(payload) }),
  getFormat: (formatId) => apiFetch(`/api/formats/${formatId}`),
  getFormatTemplateHtml: (formatId) => apiFetch(`/api/formats/${formatId}/template-html`),
  updateFormat: (formatId, payload) =>
    apiFetch(`/api/formats/${formatId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  editFormatContent: (formatId, edits) =>
    apiFetch(`/api/formats/${formatId}/content`, { method: "PATCH", body: JSON.stringify({ edits }) }),
  editScannedContent: (sourceTempToken, edits) =>
    apiFetch("/api/formats/scan/content", { method: "PATCH", body: JSON.stringify({ source_temp_token: sourceTempToken, edits }) }),
  deleteFormat: (formatId) => apiFetch(`/api/formats/${formatId}`, { method: "DELETE" }),
  // roles: { field_key: "heavy" | "easy" | null }. null hands the decision back
  // to the server's keyword matching.
  setFieldRoles: (formatId, roles) =>
    apiFetch(`/api/formats/${formatId}/field-roles`, {
      method: "PATCH",
      body: JSON.stringify({ roles }),
    }),
  // The teacher's whole field list: [{field_key?, label, anchor_index, guided, locked}].
  saveFieldSetup: (formatId, fields) =>
    apiFetch(`/api/formats/${formatId}/field-setup`, { method: "PUT", body: JSON.stringify({ fields }) }),

  formatSourceUrl: (formatId) => `${API_URL}/api/formats/${formatId}/source`,

  // A string searches by subject, as before; an object passes any of
  // subject, q, grade_band, doc_type and prefer_grade_band.
  searchCourseGuides: (params) => {
    const query = new URLSearchParams();
    Object.entries(typeof params === "string" || !params ? { subject: params || "" } : params)
      .forEach(([k, v]) => { if (v) query.set(k, v); });
    return apiFetch(`/api/course-guides?${query}`);
  },
  courseGuideFileUrl: (guideId) => `${API_URL}/api/course-guides/${guideId}/file`,
  // docType: "budget_of_work" or "curriculum_guide", the picker it came from.
  courseGuideTypes: () => apiFetch("/api/course-guides/types"),
  // A teacher's own library folder (a new document type), banner optional.
  createGuideFolder: (name, banner) => {
    const form = new FormData();
    form.append("name", name);
    if (banner) form.append("banner", banner);
    return apiFetch("/api/course-guides/folders", { method: "POST", body: form });
  },
  // Any folder's banner, by its type (built-in, "untyped" for Other, or a teacher's).
  setGuideTypeBanner: (type, banner) => {
    const form = new FormData();
    form.append("type", type);
    form.append("banner", banner);
    return apiFetch("/api/course-guides/types/banner", { method: "POST", body: form });
  },
  uploadCourseGuide: (file, subject, title, docType) => {
    const form = new FormData();
    form.append("file", file);
    form.append("subject", subject || "");
    form.append("title", title || file.name);
    if (docType) form.append("doc_type", docType);
    return apiFetch("/api/course-guides", { method: "POST", body: form });
  },
  uploadSource: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/sources", { method: "POST", body: form });
  },
  deleteSource: (sourceId) => apiFetch(`/api/sources/${sourceId}`, { method: "DELETE" }),

  generateFull: (payload) =>
    apiFetch("/api/generate/full", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  generateFullStream: async (payload, onEvent) => {
    const response = await fetch(`${API_URL}/api/generate/full-stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body) {
      let message = `Request failed (${response.status}).`;
      try {
        const data = await response.json();
        if (data && data.message) message = data.message;
      } catch (err) {

      }
      throw new ApiError(message, response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalEvent = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineIdx;
      while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "error") throw new ApiError(event.message, 500);
        if (event.type === "complete") finalEvent = event;
        onEvent(event);
      }
    }

    if (!finalEvent) throw new ApiError("Generation stopped before finishing.", 0);
    return finalEvent;
  },
  owlChat: (payload) =>
    apiFetch("/api/generate/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // params: { status: "draft"|"submitted"|"reviewed", limit: number }
  listLessonPlans: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return apiFetch(`/api/lesson-plans${qs ? `?${qs}` : ""}`);
  },
  // Re-saves a plan that already exists. Only the keys present are written,
  // so an autosave can send just the field values without clearing the title.
  updateLessonPlan: (planId, payload) =>
    apiFetch(`/api/lesson-plans/${planId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  saveLessonPlan: (payload) =>
    apiFetch("/api/lesson-plans", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getLessonPlan: (planId) => apiFetch(`/api/lesson-plans/${planId}`),
  deleteLessonPlan: (planId) =>
    apiFetch(`/api/lesson-plans/${planId}`, { method: "DELETE" }),
  exportUrl: (planId) => `${API_URL}/api/lesson-plans/${planId}/export`,
  publicLessonPlans: () => apiFetch("/api/lesson-plans/public"),
  setLessonPlanVisibility: (planId, isPublic) =>
    apiFetch(`/api/lesson-plans/${planId}/visibility`, {
      method: "PATCH",
      body: JSON.stringify({ is_public: isPublic }),
    }),
  submitLessonPlan: (planId, sectionId) =>
    apiFetch(`/api/lesson-plans/${planId}/submit`, {
      method: "POST",
      body: JSON.stringify({ section_id: sectionId }),
    }),
  reviewLessonPlan: (planId, feedback, score) =>
    apiFetch(`/api/lesson-plans/${planId}/review`, {
      method: "POST",
      body: JSON.stringify({ feedback, score }),
    }),

  // Sections (teacher-created classes with a join code)
  listSections: () => apiFetch("/api/sections"),
  getSection: (sectionId) => apiFetch(`/api/sections/${sectionId}`),
  createSection: (payload) =>
    apiFetch("/api/sections", { method: "POST", body: JSON.stringify(payload) }),
  updateSection: (sectionId, payload) =>
    apiFetch(`/api/sections/${sectionId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteSection: (sectionId) =>
    apiFetch(`/api/sections/${sectionId}`, { method: "DELETE" }),
  regenerateSectionCode: (sectionId) =>
    apiFetch(`/api/sections/${sectionId}/regenerate-code`, { method: "POST" }),
  removeStudent: (sectionId, studentId) =>
    apiFetch(`/api/sections/${sectionId}/students/${studentId}`, { method: "DELETE" }),
  sectionSubmissions: (sectionId, status) =>
    apiFetch(`/api/sections/${sectionId}/submissions${status ? `?status=${status}` : ""}`),

  joinSection: (code) =>
    apiFetch("/api/sections/join", { method: "POST", body: JSON.stringify({ code }) }),
  leaveSection: (sectionId) =>
    apiFetch(`/api/sections/${sectionId}/leave`, { method: "DELETE" }),

  // Admin
  adminStats: () => apiFetch("/api/admin/stats"),
  adminListUsers: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return apiFetch(`/api/admin/users${qs ? `?${qs}` : ""}`);
  },
  adminCreateUser: (payload) =>
    apiFetch("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  adminUpdateUser: (userId, payload) =>
    apiFetch(`/api/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  adminDeleteUser: (userId) =>
    apiFetch(`/api/admin/users/${userId}`, { method: "DELETE" }),
  adminListSections: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return apiFetch(`/api/admin/sections${qs ? `?${qs}` : ""}`);
  },
  // kind is "users" or "sections". Resolves to
  // { updated, updated_count, skipped: [{id, reason}] } — a batch can partly
  // apply, so callers must report `skipped` rather than assume all went through.
  adminBulkArchive: (kind, ids, isActive) =>
    apiFetch("/api/admin/bulk-archive", {
      method: "POST",
      body: JSON.stringify({ kind, ids, is_active: isActive }),
    }),
  adminListLessonPlans: (status) =>
    apiFetch(`/api/admin/lesson-plans${status ? `?status=${status}` : ""}`),
  adminListCourseGuides: (subject) =>
    apiFetch(`/api/admin/course-guides${subject ? `?subject=${encodeURIComponent(subject)}` : ""}`),
  adminDeleteLessonPlan: (planId) =>
    apiFetch(`/api/admin/lesson-plans/${planId}`, { method: "DELETE" }),

  // Announcements
  activeAnnouncements: () => apiFetch("/api/announcements/active"),
  myAnnouncements: () => apiFetch("/api/announcements/mine"),
  createAnnouncement: (payload) =>
    apiFetch("/api/announcements", { method: "POST", body: JSON.stringify(payload) }),
  updateAnnouncement: (id, payload) =>
    apiFetch(`/api/announcements/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAnnouncement: (id) =>
    apiFetch(`/api/announcements/${id}`, { method: "DELETE" }),
  adminListAnnouncements: () => apiFetch("/api/admin/announcements"),
  adminCreateAnnouncement: (payload) =>
    apiFetch("/api/admin/announcements", { method: "POST", body: JSON.stringify(payload) }),
  adminUpdateAnnouncement: (id, payload) =>
    apiFetch(`/api/admin/announcements/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  adminDeleteAnnouncement: (id) =>
    apiFetch(`/api/admin/announcements/${id}`, { method: "DELETE" }),
  adminDeleteAnnouncementVideo: (id) =>
    apiFetch(`/api/admin/announcements/${id}/video`, { method: "DELETE" }),
  // Sends a video in 5 MB pieces: the server stops any one request after two
  // minutes, which a large file over a school connection would outlast.
  // onProgress(fraction) after each piece. Resolves with the updated announcement.
  async adminUploadAnnouncementVideo(id, file, onProgress) {
    const CHUNK = 5 * 1024 * 1024;
    const total = Math.max(1, Math.ceil(file.size / CHUNK));
    const uploadId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    let data = null;
    for (let index = 0; index < total; index++) {
      const form = new FormData();
      form.append("upload_id", uploadId);
      form.append("index", String(index));
      form.append("total", String(total));
      form.append("filename", file.name);
      form.append("chunk", file.slice(index * CHUNK, (index + 1) * CHUNK), "chunk");
      data = await apiFetch(`/api/admin/announcements/${id}/video/chunks`, { method: "POST", body: form });
      if (onProgress) onProgress((index + 1) / total);
    }
    return data.announcement;
  },

  // Notifications
  listNotifications: () => apiFetch("/api/notifications"),
  markNotificationRead: (id) =>
    apiFetch(`/api/notifications/${id}/read`, { method: "POST" }),
  markAllNotificationsRead: () =>
    apiFetch("/api/notifications/read-all", { method: "POST" }),
};

// A small dialog that asks for one name: the export's file name, a draft's
// name on save, a plan's new name. onSubmit(name) runs with the dialog still
// open; if it throws, its message shows in the dialog, otherwise it closes.
function askName({ title, label, value = "", suffix = "", action, busy, empty, clean = (s) => s, onSubmit, onCancel }) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay export-name-overlay";
  overlay.innerHTML = `
    <form class="modal-dialog export-name-dialog" role="dialog" aria-modal="true" aria-labelledby="export-name-title" novalidate>
      <div class="modal-header">
        <h2 id="export-name-title"></h2>
        <button type="button" class="modal-close" aria-label="Cancel">&times;</button>
      </div>
      <div class="modal-body">
        <label for="export-name-input"></label>
        <div class="export-name-field">
          <input type="text" id="export-name-input" maxlength="120" autocomplete="off" />
          ${suffix ? `<span>${escapeHtml(suffix)}</span>` : ""}
        </div>
        <p class="export-name-error" role="alert" hidden></p>
        <div class="export-name-actions">
          <button type="button" class="btn btn-secondary export-name-cancel">Cancel</button>
          <button type="submit" class="btn btn-primary export-name-go"></button>
        </div>
      </div>
    </form>`;
  overlay.querySelector("h2").textContent = title;
  overlay.querySelector("label").textContent = label;
  document.body.appendChild(overlay);
  const form = overlay.querySelector("form");
  const input = overlay.querySelector("input");
  const error = overlay.querySelector(".export-name-error");
  const go = overlay.querySelector(".export-name-go");
  go.textContent = action;
  const opener = document.activeElement;
  input.value = value;
  input.addEventListener("input", () => { error.hidden = true; });
  let done = false;
  const close = () => {
    overlay.remove();
    if (opener && opener.focus) opener.focus();
  };
  const cancel = () => {
    if (done) return;
    done = true;
    close();
    if (onCancel) onCancel();
  };
  overlay.querySelector(".modal-close").addEventListener("click", cancel);
  overlay.querySelector(".export-name-cancel").addEventListener("click", cancel);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) cancel(); });
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") cancel(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = clean(input.value.replace(/\s+/g, " ").trim()).slice(0, 120);
    if (!name) {
      error.textContent = empty;
      error.hidden = false;
      input.focus();
      return;
    }
    go.disabled = true;
    go.textContent = busy;
    try {
      await onSubmit(name);
      done = true;
      close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      go.disabled = false;
      go.textContent = action;
    }
  });
  input.focus();
  input.select();
}

// Export a plan as Word, asking for the file name first. Every export button
// (the plan page, the dashboard, the plan list, submissions) goes through here.
function exportPlan(planId, suggestedName) {
  const clean = (name) => name.replace(/\.docx$/i, "").replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim();
  askName({
    title: "Export as Word", label: "File name", value: clean(suggestedName || "") || "Lesson plan",
    suffix: ".docx", action: "Export", busy: "Exporting…", empty: "Give the file a name.", clean,
    onSubmit: async (name) => {
      const res = await fetch(Api.exportUrl(planId), { credentials: "include" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.message || "The plan couldn't be exported.");
      }
      const url = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.docx` });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      showToast(`Saved as ${name}.docx`);
    },
  });
}

function showToast(message, isError = false) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    // Toasts are the only confirmation that a save or delete worked, so a
    // screen reader has to hear them. "polite" rather than "assertive":
    // they report what just finished, they never demand a response.
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.toggle("toast-error", isError);
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3200);
}

// Every modal on the site is the same .modal-overlay/.modal-dialog pair,
// wired page by page with its own Escape and backdrop-click handlers — and
// none of them handled focus, so opening one left the caret behind on the
// page underneath and Tab walked straight out of the dialog into the links
// behind it. This does the whole APG dialog contract in one place: move
// focus in, keep Tab inside, return focus to whatever opened it on close.
// Pages call openDialog/closeDialog instead of toggling `hidden` themselves
// (the names avoid the openModal/closeModal the announcements pages already
// declare for their own one-off modals).
const DIALOG_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function wireDialog(overlay, onClose) {
  const dialog = overlay.querySelector(".modal-dialog") || overlay;

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeDialog(overlay, onClose);
  });

  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDialog(overlay, onClose);
      return;
    }
    if (e.key !== "Tab") return;
    const items = [...dialog.querySelectorAll(DIALOG_FOCUSABLE)].filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    // Wrap at both ends rather than letting Tab escape to the page behind.
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}

function openDialog(overlay) {
  // Remembered on the element so a page can open the same modal from several
  // buttons and still send focus back to the right one.
  overlay._opener = document.activeElement;
  overlay.hidden = false;
  const dialog = overlay.querySelector(".modal-dialog") || overlay;
  const target = dialog.querySelector(DIALOG_FOCUSABLE);
  if (target) target.focus();
}

function closeDialog(overlay, onClose) {
  if (overlay.hidden) return;
  overlay.hidden = true;
  if (onClose) onClose();
  if (overlay._opener && document.contains(overlay._opener)) overlay._opener.focus();
}

function setButtonLoading(btn, loading, loadingLabel) {
  if (!btn) return;
  if (loading) {
    btn.dataset.originalLabel = btn.dataset.originalLabel || btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>${btn.dataset.originalLabel}`;
    if (loadingLabel) btn.setAttribute("aria-label", `${loadingLabel}…`);
    btn.setAttribute("aria-busy", "true");
  } else {
    btn.disabled = false;
    btn.removeAttribute("aria-busy");
    btn.removeAttribute("aria-label");
    if (btn.dataset.originalLabel) btn.innerHTML = btn.dataset.originalLabel;
  }
}

// Every page here is a full navigation (this is a multi-page app, not an
// SPA), and every page's sidebar/topbar starts out unfiltered — it only
// learns the signed-in user's role after Api.me() resolves, then hides
// whatever doesn't apply. Without a cache, that means an admin's links flash
// on screen for a teacher (and a teacher's for a student) on every single
// navigation, then vanish once the real role is known — a visible reflow
// that reads as "flickering." Caching the last-known user in sessionStorage
// lets the very first paint already show the right thing; requireAuth()
// still fetches the real user every time and reconciles, so a stale/wrong
// cache only ever shows for an instant, never silently.
function cacheUser(user) {
  try { sessionStorage.setItem("cached-user", JSON.stringify(user)); } catch (err) {}
}

function getCachedUser() {
  try {
    const raw = sessionStorage.getItem("cached-user");
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function clearCachedUser() {
  try {
    sessionStorage.removeItem("cached-user");
    sessionStorage.removeItem("cached-announcements");
  } catch (err) {}
}

// ---- Page transition: a brief full-screen mask over the gap between
// clicking a sidebar link and the next page settling in (this is a
// multi-page app, so that gap is a real navigation + a fresh Api.me() call,
// not an SPA route swap). Shown by default in the HTML of every dashboard
// page (so it's already covering the very first paint), hidden here once
// requireAuth() confirms the user, and re-shown on the way out the moment an
// internal link is clicked so the outgoing page doesn't visibly tear down
// first. PAGE_TRANSITION_MIN_MS keeps it from being a single unsettling
// blink on a fast local load; the timeout is a safety net in case some page
// never finishes its own init.
const PAGE_TRANSITION_MIN_MS = 180;
const PAGE_TRANSITION_MAX_MS = 4000;
let _pageTransitionShownAt = Date.now();

function showPageTransition() {
  const el = document.getElementById("page-transition");
  if (!el) return;
  el.classList.remove("page-transition-hide");
  _pageTransitionShownAt = Date.now();
}

function hidePageTransition() {
  const el = document.getElementById("page-transition");
  if (!el || el.classList.contains("page-transition-hide")) return;
  const elapsed = Date.now() - _pageTransitionShownAt;
  setTimeout(() => el.classList.add("page-transition-hide"), Math.max(0, PAGE_TRANSITION_MIN_MS - elapsed));
}

document.addEventListener("click", (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const link = e.target.closest("a[href]");
  if (!link || link.target === "_blank") return;
  const href = link.getAttribute("href");
  if (!href || !href.endsWith(".html")) return;
  showPageTransition();
});

setTimeout(hidePageTransition, PAGE_TRANSITION_MAX_MS);

async function requireAuth() {
  try {
    const data = await Api.me();
    cacheUser(data.user);
    loadAnnouncementBanner();
    addHelpButton();
    loadTourIfDue(data.user);
    wireNotificationBell();
    hidePageTransition();
    return data.user;
  } catch (err) {
    clearCachedUser();
    window.location.href = "index.html";
    return null;
  }
}

function timeAgo(iso) {
  if (!iso) return "";
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Turns the bell-btn already present on every non-admin page into a real
// notification dropdown — a personal, per-user list (a submission landing in
// your inbox, a review coming back, a new announcement reaching you) instead
// of the old hardcoded "you're all caught up" toast every page used to show
// regardless of what actually happened. No-ops on pages with no bell (the
// admin console pages don't have one).
function wireNotificationBell() {
  const btn = document.getElementById("bell-btn");
  if (!btn || btn.dataset.notifWired) return;
  btn.dataset.notifWired = "true";

  // The button has always only ever contained the unread ".dot" indicator —
  // never the bell glyph itself (Icons.bell was defined in icons.js but
  // never actually used), so the button showed as an empty circle.
  if (typeof Icons !== "undefined" && Icons.bell && !btn.querySelector("svg")) {
    btn.insertAdjacentHTML("afterbegin", Icons.bell);
  }

  const wrap = document.createElement("div");
  wrap.className = "notif-menu";
  btn.parentNode.insertBefore(wrap, btn);
  wrap.appendChild(btn);

  const panel = document.createElement("div");
  panel.className = "notif-panel";
  panel.hidden = true;
  wrap.appendChild(panel);

  const dot = btn.querySelector(".dot");
  if (dot) dot.hidden = true;

  function renderPanel(items) {
    if (!items.length) {
      panel.innerHTML = `<div class="notif-empty">You're all caught up. No notifications yet.</div>`;
      return;
    }
    panel.innerHTML = `
      <div class="notif-panel-header">
        <span>Notifications</span>
        <button type="button" class="notif-mark-all">Mark all read</button>
      </div>
      <div class="notif-list">
        ${items
          .map(
            (n) => `
          <div class="notif-item${n.is_read ? "" : " unread"}" data-id="${n.id}" data-link="${n.link || ""}">
            <div class="notif-item-title">${escapeHtml(n.title)}</div>
            <div class="notif-item-message">${escapeHtml(n.message)}</div>
            <div class="notif-item-time">${timeAgo(n.created_at)}</div>
          </div>`
          )
          .join("")}
      </div>`;

    panel.querySelectorAll(".notif-item").forEach((el) => {
      el.addEventListener("click", async () => {
        const id = el.dataset.id;
        const link = el.dataset.link;
        el.classList.remove("unread");
        try {
          await Api.markNotificationRead(id);
        } catch (err) {}
        updateDot();
        if (link) {
          showPageTransition();
          window.location.href = link;
        }
      });
    });

    const markAllBtn = panel.querySelector(".notif-mark-all");
    if (markAllBtn) {
      markAllBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        panel.querySelectorAll(".notif-item.unread").forEach((el) => el.classList.remove("unread"));
        if (dot) dot.hidden = true;
        try {
          await Api.markAllNotificationsRead();
        } catch (err) {}
      });
    }
  }

  function updateDot() {
    if (dot) dot.hidden = !panel.querySelector(".notif-item.unread");
  }

  async function refresh() {
    try {
      const data = await Api.listNotifications();
      renderPanel(data.notifications || []);
      if (dot) dot.hidden = !(data.unread_count > 0);
    } catch (err) {
      // A failed refresh just leaves the last-known panel/dot state — the
      // bell is a nice-to-have and should never surface an error of its own.
    }
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    panel.hidden = !panel.hidden;
    if (!panel.hidden) refresh();
  });
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) panel.hidden = true;
  });

  refresh();
  setInterval(refresh, 60000);
}

const ANNOUNCEMENT_TYPE_LABEL = {
  maintenance: "Maintenance",
  urgent: "Urgent",
  info: "Notice",
};

// Fetches any currently-active system announcements (e.g. a scheduled
// maintenance window) and shows them as dismissible banners at the top of
// the page, for every signed-in role. Fails silently — a banner is a
// nice-to-have and should never block the page from loading.
// Same stale-while-revalidate idea as cacheUser() above: without a cache,
// the banner (and the layout shift it causes, pushing everything below it
// down) only ever appears after the network round-trip finishes, so on
// every navigation the page first renders with no banner, then suddenly
// gets shorter as the banner shoves content down. Painting last navigation's
// known announcements immediately, then reconciling once the real fetch
// resolves, means the shift only ever happens on genuine changes (a new
// announcement, one expiring) instead of on every single page load.
// The owl's tour (js/owl-tour.js) is fetched only when it has something to do:
// a tour already under way on another tab, or a new account (or "Replay the
// tour") arriving on its landing page.
function loadTourIfDue(user) {
  let underWay = false;
  try {
    underWay = !!sessionStorage.getItem("alignedTour");
  } catch (err) {
    underWay = false;
  }
  const page = location.pathname.split("/").pop();
  const landing = page === (user.role === "admin" ? "admin-dashboard.html" : "dashboard.html");
  const replay = new URLSearchParams(location.search).get("tour") === "1";
  if (!underWay && !(landing && (replay || !user.onboarded))) return;
  if (typeof OwlTour !== "undefined") {
    OwlTour.run(user);
    return;
  }
  const script = document.createElement("script");
  script.src = "js/owl-tour.js?v=2026-10-26f";
  script.onload = () => OwlTour.run(user);
  document.body.appendChild(script);
}

// The Help and FAQ button, first in the top bar of every signed-in page. Added
// here rather than in each page's markup so no page can be missed. The icon is
// inlined because api.js loads on pages that never load icons.js.
function addHelpButton() {
  const actions = document.querySelector(".topbar-actions");
  if (!actions || document.getElementById("help-btn")) return;
  const link = document.createElement("a");
  link.id = "help-btn";
  link.className = "icon-btn";
  link.href = "faq.html";
  link.title = "Help and FAQ";
  link.setAttribute("aria-label", "Help and FAQ");
  if (location.pathname.endsWith("/faq.html")) link.setAttribute("aria-current", "page");
  link.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>`;
  actions.insertBefore(link, actions.firstChild);
}

function loadAnnouncementBanner() {
  const shell = document.querySelector(".dash-shell");
  if (!shell) return;

  let dismissed = [];
  try {
    dismissed = JSON.parse(sessionStorage.getItem("dismissed-announcements") || "[]");
  } catch (err) {
    dismissed = [];
  }

  function render(announcements) {
    const visible = announcements.filter((a) => !dismissed.includes(a.id));
    let wrap = document.getElementById("announcement-banner-wrap");

    if (!visible.length) {
      if (wrap) wrap.remove();
      return;
    }

    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "announcement-banner-wrap";
      shell.insertBefore(wrap, shell.firstChild);
    }

    wrap.innerHTML = visible
      .map(
        (a) => `
        <div class="announcement-banner announcement-${a.type}" data-id="${a.id}">
          <span class="announcement-banner-label">${ANNOUNCEMENT_TYPE_LABEL[a.type] || "Notice"}</span>
          <div class="announcement-banner-body">
            <strong>${escapeHtml(a.title)}</strong>
            <span>${escapeHtml(a.message)}</span>
            ${a.has_video ? `<a class="announcement-banner-video" href="announcements.html#announcement-${a.id}">Watch the video</a>` : ""}
          </div>
          <button type="button" class="announcement-banner-close" aria-label="Dismiss"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
        </div>`
      )
      .join("");

    wrap.querySelectorAll(".announcement-banner-close").forEach((btn) => {
      btn.addEventListener("click", () => {
        const row = btn.closest(".announcement-banner");
        const id = Number(row.dataset.id);
        dismissed.push(id);
        try {
          sessionStorage.setItem("dismissed-announcements", JSON.stringify(dismissed));
        } catch (err) {}
        row.remove();
        if (!wrap.querySelector(".announcement-banner")) wrap.remove();
      });
    });
  }

  try {
    const cached = JSON.parse(sessionStorage.getItem("cached-announcements") || "null");
    if (cached) render(cached);
  } catch (err) {}

  Api.activeAnnouncements()
    .then((data) => {
      const announcements = data.announcements || [];
      try {
        sessionStorage.setItem("cached-announcements", JSON.stringify(announcements));
      } catch (err) {}
      render(announcements);
    })
    .catch(() => {
      // A failed refresh just leaves whatever was last rendered (from cache,
      // or nothing) — the banner is a nice-to-have, never worth an error of
      // its own.
    });
}

function slugify(label) {
  return (label || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "field";
}

// ---- Alan, the guide owl -------------------------------------------------
// One owl shared by every page. He opens each step of format building and
// lesson plan making with a single fixed line and then leaves after five
// seconds. The lines are hardcoded on purpose: the guided-mode chat is what
// answers questions about a field, so if this spoke too it would be a second
// voice saying something slightly different. This one only ever says which
// part of the process you have just reached.
const OWL_GUIDE_STEPS = {
  // Lesson plan making
  "plan-formats": { pose: "wave", text: "Pick the format your school uses, or add your own. Everything after this follows that layout." },
  "plan-setup": { pose: "point", text: "Start here: who is teaching, which subject, and which course guide this lesson comes from." },
  "plan-ready": { pose: "check", text: "Setup is complete. Open “Generate & review” when you are ready to write the plan." },
  "plan-mode": { pose: "idea", text: "Two ways to write it: let me draft the whole plan, or take it field by field in guided mode." },
  "plan-guided": { pose: "point", text: "Guided mode: you write each field, and the next one opens once the current one is filled. Ask me in the chat for help with a field." },
  "plan-full": { pose: "think", text: "Writing your plan now. This takes a moment. The fields fill in as each one is finished." },
  "plan-done": { pose: "celebrate", text: "The plan is written. Read it through, change anything you like, then save it." },
  "plan-saved": { pose: "celebrate", text: "Saved. You can export it as a Word file whenever you need a copy." },

  // Lesson plan format making
  "format-source": { pose: "wave", text: "A format is the layout your plans are printed in. Upload a blank copy of yours and AlignED finds the fields." },
  "format-cleanup": { pose: "check", text: "This is a live copy of your document. Fix any typos and delete what you do not need. The fillable fields are worked out for you when you save." },
  "format-blank": { pose: "point", text: "Add a row for each field your format needs, in the order they appear on the page." },
};

// Self-contained on purpose: api.js loads on pages that never load icons.js,
// so the close icon is inlined rather than taken from Icons.
const OwlGuide = {
  _el: null,
  _timer: null,
  // Kept across steps so an owl you moved out of the way stays where you put
  // it for the rest of the page, instead of springing back each time.
  _pos: { x: 0, y: 0 },
  VISIBLE_MS: 5000,
  // Docked: during Guided mode the owl stays on screen beside the chat
  // instead of leaving after one line. See dock().
  _docked: false,
  _moveListeners: [],

  _build() {
    const el = document.createElement("div");
    el.className = "owl-guide";
    el.id = "owl-guide";
    el.hidden = true;
    el.tabIndex = 0;
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", "Guide");
    el.innerHTML = `
      <div class="owl-guide-bubble">
        <p id="owl-guide-message" aria-live="polite"></p>
        <button type="button" class="owl-guide-close" aria-label="Dismiss the guide"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
      </div>
      <span class="owl-guide-figure">
        <img class="owl-guide-img" id="owl-guide-img" src="img/owl/alan-idle.png" alt="" />
      </span>`;
    document.body.appendChild(el);

    el.querySelector(".owl-guide-close").addEventListener("click", () => (this._tour ? this._tour.onSkip() : this.hide()));

    // Hold still while it is being read or moved — a message that vanishes
    // mid-sentence is worse than one that never appeared. Bound to each part
    // that takes pointer events, since the container itself does not.
    const bubble = el.querySelector(".owl-guide-bubble");
    const owl = el.querySelector(".owl-guide-img");
    [bubble, owl].forEach((part) => {
      part.addEventListener("pointerenter", () => this._pause());
      part.addEventListener("pointerleave", () => this._resume());
    });
    el.addEventListener("focusin", () => this._pause());
    el.addEventListener("focusout", () => this._resume());

    // The owl is what you grab; the bubble is text you can select and read.
    this._wireDrag(el, owl);
    window.addEventListener("resize", () => this._moveTo(this._pos.x, this._pos.y));
    this._el = el;
    this._watchCovering(el);
    return el;
  },

  // Alan must never sit on top of the page's action buttons (Save, Export).
  // When his box overlaps an action row he steps aside: the bubble hides and he
  // shrinks to a small peek in his corner that clicks pass straight through.
  // He comes back as soon as the row is clear of him again.
  _watchCovering(el) {
    const check = () => {
      if (el.hidden) return;
      const me = el.getBoundingClientRect(); // children's peek transform doesn't change this box
      const covering = Array.from(document.querySelectorAll(".generator-footer:not([hidden]), [data-owl-avoid]"))
        .some((row) => {
          const r = row.getBoundingClientRect();
          return r.width && r.height && r.left < me.right && r.right > me.left && r.top < me.bottom && r.bottom > me.top;
        });
      el.classList.toggle("is-peeking", covering);
    };
    let queued = false;
    const soon = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        check();
      });
    };
    window.addEventListener("scroll", soon, { passive: true, capture: true });
    window.addEventListener("resize", soon);
    // ponytail: a slow poll also catches rows that appear without a scroll
    // (the footer un-hiding after generation); a MutationObserver if this ever costs.
    setInterval(soon, 800);
    soon();
  },

  _wireDrag(el, handle) {
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;
    let dragged = false;

    handle.addEventListener("pointerdown", (e) => {
      dragged = false;
      startX = e.clientX;
      startY = e.clientY;
      originX = this._pos.x;
      originY = this._pos.y;
      // Capture keeps the drag alive when the pointer outruns the bubble.
      // It throws if the pointer is already gone, which must not take the
      // drag down with it.
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (err) {
        /* no capture available; the drag still tracks while over the bubble */
      }
      el.classList.add("is-dragging");
      this._pause();
    });

    handle.addEventListener("pointermove", (e) => {
      if (!el.classList.contains("is-dragging")) return;
      // A few pixels of travel is a shaky click, not a drag.
      if (Math.abs(e.clientX - startX) > 3 || Math.abs(e.clientY - startY) > 3) dragged = true;
      this._moveTo(originX + (e.clientX - startX), originY + (e.clientY - startY));
    });

    const end = (e) => {
      if (!el.classList.contains("is-dragging")) return;
      el.classList.remove("is-dragging");
      // He has to accept pointer events to be draggable, which means he also
      // sits on top of whatever is beneath him — often the page's primary
      // button, since he rests in the bottom-right corner. If this turned out
      // to be a click rather than a drag, pass it on to whatever the pointer
      // was really over, so he never silently eats one. Docked in Guided
      // mode he is the chat's open/close control instead, so the click is his.
      if (!dragged) {
        if (this._docked && this._dockedClick) this._dockedClick();
        else this._passClickThrough(e);
      }
      try {
        if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
      } catch (err) {
        /* already released */
      }
      this._resume();
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);

    // Dragging is a pointer gesture, so it needs an equivalent that does not
    // require one: focus the owl and nudge him with the arrow keys.
    el.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 40 : 12;
      const moves = {
        ArrowLeft: [-step, 0], ArrowRight: [step, 0],
        ArrowUp: [0, -step], ArrowDown: [0, step],
      };
      if (e.key === "Escape") {
        this.hide();
        return;
      }
      if (this._docked && this._dockedClick && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        this._dockedClick();
        return;
      }
      if (!moves[e.key]) return;
      e.preventDefault();
      this._moveTo(this._pos.x + moves[e.key][0], this._pos.y + moves[e.key][1]);
    });
  },

  _passClickThrough(e) {
    const el = this._el;
    const wasHidden = el.hidden;
    el.hidden = true;
    const below = document.elementFromPoint(e.clientX, e.clientY);
    el.hidden = wasHidden;
    if (below && below !== document.documentElement && below !== document.body) below.click();
  },

  _moveTo(x, y) {
    // Clamp so he can never be pushed off-screen and stranded there.
    const el = this._el;
    // A hidden element measures 0x0, which would turn the clamp below into
    // nonsense and lose the position the user had dragged him to.
    if (!el || el.hidden) return;
    const box = el.getBoundingClientRect();
    const left = box.left - this._pos.x;
    const top = box.top - this._pos.y;
    const minX = 8 - left;
    const maxX = window.innerWidth - box.width - 8 - left;
    const minY = 8 - top;
    const maxY = window.innerHeight - box.height - 8 - top;
    this._pos.x = Math.min(Math.max(x, minX), maxX);
    this._pos.y = Math.min(Math.max(y, minY), maxY);
    el.style.setProperty("--owl-x", `${this._pos.x}px`);
    el.style.setProperty("--owl-y", `${this._pos.y}px`);
    this._moveListeners.forEach((fn) => fn());
  },

  _pause() {
    clearTimeout(this._timer);
    this._timer = null;
  },

  _resume() {
    if (this._el && !this._el.hidden) this._arm();
  },

  _arm() {
    clearTimeout(this._timer);
    // A tour step stays until the reader moves on.
    if (this._tour) return;
    this._timer = setTimeout(() => this.hide(), this.VISIBLE_MS);
  },

  // One step of a guided tour: the line, a counter, and Back / Next / Skip.
  // tour = { index, total, onBack, onNext, onSkip }. The close button skips.
  tourStep(spec, tour) {
    const el = this._el || this._build();
    this._tour = tour;
    el.classList.add("is-touring");
    this.show(spec);
    let bar = el.querySelector(".owl-tour-controls");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "owl-tour-controls";
      this._bubble().appendChild(bar);
    }
    const last = tour.index === tour.total - 1;
    const nextLabel = tour.nextLabel || (last ? "Finish" : "Next");
    bar.innerHTML = `
      <span class="owl-tour-count">${tour.index + 1} of ${tour.total}</span>
      <button type="button" class="owl-tour-skip" data-tour="skip">Skip tour</button>
      ${tour.onBack ? '<button type="button" class="btn btn-secondary btn-sm" data-tour="back">Back</button>' : ""}
      <button type="button" class="btn btn-primary btn-sm" data-tour="next">${nextLabel}</button>`;
    bar.hidden = false;
    bar.querySelector('[data-tour="next"]').addEventListener("click", tour.onNext);
    bar.querySelector('[data-tour="skip"]').addEventListener("click", tour.onSkip);
    const back = bar.querySelector('[data-tour="back"]');
    if (back) back.addEventListener("click", tour.onBack);
    bar.querySelector('[data-tour="next"]').focus({ preventScroll: true });
  },

  endTour() {
    this._tour = null;
    if (this._el) this._el.classList.remove("is-touring");
    const bar = this._el && this._el.querySelector(".owl-tour-controls");
    if (bar) bar.hidden = true;
    this.hide();
  },

  _bubble() {
    return this._el && this._el.querySelector(".owl-guide-bubble");
  },

  // show("plan-setup") for a scripted step, or show({pose, text}) for a line
  // built at runtime (a field name, say).
  show(step) {
    const spec = typeof step === "string" ? OWL_GUIDE_STEPS[step] : step;
    if (!spec) return;
    const el = this._el || this._build();
    el.querySelector("#owl-guide-message").textContent = spec.text;
    el.querySelector("#owl-guide-img").src = `img/owl/alan-${spec.pose || "idle"}.png`;
    this._cancelLeave();
    el.classList.remove("is-leaving");
    el.hidden = false;
    // Docked beside the chat, the chat is his voice: a line only changes his
    // pose, since a bubble would sit on top of the chat bar.
    this._bubble().hidden = this._docked;
    this._moveTo(this._pos.x, this._pos.y);
    this._arm();
  },

  // Docked, only the speech bubble goes away; the owl himself stays for as
  // long as Guided mode lasts.
  hide() {
    this._pause();
    if (!this._el || this._el.hidden) return;
    if (this._docked) {
      this._bubble().hidden = true;
      return;
    }
    const el = this._el;
    el.classList.add("is-leaving");
    clearTimeout(this._leaveTimer);
    this._leaveTimer = setTimeout(() => {
      el.hidden = true;
      el.classList.remove("is-leaving");
    }, 200);
  },

  // A fade-out still in flight must not hide an owl that was shown or docked
  // again in the meantime (leaving Guided mode and coming straight back).
  _cancelLeave() {
    clearTimeout(this._leaveTimer);
    this._leaveTimer = null;
  },

  // Guided mode: the owl stays on screen next to the chat instead of leaving
  // after five seconds, and he is how the chat opens: minimized, the chat is
  // gone and only he is left, and clicking him (or Enter/Space when he has
  // focus) calls onClick. Dragging still just moves him; the chat follows.
  dock(onClick) {
    const el = this._el || this._build();
    this._cancelLeave();
    el.classList.remove("is-leaving");
    el.hidden = false;
    this._dockedClick = onClick || null;
    if (this._docked) return;
    this._docked = true;
    el.classList.add("is-docked");
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", "Chat with Alan");
    this._bubble().hidden = true;
    this._pause();
    this._moveTo(this._pos.x, this._pos.y);
  },

  // What the docked owl announces: whether the chat he opens is open, and
  // whether a reply is waiting in it.
  setChatState({ open, unread }) {
    const el = this._el;
    if (!el || !this._docked) return;
    el.setAttribute("aria-expanded", String(!!open));
    el.classList.toggle("has-unread", !!unread);
    el.setAttribute("aria-label", unread ? "Chat with Alan, new reply" : "Chat with Alan");
  },

  undock() {
    if (!this._docked) return;
    this._docked = false;
    this._dockedClick = null;
    this._el.classList.remove("is-docked", "has-unread");
    this._el.setAttribute("role", "group");
    this._el.setAttribute("aria-label", "Guide");
    this._el.removeAttribute("aria-expanded");
    this._bubble().hidden = false;
    this.hide();
  },

  // Where the owl is drawn right now, for placing the chat beside him.
  rect() {
    if (!this._el || this._el.hidden) return null;
    const box = this._el.querySelector("#owl-guide-img").getBoundingClientRect();
    return box.width ? box : null;
  },

  // Called after every drag, nudge or window resize that moves him.
  onMove(fn) {
    if (!this._moveListeners.includes(fn)) this._moveListeners.push(fn);
  },
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  // innerHTML escapes < > &, but leaves quotes alone — fine for text between
  // tags, not for the many places this result is dropped into an attribute
  // (value="...", title="...", aria-label="..."). A name or a generated
  // lesson field containing a double quote would close the attribute early
  // and let the rest be parsed as markup, so escape both quote characters
  // here rather than relying on every call site to pick the safe context.
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Shared by any page that shows a read-only field label/value breakdown of
// a lesson plan (the saved-plan preview modal, and the pre-save preview in
// the generator) so both stay visually and behaviorally consistent.
function renderPreviewValue(value) {
  if (Array.isArray(value)) {
    const items = value.filter((v) => String(v).trim());
    if (!items.length) return `<div class="preview-field-value">\u2013</div>`;
    return `<ul class="preview-field-value">${items
      .map((v) => `<li>${escapeHtml(String(v))}</li>`)
      .join("")}</ul>`;
  }
  const text = value == null ? "" : String(value).trim();
  return `<div class="preview-field-value">${escapeHtml(text) || "\u2013"}</div>`;
}

// Wraps every password field on the page (login, signup, settings, the
// admin create/edit-account modal, ...) with a show/hide toggle, from one
// shared place instead of wiring it per page. Guarded by a data attribute
// so it's safe to call more than once (e.g. after a modal re-renders).
function wirePasswordToggles() {
  const eyeIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
  const eyeOffIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a21.6 21.6 0 0 1 5.06-6.06M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a21.6 21.6 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/></svg>`;

  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.dataset.toggleWired) return;
    input.dataset.toggleWired = "1";

    const wrap = document.createElement("div");
    wrap.className = "password-field";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "password-toggle-btn";
    btn.setAttribute("aria-label", "Show password");
    btn.tabIndex = -1;
    btn.innerHTML = eyeIcon;
    wrap.appendChild(btn);

    btn.addEventListener("click", () => {
      const nowShowing = input.type === "password";
      input.type = nowShowing ? "text" : "password";
      btn.innerHTML = nowShowing ? eyeOffIcon : eyeIcon;
      btn.setAttribute("aria-label", nowShowing ? "Hide password" : "Show password");
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wirePasswordToggles);
} else {
  wirePasswordToggles();
}

// Lets a table read as a stack of cards at phone width: each cell carries its
// column's header as data-label, which the CSS prints beside the value. Rows
// are rendered by each page's own script, at different times, so this
// watches for them rather than asking every page to call it.
// The scale that fits a document page to its panel's width, never past its
// true size. The page's width comes from the .docx, in points.
function docFitScale(wrapEl) {
  const page = wrapEl.querySelector(".lp-doc[data-page-width]");
  if (!page) return 1;
  const pageWidth = (parseFloat(page.dataset.pageWidth) * 96) / 72;
  const cs = getComputedStyle(wrapEl);
  const available = wrapEl.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  if (!(pageWidth > 0) || !(available > 0)) return 1;
  return Math.min(1, available / pageWidth);
}

// Fits a read-only document preview (no zoom toolbar) to its panel, and keeps
// it fitted when the panel resizes or first becomes visible in a modal.
function fitDocPage(wrapEl) {
  const apply = () => wrapEl.style.setProperty("--doc-zoom", String(docFitScale(wrapEl)));
  apply();
  if (window.ResizeObserver && !wrapEl._docFitObserver) {
    wrapEl._docFitObserver = new ResizeObserver(apply);
    wrapEl._docFitObserver.observe(wrapEl);
  }
}

function labelTableCells(root = document) {
  root.querySelectorAll("table.data-table").forEach((table) => {
    // Pages hide whole columns per tab with the hidden attribute, on the th
    // and its cells alike, so both sides skip hidden ones to stay aligned.
    const heads = Array.from(table.querySelectorAll("thead th")).filter((th) => !th.hidden).map((th) => th.textContent.trim());
    table.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).filter((td) => !td.hidden).forEach((td, i) => {
        if (td.colSpan > 1) td.classList.add("cell-full");
        else if (heads[i] && !td.hasAttribute("data-label")) td.setAttribute("data-label", heads[i]);
      });
    });
  });
}

(function watchTables() {
  let queued = false;
  const run = () => {
    queued = false;
    labelTableCells();
  };
  // Batched to one pass per frame: a page filling a table fires a mutation
  // per row, and labelling is cheap but not free.
  new MutationObserver(() => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(run);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
