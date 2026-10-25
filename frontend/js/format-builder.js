const fieldRowsEl = document.getElementById("field-rows");
const addFieldBtn = document.getElementById("add-field-btn");
const createFormatBtn = document.getElementById("create-format-btn");
const fieldCountLabel = document.getElementById("field-count-label");
const errorBox = document.getElementById("error-box");
const rowTemplate = document.getElementById("field-row-template");

const step1 = document.getElementById("step-1");
const step2 = document.getElementById("step-2");
const stepIndicator1 = document.getElementById("step-indicator-1");
const stepIndicator2 = document.getElementById("step-indicator-2");

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const scanStatus = document.getElementById("scan-status");
const scanStatusText = document.getElementById("scan-status-text");
const backToStep1Btn = document.getElementById("back-to-step1-btn");
const deleteFormatBtn = document.getElementById("delete-format-btn");
const pageTitle = document.getElementById("page-title");
const stepIndicator = document.getElementById("step-indicator");

const manualFieldEditor = document.getElementById("manual-field-editor");
const docFieldEditor = document.getElementById("doc-field-editor");
const docBuilderCanvas = document.getElementById("doc-builder-canvas");

const docToolbar = document.getElementById("doc-toolbar");

// Built from the shared module before anything inside it is looked up, so this
// toolbar and the generator's offer the same tools rather than two hand-kept
// copies that drift apart. "builder" adds the two controls that only make sense
// against the template document itself: deleting a line, and saving the edits.
if (docToolbar) {
  docToolbar.innerHTML = renderDocToolbar({ variant: "builder" });
  paintDocToolbarIcons(docToolbar);

  // Generator-only: this screen edits the blank template, which has no field
  // content to clear.
  const clearFieldBtn = docToolbar.querySelector("[data-clear-field]");
  if (clearFieldBtn) clearFieldBtn.remove();
}

const docHeadingSelect = document.getElementById("doc-heading-select");
const docSizeSelect = document.getElementById("doc-size-select");
const docDeleteLineBtn = document.getElementById("doc-delete-line-btn");
const docSaveContentBtn = document.getElementById("doc-save-content-btn");
const docContentStatus = document.getElementById("doc-content-status");

const fieldRolesPanel = document.getElementById("field-roles-panel");
const fieldRolesList = document.getElementById("field-roles-list");
const fieldRolesStatus = document.getElementById("field-roles-status");
const fieldRolesSaveBtn = document.getElementById("field-roles-save-btn");

// ---- Fields: review what AlignED detected, and place missing ones by hand ----
// setupFields is the whole list the teacher sees, in document order; saving
// sends it whole. A field placed by hand has no field_key until it is saved.
const fieldAddBtn = document.getElementById("field-add-btn");
const fieldPlaceHint = document.getElementById("field-place-hint");
let setupFields = [];
let setupDirty = false;
let placing = false;

function anchorEl(idx) {
  return docBuilderCanvas.querySelector(`[data-anchor-index="${idx}"]`);
}

// The line a field's input sits beside, as the teacher reads it on the page.
function anchorText(idx) {
  const el = anchorEl(idx);
  const text = el ? normalizeAnchorText(lineTextWithoutImages(el)) : "";
  return text.length > 70 ? `${text.slice(0, 67)}…` : text;
}

function markSetupDirty() {
  setupDirty = true;
  fieldRolesSaveBtn.disabled = false;
  fieldRolesStatus.textContent = "Unsaved changes";
}

// Scroll to a field's line and flash it, with its input if the document has one.
function showFieldInDoc(f) {
  const line = anchorEl(f.anchor_index);
  const slots = f.field_key ? [...docBuilderCanvas.querySelectorAll(`[data-field-key="${CSS.escape(f.field_key)}"]`)] : [];
  if (!line) return;
  line.scrollIntoView({ behavior: "smooth", block: "center" });
  [line, ...slots].forEach((el) => {
    el.classList.remove("field-flash");
    void el.offsetWidth;
    el.classList.add("field-flash");
  });
}

