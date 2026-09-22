// The archive is this same screen pre-filtered to archived students rather
// than a second page, so which sidebar entry highlights depends on the query
// string the page was opened with.
const initialFilters = new URLSearchParams(window.location.search);
const isArchiveView = initialFilters.get("active") === "0";

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav(isArchiveView ? "admin-archive" : "admin-users");

const errorBox = document.getElementById("error-box");
const usersBody = document.getElementById("users-body");
const roleFilter = document.getElementById("role-filter");
const statusFilter = document.getElementById("status-filter");
const searchInput = document.getElementById("search-input");

const userOverlay = document.getElementById("user-overlay");
const userModalTitle = document.getElementById("user-modal-title");
const userForm = document.getElementById("user-form");
const userIdInput = document.getElementById("user-id");
const userNameInput = document.getElementById("user-name");
const userEmailInput = document.getElementById("user-email");
const userRoleSelect = document.getElementById("user-role");
const userPasswordInput = document.getElementById("user-password");
const userPasswordHint = document.getElementById("user-password-hint");
const userSubmitBtn = document.getElementById("user-submit-btn");
const userModalClose = document.getElementById("user-modal-close");

let currentUser = null;
let searchTimer = null;
// Assigned further down, once the table body it wires into exists. Declared
// here because renderUsers() guards on it and would otherwise hit the
// temporal dead zone of a later declaration instead of seeing undefined.
let bulk = null;

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function roleLabel(role) {
  return role ? role[0].toUpperCase() + role.slice(1) : "\u2013";
}

