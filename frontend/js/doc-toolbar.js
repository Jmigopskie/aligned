// The document toolbar, shared by the format builder's canvas and the
// generator's live lesson-plan document. Both pages used to carry their own
// copy of the markup, which is how they drifted into having different tools:
// the builder had headings and alignment, the generator only bold/italic/
// underline and lists. The markup is built here once so they cannot diverge
// again.
//
// What each page does with a button still differs, and has to. The builder
// edits the template document itself and tracks per-line edits it later saves
// (headingEdits/listEdits keyed by anchor index); the generator edits the
// contenteditable field slots inside a filled plan. So this module owns the
// markup and the tools that behave identically in both — the view controls and
// the execCommand text tools — and each page wires its own model-specific
// handlers on top.

// A fixed vocabulary rather than free-form CSS. Every size, colour and
// highlight a teacher can pick maps to one class name that the whole pipeline
// understands: the sanitizer keeps it, and the Word export turns it into a real
// run property. Free-form styles would look fine on screen and then vanish on
// export, so the set is deliberately closed.
const DOC_FONT_SIZES = [
  { value: "", label: "Size" },
  { value: "fs-sm", label: "Small" },
  { value: "fs-md", label: "Normal" },
  { value: "fs-lg", label: "Large" },
  { value: "fs-xl", label: "Extra large" },
];

const DOC_TEXT_COLORS = [
  { cls: "fc-default", label: "Default", swatch: "#16231E" },
  { cls: "fc-red", label: "Red", swatch: "#AB3524" },
  { cls: "fc-amber", label: "Amber", swatch: "#B8842E" },
  { cls: "fc-green", label: "Green", swatch: "#1C5C4E" },
  { cls: "fc-blue", label: "Blue", swatch: "#1D4ED8" },
];

const DOC_HIGHLIGHTS = [
  { cls: "hl-none", label: "None", swatch: "transparent" },
  { cls: "hl-yellow", label: "Yellow", swatch: "#FDE68A" },
  { cls: "hl-green", label: "Green", swatch: "#BBF7D0" },
  { cls: "hl-cyan", label: "Cyan", swatch: "#A5F3FC" },
];

// Zoom steps, as multipliers of the document's natural size. A fixed ladder
// rather than free zooming, so the − and + buttons always land somewhere sane.
const DOC_ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
const DOC_ZOOM_DEFAULT_INDEX = 4; // 1.0

function docColorMenu(kind, options) {
  const items = options
    .map(
      (opt) => `
      <button type="button" class="doc-color-option" data-${kind}="${opt.cls}" title="${opt.label}">
        <span class="doc-color-swatch" style="background:${opt.swatch};"></span>
        <span>${opt.label}</span>
      </button>`
    )
    .join("");
  return `<div class="doc-color-menu" data-menu="${kind}" hidden>${items}</div>`;
}