function renderFieldSetup() {
  fieldRolesPanel.hidden = false;
  fieldRolesSaveBtn.disabled = !setupDirty;
  if (!setupDirty) fieldRolesStatus.textContent = `${setupFields.length} field${setupFields.length === 1 ? "" : "s"}`;
  fieldRolesList.replaceChildren(...setupFields.map((f, i) => {
    const row = document.createElement("div");
    row.className = `field-setup-row${f.locked ? " is-locked" : ""}`;
    const where = anchorText(f.anchor_index);
    row.innerHTML = `
      <div class="field-setup-main">
        <input type="text" class="field-setup-name" maxlength="200" aria-label="Field name" />
        <button type="button" class="field-setup-where"><span data-icon="eye"></span><span class="field-setup-where-text"></span></button>
      </div>
      <label class="field-setup-check"><input type="checkbox" data-flag="guided" /><span>Guided</span></label>
      <label class="field-setup-check"><input type="checkbox" data-flag="locked" /><span>Locked</span></label>
      <button type="button" class="field-setup-remove" aria-label="Remove this field"><span data-icon="x"></span></button>`;
    row.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = Icons[el.dataset.icon] || ""; });
    const name = row.querySelector(".field-setup-name");
    name.value = f.label;
    name.addEventListener("input", () => {
      f.label = name.value;
      markSetupDirty();
    });
    row.querySelector(".field-setup-where-text").textContent =
      `${f.manual && !f.field_key ? "New · " : ""}Written beside “${where || "this line"}” · Show`;
    row.querySelector(".field-setup-where").addEventListener("click", () => showFieldInDoc(f));
    row.querySelectorAll("[data-flag]").forEach((box) => {
      box.checked = !!f[box.dataset.flag];
      box.addEventListener("change", () => {
        f[box.dataset.flag] = box.checked;
        row.classList.toggle("is-locked", !!f.locked);
        markSetupDirty();
      });
    });
    row.querySelector(".field-setup-remove").addEventListener("click", () => {
      setupFields.splice(i, 1);
      markSetupDirty();
      renderFieldSetup();
    });
    return row;
  }));
}

function renderFieldRoles(fields) {
  if (!fields || !fields.length) {
    fieldRolesPanel.hidden = true;
    return;
  }
  setupFields = fields
    .filter((f) => f.anchor_index !== null && f.anchor_index !== undefined)
    .map((f) => ({ field_key: f.field_key, label: f.label, anchor_index: f.anchor_index, guided: f.role === "heavy", locked: !!f.locked, manual: !!f.manual }))
    .sort((a, b) => a.anchor_index - b.anchor_index);
  setupDirty = false;
  renderFieldSetup();
}

// ---- placing a field by hand: the next click on a line picks its spot ----
function setPlacing(on) {
  placing = on;
  docBuilderCanvas.classList.toggle("is-placing", on);
  fieldPlaceHint.hidden = !on;
  fieldAddBtn.disabled = on;
  if (on) docBuilderCanvas.scrollIntoView({ behavior: "smooth", block: "start" });
}

fieldAddBtn.addEventListener("click", () => setPlacing(true));
document.getElementById("field-place-cancel").addEventListener("click", () => setPlacing(false));
document.addEventListener("keydown", (e) => {
  if (placing && e.key === "Escape") setPlacing(false);
});

// Capture phase, so the pick never also starts editing the line.
docBuilderCanvas.addEventListener("click", (e) => {
  if (!placing) return;
  const line = e.target.closest("[data-anchor-index]");
  if (!line) return;
  e.preventDefault();
  e.stopPropagation();
  const idx = parseInt(line.dataset.anchorIndex, 10);
  if (setupFields.some((f) => f.anchor_index === idx)) {
    showToast("That line already has a field. Pick another line.", true);
    return;
  }
  const label = anchorText(idx).replace(/[:\s]+$/, "").slice(0, 60) || "New field";
  setupFields.push({ field_key: null, label, anchor_index: idx, guided: true, locked: false, manual: true });
  setupFields.sort((a, b) => a.anchor_index - b.anchor_index);
  setPlacing(false);
  markSetupDirty();
  renderFieldSetup();
  const added = setupFields.findIndex((f) => f.anchor_index === idx);
  const input = fieldRolesList.querySelectorAll(".field-setup-name")[added];
  if (input) {
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.focus();
    input.select();
  }
}, true);
docBuilderCanvas.addEventListener("mouseover", (e) => {
  if (!placing) return;
  docBuilderCanvas.querySelectorAll(".field-place-target").forEach((el) => el.classList.remove("field-place-target"));
  const line = e.target.closest("[data-anchor-index]");
  if (line) line.classList.add("field-place-target");
});

