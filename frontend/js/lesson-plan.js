const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const grid = document.getElementById("format-grid");
const errorBox = document.getElementById("error-box");
const searchRow = document.getElementById("format-search-row");
const searchInput = document.getElementById("format-search");
const draftsStrip = document.getElementById("drafts-strip");
const draftsList = document.getElementById("drafts-list");

let currentUser = null;
let allFormats = [];

searchInput.addEventListener("input", () => renderFormats(allFormats));

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("lesson-plan");

document.getElementById("new-format-btn").addEventListener("click", () => {
  window.location.href = "format-builder.html";
});


document.addEventListener("click", () => {
  document.querySelectorAll(".row-menu-dropdown.open").forEach((m) => m.classList.remove("open"));
});

function renderFormats(formats) {
  loadingState.hidden = true;
  allFormats = formats;
  searchRow.hidden = !formats.length;

  const query = searchInput.value.trim().toLowerCase();
  const shown = query ? formats.filter((f) => f.name.toLowerCase().includes(query)) : formats;

  if (!shown.length) {
    emptyState.querySelector("h3").textContent = query ? "No matching formats" : "No formats yet";
    emptyState.querySelector("p").textContent = query
      ? `No format name matches "${searchInput.value.trim()}".`
      : "Add a lesson plan format, such as your school's DLP or SDLP, to start generating plans.";
    emptyState.hidden = false;
    grid.hidden = true;
    return;
  }

  emptyState.hidden = true;
  grid.hidden = false;
  grid.innerHTML = "";

  shown.forEach((fmt) => {
    const isOwner = currentUser && fmt.owner_id === currentUser.id;
    const hasMenu = isOwner || fmt.has_source_file;
    const card = document.createElement("div");
    card.className = "format-card";
    card.innerHTML = `
      <div class="format-card-top">
        <div class="format-card-heading">
          <h3>${escapeHtml(fmt.name)}</h3>
          <span class="badge${fmt.is_public ? "" : " badge-neutral"}">${fmt.is_public ? "Public" : "Private"}</span>
        </div>
        ${
          hasMenu
            ? `<div class="row-menu">
                <button class="row-menu-btn" type="button">&hellip;</button>
                <div class="row-menu-dropdown">
                  ${fmt.has_source_file ? `<button type="button" data-action="source">View original file</button>` : ""}
                  ${isOwner ? `<button type="button" data-action="edit">Edit</button>` : ""}
                  ${isOwner ? `<button type="button" data-action="delete" class="danger">Delete</button>` : ""}
                </div>
              </div>`
            : ""
        }
      </div>
      <p class="format-card-meta">Added ${new Date(fmt.created_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })}${isOwner ? "" : ` &middot; by ${escapeHtml(fmt.owner_name || "another teacher")}`}</p>
      <button class="btn btn-primary btn-block format-card-cta" type="button" data-action="use">Use this format</button>
    `;

    card.querySelector('[data-action="use"]').addEventListener("click", () => {
      window.location.href = `generator.html?format_id=${fmt.id}`;
    });

    const menuBtn = card.querySelector(".row-menu-btn");
    if (menuBtn) {
      // Set via the DOM API rather than interpolated into the HTML string —
      // escapeHtml() only escapes &, <, > for text-node context, so a format
      // name containing a literal " could otherwise break out of the
      // aria-label attribute.
      menuBtn.setAttribute("aria-label", `More actions for ${fmt.name}`);
      const menu = card.querySelector(".row-menu-dropdown");
      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        document.querySelectorAll(".row-menu-dropdown.open").forEach((m) => {
          if (m !== menu) m.classList.remove("open");
        });
        menu.classList.toggle("open");
      });
    }

    const sourceBtn = card.querySelector('[data-action="source"]');
    if (sourceBtn) {
      sourceBtn.addEventListener("click", () => {
        window.open(Api.formatSourceUrl(fmt.id), "_blank", "noopener");
      });
    }
    const editBtn = card.querySelector('[data-action="edit"]');
    if (editBtn) {
      editBtn.addEventListener("click", () => {
        window.location.href = `format-builder.html?format_id=${fmt.id}`;
      });
    }
    const deleteBtn = card.querySelector('[data-action="delete"]');
    if (deleteBtn) {
      deleteBtn.addEventListener("click", () => deleteFormat(fmt.id, deleteBtn));
    }
    grid.appendChild(card);
  });

  const tile = document.createElement("button");
  tile.className = "new-format-tile";
  tile.innerHTML = `<span class="plus">+</span><span>New format</span>`;
  tile.addEventListener("click", () => (window.location.href = "format-builder.html"));
  grid.appendChild(tile);
}

