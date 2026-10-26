// Built-in formats, run by the admin: rework each one's fields (and what goes
// in each) in the format builder, then switch it On so teachers and students
// see it. On hold keeps it out of their lists; plans already made with it
// still open.
document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("admin-formats");

const errorBox = document.getElementById("error-box");
const formatsBody = document.getElementById("formats-body");

function fmtRow(f) {
  const name = escapeHtml(f.name || "Untitled format");
  const count = f.field_count || 0;
  return `
    <tr>
      <td>
        <span class="fmt-name">${name}</span>
        ${f.description ? `<span class="fmt-desc">${escapeHtml(f.description)}</span>` : ""}
      </td>
      <td data-label="Fields">${count}</td>
      <td data-label="Fields reviewed">${
        f.fields_reviewed
          ? `<span class="fmt-reviewed is-done">Reviewed</span>`
          : `<span class="fmt-reviewed">Not yet</span>`
      }</td>
      <td data-label="Status">
        <div class="fmt-switch-cell">
          <button type="button" class="fmt-switch" role="switch" aria-checked="${f.available ? "true" : "false"}"
                  data-id="${f.id}" aria-label="Show ${name} to teachers and students"></button>
          ${f.available
            ? `<span class="status-pill reviewed">On</span>`
            : `<span class="status-pill draft">On hold</span>`}
        </div>
      </td>
      <td data-label="Actions">
        <a class="btn btn-secondary btn-sm" href="format-builder.html?id=${f.id}"
           aria-label="Edit the fields of ${name}"><span data-icon="edit"></span>Edit fields</a>
      </td>
    </tr>`;
}

function render(formats) {
  if (!formats.length) {
    formatsBody.innerHTML = `<tr class="table-empty-row"><td colspan="5">No built-in formats yet. Upload one to get started.</td></tr>`;
    return;
  }
  formatsBody.innerHTML = formats.map(fmtRow).join("");
  hydrateIcons(formatsBody);
}

let formats = [];

async function load() {
  errorBox.hidden = true;
  try {
    const data = await Api.adminBuiltinFormats();
    formats = data.formats || [];
    render(formats);
  } catch (err) {
    formatsBody.innerHTML = `<tr class="table-empty-row"><td colspan="5">Couldn't load the built-in formats.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

formatsBody.addEventListener("click", async (e) => {
  const sw = e.target.closest(".fmt-switch");
  if (!sw) return;
  const id = Number(sw.dataset.id);
  const turnOn = sw.getAttribute("aria-checked") !== "true";
  if (!turnOn && !confirm("Teachers and students will stop seeing this format. Plans already made with it still open.")) return;
  sw.disabled = true;
  try {
    const data = await Api.setFormatAvailability(id, turnOn);
    formats = formats.map((f) => (f.id === id ? { ...f, ...data.format } : f));
    render(formats);
    const name = (formats.find((f) => f.id === id) || {}).name || "Format";
    showToast(turnOn ? `${name} is On: teachers and students can use it.` : `${name} is on hold.`);
    const again = formatsBody.querySelector(`.fmt-switch[data-id="${id}"]`);
    if (again) again.focus();
  } catch (err) {
    sw.disabled = false;
    showToast(err.message, true);
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
  hydrateIcons(document.querySelector(".page-actions"));
  load();
}

init();