// Returns false when there was something to save and it didn't happen.
async function saveFieldSetup() {
  if (!editingFormatId || !setupDirty) return true;
  if (!setupFields.length) {
    showToast("A format needs at least one field.", true);
    return false;
  }
  if (setupFields.some((f) => !f.label.trim())) {
    showToast("Every field needs a name.", true);
    return false;
  }
  setButtonLoading(fieldRolesSaveBtn, true, "Saving");
  try {
    const data = await Api.saveFieldSetup(editingFormatId, setupFields.map(({ field_key, label, anchor_index, guided, locked }) =>
      ({ field_key, label: label.trim(), anchor_index, guided, locked })));
    // Redraw the document so each field's input shows where it now goes.
    const refreshed = await Api.getFormatTemplateHtml(editingFormatId);
    renderDocCanvas(refreshed.plain ? "" : refreshed.html); // the builder edits the real file, never the plain stand-in
    renderFieldRoles(data.format.fields);
    showToast("Fields saved.");
    return true;
  } catch (err) {
    showToast(err.message, true);
    return false;
  } finally {
    setButtonLoading(fieldRolesSaveBtn, false);
  }
}

fieldRolesSaveBtn.addEventListener("click", saveFieldSetup);

document.querySelectorAll("[data-icon]").forEach((el) => {
  const icon = Icons[el.dataset.icon] || "";
  el.innerHTML = el.dataset.iconLabel ? `${icon}<span>${el.dataset.iconLabel}</span>` : icon;
});

let sourceTempToken = null;
let sourceFilename = null;
let editingFormatId = null;

// ---- Content-edit state — the only thing the document canvas is for now.
// Fields are never defined by hand: AlignED reads them automatically from
// whatever's left in the document once the format is saved. ----
let contentSnapshot = {}; // anchor_index -> { text, bold, italic, underline, align }
let headingEdits = {};    // anchor_index -> 0|1|2|3, only set once the teacher changes it
let listEdits = {};       // anchor_index -> "bullet" | "number" | null, only set once changed
// Font size, colour and highlight, applied to a whole line here rather than to a
// selection. The builder's whole edit model is per-line (bold and alignment work
// the same way), and the saved .docx carries these on every run of the line.
let sizeEdits = {};       // anchor_index -> "fs-sm" | "fs-md" | "fs-lg" | "fs-xl" | ""
let colorEdits = {};      // anchor_index -> "fc-default" | "fc-red" | ...
let highlightEdits = {};  // anchor_index -> "hl-none" | "hl-yellow" | ...
let markedDeletes = new Set(); // lines marked with the toolbar's Delete button
let imageSnapshot = {};    // "anchor:n" -> readDocImage(fig) for the document's own pictures
let lastFocusedAnchor = null; // where an inserted picture goes; the file dialog drops the selection

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFileSelected(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFileSelected(fileInput.files[0]);
});

async function handleFileSelected(file) {
  const allowed = /\.(docx|dotx|pdf)$/i;
  if (!allowed.test(file.name)) {
    showError("Only .docx, .dotx, or .pdf files are allowed.");
    return;
  }
  errorBox.hidden = true;

  scanStatus.hidden = false;
  scanStatusText.textContent = `Reading ${file.name}…`;
  dropzone.style.opacity = "0.5";
  dropzone.style.pointerEvents = "none";

  try {
    const data = await Api.scanFormat(file);
    sourceTempToken = data.source_temp_token;
    sourceFilename = data.source_filename;

    if (data.preview_html) {
      manualFieldEditor.hidden = true;
      docFieldEditor.hidden = false;
      renderDocCanvas(data.preview_html);
      updateFieldCount();
      showToast(`Loaded "${file.name}". Clean it up below, then save. AlignED works out the fields for you.`);
    } else {
      // Couldn't render this file as a real document (e.g. a scanned/image
      // PDF). Formats are only made from a readable file, never typed by hand.
      sourceTempToken = null;
      sourceFilename = null;
      showError(data.scan_error ||
        "AlignED couldn't read that file. Upload a .docx copy of your format, or a PDF that has real text rather than a scan.");
      return;
    }

    goToStep2();
  } catch (err) {
    showError(err.message);
  } finally {
    scanStatus.hidden = true;
    dropzone.style.opacity = "1";
    dropzone.style.pointerEvents = "auto";
  }
}

// ---- Document canvas — a real formatting toolbar over the live document,
// for cleaning up leftover/unwanted content (fix typos, delete a stray
// line, restyle text). Always editable; there's no separate "define fields"
// mode anymore. ----