async function deleteFormat(id, btn) {
  if (!confirm("Delete this format permanently? This can't be undone.")) return;
  setButtonLoading(btn, true, "Deleting");
  try {
    await Api.deleteFormat(id);
    showToast("Format deleted.");
    const data = await Api.listFormats();
    renderFormats(data.formats || []);
  } catch (err) {
    showToast(err.message, true);
    setButtonLoading(btn, false);
  }
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  currentUser = user;
  wireTopbar(user);

  // First step of making a lesson plan: choosing the format everything else
  // follows from.
  OwlGuide.show("plan-formats");

  // Kicked off alongside the formats rather than after them: the strip is
  // independent of the picker, so one shouldn't wait on the other.
  loadDrafts();

  try {
    const data = await Api.listFormats();
    renderFormats(data.formats || []);
  } catch (err) {
    loadingState.hidden = true;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

init();

// ---- Unfinished work ------------------------------------------------------
// A teacher's last few drafts, shown above the format picker so resuming is
// the first thing on the page rather than something to go hunting for in the
// plan list. Drafts are whatever the generator autosaved and nobody has
// submitted yet, newest edit first.

const DRAFTS_SHOWN = 4;

function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// How much of the plan is filled in, so a card says what is actually left to
// do rather than just when it was touched.
function draftProgress(plan) {
  const values = plan.field_values || {};
  const filled = Object.values(values).filter((v) => {
    if (Array.isArray(v)) return v.some((item) => String(item).trim());
    return String(v == null ? "" : v).trim();
  }).length;
  const total = Object.keys(values).length;
  // Editing the document body is real work on the plan, so a card must not
  // report "nothing filled in yet" over it. It counts separately from the AI
  // fields because the two are different kinds of progress.
  const edits = (plan.doc_edits || []).length;
  const editNote = edits ? `${edits} document edit${edits === 1 ? "" : "s"}` : "";

  if (!total) return editNote || "Nothing filled in yet";
  const fieldNote = filled === total
    ? `All ${total} fields filled in`
    : `${filled} of ${total} fields filled in`;
  return editNote ? `${fieldNote}, ${editNote}` : fieldNote;
}

function renderDrafts(plans) {
  if (!plans.length) {
    draftsStrip.hidden = true;
    return;
  }

  draftsStrip.hidden = false;
  draftsList.innerHTML = "";

  plans.forEach((plan) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "draft-card";
    card.innerHTML = `
      <span class="draft-card-title">${escapeHtml(plan.title || "Untitled lesson plan")}</span>
      <span class="draft-card-meta">${escapeHtml(draftProgress(plan))}</span>
      <span class="draft-card-time">Edited ${escapeHtml(relativeTime(plan.updated_at))}</span>`;
    card.addEventListener("click", () => {
      window.location.href = `generator.html?plan_id=${plan.id}`;
    });
    draftsList.appendChild(card);
  });
}

async function loadDrafts() {
  try {
    const data = await Api.listLessonPlans({ status: "draft", limit: DRAFTS_SHOWN });
    renderDrafts(data.lesson_plans || []);
  } catch (err) {
    // The format picker below is the point of this page, so a failure here
    // stays silent rather than showing an error for a convenience strip.
    draftsStrip.hidden = true;
  }
}
