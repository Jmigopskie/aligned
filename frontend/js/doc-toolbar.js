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

// Zoom steps, as multipliers of the page's true size (100% is what Word shows
// at 100%). A fixed ladder, so − and + always land somewhere sane.
const DOC_ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
// "Fit": the page scaled to the panel's width, never past 100%. The default.
const DOC_ZOOM_FIT = -1;

// The ladder step one notch in `direction` (+1 in, -1 out) from `scale`, or
// null when there is none. A phone's Fit (about 19%) sits below every step, so
// zooming out from it stays put rather than jumping up to 50%.
function docZoomStepIndex(scale, direction) {
  if (direction > 0) {
    const next = DOC_ZOOM_STEPS.findIndex((s) => s > scale + 0.001);
    return next === -1 ? null : next;
  }
  let next = null;
  DOC_ZOOM_STEPS.forEach((s, i) => {
    if (s < scale - 0.001) next = i;
  });
  return next;
}

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
      <button type="button" class="doc-tool-btn" data-image-insert="1" data-icon="image" title="Insert image"></button>
      <input type="file" data-image-input accept="image/png,image/jpeg,image/gif,image/webp" hidden />
    </div>
    <div class="doc-toolbar-sep"></div>
    <div class="doc-toolbar-group">
      <button type="button" class="doc-tool-btn" data-zoom="out" data-icon="zoomOut" title="Zoom out"></button>
      <button type="button" class="doc-tool-btn doc-zoom-readout" data-zoom="reset" title="Fit the page to the panel">Fit</button>
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
  // Icon-only buttons need a spoken name; title alone isn't reliably announced.
  toolbarEl.querySelectorAll("button[title]:not([aria-label])").forEach((btn) => {
    btn.setAttribute("aria-label", btn.title);
  });
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

// Zoom (a ladder of steps, plus Fit) and fullscreen for a document page.
function initDocViewControls({ toolbarEl, wrapEl, stageEl, storageKey }) {
  // What goes fullscreen. The toolbar has to be inside it or it vanishes the
  // moment fullscreen starts, so callers pass the element containing both.
  // Both call sites pass stageEl, and the wrapper-level fullscreen CSS was
  // removed when the stage was introduced, so fsEl is always the stage.
  const fsEl = stageEl;

  let zoomIndex = DOC_ZOOM_FIT;

  const readout = toolbarEl.querySelector(".doc-zoom-readout");
  const fullscreenBtn = toolbarEl.querySelector("[data-fullscreen=toggle]");

  // Remembered per page so a teacher who works zoomed in doesn't have to set
  // it again every visit. A failure here is ignored: private mode and blocked
  // storage must not stop the document from rendering. The key is new with
  // Fit: the old one held "100%" for everyone, saved on every visit.
  const zoomKey = storageKey ? `${storageKey}/2` : null;
  if (zoomKey) {
    try {
      const saved = parseInt(localStorage.getItem(zoomKey), 10);
      if (!Number.isNaN(saved) && saved >= DOC_ZOOM_FIT && saved < DOC_ZOOM_STEPS.length) zoomIndex = saved;
    } catch (err) {
      /* storage unavailable; Fit applies */
    }
  }

  function currentScale() {
    return zoomIndex === DOC_ZOOM_FIT ? docFitScale(wrapEl) : DOC_ZOOM_STEPS[zoomIndex];
  }

  function applyZoom() {
    const scale = currentScale();
    wrapEl.style.setProperty("--doc-zoom", String(scale));
    const pct = `${Math.round(scale * 100)}%`;
    if (readout) readout.textContent = zoomIndex === DOC_ZOOM_FIT ? `Fit ${pct}` : pct;
    if (zoomKey) {
      try {
        localStorage.setItem(zoomKey, String(zoomIndex));
      } catch (err) {
        /* storage unavailable; the zoom still applies for this visit */
      }
    }
  }

  function setZoom(index) {
    zoomIndex = Math.max(DOC_ZOOM_FIT, Math.min(DOC_ZOOM_STEPS.length - 1, index));
    applyZoom();
  }

  // − and + step along the ladder from wherever the page is now, Fit included.
  function stepZoom(direction) {
    const next = docZoomStepIndex(currentScale(), direction);
    if (next !== null) setZoom(next);
  }

  toolbarEl.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.zoom;
      if (action === "in") stepZoom(1);
      else if (action === "out") stepZoom(-1);
      else setZoom(DOC_ZOOM_FIT);
    });
  });

  // Ctrl+scroll over the document zooms, as it does in every document viewer.
  wrapEl.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      stepZoom(event.deltaY < 0 ? 1 : -1);
    },
    { passive: false }
  );

  // Fit follows the panel: a resize, fullscreen, or a new document loaded in.
  const refit = () => {
    if (zoomIndex === DOC_ZOOM_FIT) applyZoom();
  };
  if (window.ResizeObserver) new ResizeObserver(refit).observe(wrapEl);
  new MutationObserver(refit).observe(wrapEl, { childList: true });

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