function renderDocCanvas(html) {
  docBuilderCanvas.innerHTML = html;
  docBuilderCanvas.contentEditable = "true";
  hydrateDocImages(docBuilderCanvas);
  lastFocusedAnchor = null;
  snapshotContentState();
}

// A line's own text. A picture's caption is part of the picture, not the line,
// so it must not make the line look edited.
function lineTextWithoutImages(el) {
  const clone = el.cloneNode(true);
  clone.querySelectorAll(".lp-img").forEach((f) => f.remove());
  return clone.textContent;
}

function normalizeAnchorText(raw) {
  return (raw || "").replace(/ /g, " ").trim();
}

function extractAnchorState(el) {
  const cs = getComputedStyle(el);
  const align = cs.textAlign === "start" ? "left" : cs.textAlign;
  return {
    text: normalizeAnchorText(lineTextWithoutImages(el)),
    bold: parseInt(cs.fontWeight, 10) >= 600,
    italic: cs.fontStyle === "italic",
    underline: (cs.textDecorationLine || cs.textDecoration || "").includes("underline"),
    align,
  };
}

function snapshotContentState() {
  contentSnapshot = {};
  headingEdits = {};
  listEdits = {};
  sizeEdits = {};
  colorEdits = {};
  highlightEdits = {};
  markedDeletes = new Set();
  docBuilderCanvas.querySelectorAll(".doc-preview-h1, .doc-preview-h2, .doc-preview-h3, .doc-preview-bullet, .doc-preview-number, .doc-marked-delete")
    .forEach((el) => el.classList.remove("doc-preview-h1", "doc-preview-h2", "doc-preview-h3", "doc-preview-bullet", "doc-preview-number", "doc-marked-delete"));
  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    contentSnapshot[idx] = extractAnchorState(el);
  });
  imageSnapshot = {};
  docBuilderCanvas.querySelectorAll("[data-anchor-index] .lp-img[data-docx-image]").forEach((fig) => {
    const idx = fig.closest("[data-anchor-index]").dataset.anchorIndex;
    // Where the picture started: Backspace can carry it into another line.
    fig.dataset.originAnchor = idx;
    imageSnapshot[`${idx}:${fig.dataset.docxImage}`] = readDocImage(fig);
  });
  updateSaveContentButton();
}

function getSelectedAnchorEls() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return [];
  const range = sel.getRangeAt(0);
  return [...docBuilderCanvas.querySelectorAll("[data-anchor-index]")].filter((el) => range.intersectsNode(el));
}

function buildContentEdits() {
  const edits = [];
  const present = new Set();
  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => present.add(parseInt(el.dataset.anchorIndex, 10)));

  // A line removed with Backspace/Delete is simply gone from the canvas; it has
  // to be sent as a delete or the next render brings it straight back. Worked
  // out fresh on every call, so undoing the Backspace un-deletes it too.
  const deletes = new Set(markedDeletes);
  Object.keys(contentSnapshot).forEach((key) => {
    const idx = parseInt(key, 10);
    if (!present.has(idx)) deletes.add(idx);
  });
  deletes.forEach((idx) => {
    const edit = { anchor_index: idx, action: "delete" };
    // A line merged into the one above takes its picture with it on screen; the
    // file has to do the same, or deleting the line deletes the picture too.
    const carried = docBuilderCanvas.querySelector(`.lp-img[data-origin-anchor="${idx}"]`);
    const home = carried && carried.closest("[data-anchor-index]");
    if (home && !markedDeletes.has(idx)) edit.move_images_to = parseInt(home.dataset.anchorIndex, 10);
    edits.push(edit);
  });

  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    if (deletes.has(idx)) return;

    const before = contentSnapshot[idx];
    if (!before) return;
    const now = extractAnchorState(el);
    const patch = {};

    if (now.text !== before.text) patch.text = now.text;
    if (now.bold !== before.bold) patch.bold = now.bold;
    if (now.italic !== before.italic) patch.italic = now.italic;
    if (now.underline !== before.underline) patch.underline = now.underline;
    if (now.align !== before.align) patch.align = now.align;
    if (headingEdits[idx] !== undefined) patch.heading = headingEdits[idx];
    if (listEdits[idx] !== undefined) patch.list = listEdits[idx];
    if (sizeEdits[idx]) patch.size = sizeEdits[idx];
    if (colorEdits[idx]) patch.color = colorEdits[idx];
    if (highlightEdits[idx]) patch.highlight = highlightEdits[idx];

    // The document's own pictures in this line: removed, or restyled.
    const removed = [];
    const restyled = [];
    Object.keys(imageSnapshot).filter((k) => k.startsWith(`${idx}:`)).forEach((k) => {
      const n = parseInt(k.split(":")[1], 10);
      const fig = el.querySelector(`.lp-img[data-docx-image="${n}"][data-origin-anchor="${idx}"]`);
      if (!fig) {
        removed.push(n);
        return;
      }
      const state = readDocImage(fig);
      if (JSON.stringify(state) !== JSON.stringify(imageSnapshot[k])) restyled.push({ n, ...state });
    });
    if (removed.length) patch.remove_images = removed;
    if (restyled.length) patch.image_format = restyled;

    if (Object.keys(patch).length) edits.push({ anchor_index: idx, action: "format", ...patch });

    // New pictures the teacher inserted into this line go in right after it.
    el.querySelectorAll(".lp-img[data-img-id]").forEach((fig) => {
      edits.push({ anchor_index: idx, action: "insert_image", image_id: fig.dataset.imgId, ...readDocImage(fig) });
    });
  });

  return edits;
}

