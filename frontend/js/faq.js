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
          <span class="help-topic-count">${count}</span>
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
    group.hidden = !groupShown;
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

async function init() {
  const user = await requireAuth();
  if (!user) return;
  wireTopbar(user);
  document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("faq");
  // The tour starts from the landing page for this role.
  document.getElementById("replay-tour-btn").href = `${homeForRole(user.role)}?tour=1`;
  hydrateIcons();
  renderTopics();
  watchTopics();
  linkTutorial();
}

init();
