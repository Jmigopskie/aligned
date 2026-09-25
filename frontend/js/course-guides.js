const errorBox = document.getElementById("error-box");
const subjectInput = document.getElementById("subject-input");
const searchBtn = document.getElementById("search-btn");
const resultsGrid = document.getElementById("results-grid");
const resultsEmpty = document.getElementById("results-empty");
const uploadToggleBtn = document.getElementById("upload-toggle-btn");
const uploadPanel = document.getElementById("upload-panel");
const uploadSubject = document.getElementById("upload-subject");
const uploadTitle = document.getElementById("upload-title");
const cgDropzone = document.getElementById("cg-dropzone");
const cgFileInput = document.getElementById("cg-file-input");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("course-guides");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function renderResults(guides, searchedSubject) {
  if (!guides.length) {
    resultsGrid.hidden = true;
    resultsEmpty.hidden = false;
    if (searchedSubject) {
      resultsEmpty.querySelector("h3").textContent = "No course guides found";
      resultsEmpty.querySelector("p").textContent = "No one has shared a guide for this topic yet. Be the first to upload one.";
    } else {
      resultsEmpty.querySelector("h3").textContent = "No course guides yet";
      resultsEmpty.querySelector("p").textContent = "Be the first to upload a TLE-ICT course guide for other teachers to use.";
    }
    return;
  }
  resultsEmpty.hidden = true;
  resultsGrid.hidden = false;
  resultsGrid.innerHTML = guides
    .map(
      (g) => `
      <div class="format-card">
        <div class="format-card-top">
          <h3>${escapeHtml(g.title)}</h3>
          <span class="badge">${escapeHtml(g.subject)}</span>
        </div>
        <p class="format-card-meta">Uploaded by ${escapeHtml(g.uploaded_by || "a teacher")} &middot; ${fmtDate(g.created_at)}</p>
      </div>`
    )
    .join("");
}

async function runSearch() {
  const subject = subjectInput.value.trim();
  errorBox.hidden = true;
  setButtonLoading(searchBtn, true, "Searching");
  try {
    const data = await Api.searchCourseGuides(subject);
    renderResults(data.course_guides || [], subject);
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(searchBtn, false);
  }
}

searchBtn.addEventListener("click", runSearch);
subjectInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

uploadToggleBtn.addEventListener("click", () => {
  uploadPanel.hidden = !uploadPanel.hidden;
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
    await Api.uploadCourseGuide(file, subject, uploadTitle.value.trim() || file.name);
    showToast("Course guide added to the shared library.");
    subjectInput.value = subject;
    uploadPanel.hidden = true;
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