function updateSaveContentButton() {
  const count = buildContentEdits().length;
  docSaveContentBtn.disabled = count === 0;
  docContentStatus.textContent = count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "";
}

function updateToolbarActiveStates() {
  ["bold", "italic", "underline", "justifyLeft", "justifyCenter", "justifyRight", "justifyFull"].forEach((cmd) => {
    const btn = docToolbar.querySelector(`[data-cmd="${cmd}"]`);
    if (btn) {
      let active = false;
      try { active = document.queryCommandState(cmd); } catch (e) { /* unsupported in this browser */ }
      btn.classList.toggle("active", active);
    }
  });
}

if (docToolbar) {
  // Keep the canvas selection alive when a toolbar control is clicked —
  // otherwise the button/select would steal focus and the command would
  // have nothing to act on.
  docToolbar.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  // The view controls (zoom, fullscreen) behave identically on both document
  // screens, so they come straight from the shared module.
  initDocViewControls({
    toolbarEl: docToolbar,
    wrapEl: docBuilderCanvas,
    stageEl: document.getElementById("doc-stage"),
    storageKey: "alignedDocZoom:builder",
  });

  // Font size, text colour and highlight apply to the whole selected line,
  // matching how this page already treats bold and alignment: its edit model is
  // per-line, keyed by anchor index, and the saved .docx carries the property on
  // every run of that line. Styling an arbitrary selection instead would look
  // right in the canvas and then be dropped by the per-line save.
  function applyLineStyle(kind, className) {
    const anchors = getSelectedAnchorEls();
    if (!anchors.length) {
      showToast("Click into a line first, then choose a style.", true);
      return;
    }

    const store = kind === "size" ? sizeEdits : kind === "color" ? colorEdits : highlightEdits;
    const prefix = kind === "size" ? "fs-" : kind === "color" ? "fc-" : "hl-";

    anchors.forEach((el) => {
      const idx = parseInt(el.dataset.anchorIndex, 10);
      store[idx] = className;

      // Preview it immediately. The class is swapped rather than added, so
      // picking red after blue replaces it.
      Array.from(el.classList)
        .filter((cls) => cls.startsWith(prefix))
        .forEach((cls) => el.classList.remove(cls));
      if (className) el.classList.add(className);
    });

    updateSaveContentButton();
  }

  initDocToolbarMenus({
    toolbarEl: docToolbar,
    onPick: (kind, className) => applyLineStyle(kind, className),
  });

  if (docSizeSelect) {
    docSizeSelect.addEventListener("change", () => {
      applyLineStyle("size", docSizeSelect.value);
      docSizeSelect.value = "";
    });
  }

  docToolbar.querySelectorAll(".doc-tool-btn[data-cmd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      docBuilderCanvas.focus();
      document.execCommand(btn.dataset.cmd, false, null);
      updateToolbarActiveStates();
      updateSaveContentButton();
    });
  });

  docToolbar.querySelectorAll(".doc-tool-btn[data-list]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const anchors = getSelectedAnchorEls();
      if (!anchors.length) {
        showToast("Click into a line first, then choose a list style.", true);
        return;
      }
      const listType = btn.dataset.list;
      anchors.forEach((el) => {
        const idx = parseInt(el.dataset.anchorIndex, 10);
        const current = listEdits[idx] !== undefined
          ? listEdits[idx]
          : (el.classList.contains("doc-preview-bullet") ? "bullet" : el.classList.contains("doc-preview-number") ? "number" : null);
        const next = current === listType ? null : listType;
        listEdits[idx] = next;
        el.classList.remove("doc-preview-bullet", "doc-preview-number");
        if (next === "bullet") el.classList.add("doc-preview-bullet");
        if (next === "number") el.classList.add("doc-preview-number");
      });
      updateSaveContentButton();
    });
  });

  docHeadingSelect.addEventListener("change", () => {
    const anchors = getSelectedAnchorEls();
    if (!anchors.length) {
      showToast("Click into a line first, then choose a style.", true);
      docHeadingSelect.value = "p";
      return;
    }
    const level = docHeadingSelect.value === "p" ? 0 : parseInt(docHeadingSelect.value.slice(1), 10);
    anchors.forEach((el) => {
      const idx = parseInt(el.dataset.anchorIndex, 10);
      headingEdits[idx] = level;
      el.classList.remove("doc-preview-h1", "doc-preview-h2", "doc-preview-h3");
      if (level) el.classList.add(`doc-preview-h${level}`);
    });
    docHeadingSelect.value = "p";
    updateSaveContentButton();
  });

  docDeleteLineBtn.addEventListener("click", () => {
    const anchors = getSelectedAnchorEls();
    if (!anchors.length) {
      showToast("Click into a line first, then Delete.", true);
      return;
    }
    anchors.forEach((el) => {
      const idx = parseInt(el.dataset.anchorIndex, 10);
      if (markedDeletes.has(idx)) {
        markedDeletes.delete(idx);
        el.classList.remove("doc-marked-delete");
      } else {
        markedDeletes.add(idx);
        el.classList.add("doc-marked-delete");
      }
    });
    updateSaveContentButton();
  });

  function rememberAnchor() {
    lastFocusedAnchor = getSelectedAnchorEls().pop() || lastFocusedAnchor;
  }

  docBuilderCanvas.addEventListener("keyup", () => { updateToolbarActiveStates(); rememberAnchor(); });
  docBuilderCanvas.addEventListener("mouseup", () => { updateToolbarActiveStates(); rememberAnchor(); });
  docBuilderCanvas.addEventListener("input", updateSaveContentButton);

  initDocImageTools({
    rootEl: docBuilderCanvas,
    onChange: () => updateSaveContentButton(),
    onDelete: (fig) => {
      fig.remove();
      updateSaveContentButton();
    },
  });

  initDocImageInsert({
    toolbarEl: docToolbar,
    beforePick: () => {
      rememberAnchor();
      if (lastFocusedAnchor && docBuilderCanvas.contains(lastFocusedAnchor)) return true;
      showToast("Click into the line the picture should follow, then choose Insert image.", true);
      return false;
    },
    onUploaded: (res) => {
      const anchor = lastFocusedAnchor;
      if (!anchor || !docBuilderCanvas.contains(anchor)) return;
      anchor.insertAdjacentHTML("beforeend", docImageMarkup({ id: res.id }));
      hydrateDocImages(anchor);
      updateSaveContentButton();
    },
  });

  docSaveContentBtn.addEventListener("click", flushContentEdits);
}