// ---------------------------------------------------------------------------
// Images: one markup, one image bar, used by the builder and the generator.
// The vocabulary is closed for the same reason the font sizes are: the Word
// export reproduces exactly these properties and nothing else.
// ---------------------------------------------------------------------------

const DOC_IMG_ALIGNS = ["left", "center", "right"];
const DOC_IMG_WRAPS = ["inline", "left", "right"];

function docImageMarkup({ id, widthPct = 50, align = "center", wrap = "inline", border = false, caption = "" }) {
  const cap = caption ? `<span class="lp-img-cap" contenteditable="true">${escapeHtml(caption)}</span>` : "";
  return `<span class="lp-img img-align-${align} img-wrap-${wrap}${border ? " img-border" : ""}" data-img-id="${escapeHtml(id)}" data-width-pct="${widthPct}" contenteditable="false"><img src="${docImageUrl(id)}" alt="">${cap}</span>`;
}

function docImgClassValue(fig, prefix, allowed, fallback) {
  const cls = Array.from(fig.classList).find((c) => c.startsWith(prefix));
  const val = cls ? cls.slice(prefix.length) : fallback;
  return allowed.includes(val) ? val : fallback;
}

function readDocImage(fig) {
  const cap = fig.querySelector(".lp-img-cap");
  return {
    width_pct: Math.max(10, Math.min(100, parseInt(fig.dataset.widthPct, 10) || 50)),
    align: docImgClassValue(fig, "img-align-", DOC_IMG_ALIGNS, "left"),
    wrap: docImgClassValue(fig, "img-wrap-", DOC_IMG_WRAPS, "inline"),
    border: fig.classList.contains("img-border"),
    caption: cap ? cap.textContent.trim() : "",
  };
}

function hydrateDocImages(rootEl) {
  // Pictures straight from the Word file keep the layout's own size.
  rootEl.querySelectorAll(".lp-img:not(.lp-img-docx)").forEach((fig) => {
    fig.style.width = `${readDocImage(fig).width_pct}%`;
    const img = fig.querySelector("img");
    if (fig.dataset.imgId && img) img.src = docImageUrl(fig.dataset.imgId);
  });
}

function setDocImgClass(fig, prefix, value) {
  Array.from(fig.classList).filter((c) => c.startsWith(prefix)).forEach((c) => fig.classList.remove(c));
  fig.classList.add(prefix + value);
}

