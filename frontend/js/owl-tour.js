// The owl's first-sign-in tour. Runs on the landing page (dashboard for
// students and teachers, admin dashboard for admins) once per account, or again
// on demand with ?tour=1 (the FAQ's "Replay the tour"). Each step can point at a
// sidebar link; on a phone, where the menu is folded away, the words name it.
const TOUR_STEPS = {
  teacher: [
    { pose: "wave", text: "Hi, I'm Alan. Let me show you around AlignED. It only takes a minute." },
    { pose: "point", target: "lesson-plan.html", text: "Create Lesson Plan is where every plan starts. Pick your school's format, or add your own with New format." },
    { pose: "point", target: "lesson-plan-list.html", text: "List of Lesson Plans keeps everything you make. Unfinished plans stay here as drafts; use Continue to pick one up." },
    { pose: "idea", target: "sections.html", text: "In My Sections you create a class and share its join code. What your students hand in shows up in Submissions." },
    { pose: "point", target: "course-guides.html", text: "Curriculum/Course Guide has the official DepEd guides for ICT, CP, AFA, HE, IA and Electrical. Your plans are written from these." },
    { pose: "celebrate", target: "announcements.html", help: true, text: "Announcements has school news and the tutorial video. For quick answers any time, use the Help button at the top." },
  ],
  student: [
    { pose: "wave", text: "Hi, I'm Alan. Let me show you around AlignED. It only takes a minute." },
    { pose: "point", target: "lesson-plan.html", text: "Create Lesson Plan is where every plan starts. Pick the format your school uses and fill in a short setup." },
    { pose: "point", target: "lesson-plan-list.html", text: "List of Lesson Plans keeps everything you make. Drafts wait here for you, and Submit to class hands a plan to your teacher." },
    { pose: "idea", target: "my-classes.html", text: "In My Classes, join your teacher's class with the code they give you." },
    { pose: "point", target: "course-guides.html", text: "Curriculum/Course Guide has the official DepEd guides your plans are written from." },
    { pose: "celebrate", target: "announcements.html", help: true, text: "Announcements has school news and the tutorial video. For quick answers any time, use the Help button at the top." },
  ],
  admin: [
    { pose: "wave", text: "Hi, I'm Alan. Here is a quick look at the admin console." },
    { pose: "point", target: "admin-users.html", text: "Manage Users is where you add teacher and student accounts, and archive the ones that leave." },
    { pose: "point", target: "admin-sections.html", text: "Manage Sections shows every class and who teaches it." },
    { pose: "idea", target: "admin-documents.html", text: "Documents gathers the lesson plans and files across the school." },
    { pose: "point", target: "admin-announcements.html", text: "In Announcements you post notices to everyone, and you can attach a tutorial video that plays right inside the notice." },
    { pose: "celebrate", help: true, text: "For quick answers any time, use the Help button at the top. That's it. Enjoy AlignED!" },
  ],
};

const OwlTour = {
  _steps: [],
  _index: 0,
  _firstRun: false,

  _clearHighlight() {
    document.querySelectorAll(".tour-target").forEach((el) => el.classList.remove("tour-target"));
  },

  _highlight(step) {
    this._clearHighlight();
    const targets = [];
    if (step.target) {
      const link = document.querySelector(`#sidebar-nav a[href="${step.target}"]`);
      if (link) targets.push(link);
    }
    if (step.help) {
      const help = document.getElementById("help-btn");
      if (help) targets.push(help);
    }
    targets.forEach((el) => {
      // Folded-away menus (phones) have nothing to point at; the words do it.
      if (!el.getClientRects().length) return;
      el.classList.add("tour-target");
      el.scrollIntoView({ block: "nearest" });
    });
  },

  _go(index) {
    this._index = index;
    const step = this._steps[index];
    this._highlight(step);
    OwlGuide.tourStep(step, {
      index,
      total: this._steps.length,
      onBack: () => this._go(Math.max(0, index - 1)),
      onNext: () => (index === this._steps.length - 1 ? this._end() : this._go(index + 1)),
      onSkip: () => this._end(),
    });
  },

  _end() {
    this._clearHighlight();
    OwlGuide.endTour();
    // Off the URL, so a reload doesn't replay it.
    if (location.search.includes("tour=1")) history.replaceState(null, "", location.pathname);
    if (this._firstRun) Api.markOnboarded().catch(() => {});
    this._firstRun = false;
  },

  start(user, { firstRun }) {
    this._steps = TOUR_STEPS[user.role] || TOUR_STEPS.student;
    this._firstRun = firstRun;
    this._go(0);
  },
};

(async function startTourIfDue() {
  let user;
  try {
    user = (await Api.me()).user;
  } catch (err) {
    return;
  }
  const replay = new URLSearchParams(location.search).get("tour") === "1";
  if (!replay && user.onboarded) return;
  // After the page has drawn its sidebar and the loading screen is gone.
  setTimeout(() => OwlTour.start(user, { firstRun: !user.onboarded }), 700);
})();