// Applies the canvas edits. Returns false when there was something to save and
// it didn't happen (the teacher cancelled, or the request failed), so callers
// can stop instead of quietly leaving work behind.
async function flushContentEdits() {
  const edits = buildContentEdits();
  if (!edits.length) return true;
  // Unsaved field changes point at lines as they are now; an edit could move them.
  if (editingFormatId && setupDirty) {
    showToast("Save your field changes first, then save the document.", true);
    return false;
  }

  const deleteCount = edits.filter((e) => e.action === "delete").length;
  const warning = deleteCount
    ? `This permanently deletes ${deleteCount} line${deleteCount === 1 ? "" : "s"} from the document. This can't be undone. Continue?`
    : "Save these changes into the document? This can't be undone.";
  if (!confirm(warning)) return false;

  setButtonLoading(docSaveContentBtn, true, "Saving");
  try {
    if (editingFormatId) {
      const res = await Api.editFormatContent(editingFormatId, edits);
      const refreshed = await Api.getFormatTemplateHtml(editingFormatId);
      renderDocCanvas(refreshed.plain ? "" : refreshed.html);
      renderFieldRoles(res.format.fields);
      showToast(res.format.fields_reviewed ? "Document updated. Your fields moved with their lines." : "Document updated. Fields refreshed automatically.");
    } else {
      const data = await Api.editScannedContent(sourceTempToken, edits);
      renderDocCanvas(data.preview_html);
      showToast("Document updated.");
    }
    return true;
  } catch (err) {
    showError(err.message);
    return false;
  } finally {
    setButtonLoading(docSaveContentBtn, false);
  }
}