// `selectable(fig)` says which pictures this page lets the teacher change;
// `onChange(fig)` / `onDelete(fig)` persist the result in the page's own model.
function initDocImageTools({ rootEl, selectable = () => true, onChange, onDelete }) {
  const bar = document.createElement("div");
  bar.className = "doc-img-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Image options");
  bar.hidden = true;
  const btn = (act, val, label, html) =>
    `<button type="button" class="doc-img-btn" data-act="${act}" data-val="${val}" aria-label="${label}" title="${label}">${html}</button>`;
  bar.innerHTML = [
    btn("w", 25, "Small", "S"), btn("w", 50, "Medium", "M"), btn("w", 75, "Large", "L"), btn("w", 100, "Full width", "Full"),
    '<span class="doc-img-sep"></span>',
    btn("align", "left", "Align left", Icons.alignLeft), btn("align", "center", "Align centre", Icons.alignCenter), btn("align", "right", "Align right", Icons.alignRight),
    '<span class="doc-img-sep"></span>',
    btn("wrap", "inline", "In line with text", "Inline"), btn("wrap", "left", "Wrap text, image left", "Wrap L"), btn("wrap", "right", "Wrap text, image right", "Wrap R"),
    '<span class="doc-img-sep"></span>',
    btn("border", "", "Border", "Border"), btn("caption", "", "Caption", "Caption"),
    btn("delete", "", "Delete image", Icons.trash),
  ].join("");
  // Inside the document's stage when there is one, so it stays visible when
  // the stage goes fullscreen; fixed-positioned against the viewport.
  (rootEl.closest(".doc-stage") || document.body).appendChild(bar);

  let selected = null;

  function place() {
    if (!selected) return;
    const r = selected.getBoundingClientRect();
    const h = bar.offsetHeight;
    const top = r.top - h - 8 >= 8 ? r.top - h - 8 : r.bottom + 8;
    bar.style.top = `${top}px`;
    bar.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - bar.offsetWidth - 8))}px`;
  }

  function syncBar() {
    const s = readDocImage(selected);
    bar.querySelectorAll("[data-act]").forEach((b) => {
      const { act, val } = b.dataset;
      const on = (act === "w" && Number(val) === s.width_pct) || (act === "align" && val === s.align)
        || (act === "wrap" && val === s.wrap) || (act === "border" && s.border)
        || (act === "caption" && !!selected.querySelector(".lp-img-cap"));
      if (act !== "delete") b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function select(fig) {
    deselect();
    selected = fig;
    fig.classList.add("lp-img-selected");
    const handle = document.createElement("span");
    handle.className = "lp-img-handle";
    handle.setAttribute("aria-hidden", "true");
    fig.appendChild(handle);
    bar.hidden = false;
    syncBar();
    place();
  }

  function deselect() {
    if (!selected) return;
    selected.classList.remove("lp-img-selected");
    selected.querySelectorAll(".lp-img-handle").forEach((h) => h.remove());
    selected = null;
    bar.hidden = true;
  }

  function changed() {
    // The first change to a Word picture switches it from the layout's exact
    // placement to the editable preview, so the change can be seen.
    if (selected.classList.contains("lp-img-docx")) {
      selected.classList.remove("lp-img-docx");
      const img = selected.querySelector("img");
      if (img) img.removeAttribute("style");
    }
    hydrateDocImages(selected.parentElement || rootEl);
    syncBar();
    place();
    onChange(selected);
  }

  rootEl.addEventListener("click", (e) => {
    const fig = e.target.closest(".lp-img");
    if (fig && rootEl.contains(fig) && selectable(fig)) {
      if (e.target.closest(".lp-img-cap")) return; // typing a caption, not selecting
      select(fig);
    } else {
      deselect();
    }
  });
  document.addEventListener("click", (e) => {
    if (selected && !rootEl.contains(e.target) && !bar.contains(e.target)) deselect();
  });

  bar.addEventListener("mousedown", (e) => e.preventDefault());
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b || !selected) return;
    const { act, val } = b.dataset;
    if (act === "w") selected.dataset.widthPct = val;
    else if (act === "align") setDocImgClass(selected, "img-align-", val);
    else if (act === "wrap") setDocImgClass(selected, "img-wrap-", val);
    else if (act === "border") selected.classList.toggle("img-border");
    else if (act === "caption") {
      const cap = selected.querySelector(".lp-img-cap");
      if (cap) cap.remove();
      else {
        const c = document.createElement("span");
        c.className = "lp-img-cap";
        c.contentEditable = "true";
        c.textContent = "Caption";
        selected.insertBefore(c, selected.querySelector(".lp-img-handle"));
        c.focus();
        document.getSelection().selectAllChildren(c);
      }
    } else if (act === "delete") {
      const fig = selected;
      deselect();
      onDelete(fig);
      return;
    }
    changed();
  });

  // Corner drag: width as a share of the line the picture sits in, so the
  // number means the same thing in the canvas and in the exported document.
  rootEl.addEventListener("pointerdown", (e) => {
    if (!e.target.classList.contains("lp-img-handle") || !selected) return;
    e.preventDefault();
    const fig = selected;
    const box = (fig.parentElement || rootEl).getBoundingClientRect();
    const left = fig.getBoundingClientRect().left;
    const move = (ev) => {
      const pct = Math.round(((ev.clientX - left) / box.width) * 100);
      fig.dataset.widthPct = String(Math.max(10, Math.min(100, pct)));
      fig.style.width = `${fig.dataset.widthPct}%`;
      place();
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      if (selected === fig) changed();
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  });

  document.addEventListener("keydown", (e) => {
    if (!selected) return;
    if (e.key === "Escape") deselect();
    else if ((e.key === "Delete" || e.key === "Backspace") && !(e.target.closest && e.target.closest(".lp-img-cap"))) {
      e.preventDefault();
      const fig = selected;
      deselect();
      onDelete(fig);
    }
  });
  window.addEventListener("scroll", place, true);
  window.addEventListener("resize", place);

  return { deselect };
}

// The Image button: `beforePick()` may refuse (e.g. no line or field chosen
// yet) and should remember where the picture goes, since the file dialog
// takes the selection away; `onUploaded(result)` puts it there.
function initDocImageInsert({ toolbarEl, beforePick, onUploaded }) {
  const button = toolbarEl.querySelector("[data-image-insert]");
  const input = toolbarEl.querySelector("[data-image-input]");
  if (!button || !input) return;
  button.addEventListener("mousedown", (e) => e.preventDefault());
  button.addEventListener("click", () => {
    if (beforePick && !beforePick()) return;
    input.value = "";
    input.click();
  });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      showToast("Images must be 5 MB or smaller.", true);
      return;
    }
    button.disabled = true;
    try {
      onUploaded(await Api.uploadImage(file));
    } catch (err) {
      showToast(err.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
