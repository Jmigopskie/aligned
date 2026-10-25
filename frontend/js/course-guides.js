const errorBox = document.getElementById("error-box");
const searchInput = document.getElementById("subject-input");
const typeFilter = document.getElementById("type-filter");
const folderGrid = document.getElementById("folder-grid");
const officialSection = document.getElementById("official-guides-section");
const officialGrid = document.getElementById("official-grid");
const sharedSection = document.getElementById("shared-guides-section");
const resultsGrid = document.getElementById("results-grid");
const resultsEmpty = document.getElementById("results-empty");
const clearFiltersBtn = document.getElementById("clear-filters-btn");
const newFolderBtn = document.getElementById("new-folder-btn");
const uploadToggleBtn = document.getElementById("upload-toggle-btn");
const uploadPanel = document.getElementById("upload-panel");
const uploadSubject = document.getElementById("upload-subject");
const uploadTitle = document.getElementById("upload-title");
const uploadType = document.getElementById("upload-type");
const uploadTypeOptions = document.getElementById("upload-type-options");
const cgDropzone = document.getElementById("cg-dropzone");
const cgFileInput = document.getElementById("cg-file-input");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("course-guides");

let types = [];
let isStaff = false;

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fmtDate(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// "9-10" reads as "Grades 9 to 10", "7" as "Grade 7".
function gradesLabel(grades) {
  if (!grades) return "";
  const [from, to] = String(grades).split("-");
  return to ? `Grades ${from} to ${to}` : `Grade ${from}`;
}

function guideRow(g) {
  const row = document.createElement("article");
  row.className = `guide-card${g.is_builtin ? " is-official" : ""}`;
  const meta = g.is_builtin
    ? [g.type_label, gradesLabel(g.grades), g.curriculum, g.retrieved_at ? `Retrieved ${fmtDate(g.retrieved_at)}` : ""]
    : [g.doc_type ? g.type_label : "", g.subject, `Shared by ${g.uploaded_by || "a teacher"}`, fmtDate(g.created_at)];
  row.innerHTML = `
    <span class="guide-icon" aria-hidden="true">${g.is_builtin ? Icons.shieldCheck : Icons.file}</span>
    <div class="guide-body">
      <h3 class="guide-title"></h3>
      <p class="guide-meta"></p>
    </div>
    <a class="btn btn-secondary guide-open" href="${Api.courseGuideFileUrl(g.id)}" target="_blank" rel="noopener"><span data-icon="externalLink"></span>Open</a>`;
  row.querySelector(".guide-title").textContent = g.title;
  row.querySelector(".guide-meta").textContent = meta.filter(Boolean).join(" · ");
  row.querySelector(".guide-open").setAttribute("aria-label", `Open ${g.title}`);
  hydrateIcons(row);
  return row;
}

// ---- folders: one box per document type, each with its banner ----
async function loadTypes() {
  try {
    types = (await Api.courseGuideTypes()).types || [];
  } catch (err) {
    showError(err.message);
    return;
  }
  const chosen = typeFilter.value;
  typeFilter.replaceChildren(new Option("All types", ""), ...types.map((t) => new Option(t.label, t.value)));
  typeFilter.value = types.some((t) => t.value === chosen) ? chosen : "";
  uploadTypeOptions.replaceChildren(...types.filter((t) => t.value !== "untyped").map((t) => new Option(t.label)));
  renderFolders();
}

function renderFolders() {
  folderGrid.replaceChildren(...types.map((t) => {
    const box = document.createElement("button");
    box.type = "button";
    box.className = "folder-box";
    const banner = Object.assign(document.createElement("img"), { className: "folder-banner", alt: "", loading: "lazy", src: t.banner_url });
    box.innerHTML = `<span class="folder-text"><span class="folder-name"></span><span class="folder-count"></span></span>`;
    box.prepend(banner);
    box.querySelector(".folder-name").textContent = t.label;
    box.querySelector(".folder-count").textContent = `${t.count} document${t.count === 1 ? "" : "s"}`;
    box.setAttribute("aria-label", `${t.label}, ${t.count} document${t.count === 1 ? "" : "s"}`);
    box.addEventListener("click", () => openFolder(t, box));
    return box;
  }));
}

// A small dialog on the page's own modal styles; returns its parts.
function dialog(title, { wide = false } = {}) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-dialog${wide ? " folder-dialog" : " folder-form-dialog"}" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title">
      <div class="modal-header">
        <h2 id="folder-dialog-title"></h2>
        <button type="button" class="modal-close" aria-label="Close">&times;</button>
      </div>
      <div class="modal-body"></div>
    </div>`;
  overlay.querySelector("h2").textContent = title;
  const opener = document.activeElement;
  const close = () => {
    overlay.remove();
    if (opener && opener.focus) opener.focus();
  };
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  document.body.appendChild(overlay);
  return { overlay, body: overlay.querySelector(".modal-body"), close };
}

// Clicking a box: what's in that folder pops out.
async function openFolder(t) {
  const { overlay, body, close } = dialog(t.label, { wide: true });
  const head = overlay.querySelector(".modal-header");
  const banner = Object.assign(document.createElement("img"), { className: "folder-dialog-banner", alt: "", src: t.banner_url });
  head.before(banner);

  const actions = document.createElement("div");
  actions.className = "folder-actions";
  if (isStaff && t.value !== "untyped") {
    const up = document.createElement("button");
    up.type = "button";
    up.className = "btn btn-primary btn-sm";
    up.innerHTML = `${Icons.upload}<span>Upload to this folder</span>`;
    up.addEventListener("click", () => {
      close();
      openUploadPanel(t.label);
    });
    actions.append(up);
  }
  if (t.can_edit) {
    const pick = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", hidden: true });
    const change = document.createElement("button");
    change.type = "button";
    change.className = "btn btn-secondary btn-sm";
    change.innerHTML = `${Icons.image}<span>Change banner</span>`;
    change.addEventListener("click", () => pick.click());
    pick.addEventListener("change", async () => {
      if (!pick.files.length) return;
      setButtonLoading(change, true, "Saving");
      try {
        const res = t.folder_id
          ? await Api.setGuideFolderBanner(t.folder_id, pick.files[0])
          : await Api.createGuideFolder(t.label, pick.files[0]);
        Object.assign(t, res.type);
        banner.src = t.banner_url;
        showToast("Banner updated.");
        loadTypes();
      } catch (err) {
        showToast(err.message, true);
      } finally {
        setButtonLoading(change, false);
      }
    });
    actions.append(change, pick);
  }
  const list = document.createElement("div");
  list.className = "guide-list folder-list";
  list.innerHTML = `<p class="text-sm">Loading…</p>`;
  body.append(...(actions.children.length ? [actions] : []), list);
  overlay.querySelector(".modal-close").focus();

  try {
    const data = await Api.searchCourseGuides({ doc_type: t.value });
    const guides = data.course_guides || [];
    if (guides.length) list.replaceChildren(...guides.map(guideRow));
    else list.innerHTML = `<p class="text-sm">Nothing in this folder yet.${isStaff ? " Upload the first one." : ""}</p>`;
  } catch (err) {
    list.innerHTML = "";
    list.append(Object.assign(document.createElement("p"), { className: "text-sm", textContent: err.message }));
  }
}

// A teacher's own folder: a name and, if they like, a banner picture.
function openNewFolder() {
  const { body, close } = dialog("New folder");
  body.innerHTML = `
    <form class="folder-form" novalidate>
      <div class="field">
        <label for="folder-name">Folder name</label>
        <input type="text" id="folder-name" maxlength="60" autocomplete="off" placeholder="e.g. Learning Activity Sheets" />
      </div>
      <div class="field">
        <label for="folder-banner">Banner picture (optional)</label>
        <input type="file" id="folder-banner" accept="image/*" />
      </div>
      <p class="folder-form-error" role="alert" hidden></p>
      <div class="folder-form-actions">
        <button type="button" class="btn btn-secondary folder-cancel">Cancel</button>
        <button type="submit" class="btn btn-primary folder-create">Create folder</button>
      </div>
    </form>`;
  const form = body.querySelector("form");
  const name = body.querySelector("#folder-name");
  const file = body.querySelector("#folder-banner");
  const error = body.querySelector(".folder-form-error");
  let preview = null;
  // The chosen picture, cropped the way its box will show it.
  file.addEventListener("change", () => {
    if (preview) preview.remove();
    preview = file.files.length
      ? Object.assign(document.createElement("img"), { className: "folder-banner-preview", alt: "", src: URL.createObjectURL(file.files[0]) })
      : null;
    if (preview) file.after(preview);
  });
  body.querySelector(".folder-cancel").addEventListener("click", close);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!name.value.trim()) {
      error.textContent = "Give the folder a name.";
      error.hidden = false;
      name.focus();
      return;
    }
    const btn = body.querySelector(".folder-create");
    setButtonLoading(btn, true, "Creating");
    try {
      await Api.createGuideFolder(name.value.trim(), file.files[0]);
      close();
      showToast("Folder created.");
      loadTypes();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      setButtonLoading(btn, false);
    }
  });
  name.focus();
}

newFolderBtn.addEventListener("click", openNewFolder);

// ---- search and type: a list across folders ----
function currentFilters() {
  return { q: searchInput.value.trim(), doc_type: typeFilter.value };
}

function hasFilters() {
  const f = currentFilters();
  return !!(f.q || f.doc_type);
}

function renderResults(guides) {
  const official = guides.filter((g) => g.is_builtin);
  const shared = guides.filter((g) => !g.is_builtin);
  officialGrid.replaceChildren(...official.map(guideRow));
  resultsGrid.replaceChildren(...shared.map(guideRow));
  officialSection.hidden = !official.length;
  sharedSection.hidden = !shared.length;
  resultsEmpty.hidden = guides.length > 0;
  clearFiltersBtn.hidden = false;
  resultsEmpty.querySelector("h2").textContent = "No guides match";
  resultsEmpty.querySelector("p").textContent = "Try other words or another type, or clear the search to see every folder.";
}

// With nothing searched the folders show; a search or a type shows the list.
let searchSeq = 0;
async function runSearch() {
  const seq = ++searchSeq;
  errorBox.hidden = true;
  const browsing = !hasFilters();
  folderGrid.hidden = !browsing;
  if (browsing) {
    officialSection.hidden = sharedSection.hidden = resultsEmpty.hidden = true;
    return;
  }
  try {
    const data = await Api.searchCourseGuides(currentFilters());
    // A slower earlier response must not overwrite a newer one.
    if (seq === searchSeq) renderResults(data.course_guides || []);
  } catch (err) {
    showError(err.message);
  }
}

typeFilter.addEventListener("change", runSearch);
let searchTimer = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 250);
});
clearFiltersBtn.addEventListener("click", () => {
  searchInput.value = "";
  typeFilter.value = "";
  runSearch();
});

// ---- uploading ----
function openUploadPanel(typeLabel) {
  uploadPanel.hidden = false;
  uploadToggleBtn.setAttribute("aria-expanded", "true");
  if (typeLabel !== undefined) uploadType.value = typeLabel;
  uploadPanel.scrollIntoView({ behavior: "smooth", block: "center" });
  uploadSubject.focus({ preventScroll: true });
}

uploadToggleBtn.addEventListener("click", () => {
  if (uploadPanel.hidden) openUploadPanel();
  else {
    uploadPanel.hidden = true;
    uploadToggleBtn.setAttribute("aria-expanded", "false");
  }
});

cgDropzone.addEventListener("click", () => cgFileInput.click());
cgDropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  cgDropzone.classList.add("dragover");
});
cgDropzone.addEventListener("dragleave", () => cgDropzone.classList.remove("dragover"));
cgDropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  cgDropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]);
});
cgFileInput.addEventListener("change", () => {
  if (cgFileInput.files.length) handleUpload(cgFileInput.files[0]);
});

async function handleUpload(file) {
  const allowed = /\.(docx|dotx|pdf)$/i;
  if (!allowed.test(file.name)) {
    showError("Only .docx, .dotx, or .pdf files are allowed.");
    return;
  }
  const subject = uploadSubject.value.trim();
  if (!subject) {
    showError("Enter a subject first, so this course guide can be filed correctly.");
    return;
  }

  errorBox.hidden = true;
  cgDropzone.style.opacity = "0.5";
  cgDropzone.style.pointerEvents = "none";
  try {
    const res = await Api.uploadCourseGuide(file, subject, uploadTitle.value.trim() || file.name, uploadType.value.trim());
    showToast(res.duplicate ? "That guide is already in the library." : "Course guide added to the shared library.");
    uploadPanel.hidden = true;
    uploadToggleBtn.setAttribute("aria-expanded", "false");
    uploadSubject.value = "";
    uploadTitle.value = "";
    uploadType.value = "";
    cgFileInput.value = "";
    await loadTypes();
    runSearch();
  } catch (err) {
    showError(err.message);
  } finally {
    cgDropzone.style.opacity = "1";
    cgDropzone.style.pointerEvents = "auto";
  }
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  wireTopbar(user);
  isStaff = user.role !== "student";
  newFolderBtn.hidden = !isStaff;
  await loadTypes();
  runSearch();
}

init();