// ---- Manual (blank-start) row editor — unchanged flow for formats with no reference file ----

function renumberContainer(container) {
  const rows = container.querySelectorAll(".field-row");
  rows.forEach((row, i) => {
    row.querySelector(".field-index").textContent = `Field ${i + 1}`;
  });
}

function updateFieldCount() {
  if (!manualFieldEditor.hidden) {
    const total = fieldRowsEl.querySelectorAll(".field-row").length;
    fieldCountLabel.hidden = false;
    fieldCountLabel.textContent = `${total} field${total === 1 ? "" : "s"}`;
    createFormatBtn.disabled = total === 0;
  } else {
    fieldCountLabel.hidden = true;
    createFormatBtn.disabled = false;
  }
}

function addFieldRow(initial, container) {
  const target = container || fieldRowsEl;
  const node = rowTemplate.content.cloneNode(true);
  const row = node.querySelector(".field-row");

  const labelInput = row.querySelector(".field-label");
  const keyPreview = row.querySelector(".field-key-preview");
  const typeSelect = row.querySelector(".field-type");
  const requiredInput = row.querySelector(".field-required");

  const roleSelect = row.querySelector(".field-role");

  if (initial) {
    labelInput.value = initial.label || "";
    if (initial.field_type) typeSelect.value = initial.field_type;
    requiredInput.checked = initial.is_required !== false;
    keyPreview.textContent = labelInput.value.trim() ? slugify(labelInput.value) : "\u2013";
    // The stored override, not the resolved role: "decide automatically" has to
    // stay distinguishable from an explicit choice that happens to agree.
    roleSelect.value = initial.role_override || "";
    row.querySelector(".field-locked").checked = !!initial.locked;
  }

  labelInput.addEventListener("input", () => {
    keyPreview.textContent = labelInput.value.trim() ? slugify(labelInput.value) : "\u2013";
  });

  row.querySelector(".remove-field-btn").addEventListener("click", () => {
    row.remove();
    renumberContainer(target);
    updateFieldCount();
  });

  target.appendChild(row);
  renumberContainer(target);
  updateFieldCount();
  if (!initial && target === fieldRowsEl) labelInput.focus();
}

addFieldBtn.addEventListener("click", () => addFieldRow());

function collectManualFields() {
  const usedKeys = new Set();
  const rows = [...fieldRowsEl.querySelectorAll(".field-row")];
  const collected = [];

  rows.forEach((row, i) => {
    const label = row.querySelector(".field-label").value.trim();
    if (!label) return;

    let key = slugify(label);
    let finalKey = key;
    let suffix = 2;
    while (usedKeys.has(finalKey)) {
      finalKey = `${key}_${suffix}`;
      suffix += 1;
    }
    usedKeys.add(finalKey);

    collected.push({
      field_key: finalKey,
      label,
      field_type: row.querySelector(".field-type").value,
      is_required: row.querySelector(".field-required").checked,
      sort_order: i,
      role: row.querySelector(".field-role").value || null,
      locked: row.querySelector(".field-locked").checked,
    });
  });

  return collected;
}

function goToStep2() {
  step1.hidden = true;
  step2.hidden = false;
  stepIndicator1.classList.remove("active");
  stepIndicator1.classList.add("done");
  stepIndicator2.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
  document.getElementById("format-name").focus();
  OwlGuide.show(docFieldEditor.hidden ? "format-blank" : "format-cleanup");
}