// Builds the toolbar's inner HTML. `variant` is "builder" or "generator": the
// only difference is the two buttons that make sense on the template document
// alone (deleting a line, saving the edits back to the template).
function renderDocToolbar({ variant }) {
  const isBuilder = variant === "builder";

  const sizeOptions = DOC_FONT_SIZES
    .map((s) => `<option value="${s.value}">${s.label}</option>`)
    .join("");

  return `
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-cmd="undo" data-icon="undo" title="Undo (Ctrl+Z)"></button>
      <button type="button" class="doc-tool-btn" data-cmd="redo" data-icon="redo" title="Redo (Ctrl+Y)"></button>
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <select id="doc-heading-select" class="doc-tool-select" title="Paragraph style">
        <option value="p">Paragraph</option>
        <option value="h1">Heading 1</option>
        <option value="h2">Heading 2</option>
        <option value="h3">Heading 3</option>
      </select>
      <select id="doc-size-select" class="doc-tool-select" title="Font size">${sizeOptions}</select>
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-cmd="bold" title="Bold (Ctrl+B)"><strong>B</strong></button>
      <button type="button" class="doc-tool-btn" data-cmd="italic" title="Italic (Ctrl+I)"><em>I</em></button>
      <button type="button" class="doc-tool-btn" data-cmd="underline" title="Underline (Ctrl+U)"><span style="text-decoration:underline;">U</span></button>
      <div class="doc-tool-menu-wrap">
        <button type="button" class="doc-tool-btn" data-menu-toggle="color" data-icon="palette" title="Text colour"></button>
        ${docColorMenu("color", DOC_TEXT_COLORS)}
      </div>
      <div class="doc-tool-menu-wrap">
        <button type="button" class="doc-tool-btn" data-menu-toggle="highlight" data-icon="highlight" title="Highlight"></button>
        ${docColorMenu("highlight", DOC_HIGHLIGHTS)}
      </div>
      <button type="button" class="doc-tool-btn" data-cmd="removeFormat" data-icon="clearFormat" title="Clear formatting"></button>
      <button type="button" class="doc-tool-btn" data-clear-field="1" data-icon="eraser" title="Clear this field's content"></button>
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-cmd="justifyLeft" data-icon="alignLeft" title="Align left"></button>
      <button type="button" class="doc-tool-btn" data-cmd="justifyCenter" data-icon="alignCenter" title="Align centre"></button>
      <button type="button" class="doc-tool-btn" data-cmd="justifyRight" data-icon="alignRight" title="Align right"></button>
      <button type="button" class="doc-tool-btn" data-cmd="justifyFull" data-icon="alignJustify" title="Justify"></button>
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-list="bullet" data-icon="list" title="Bulleted list"></button>
      <button type="button" class="doc-tool-btn" data-list="number" title="Numbered list">1.</button>
      <button type="button" class="doc-tool-btn" data-cmd="outdent" data-icon="outdent" title="Decrease indent"></button>
      <button type="button" class="doc-tool-btn" data-cmd="indent" data-icon="indent" title="Increase indent"></button>
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-zoom="out" data-icon="zoomOut" title="Zoom out"></button>
      <button type="button" class="doc-tool-btn doc-zoom-readout" data-zoom="reset" title="Reset zoom to 100%">100%</button>
      <button type="button" class="doc-tool-btn" data-zoom="in" data-icon="zoomIn" title="Zoom in"></button>
      <button type="button" class="doc-tool-btn" data-fullscreen="toggle" data-icon="expand" title="Fullscreen"></button>
    </div>
    ${
      isBuilder
        ? `<div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" id="doc-delete-line-btn" class="doc-tool-btn danger" data-icon="trash" data-icon-label="Delete" title="Delete this line"></button>
    </div>
    <div class="doc-toolbar-save">
      <span class="text-sm" id="doc-content-status"></span>
      <button type="button" id="doc-save-content-btn" class="btn btn-primary btn-sm" disabled>Save changes to document</button>
    </div>`
        : ""
    }`;
}

// Paints the SVG for every button that asked for one by name, so the markup
// above can stay declarative instead of interpolating icon strings.
function paintDocToolbarIcons(toolbarEl) {
  toolbarEl.querySelectorAll("[data-icon]").forEach((btn) => {
    const icon = Icons[btn.dataset.icon];
    if (!icon) return;
    const label = btn.dataset.iconLabel;
    btn.innerHTML = label ? `${icon}<span>${label}</span>` : icon;
  });
}

// ---------------------------------------------------------------------------
// Zoom and fullscreen
// ---------------------------------------------------------------------------

