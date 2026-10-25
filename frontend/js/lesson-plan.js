const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const errorBox = document.getElementById("error-box");
const searchInput = document.getElementById("format-search");

// Three shelves: the ready-made formats everyone gets, the teacher's own, and
// whatever other teachers chose to share. Built-ins come first because a new
// teacher has nothing else yet, and most schools use one of them anyway.
const sections = {
  builtin: { section: document.getElementById("builtin-section"), grid: document.getElementById("builtin-grid") },
  mine: { section: document.getElementById("mine-section"), grid: document.getElementById("mine-grid") },
  shared: { section: document.getElementById("shared-section"), grid: document.getElementById("shared-grid") },
};
const mineEmpty = document.getElementById("mine-empty");

// Each shelf folds away under its heading (remembered in this browser), so the
// page isn't one long wall of cards. Your own shelf starts open, the others
// folded; a search opens every shelf it found something on.
const FOLD_KEY = "alignedFormatShelves:v1";
let folded = { builtin: true, mine: false, shared: true };
try {
  folded = { ...folded, ...JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") };
} catch (err) {
  /* private mode: the defaults hold */
}

Object.entries(sections).forEach(([key, shelf]) => {
  const head = shelf.section.querySelector(".format-section-head");
  const title = head.querySelector(".section-title");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "section-toggle";
  btn.setAttribute("aria-controls", `${key}-shelf`);
  btn.innerHTML = `<span class="section-toggle-text"></span><span class="section-count"></span>${Icons.chevronDown}`;
  btn.querySelector(".section-toggle-text").textContent = title.textContent;
  title.replaceChildren(btn);
  const body = document.createElement("div");
  body.id = `${key}-shelf`;
  while (head.nextSibling) body.append(head.nextSibling);
  shelf.section.append(body);
  Object.assign(shelf, { btn, body, note: head.querySelector(".section-note") });
  btn.addEventListener("click", () => {
    folded[key] = btn.getAttribute("aria-expanded") === "true";
    try {
      localStorage.setItem(FOLD_KEY, JSON.stringify(folded));
    } catch (err) {
      /* the choice just won't be remembered */
    }
    showShelf(key, !folded[key]);
  });
});

function showShelf(key, open) {
  const { btn, body, note } = sections[key];
  btn.setAttribute("aria-expanded", String(open));
  body.hidden = !open;
  if (note) note.hidden = !open;
}

let currentUser = null;
let allFormats = [];

searchInput.addEventListener("input", () => renderFormats(allFormats));

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("formats");

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
  // A compact row: the top of page one as a small thumbnail beside the name,
  // so five formats fit on a screen instead of five screens.
  card.innerHTML = `
    <button type="button" class="format-thumb-frame" data-action="use" tabindex="-1" aria-hidden="true">
      <img class="format-thumb" src="${fmt.thumbnail}" alt="" loading="lazy" width="480" height="679" />
    </button>
    <div class="format-card-body">
      <div class="format-card-title-row">
        <h3></h3>
        <span class="badge badge-lock" title="Built-in formats can't be edited or deleted">${Icons.lock}Built-in</span>
      </div>
      <p class="format-card-desc"></p>
      <div class="format-card-foot">
        <span class="format-card-meta">${fmt.field_count} fields</span>
        <button class="btn btn-ghost btn-sm" type="button" data-action="source"><span data-icon="externalLink"></span>View original</button>
        <button class="btn btn-primary btn-sm" type="button" data-action="use">Use this format</button>
      </div>
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
    <div class="format-card-foot">
      <span class="format-card-meta">${fmt.field_count} fields &middot; added ${fmtAdded(fmt.created_at)}${
        isOwner ? "" : ` &middot; by ${escapeHtml(fmt.owner_name || "another teacher")}`
      }</span>
      <button class="btn btn-primary btn-sm" type="button" data-action="use">Use this format</button>
    </div>`;
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
    sections[key].btn.querySelector(".section-count").textContent = String(shelves[key].length);
    showShelf(key, query ? shown.length > 0 : !folded[key]);
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
  // Formats are a teacher's to manage; students start plans from the flow.
  if (user.role === "student") {
    window.location.replace("generator.html");
    return;
  }
  currentUser = user;
  wireTopbar(user);

  // First step of making a lesson plan: choosing the format everything else
  // follows from.
  OwlGuide.show("plan-formats");

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
