// The owl's tour of the app. It runs once for a new account (or again from the
// FAQ's "Replay the tour") and walks through the tabs themselves: each stop
// opens its page and points at the part that matters there. Where it is up to
// is kept in sessionStorage, so it carries on across page loads; Skip or
// Finish ends it everywhere. api.js loads this file only while a tour is due.
const TOUR_KEY = "alignedTour";

const TOUR_STOPS = {
  teacher: [
    { page: "dashboard.html", pose: "wave", text: "Hi, I'm Alan. I'll open each tab and show you what it's for. It takes about a minute." },
    { page: "dashboard.html", focus: '#sidebar-nav a[href="generator.html"]', pose: "point", text: "Create Lesson Plan starts a new plan. I ask a few questions, one at a time, then we write it together." },
    { page: "lesson-plan.html", focus: "#new-format-btn", pose: "idea", text: "Formats is where you upload your school's own layout with New format. Your students can use every format you upload." },
    { page: "lesson-plan-list.html", focus: ["#status-filter", "#plans-body"], pose: "point", text: "List of Lesson Plans keeps everything you make. Unfinished plans stay here as drafts; use Continue to finish one." },
    { page: "sections.html", focus: "#new-section-btn", pose: "point", text: "My Sections is where you create a class. Each one gets a join code to share with your students." },
    { page: "lesson-plan-list.html", focus: "#submissions-tab", pose: "check", text: "Student Submissions, a tab of this list, collects the plans your students hand in, ready for you to review and score." },
    { page: "course-guides.html", focus: "#folder-grid", pose: "point", text: "Curriculum/Course Guide keeps the guides in folders by type. Open one to see what's in it, or make your own with New folder." },
    { page: "announcements.html", focus: "#announcements-body", pose: "idea", text: "Announcements has school news, and the tutorial video when your admin posts one." },
    { page: "announcements.html", focus: "#help-btn", pose: "celebrate", text: "Questions later? The Help button opens the FAQ, where you can also replay this tour. Enjoy AlignED!" },
  ],
  student: [
    { page: "dashboard.html", pose: "wave", text: "Hi, I'm Alan. I'll open each tab and show you what it's for. It takes about a minute." },
    { page: "dashboard.html", focus: '#sidebar-nav a[href="generator.html"]', pose: "point", text: "Create Lesson Plan starts a new plan. I ask a few questions, one at a time, then we write it together." },
    { page: "lesson-plan-list.html", focus: ["#status-filter", "#plans-body"], pose: "point", text: "List of Lesson Plans keeps everything you make. Drafts wait here, and Submit to class hands a plan to your teacher." },
    { page: "my-classes.html", focus: "#join-form", pose: "idea", text: "In My Classes, join your teacher's class with the code they give you." },
    { page: "course-guides.html", focus: "#folder-grid", pose: "point", text: "Curriculum/Course Guide has the guides your plans are written from, in folders by type. Open one to see what's in it." },
    { page: "announcements.html", focus: "#announcements-body", pose: "idea", text: "Announcements has news from your school and teachers, and the tutorial video when one is posted." },
    { page: "announcements.html", focus: "#help-btn", pose: "celebrate", text: "Questions later? The Help button opens the FAQ, where you can also replay this tour. Enjoy AlignED!" },
  ],
  admin: [
    { page: "admin-dashboard.html", pose: "wave", text: "Hi, I'm Alan. I'll open each part of the admin console and show you what it's for." },
    { page: "admin-users.html", focus: "#new-user-btn", pose: "point", text: "Manage Users is where you add teacher and student accounts, and archive the ones who leave." },
    { page: "admin-sections.html", focus: ["#sections-body"], pose: "point", text: "Manage Sections lists every class in the school and who teaches it." },
    { page: "admin-documents.html", focus: "#doc-tabs", pose: "idea", text: "Documents brings the school's lesson plans, course guides and sections together in one place." },
    { page: "admin-announcements.html", focus: "#new-announcement-btn", pose: "point", text: "Post notices to everyone here. Attach a video to an announcement to share a tutorial with the whole school." },
    { page: "admin-announcements.html", focus: "#help-btn", pose: "celebrate", text: "The Help button opens the FAQ, where you can also replay this tour. That's the tour!" },
  ],
};

