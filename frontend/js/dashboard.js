const errorBox = document.getElementById("error-box");
const recentBody = document.getElementById("recent-plans-body");

document.getElementById("icon-todo").innerHTML = Icons.checkSquare;
document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("dashboard");

// Hero action buttons keep their text label — this prepends the icon
// instead of the generic [data-icon] pattern (used elsewhere for icon-only
// buttons), which replaces the element's content outright.
document.querySelectorAll(".hero-actions .btn[data-icon]").forEach((btn) => {
  const icon = Icons[btn.dataset.icon];
  if (icon) btn.insertAdjacentHTML("afterbegin", icon);
});


function greetingForNow(firstName) {
  const hour = new Date().getHours();
  const time = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  return `${time}, ${firstName}`;
}

const TODO_KEY = "aligned_todo_v1";

function loadTodos() {
  try {
    const raw = localStorage.getItem(TODO_KEY);
    if (raw) return JSON.parse(raw);
  } catch (err) {

  }
  const defaults = [
    { text: "Finish lesson plan for Computer Systems Servicing", done: false },
    { text: "Review Web Development learning objectives", done: false },
    { text: "Prepare TLE-ICT materials for next week", done: false },
  ];
  localStorage.setItem(TODO_KEY, JSON.stringify(defaults));
  return defaults;
}

function saveTodos(todos) {
  localStorage.setItem(TODO_KEY, JSON.stringify(todos));
}

function renderTodos() {
  const todos = loadTodos();
  const list = document.getElementById("todo-list");
  if (!todos.length) {
    list.innerHTML = `<p class="todo-empty">Nothing on your list yet.</p>`;
    return;
  }
  list.innerHTML = todos
    .map(
      (t, i) => `
      <div class="todo-item ${t.done ? "done" : ""}">
        <input type="checkbox" data-idx="${i}" ${t.done ? "checked" : ""} />
        <span>${escapeHtml(t.text)}</span>
      </div>`
    )
    .join("");
  list.querySelectorAll("input[type='checkbox']").forEach((cb) => {
    cb.addEventListener("change", () => {
      const todos2 = loadTodos();
      todos2[+cb.dataset.idx].done = cb.checked;
      saveTodos(todos2);
      renderTodos();
    });
  });
}

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function renderRecentPlans(plans) {
  if (!plans.length) {
    recentBody.innerHTML = `
      <tr class="table-empty-row">
        <td colspan="5">No lesson plans yet. <a href="lesson-plan.html">Create your first one</a>.</td>
      </tr>`;
    return;
  }

  const recent = [...plans]
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    .slice(0, 5);

  recentBody.innerHTML = recent
    .map(
      (p) => `
      <tr>
        <td>
          <div class="plan-title-cell">
            <span class="file-ico">${Icons.file}</span>
            <span>${escapeHtml(p.title)}</span>
          </div>
        </td>
        <td>${escapeHtml(p.subject || "\u2013")}</td>
        <td>${escapeHtml(p.grade_level || "\u2013")}</td>
        <td>${fmtDate(p.updated_at)}</td>
        <td>
          <div class="row-menu">
            <button class="row-menu-btn" type="button" data-plan="${p.id}" aria-label="More actions" title="More actions">${Icons.moreHorizontal}</button>
            <div class="row-menu-dropdown" data-menu="${p.id}">
              <button type="button" data-action="export" data-plan="${p.id}">Export as Word</button>
              <button type="button" data-action="delete" data-plan="${p.id}" class="danger">Delete</button>
            </div>
          </div>
        </td>
      </tr>`
    )
    .join("");

  wireRowMenus();
}

function wireRowMenus() {
  document.querySelectorAll(".row-menu-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const menu = document.querySelector(`.row-menu-dropdown[data-menu="${btn.dataset.plan}"]`);
      document.querySelectorAll(".row-menu-dropdown.open").forEach((m) => {
        if (m !== menu) m.classList.remove("open");
      });
      menu.classList.toggle("open");
    });
  });

  document.querySelectorAll(".row-menu-dropdown button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const planId = btn.dataset.plan;
      if (btn.dataset.action === "export") {
        window.open(Api.exportUrl(planId), "_blank", "noopener");
      } else if (btn.dataset.action === "delete") {
        if (!confirm("Delete this lesson plan? This can't be undone.")) return;
        try {
          await Api.deleteLessonPlan(planId);
          showToast("Lesson plan deleted.");
          init();
        } catch (err) {
          showToast(err.message, true);
        }
      }
    });
  });

  document.addEventListener("click", () => {
    document.querySelectorAll(".row-menu-dropdown.open").forEach((m) => m.classList.remove("open"));
  });
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role === "admin") {
    window.location.href = "admin-dashboard.html";
    return;
  }
  wireTopbar(user);
  renderTodos();

  document.querySelectorAll(".js-role-action").forEach((el) => {
    el.hidden = el.dataset.role !== user.role;
  });

  const firstName = (user.full_name || "").split(" ")[0] || "there";
  document.getElementById("hero-greeting").textContent = greetingForNow(firstName);

  // Teachers see their own banner; students see whichever teacher's section
  // they most recently joined (see User.effective_banner on the backend) —
  // falls back to the default illustration when neither has set one.
  if (user.banner_url) {
    document.getElementById("hero-banner-img").src = user.banner_url;
  }

  try {
    const data = await Api.listLessonPlans();
    renderRecentPlans(data.lesson_plans || []);
  } catch (err) {
    recentBody.innerHTML = `<tr class="table-empty-row"><td colspan="5">Couldn't load lesson plans.</td></tr>`;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

init();