backToStep1Btn.addEventListener("click", () => {
  step1.hidden = false;
  step2.hidden = true;
  OwlGuide.show("format-source");
  stepIndicator1.classList.add("active");
  stepIndicator1.classList.remove("done");
  stepIndicator2.classList.remove("active");
  errorBox.hidden = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

createFormatBtn.addEventListener("click", async () => {
  errorBox.hidden = true;

  const name = document.getElementById("format-name").value.trim();
  if (!name) {
    showError("Give this format a name.");
    return;
  }

  const isDocBased = !docFieldEditor.hidden;
  // Edits still waiting behind "Save changes to document" are applied first;
  // saving the format must never quietly leave them behind.
  if (isDocBased && !(await saveFieldSetup())) return;
  if (isDocBased && !(await flushContentEdits())) return;
  const fields = isDocBased ? undefined : collectManualFields();
  if (!isDocBased && !fields.length) {
    showError("Add at least one field with a label.");
    return;
  }

  setButtonLoading(createFormatBtn, true, "Saving");
  try {
    if (editingFormatId) {
      const payload = { name, is_public: document.getElementById("is-public").checked };
      if (fields) payload.fields = fields; // omitted for doc-based — the server keeps its auto-detected fields as-is
      await Api.updateFormat(editingFormatId, payload);
      showToast("Format updated.");
    } else {
      const created = await Api.createFormat({
        name,
        is_public: document.getElementById("is-public").checked,
        fields,
        source_temp_token: sourceTempToken || undefined,
        source_filename: sourceFilename || undefined,
      });
      // A document-based format opens straight into reviewing what was detected.
      if (isDocBased && created.format) {
        window.location.href = `format-builder.html?format_id=${created.format.id}&review=1`;
        return;
      }
      showToast("Format created.");
    }
    window.location.href = "lesson-plan.html";
  } catch (err) {
    showError(err.message);
  } finally {
    setButtonLoading(createFormatBtn, false);
  }
});

deleteFormatBtn.addEventListener("click", async () => {
  if (!editingFormatId) return;
  if (!confirm("Delete this format permanently? This can't be undone.")) return;
  setButtonLoading(deleteFormatBtn, true, "Deleting");
  try {
    await Api.deleteFormat(editingFormatId);
    showToast("Format deleted.");
    window.location.href = "lesson-plan.html";
  } catch (err) {
    showError(err.message);
    setButtonLoading(deleteFormatBtn, false);
  }
});

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("formats");

async function enterEditMode(fmt) {
  editingFormatId = fmt.id;
  pageTitle.textContent = "Edit format";
  document.title = "Edit format | AlignED";
  stepIndicator.hidden = true;
  backToStep1Btn.textContent = "Cancel";
  backToStep1Btn.onclick = () => (window.location.href = "lesson-plan.html");
  deleteFormatBtn.hidden = false;
  createFormatBtn.textContent = "Save changes";

  document.getElementById("format-name").value = fmt.name || "";
  document.getElementById("is-public").checked = !!fmt.is_public;

  if (fmt.has_source_file) {
    manualFieldEditor.hidden = true;
    docFieldEditor.hidden = false;

    try {
      const data = await Api.getFormatTemplateHtml(fmt.id);
      renderDocCanvas(data.plain ? "" : data.html);
    } catch (err) {
      // No usable rendering of the reference file (e.g. it was removed from
      // disk) — the format still has its fields, just nothing to edit visually.
      docBuilderCanvas.innerHTML = '<p class="hint">This format\'s reference file couldn\'t be rendered.</p>';
    }

    // Only for a format that already exists: fields are saved against a format
    // id, so a brand-new format opens here right after its first save.
    renderFieldRoles(fmt.fields || []);
    if (new URLSearchParams(location.search).get("review")) {
      const n = (fmt.fields || []).length;
      fieldRolesStatus.textContent = `AlignED found ${n} field${n === 1 ? "" : "s"}. Check them, then save.`;
      fieldRolesSaveBtn.disabled = false;
      setupDirty = true;
      requestAnimationFrame(() => fieldRolesPanel.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  } else {
    manualFieldEditor.hidden = false;
    docFieldEditor.hidden = true;
    fieldRowsEl.innerHTML = "";
    const allFields = (fmt.fields || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    if (allFields.length) {
      allFields.forEach((f) => addFieldRow(f));
    } else {
      addFieldRow();
    }
  }

  updateFieldCount();
  step1.hidden = true;
  step2.hidden = false;
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  // Only teachers upload or change formats (the server refuses students too).
  if (user.role === "student") {
    window.location.replace("generator.html");
    return;
  }
  wireTopbar(user);

  const formatId = new URLSearchParams(window.location.search).get("format_id");
  if (!formatId) OwlGuide.show("format-source");
  if (formatId) {
    try {
      const data = await Api.getFormat(formatId);
      const fmt = data.format;
      if (fmt.owner_id !== user.id) {
        showToast("Only the teacher who created this format can edit it.", true);
        window.location.href = "lesson-plan.html";
        return;
      }
      await enterEditMode(fmt);
    } catch (err) {
      showToast(err.message, true);
      window.location.href = "lesson-plan.html";
    }
  }
}

init();
