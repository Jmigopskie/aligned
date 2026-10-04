const faqSearch = document.getElementById("faq-search");
const faqEmpty = document.getElementById("faq-empty");
const faqGroups = Array.from(document.querySelectorAll(".faq-group"));

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
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  wireTopbar(user);
  document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("faq");
  // The tour lives on the landing page for this role.
  document.getElementById("replay-tour-btn").href = `${homeForRole(user.role)}?tour=1`;
  hydrateIcons();
}

init();