// Scales the document without reflowing the page around it: the wrapper keeps
// the scaled height so scrollbars stay correct, which a bare transform on the
// page would get wrong.
function initDocViewControls({ toolbarEl, wrapEl, stageEl, storageKey }) {
  // What goes fullscreen. The toolbar has to be inside it or it vanishes the
  // moment fullscreen starts, so callers pass the element containing both.
  // Falls back to wrapEl so a caller with no stage still works.
  const fsEl = stageEl || wrapEl;

  let zoomIndex = DOC_ZOOM_DEFAULT_INDEX;

  const readout = toolbarEl.querySelector(".doc-zoom-readout");
  const fullscreenBtn = toolbarEl.querySelector("[data-fullscreen=toggle]");

  // Remembered per page so a teacher who works zoomed in doesn't have to set
  // it again every visit. A failure here is ignored: private mode and blocked
  // storage must not stop the document from rendering.
  if (storageKey) {
    try {
      const saved = parseInt(localStorage.getItem(storageKey), 10);
      if (!Number.isNaN(saved) && saved >= 0 && saved < DOC_ZOOM_STEPS.length) zoomIndex = saved;
    } catch (err) {
      /* storage unavailable; the default zoom applies */
    }
  }

  function applyZoom() {
    const scale = DOC_ZOOM_STEPS[zoomIndex];
    wrapEl.style.setProperty("--doc-zoom", String(scale));
    wrapEl.classList.toggle("is-zoomed", scale !== 1);
    if (readout) readout.textContent = `${Math.round(scale * 100)}%`;
    if (storageKey) {
      try {
        localStorage.setItem(storageKey, String(zoomIndex));
      } catch (err) {
        /* storage unavailable; the zoom still applies for this visit */
      }
    }
  }

  function setZoom(next) {
    zoomIndex = Math.max(0, Math.min(DOC_ZOOM_STEPS.length - 1, next));
    applyZoom();
  }

  toolbarEl.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.zoom;
      if (action === "in") setZoom(zoomIndex + 1);
      else if (action === "out") setZoom(zoomIndex - 1);
      else setZoom(DOC_ZOOM_DEFAULT_INDEX);
    });
  });

  // Ctrl+scroll over the document zooms, as it does in every document viewer.
  wrapEl.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      setZoom(zoomIndex + (event.deltaY < 0 ? 1 : -1));
    },
    { passive: false }
  );

  // The native Fullscreen API on the wrapper, so the document fills the screen
  // with its own toolbar still reachable. The fallback class covers browsers
  // that refuse the request (an iframe without the permission, mainly).
  function isFullscreen() {
    return document.fullscreenElement === fsEl || fsEl.classList.contains("is-pseudo-fullscreen");
  }

  function syncFullscreenButton() {
    if (!fullscreenBtn) return;
    const on = isFullscreen();
    fullscreenBtn.innerHTML = on ? Icons.collapse : Icons.expand;
    fullscreenBtn.title = on ? "Exit fullscreen" : "Fullscreen";
    fullscreenBtn.setAttribute("aria-pressed", on ? "true" : "false");
  }

  async function toggleFullscreen() {
    if (isFullscreen()) {
      if (document.fullscreenElement === fsEl) {
        try {
          await document.exitFullscreen();
        } catch (err) {
          /* already leaving */
        }
      }
      fsEl.classList.remove("is-pseudo-fullscreen");
      syncFullscreenButton();
      return;
    }

    try {
      await fsEl.requestFullscreen();
    } catch (err) {
      // Not available here, so fill the viewport with CSS instead. The
      // document is still usable, which is the point.
      fsEl.classList.add("is-pseudo-fullscreen");
    }
    syncFullscreenButton();
  }

  if (fullscreenBtn) fullscreenBtn.addEventListener("click", toggleFullscreen);

  // Leaving fullscreen with Escape doesn't go through the button, so the
  // button's own state has to follow the document rather than its own clicks.
  document.addEventListener("fullscreenchange", syncFullscreenButton);

  // Escape also leaves the CSS fallback, matching what Escape does natively.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && fsEl.classList.contains("is-pseudo-fullscreen")) {
      fsEl.classList.remove("is-pseudo-fullscreen");
      syncFullscreenButton();
    }
  });

  applyZoom();
  syncFullscreenButton();

  return { setZoom, applyZoom, toggleFullscreen };
}

// ---------------------------------------------------------------------------
// Dropdown menus (colour, highlight)
// ---------------------------------------------------------------------------

// `onPick(kind, className)` is called with the chosen class. Opening a menu
// must not disturb the document's selection, or the pick would have nothing to
// apply to, which is why mousedown is suppressed throughout.
function initDocToolbarMenus({ toolbarEl, onPick }) {
  const menus = Array.from(toolbarEl.querySelectorAll(".doc-color-menu"));

  function closeAll(except) {
    menus.forEach((menu) => {
      if (menu !== except) menu.hidden = true;
    });
  }

  toolbarEl.querySelectorAll("[data-menu-toggle]").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", () => {
      const menu = toolbarEl.querySelector(`.doc-color-menu[data-menu="${btn.dataset.menuToggle}"]`);
      if (!menu) return;
      const opening = menu.hidden;
      closeAll(menu);
      menu.hidden = !opening;
    });
  });

  menus.forEach((menu) => {
    const kind = menu.dataset.menu;
    menu.querySelectorAll(".doc-color-option").forEach((opt) => {
      opt.addEventListener("mousedown", (e) => e.preventDefault());
      opt.addEventListener("click", () => {
        menu.hidden = true;
        onPick(kind, opt.dataset[kind]);
      });
    });
  });

  document.addEventListener("click", (event) => {
    if (!toolbarEl.contains(event.target)) closeAll(null);
  });
}
