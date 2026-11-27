const errorBox = document.getElementById("error-box");
const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const classGrid = document.getElementById("class-grid");
const joinForm = document.getElementById("join-form");
const joinCodeInput = document.getElementById("join-code");
const joinSubmitBtn = document.getElementById("join-submit-btn");

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("my-classes");

function renderClasses(sections) {
  loadingState.hidden = true;
  if (!sections.length) {
    emptyState.hidden = false;
    classGrid.hidden = true;
    return;
  }
  emptyState.hidden = true;
  classGrid.hidden = false;
  classGrid.innerHTML = sections
    .map(
      (s) => `
      <div class="class-card" style="cursor:default;" data-section="${s.id}">
        <h3>${escapeHtml(s.name)}</h3>
        <div class="class-meta">Teacher: ${escapeHtml(s.teacher_name || "\u2013")}</div>
        <div style="margin-top:14px; display:flex; flex-wrap:wrap; gap:8px;">
          <button class="btn btn-secondary" type="button" data-members="${s.id}" aria-expanded="false"
            aria-controls="members-${s.id}">${Icons.users}<span>Class members</span></button>
          <button class="btn btn-secondary" type="button" onclick="window.location.href='lesson-plan-list.html'">Submit a plan</button>
          <button class="btn btn-secondary danger" type="button" data-leave="${s.id}">Leave</button>
        </div>
        <div class="class-members" id="members-${s.id}" hidden></div>
      </div>`
    )
    .join("");

  // Who is in the class (user, 2026-11-28): the teacher, then everyone who
  // joined, loaded the first time the list is opened.
  classGrid.querySelectorAll("[data-members]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const box = document.getElementById(`members-${btn.dataset.members}`);
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      box.hidden = !open;
      if (!open || box.dataset.loaded) return;
      box.innerHTML = `<p class="text-sm">Loading&hellip;</p>`;
      try {
        const { section } = await Api.getSection(btn.dataset.members);
        const members = section.members || [];
        box.dataset.loaded = "1";
        box.innerHTML = `
          <p class="class-members-teacher"><span class="avatar-chip">${escapeHtml(initials(section.teacher_name))}</span>
            <span><strong>${escapeHtml(section.teacher_name || "\u2013")}</strong><span class="text-sm">Teacher</span></span></p>
          <h4 class="class-members-title">${members.length} student${members.length === 1 ? "" : "s"}</h4>
          <ul class="class-members-list">${members.map((m) => `
            <li><span class="avatar-chip">${escapeHtml(initials(m.name))}</span>
              <span>${escapeHtml(m.name || "\u2013")}${m.you ? ` <span class="badge">You</span>` : ""}</span></li>`).join("")}
          </ul>`;
      } catch (err) {
        box.innerHTML = "";
        box.append(Object.assign(document.createElement("p"), { className: "text-sm", textContent: err.message }));
      }
    });
  });

  classGrid.querySelectorAll("[data-leave]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Leave this class? You can rejoin later with the class code.")) return;
      try {
        await Api.leaveSection(btn.dataset.leave);
        showToast("You left the class.");
        loadClasses();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function loadClasses() {
  try {
    const data = await Api.listSections();
    renderClasses(data.sections || []);
  } catch (err) {
    loadingState.hidden = true;
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
}

joinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = joinCodeInput.value.trim();
  if (!code) return;
  setButtonLoading(joinSubmitBtn, true, "Joining");
  try {
    const data = await Api.joinSection(code);
    showToast(`Joined ${data.section.name}!`);
    joinCodeInput.value = "";
    loadClasses();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setButtonLoading(joinSubmitBtn, false);
  }
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  if (user.role !== "student") {
    window.location.href = homeForRole(user.role);
    return;
  }
  wireTopbar(user);
  document.getElementById("points-balance").innerHTML = pointsBalanceHtml(user.points);
  document.getElementById("points-panel").hidden = false;
  loadClasses();
}

init();
