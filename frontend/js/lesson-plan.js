const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const errorBox = document.getElementById("error-box");
const searchInput = document.getElementById("format-search");
const draftsStrip = document.getElementById("drafts-strip");
const draftsList = document.getElementById("drafts-list");

// Three shelves: the ready-made formats everyone gets, the teacher's own, and
// whatever other teachers chose to share. Built-ins come first because a new
// teacher has nothing else yet, and most schools use one of them anyway.
const sections = {
  builtin: { section: document.getElementById("builtin-section"), grid: document.getElementById("builtin-grid") },
  mine: { section: document.getElementById("mine-section"), grid: document.getElementById("mine-grid") },
  shared: { section: document.getElementById("shared-section"), grid: document.getElementById("shared-grid") },
};
const mineEmpty = document.getElementById("mine-empty");

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

function shelfOf(fmt) {
  if (fmt.is_builtin) return "builtin";
  return currentUser && fmt.owner_id === currentUser.id ? "mine" : "shared";
}

function matches(fmt, query) {
  if (!query) return true;
  return `${fmt.name} ${fmt.description || ""}`.toLowerCase().includes(query);
}

function fmtAdded(iso) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function useFormat(fmt) {
  window.location.href = `generator.html?format_id=${fmt.id}`;
}

function openOriginal(fmt) {
  window.open(`${Api.formatSourceUrl(fmt.id)}?inline=1`, "_blank", "noopener");
}

// A built-in shows its first page, so a teacher recognises the layout their
// school hands out before reading a single word. It has no menu: there is
// nothing to edit or delete.
function builtinCard(fmt) {
  const card = document.createElement("article");
  card.className = "format-card is-builtin";
  card.innerHTML = `
    <div class="format-thumb-wrap">
      <button type="button" class="format-thumb-frame" data-action="use" tabindex="-1" aria-hidden="true">
        <img class="format-thumb" src="${fmt.thumbnail}" alt="" loading="lazy" width="480" height="679" />
      </button>
      <span class="badge badge-lock" title="Built-in formats can't be edited or deleted">${Icons.lock}Built-in</span>
    </div>
    <div class="format-card-body">
      <h3></h3>
      <p class="format-card-desc"></p>
      <p class="format-card-meta">${fmt.field_count} fields</p>
    </div>
    <div class="format-card-actions">
      <button class="btn btn-primary" type="button" data-action="use">Use this format</button>
      <button class="btn btn-secondary" type="button" data-action="source"><span data-icon="externalLink"></span>View original</button>
    </div>`;
  card.querySelector("h3").textContent = fmt.name;
  card.querySelector(".format-card-desc").textContent = fmt.description || "";
  card.querySelectorAll('[data-action="use"]').forEach((b) => b.addEventListener("click", () => useFormat(fmt)));
  card.querySelector('[data-action="source"]').addEventListener("click", () => openOriginal(fmt));
  hydrateIcons(card);
  return card;
}

function teacherCard(fmt) {
  const isOwner = currentUser && fmt.owner_id === currentUser.id;
  const hasMenu = isOwner || fmt.has_source_file;
  const card = document.createElement("article");
  card.className = "format-card";
  card.innerHTML = `
    <div class="format-card-top">
      <div class="format-card-heading">
        <h3></h3>
        <span class="badge${fmt.is_public ? "" : " badge-neutral"}">${fmt.is_public ? "Public" : "Private"}</span>
      </div>
      ${
        hasMenu
          ? `<div class="row-menu">
              <button class="row-menu-btn" type="button" title="More actions">${Icons.moreHorizontal}</button>
              <div class="row-menu-dropdown">
                ${fmt.has_source_file ? `<button type="button" data-action="source">View original file</button>` : ""}
                ${isOwner ? `<button type="button" data-action="edit">Edit</button>` : ""}
                ${isOwner ? `<button type="button" data-action="delete" class="danger">Delete</button>` : ""}
              </div>
            </div>`
          : ""
      }
    </div>
    <p class="format-card-meta">${fmt.field_count} fields &middot; added ${fmtAdded(fmt.created_at)}${
      isOwner ? "" : ` &middot; by ${escapeHtml(fmt.owner_name || "another teacher")}`
    }</p>
    <button class="btn btn-primary btn-block format-card-cta" type="button" data-action="use">Use this format</button>`;
  card.querySelector("h3").textContent = fmt.name;
  card.querySelector('[data-action="use"]').addEventListener("click", () => useFormat(fmt));

  const menuBtn = card.querySelector(".row-menu-btn");
  if (menuBtn) {
    // Set via the DOM API rather than interpolated into the HTML string:
    // escapeHtml() only escapes &, <, > for text-node context, so a format
    // name containing a literal " could otherwise break out of the attribute.
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
  if (sourceBtn) sourceBtn.addEventListener("click", () => openOriginal(fmt));
  const editBtn = card.querySelector('[data-action="edit"]');
  if (editBtn) {
    editBtn.addEventListener("click", () => {
      window.location.href = `format-builder.html?format_id=${fmt.id}`;
    });
  }
  const deleteBtn = card.querySelector('[data-action="delete"]');
  if (deleteBtn) deleteBtn.addEventListener("click", () => deleteFormat(fmt.id, deleteBtn));
  return card;
}

function newFormatTile() {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "new-format-tile";
  tile.innerHTML = `<span class="new-format-tile-icon">${Icons.plus}</span><span>New format</span>`;
  tile.addEventListener("click", () => (window.location.href = "format-builder.html"));
  return tile;
}

function renderFormats(formats) {
  loadingState.hidden = true;
  allFormats = formats;

  const query = searchInput.value.trim().toLowerCase();
  const shelves = { builtin: [], mine: [], shared: [] };
  formats.forEach((f) => shelves[shelfOf(f)].push(f));
  // Built-ins keep the order they were seeded in, so they never shuffle
  // between visits; the teacher shelves stay newest first.
  shelves.builtin.sort((a, b) => a.id - b.id);

  let shownAnywhere = 0;
  Object.entries(sections).forEach(([key, { section, grid }]) => {
    const shown = shelves[key].filter((f) => matches(f, query));
    shownAnywhere += shown.length;
    grid.innerHTML = "";
    shown.forEach((f) => grid.appendChild(key === "builtin" ? builtinCard(f) : teacherCard(f)));

    if (key === "mine") {
      // Your own shelf stays visible while browsing, empty or not, since it
      // is where a new format would land. A search that matches none of
      // yours hides it like any other shelf.
      const hasOwn = shelves.mine.length > 0;
      mineEmpty.hidden = hasOwn || !!query;
      if (hasOwn && !query) grid.appendChild(newFormatTile());
      grid.hidden = !grid.children.length;
      section.hidden = query ? shown.length === 0 : false;
    } else {
      section.hidden = shown.length === 0;
    }
  });

  emptyState.hidden = !(query && shownAnywhere === 0);
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
