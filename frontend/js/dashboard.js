const errorBox = document.getElementById("error-box");
const recentBody = document.getElementById("recent-plans-body");

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

function fmtDate(iso) {
  if (!iso) return "\u2013";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// A draft opens where it was left off; a submitted plan is locked, so it
// opens as a preview in the list instead.
function planHref(p) {
  return p.status && p.status !== "draft"
    ? `lesson-plan-list.html?preview=${p.id}`
    : `generator.html?plan_id=${p.id}`;
}

// The whole row opens the plan; the title link is the keyboard way in.
recentBody.addEventListener("click", (e) => {
  const row = e.target.closest("tr.row-link");
  if (!row || e.target.closest("a, button, .row-menu")) return;
  window.location.href = row.dataset.href;
});

function renderRecentPlans(plans) {
  // Column headings over nothing read as a broken table, so they only show
  // once there is a row to label.
  recentBody.closest("table").tHead.hidden = !plans.length;
  if (!plans.length) {
    recentBody.innerHTML = `
      <tr class="table-empty-row">
        <td colspan="5">No lesson plans yet. <a href="generator.html">Create your first one</a>.</td>
      </tr>`;
    return;
  }

  const recent = [...plans]
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    .slice(0, 5);

  recentBody.innerHTML = recent
    .map(
      (p) => `
      <tr class="row-link" data-href="${planHref(p)}">
        <td>
          <div class="plan-title-cell">
            <span class="file-ico">${Icons.file}</span>
            <a class="row-link-title" href="${planHref(p)}">${escapeHtml(p.title)}</a>
          </div>
        </td>
        <td>${escapeHtml(p.subject || "\u2013")}</td>
        <td>${escapeHtml(p.grade_level || "\u2013")}</td>
        <td>${fmtDate(p.updated_at)}</td>
        <td>
          <div class="row-menu">
            <button class="row-menu-btn" type="button" data-plan="${p.id}" aria-label="More actions" title="More actions">${Icons.moreHorizontal}</button>
            <div class="row-menu-dropdown" data-menu="${p.id}">
              <button type="button" data-action="export" data-plan="${p.id}" data-title="${escapeHtml(p.title || "")}">Export as Word</button>
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
        exportPlan(planId, btn.dataset.title);
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

  document.querySelectorAll(".js-role-action").forEach((el) => {
    el.hidden = el.dataset.role !== user.role;
  });

  const firstName = (user.full_name || "").split(" ")[0] || "there";
  document.getElementById("hero-greeting").textContent = greetingForNow(firstName);

  // A student's points: each lesson plan they start uses 30.
  if (user.role === "student") {
    const n = Number(user.points) || 0;
    const chip = document.getElementById("hero-points");
    chip.innerHTML = `<span aria-hidden="true">${Icons.coins}</span><strong>${n}</strong> point${n === 1 ? "" : "s"}`
      + `<span class="points-chip-note">Each lesson plan you start uses ${POINTS_PER_PLAN} points. Ask your teacher for more.</span>`;
    chip.classList.toggle("is-short", n < POINTS_PER_PLAN);
  }

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
