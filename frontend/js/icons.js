
const Icons = {
  undo: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M3.5 13a9 9 0 1 0 2.6-8.4L3 7"/></svg>`,
  redo: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 7v6h-6"/><path d="M20.5 13a9 9 0 1 1-2.6-8.4L21 7"/></svg>`,
  indent: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 6h10M11 12h10M11 18h10"/><path d="m3 9 3 3-3 3"/></svg>`,
  outdent: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 6h10M11 12h10M11 18h10"/><path d="m6 9-3 3 3 3"/></svg>`,
  clearFormat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5h14"/><path d="M13 5 9 19"/><path d="m16 14 5 5M21 14l-5 5"/></svg>`,
  zoomIn: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M11 8v6M8 11h6"/><path d="m20 20-3.7-3.7"/></svg>`,
  zoomOut: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M8 11h6"/><path d="m20 20-3.7-3.7"/></svg>`,
  expand: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>`,
  collapse: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3M16 3v3a2 2 0 0 0 2 2h3M21 16h-3a2 2 0 0 0-2 2v3M3 16h3a2 2 0 0 1 2 2v3"/></svg>`,
  palette: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="8.5" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="12" cy="7.8" r="1.2" fill="currentColor" stroke="none"/><circle cx="15.5" cy="10" r="1.2" fill="currentColor" stroke="none"/><path d="M12 21a3 3 0 0 1 0-6 2 2 0 0 0 0-4"/></svg>`,
  highlight: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16"/><path d="m9 16 8-8-4-4-8 8v4z"/><path d="M13 4l4 4"/></svg>`,
  dashboard: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>`,
  image: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>`,
  filePlus: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/><path d="M12 12v6M9 15h6"/></svg>`,
  list: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/></svg>`,
  alignLeft: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h10M4 18h13"/></svg>`,
  alignCenter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M7 12h10M5.5 18h13"/></svg>`,
  alignRight: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M10 12h10M7 18h13"/></svg>`,
  alignJustify: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>`,
  bookOpen: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4.5A2.5 2.5 0 0 1 4.5 2H10a2 2 0 0 1 2 2v18a1.5 1.5 0 0 0-1.5-1.5H2z"/><path d="M22 4.5A2.5 2.5 0 0 0 19.5 2H14a2 2 0 0 0-2 2v18a1.5 1.5 0 0 1 1.5-1.5H22z"/></svg>`,
  settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  bell: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
  chevronDown: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
  file: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/></svg>`,
  folder: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  book: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`,
  checkSquare: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>`,
  bulb: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1v.2h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z"/></svg>`,
  sparkle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`,
  upload: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M4 17v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg>`,
  download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-.9 14a2 2 0 0 1-2 1.9H6.9a2 2 0 0 1-2-1.9L4 6"/></svg>`,
  eraser: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 16 6-6 5 5-4 4H7z"/><path d="M11 10 16 5a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3l-5 5"/><path d="M4 21h16"/></svg>`,
  user: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>`,
  logout: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></svg>`,
  eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
  x: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`,
  users: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  inbox: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>`,
  plusCircle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>`,
  copy: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
  shield: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  userCog: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><circle cx="19" cy="16" r="2"/><path d="M19 12v1M19 19v1M22 16h-1M17 16h-1M20.4 14.6l-.7.7M18.3 16.7l-.7.7M20.4 17.4l-.7-.7M18.3 15.3l-.7-.7"/></svg>`,
  edit: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>`,
  megaphone: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 11 18-5v12L3 13v-2z"/><path d="M11.6 16.8 13 21h-3l-1.2-4.2"/></svg>`,
  files: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15.5 2H6.5A2.5 2.5 0 0 0 4 4.5v13A2.5 2.5 0 0 0 6.5 20H10"/><path d="M8 22h10a2 2 0 0 0 2-2V8l-6-6H10a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2z"/><path d="M14 2v6h6"/></svg>`,
  globe: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`,
  lock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`,
  archive: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1.5"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>`,
  chevronLeft: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>`,
  menu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>`,
};

function matchesRole(rule, role) {
  if (!rule) return true;
  return rule.startsWith("!") ? rule.slice(1) !== role : rule === role;
}