function renderUsers(users) {
  if (!users.length) {
    usersBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">${
      statusFilter.value === "0" ? "No archived accounts." : "No accounts match."
    }</td></tr>`;
    if (bulk) bulk.sync();
    return;
  }

  usersBody.innerHTML = users
    .map(
      (u) => `
      <tr>
        ${bulkCheckboxCell(u.id, u.full_name)}
        <td>${escapeHtml(u.full_name)}</td>
        <td>${escapeHtml(u.email)}</td>
        <td><span class="badge">${roleLabel(u.role)}</span></td>
        <td>${u.is_active ? `<span class="status-pill reviewed">Active</span>` : `<span class="status-pill draft">Archived</span>`}</td>
        <td>${fmtDate(u.created_at)}</td>
        <td>
          <div class="row-actions">
            <button class="row-action-btn" type="button" data-action="edit" data-id="${u.id}" title="Edit" aria-label="Edit ${escapeHtml(u.full_name)}">${Icons.edit}</button>
            <button class="row-action-btn" type="button" data-action="toggle" data-id="${u.id}" data-active="${u.is_active}" title="${u.is_active ? "Archive" : "Restore"}" aria-label="${u.is_active ? "Archive" : "Restore"} ${escapeHtml(u.full_name)}">${u.is_active ? Icons.archive : Icons.upload}</button>
            <button class="row-action-btn danger" type="button" data-action="delete" data-id="${u.id}" title="Delete" aria-label="Delete ${escapeHtml(u.full_name)}">${Icons.trash}</button>
          </div>
        </td>
      </tr>`
    )
    .join("");

  usersBody.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleAction(btn));
  });

  // Rows were just replaced, so re-apply whatever is still selected.
  if (bulk) bulk.sync();
}

let allUsers = [];

// Ticking rows and archiving them as a batch. Declared up here because
// renderUsers() calls bulk.sync() after every render, including the first.
bulk = initBulkSelect({
  kind: "users",
  tbody: usersBody,
  selectAllEl: document.getElementById("bulk-select-all"),
  barEl: document.getElementById("bulk-bar"),
  countEl: document.getElementById("bulk-count"),
  archiveBtn: document.getElementById("bulk-archive-btn"),
  restoreBtn: document.getElementById("bulk-restore-btn"),
  clearBtn: document.getElementById("bulk-clear-btn"),
  onApplied: () => loadUsers(),
});

async function loadUsers() {
  usersBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Loading&hellip;</td></tr>`;
  try {
    const params = {};
    if (roleFilter.value) params.role = roleFilter.value;
    if (statusFilter.value) params.active = statusFilter.value;
    if (searchInput.value.trim()) params.q = searchInput.value.trim();

    // Mirror the filters into the address bar so this view can be linked,
    // bookmarked and reloaded. replaceState, not pushState: typing in the
    // search box shouldn't bury the previous page under a dozen history
    // entries to click Back through.
    const qs = new URLSearchParams(params).toString();
    history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);

    const data = await Api.adminListUsers(params);
    allUsers = data.users || [];
    renderUsers(allUsers);
  } catch (err) {
    usersBody.innerHTML = `<tr class="table-empty-row"><td colspan="7">Couldn't load accounts.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

async function handleAction(btn) {
  const id = btn.dataset.id;
  const action = btn.dataset.action;

  if (action === "edit") {
    const user = allUsers.find((u) => String(u.id) === id);
    if (user) openUserModal(user);
    return;
  }

  if (action === "toggle") {
    const isActive = btn.dataset.active === "true";
    const prompt = isActive
      ? "Archive this account? The account keeps all of its records but can no longer sign in."
      : "Restore this account? The account will be able to sign in again.";
    if (!confirm(prompt)) return;
    try {
      await Api.adminUpdateUser(id, { is_active: !isActive });
      showToast(isActive ? "Account archived." : "Account restored.");
      loadUsers();
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }

  if (action === "delete") {
    if (!confirm("Delete this account permanently? This can't be undone.")) return;
    try {
      await Api.adminDeleteUser(id);
      showToast("Account deleted.");
      loadUsers();
    } catch (err) {
      showToast(err.message, true);
    }
  }
}

function openUserModal(user) {
  userForm.reset();
  if (user) {
    userModalTitle.textContent = "Edit account";
    userIdInput.value = user.id;
    userNameInput.value = user.full_name;
    userEmailInput.value = user.email;
    userRoleSelect.value = user.role;
    userPasswordHint.textContent = "Leave blank to keep the current password.";
    userPasswordInput.placeholder = "Leave blank to keep current password";
  } else {
    userModalTitle.textContent = "Add account";
    userIdInput.value = "";
    userRoleSelect.value = "teacher";
    userPasswordHint.textContent = "Required for new accounts, at least 8 characters.";
    userPasswordInput.placeholder = "At least 8 characters";
  }
  openDialog(userOverlay);
}

function closeUserModal() {
  closeDialog(userOverlay);
}

// Escape, backdrop click, the focus trap and returning focus to the button
// that opened it all come from wireDialog (api.js).
wireDialog(userOverlay);
document.getElementById("new-user-btn").addEventListener("click", () => openUserModal(null));
userModalClose.addEventListener("click", closeUserModal);

userForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = userIdInput.value;
  const payload = {
    full_name: userNameInput.value.trim(),
    email: userEmailInput.value.trim(),
    role: userRoleSelect.value,
  };
  if (userPasswordInput.value) payload.password = userPasswordInput.value;

  if (!id && !payload.password) {
    showToast("Set a password for the new account.", true);
    return;
  }

  setButtonLoading(userSubmitBtn, true, "Saving");
  try {
    if (id) {
      await Api.adminUpdateUser(id, payload);
    } else {
      await Api.adminCreateUser(payload);
    }
    showToast("Account saved.");
    closeUserModal();
    loadUsers();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(userSubmitBtn, false);
  }
});

roleFilter.addEventListener("change", loadUsers);
statusFilter.addEventListener("change", loadUsers);
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadUsers, 300);
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.href = homeForRole(user.role);
    return;
  }
  currentUser = user;
  wireTopbar(user);

  if (initialFilters.has("role")) roleFilter.value = initialFilters.get("role");
  if (initialFilters.has("active")) statusFilter.value = initialFilters.get("active");
  if (isArchiveView) {
    document.title = "Student Archive — AlignED";
    document.getElementById("page-title").textContent = "Student Archive";
    document.getElementById("page-intro").textContent =
      "Archived accounts can no longer sign in, but their sections, lesson plans and submissions are kept. Restore an account to give it access again.";
  }

  loadUsers();
}

init();
