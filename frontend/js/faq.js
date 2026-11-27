const faqSearch = document.getElementById("faq-search");
const faqEmpty = document.getElementById("faq-empty");
const topicsNav = document.getElementById("help-topics");
const faqGroups = Array.from(document.querySelectorAll(".faq-group"));

// The topic list on the left: one link per group, with how many questions it
// holds (the count follows the search).
function renderTopics() {
  topicsNav.innerHTML = faqGroups
    .map((group) => {
      const title = group.querySelector(".faq-group-title").textContent;
      const icon = Icons[group.dataset.iconName] || "";
      const count = group.querySelectorAll("details:not([hidden])").length;
      return `
        <a class="help-topic" href="#${group.id}" data-topic="${group.id}"${group.hidden ? " hidden" : ""}>
          <span class="help-topic-icon">${icon}</span>
          <span class="help-topic-label">${escapeHtml(title)}</span>
          ${count ? `<span class="help-topic-count">${count}</span>` : ""}
        </a>`;
    })
    .join("");
}

// Filters questions and answers as you type; a group with nothing left hides.
// A match opens its answer, so the words searched for are on screen.
faqSearch.addEventListener("input", () => {
  const term = faqSearch.value.trim().toLowerCase();
  let shown = 0;
  faqGroups.forEach((group) => {
    let groupShown = 0;
    group.querySelectorAll("details").forEach((item) => {
      const match = !term || item.textContent.toLowerCase().includes(term);
      item.hidden = !match;
      item.open = !!term && match;
      if (match) groupShown++;
    });
    // The tutorial has no questions: it shows whenever nothing is searched.
    group.hidden = term ? !groupShown : false;
    shown += groupShown;
  });
  faqEmpty.hidden = shown > 0;
  renderTopics();
});

// The topic being read is marked in the list. An observer rather than a
// scroll listener: it only fires when a group crosses the reading line.
function watchTopics() {
  if (!("IntersectionObserver" in window)) return;
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        topicsNav.querySelectorAll(".help-topic").forEach((link) => {
          link.classList.toggle("is-current", link.dataset.topic === entry.target.id);
        });
      });
    },
    { rootMargin: "-20% 0px -70% 0px" }
  );
  faqGroups.forEach((group) => observer.observe(group));
}

// "Watch the tutorial" appears only when a tutorial video has been posted,
// and goes straight to it.
async function linkTutorial() {
  try {
    const data = await Api.myAnnouncements();
    const withVideo = (data.announcements || []).find((a) => a.has_video);
    if (!withVideo) return;
    const link = document.getElementById("tutorial-link");
    link.href = `announcements.html#announcement-${withVideo.id}`;
    link.hidden = false;
  } catch (err) {
    /* no announcements to point at; the button stays hidden */
  }
}

// ---- The tutorial: a walkthrough, one step at a time with Alan ----
// The steps are plain list items in the page (readable without script); this
// shows one, lists them all in the rail, and moves Alan with them. Students
// and teachers each have their own steps; it opens on the reader's role.
const roleTabs = Array.from(document.querySelectorAll("[data-role-tab]"));
const tutorial = document.getElementById("topic-how-aligned-works");
const rail = tutorial.querySelector(".tutorial-rail");
const alan = tutorial.querySelector(".tutorial-alan");
const panels = tutorial.querySelector(".tutorial-panels");
let stepsRole = "student";
let stepAt = 0;

const foot = document.createElement("div");
foot.className = "tutorial-foot";
foot.innerHTML = `
  <p class="tutorial-where"><span class="tutorial-where-icon">${Icons.arrowRight}</span><span>Find it in <strong></strong></span></p>
  <div class="tutorial-nav">
    <button type="button" class="btn btn-secondary tutorial-back">Back</button>
    <span class="tutorial-count" aria-live="polite"></span>
    <button type="button" class="btn btn-primary tutorial-next">Next</button>
    <a class="btn btn-primary tutorial-start" href="generator.html">Make a lesson plan</a>
  </div>`;
panels.append(foot);
tutorial.classList.add("is-walkthrough");

const stepItems = () => Array.from(document.getElementById(`steps-${stepsRole}`).children);

function drawRail() {
  rail.innerHTML = `<ol>${stepItems().map((li, i) => `
    <li><button type="button" class="tutorial-rail-step" data-step="${i}">
      <span class="tutorial-rail-num" aria-hidden="true">${i + 1}</span>
      <span class="tutorial-rail-label">${escapeHtml(li.querySelector("h3").textContent)}</span>
    </button></li>`).join("")}</ol>`;
}

function showStep(i, focusStep = false) {
  const list = stepItems();
  stepAt = Math.max(0, Math.min(i, list.length - 1));
  const li = list[stepAt];
  list.forEach((item, n) => { item.hidden = n !== stepAt; });
  alan.src = `img/owl/alan-${li.dataset.pose || "idle"}.png`;
  rail.querySelectorAll(".tutorial-rail-step").forEach((btn, n) => {
    btn.classList.toggle("is-done", n < stepAt);
    if (n === stepAt) btn.setAttribute("aria-current", "step");
    else btn.removeAttribute("aria-current");
  });
  foot.querySelector(".tutorial-where").hidden = !li.dataset.where;
  foot.querySelector(".tutorial-where strong").textContent = li.dataset.where || "";
  foot.querySelector(".tutorial-count").textContent = `Step ${stepAt + 1} of ${list.length}`;
  foot.querySelector(".tutorial-back").disabled = stepAt === 0;
  const last = stepAt === list.length - 1;
  foot.querySelector(".tutorial-next").hidden = last;
  foot.querySelector(".tutorial-start").hidden = !last;
  // The one authored moment: the step and Alan arrive together.
  panels.classList.remove("is-arriving");
  void panels.offsetWidth;
  panels.classList.add("is-arriving");
  if (focusStep) li.querySelector("h3").focus();
}

rail.addEventListener("click", (e) => {
  const btn = e.target.closest(".tutorial-rail-step");
  if (btn) showStep(Number(btn.dataset.step), e.detail === 0);
});
// Focus moves to the step only for the keyboard (detail 0), not a mouse click.
foot.querySelector(".tutorial-back").addEventListener("click", (e) => showStep(stepAt - 1, e.detail === 0));
foot.querySelector(".tutorial-next").addEventListener("click", (e) => showStep(stepAt + 1, e.detail === 0));
tutorial.querySelectorAll(".tutorial-steps h3").forEach((h) => { h.tabIndex = -1; });

function showSteps(role) {
  stepsRole = role;
  roleTabs.forEach((tab) => {
    const on = tab.dataset.roleTab === role;
    tab.classList.toggle("active", on);
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !on;
  });
  drawRail();
  showStep(0);
}
roleTabs.forEach((tab, i) => {
  tab.addEventListener("click", () => showSteps(tab.dataset.roleTab));
  tab.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = roleTabs[(i + (e.key === "ArrowRight" ? 1 : roleTabs.length - 1)) % roleTabs.length];
    showSteps(next.dataset.roleTab);
    next.focus();
  });
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  wireTopbar(user);
  document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("faq");
  // The tour starts from the landing page for this role.
  document.getElementById("replay-tour-btn").href = `${homeForRole(user.role)}?tour=1`;
  showSteps(user.role === "student" ? "student" : "teacher");
  hydrateIcons();
  renderTopics();
  watchTopics();
  linkTutorial();
}

init();