function renderSidebarNav(active) {
  // data-role marks items that only apply to one account type; wireTopbar()
  // authoritatively hides the ones that don't match once Api.me() confirms
  // who's signed in. Rendering also bakes in a same-instant guess from the
  // last-known cached user (see cacheUser() in api.js) so a returning user's
  // sidebar is already correct on first paint instead of flashing every
  // role's links before narrowing down to theirs a moment later.
  const items = [
    { key: "admin-dashboard", href: "admin-dashboard.html", icon: Icons.shield, label: "Admin Dashboard", role: "admin" },
    { key: "admin-documents", href: "admin-documents.html", icon: Icons.files, label: "Documents", role: "admin" },
    { key: "admin-users", href: "admin-users.html", icon: Icons.userCog, label: "Manage Users", role: "admin" },
    { key: "admin-sections", href: "admin-sections.html", icon: Icons.users, label: "Manage Sections", role: "admin" },
    { key: "admin-archive", href: "admin-users.html?role=student&active=0", icon: Icons.archive, label: "Student Archive", role: "admin" },
    { key: "admin-announcements", href: "admin-announcements.html", icon: Icons.megaphone, label: "Announcements", role: "admin" },
    { key: "dashboard", href: "dashboard.html", icon: Icons.dashboard, label: "Dashboard", role: "!admin" },
    { key: "lesson-plan", href: "lesson-plan.html", icon: Icons.filePlus, label: "Create Lesson Plan", role: "!admin" },
    { key: "lesson-plan-list", href: "lesson-plan-list.html", icon: Icons.list, label: "List of Lesson Plan", role: "!admin" },
    { key: "sections", href: "sections.html", icon: Icons.users, label: "My Sections", role: "teacher" },
    { key: "submissions", href: "submissions.html", icon: Icons.inbox, label: "Submissions", role: "teacher" },
    { key: "my-classes", href: "my-classes.html", icon: Icons.users, label: "My Classes", role: "student" },
    { key: "course-guides", href: "course-guides.html", icon: Icons.bookOpen, label: "Curriculum/Course Guide", role: "!admin" },
    { key: "announcements", href: "announcements.html", icon: Icons.megaphone, label: "Announcements", role: "!admin" },
    { key: "settings", href: "settings.html", icon: Icons.settings, label: "Settings" },
  ];
  const cached = typeof getCachedUser === "function" ? getCachedUser() : null;
  const cachedRole = cached ? cached.role : null;
  return items
    .map((item) => {
      const guessHidden = cachedRole && !matchesRole(item.role, cachedRole);
      return `
      <a href="${item.href}" class="${item.key === active ? "active" : ""}" ${item.role ? `data-role="${item.role}"` : ""}${guessHidden ? ' style="display:none"' : ""}>
        ${item.icon}
        <span>${item.label}</span>
      </a>`;
    })
    .join("");
}

function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  const first = parts[0] ? parts[0][0] : "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

// Every ".avatar-chip.js-user-initials" span (topbar, sidebar footer,
// settings header) doubles as the avatar: plain initials by default, or a
// cropped profile picture as a CSS background once the user has uploaded
// one — no template changes needed either way, and it stays a perfect
// circle either way since the chip's own border-radius doesn't change.
function applyAvatar(user) {
  const initialsStr = initials(user.full_name);
  document.querySelectorAll(".js-user-initials").forEach((el) => {
    if (user.avatar_url) {
      el.style.backgroundImage = `url("${user.avatar_url}")`;
      el.style.backgroundSize = "cover";
      el.style.backgroundPosition = "center";
      el.textContent = "";
    } else {
      el.style.backgroundImage = "";
      el.textContent = initialsStr;
    }
  });
}

// Restore the collapsed rail at script-parse time (icons.js sits at the end
// of <body>, so this lands before the sidebar's first paint) rather than
// inside wireTopbar, which only runs after the auth round-trip.
if (localStorage.getItem("sidebarCollapsed")) {
  document.body.classList.add("sidebar-collapsed");
}