function readTour() {
  try {
    return JSON.parse(sessionStorage.getItem(TOUR_KEY) || "null");
  } catch (err) {
    return null;
  }
}

function writeTour(state) {
  try {
    if (state) sessionStorage.setItem(TOUR_KEY, JSON.stringify(state));
    else sessionStorage.removeItem(TOUR_KEY);
  } catch (err) {
    /* storage blocked: the tour simply ends on the next page */
  }
}

function currentPage() {
  return location.pathname.split("/").pop() || "index.html";
}

const OwlTour = {
  _clearHighlight() {
    document.querySelectorAll(".tour-target").forEach((el) => el.classList.remove("tour-target"));
  },

  // The part of the page a stop is about. Pages fill in after loading, so it
  // is looked for a few times before the stop shows without a highlight.
  // `focus` may list several places, best first: some only show in certain
  // states (a filter that appears once there are plans to filter). With none
  // of them on screen, the tab's own menu item is pointed at instead.
  async _focus(focus) {
    if (!focus) return;
    const selectors = [].concat(focus);
    const visible = (sel) => {
      const el = document.querySelector(sel);
      return el && el.getClientRects().length && el.offsetHeight > 4 ? el : null;
    };
    for (let tries = 0; tries < 12; tries++) {
      const el = selectors.map(visible).find(Boolean);
      if (el) return this._mark(el);
      await new Promise((r) => setTimeout(r, 200));
    }
    const menuItem = document.querySelector(`#sidebar-nav a[href="${currentPage()}"]`);
    if (menuItem && menuItem.getClientRects().length) this._mark(menuItem);
  },

  _mark(el) {
    el.classList.add("tour-target");
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  },

  _stops(state) {
    return TOUR_STOPS[state.role] || TOUR_STOPS.student;
  },

  // Moving to a stop: on this page it just shows; on another page it saves
  // where it's up to and opens that page, which picks the tour up from there.
  _goTo(state, index) {
    const stops = this._stops(state);
    const next = { ...state, index };
    writeTour(next);
    if (stops[index].page !== currentPage()) {
      this._clearHighlight();
      window.location.href = stops[index].page;
      return;
    }
    this._show(next);
  },

  async _show(state) {
    const stops = this._stops(state);
    const stop = stops[state.index];
    this._clearHighlight();

    // Somewhere else than this stop's page (the reader wandered off, or used
    // the menu mid-tour): offer to carry on rather than talk about a page
    // that isn't on screen.
    if (stop.page !== currentPage()) {
      OwlGuide.tourStep(
        { pose: "idle", text: "Want to carry on with the tour? I'll take you back to where we were." },
        { index: state.index, total: stops.length, nextLabel: "Continue the tour",
          onNext: () => this._goTo(state, state.index), onSkip: () => this._end(state) }
      );
      return;
    }

    const last = state.index === stops.length - 1;
    OwlGuide.tourStep(stop, {
      index: state.index,
      total: stops.length,
      onBack: state.index ? () => this._goTo(state, state.index - 1) : null,
      onNext: () => (last ? this._end(state) : this._goTo(state, state.index + 1)),
      onSkip: () => this._end(state),
    });
    await this._focus(stop.focus);
  },

  _end(state) {
    this._clearHighlight();
    OwlGuide.endTour();
    writeTour(null);
    if (location.search.includes("tour=1")) history.replaceState(null, "", location.pathname);
    if (state && state.firstRun) Api.markOnboarded().catch(() => {});
  },

  // Called by api.js once the user is known.
  run(user) {
    let state = readTour();
    const replay = new URLSearchParams(location.search).get("tour") === "1";
    if (!state && (replay || !user.onboarded)) {
      state = { role: user.role, index: 0, firstRun: !user.onboarded };
      writeTour(state);
    }
    if (!state) return;
    // After the page has drawn and the loading screen has gone.
    setTimeout(() => this._show(state), 600);
  },
};
