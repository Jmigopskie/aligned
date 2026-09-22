const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const grid = document.getElementById("format-grid");
const errorBox = document.getElementById("error-box");
const searchRow = document.getElementById("format-search-row");
const searchInput = document.getElementById("format-search");

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
      : "Add a lesson plan format — DLP, SDLP, ILAP, or your own — to start generating plans.";
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