// On phone widths the sidebar becomes an off-canvas drawer (see the
// max-width:640px rules in style.css) instead of the permanent icon rail
// used on tablets — this injects the hamburger button and backdrop needed
// to open/close it into every dashboard-shell page from one place, rather
// than duplicating the same markup across ~15 HTML files. On desktop the
// drawer doesn't exist, so collapsing to an icon rail is driven instead by
// a handle pinned halfway down the sidebar's outer edge (the hamburger is
// hidden there). Either way the collapsed state is remembered across pages
// in localStorage.
function ensureMobileSidebarToggle() {
  const topbar = document.querySelector(".dash-topbar");
  const sidebar = document.querySelector(".sidebar");
  if (!topbar || !sidebar || document.getElementById("sidebar-toggle-btn")) return;

  const toggleBtn = document.createElement("button");
  toggleBtn.type = "button";
  toggleBtn.id = "sidebar-toggle-btn";
  toggleBtn.className = "icon-btn sidebar-toggle-btn";
  toggleBtn.setAttribute("aria-label", "Menu");
  toggleBtn.innerHTML = Icons.menu;
  topbar.insertBefore(toggleBtn, topbar.firstChild);

  const backdrop = document.createElement("div");
  backdrop.id = "sidebar-backdrop";
  backdrop.className = "sidebar-backdrop";
  document.body.appendChild(backdrop);

  // Every page repeats the same ~10 sidebar links before its actual content,
  // which is a long way to tab past on each navigation. The skip link is the
  // first thing in the tab order and is only visible while focused.
  const main = document.querySelector(".dash-main");
  if (main) {
    if (!main.id) main.id = "main-content";
    const skip = document.createElement("a");
    skip.className = "skip-link";
    skip.href = "#" + main.id;
    skip.textContent = "Skip to content";
    document.body.insertBefore(skip, document.body.firstChild);
    // A <main> isn't focusable on its own, so following the link would move
    // the caret nowhere without this.
    main.tabIndex = -1;
  }

  const closeSidebar = () => {
    sidebar.classList.remove("open");
    backdrop.classList.remove("open");
    document.body.classList.remove("sidebar-lock-scroll");
  };
  const openSidebar = () => {
    sidebar.classList.add("open");
    backdrop.classList.add("open");
    document.body.classList.add("sidebar-lock-scroll");
  };

  // The handle sits on the sidebar's edge but is position:fixed on <body>,
  // not a child of .sidebar — .sidebar is overflow-y:auto, so a child would
  // be clipped at the edge and would scroll away with a long nav list.
  const collapseBtn = document.createElement("button");
  collapseBtn.type = "button";
  collapseBtn.id = "sidebar-collapse-btn";
  collapseBtn.className = "sidebar-collapse-btn";
  collapseBtn.innerHTML = Icons.chevronLeft;
  // Fixed positioning means DOM order only affects the tab order, so insert
  // it right after the sidebar it controls instead of at the end of the page.
  sidebar.insertAdjacentElement("afterend", collapseBtn);

  const syncCollapseBtn = () => {
    const collapsed = document.body.classList.contains("sidebar-collapsed");
    collapseBtn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
    collapseBtn.setAttribute("aria-label", collapseBtn.title);
    collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  };
  const toggleCollapsed = () => {
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "");
    syncCollapseBtn();
  };
  syncCollapseBtn();
  collapseBtn.addEventListener("click", toggleCollapsed);

  toggleBtn.addEventListener("click", () => {
    if (window.innerWidth <= 640) {
      if (sidebar.classList.contains("open")) closeSidebar();
      else openSidebar();
    } else {
      toggleCollapsed();
    }
  });
  backdrop.addEventListener("click", closeSidebar);
  sidebar.querySelectorAll("a").forEach((a) => a.addEventListener("click", closeSidebar));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 640) closeSidebar();
  });
}

function wireTopbar(user) {
  ensureMobileSidebarToggle();

  const avatarBtn = document.getElementById("avatar-btn");
  const dropdown = document.getElementById("avatar-dropdown");

  if (avatarBtn && dropdown) {
    avatarBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.toggle("open");
    });
    document.addEventListener("click", (e) => {
      if (!dropdown.contains(e.target) && e.target !== avatarBtn) {
        dropdown.classList.remove("open");
      }
    });
  }

  const ddLogout = document.getElementById("dd-logout-btn");
  if (ddLogout) {
    ddLogout.addEventListener("click", async () => {
      try {
        await Api.logout();
      } finally {
        clearCachedUser();
        window.location.href = "index.html";
      }
    });
  }

  if (!user) return;
  applyAvatar(user);
  document.querySelectorAll(".js-user-name").forEach((el) => (el.textContent = user.full_name));
  document.querySelectorAll(".js-user-role").forEach((el) => {
    el.textContent = user.role ? user.role[0].toUpperCase() + user.role.slice(1) : "Teacher";
  });

  // Authoritative pass: show/hide every sidebar link based on the confirmed
  // role, in both directions — never just hiding non-matches — so a wrong
  // guess baked in by renderSidebarNav's cached pre-render (stale cache,
  // role changed by an admin, etc.) always gets corrected either way instead
  // of a wrongly-hidden link staying hidden forever.
  document.querySelectorAll("#sidebar-nav a[data-role]").forEach((a) => {
    a.style.display = matchesRole(a.dataset.role, user.role) ? "" : "none";
  });
}

function homeForRole(role) {
  return role === "admin" ? "admin-dashboard.html" : "dashboard.html";
}
