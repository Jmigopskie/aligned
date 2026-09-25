const errorBox = document.getElementById("error-box");
const searchInput = document.getElementById("subject-input");
const gradeChips = document.getElementById("grade-chips");
const subjectFilter = document.getElementById("subject-filter");
const typeFilter = document.getElementById("type-filter");
const officialSection = document.getElementById("official-guides-section");
const officialGrid = document.getElementById("official-grid");
const sharedSection = document.getElementById("shared-guides-section");
const resultsGrid = document.getElementById("results-grid");
const resultsEmpty = document.getElementById("results-empty");
const clearFiltersBtn = document.getElementById("clear-filters-btn");
const uploadToggleBtn = document.getElementById("upload-toggle-btn");
const uploadPanel = document.getElementById("upload-panel");
const uploadSubject = document.getElementById("upload-subject");
const uploadTitle = document.getElementById("upload-title");
const cgDropzone = document.getElementById("cg-dropzone");
const cgFileInput = document.getElementById("cg-file-input");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("course-guides");

const DOC_TYPE_LABELS = { budget_of_work: "Budget of Work", curriculum_guide: "Curriculum Guide" };

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

function pressed(group) {
  const btn = group.querySelector('[aria-pressed="true"]');
  return btn ? btn.dataset.band ?? btn.dataset.subject ?? "" : "";
}

function currentFilters() {
  return {
    q: searchInput.value.trim(),
    grade_band: pressed(gradeChips),
    subject: pressed(subjectFilter),
    doc_type: typeFilter.value,
  };
}

function hasFilters() {
  const f = currentFilters();
  return !!(f.q || f.grade_band || f.subject || f.doc_type);
}

function guideRow(g) {
  const row = document.createElement("article");
  row.className = `guide-card${g.is_builtin ? " is-official" : ""}`;
  const meta = g.is_builtin
    ? [DOC_TYPE_LABELS[g.doc_type], gradesLabel(g.grades), g.curriculum, g.retrieved_at ? `Retrieved ${fmtDate(g.retrieved_at)}` : ""]
    : [g.subject, `Shared by ${g.uploaded_by || "a teacher"}`, fmtDate(g.created_at)];
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

function renderResults(guides) {
  const official = guides.filter((g) => g.is_builtin);
  const shared = guides.filter((g) => !g.is_builtin);

  officialGrid.replaceChildren(...official.map(guideRow));
  resultsGrid.replaceChildren(...shared.map(guideRow));
  officialSection.hidden = !official.length;
  sharedSection.hidden = !shared.length;

  const filtered = hasFilters();
  resultsEmpty.hidden = guides.length > 0;
  clearFiltersBtn.hidden = !filtered;
  resultsEmpty.querySelector("h3").textContent = filtered ? "No guides match these filters" : "No course guides yet";
  resultsEmpty.querySelector("p").textContent = filtered
    ? "Try another grade or subject, or clear the filters to see every guide."
    : "Be the first to upload a course guide for other teachers to use.";
}

let searchSeq = 0;
async function runSearch() {
  const seq = ++searchSeq;
  errorBox.hidden = true;
  try {
    const data = await Api.searchCourseGuides(currentFilters());
    // A slower earlier response must not overwrite a newer one.
    if (seq === searchSeq) renderResults(data.course_guides || []);
  } catch (err) {
    showError(err.message);
  }
}

function wireChips(group) {
  group.addEventListener("click", (e) => {
    const btn = e.target.closest("button.chip");
    if (!btn) return;
    group.querySelectorAll("button.chip").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    runSearch();
  });
}
wireChips(gradeChips);
wireChips(subjectFilter);
typeFilter.addEventListener("change", runSearch);

let searchTimer = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 250);
});

clearFiltersBtn.addEventListener("click", () => {
  searchInput.value = "";
  typeFilter.value = "";
  [gradeChips, subjectFilter].forEach((group) =>
    group.querySelectorAll("button.chip").forEach((b, i) => b.setAttribute("aria-pressed", String(i === 0))));
  runSearch();
});

uploadToggleBtn.addEventListener("click", () => {
  uploadPanel.hidden = !uploadPanel.hidden;
  uploadToggleBtn.setAttribute("aria-expanded", String(!uploadPanel.hidden));
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
    const res = await Api.uploadCourseGuide(file, subject, uploadTitle.value.trim() || file.name);
    showToast(res.duplicate ? "That guide is already in the library." : "Course guide added to the shared library.");
    searchInput.value = subject;
    uploadPanel.hidden = true;
    uploadToggleBtn.setAttribute("aria-expanded", "false");
    uploadSubject.value = "";
    uploadTitle.value = "";
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
  runSearch();
}

init();
