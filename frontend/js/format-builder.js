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

const chooseUploadBtn = document.getElementById("choose-upload");
const chooseBlankBtn = document.getElementById("choose-blank");
const uploadArea = document.getElementById("upload-area");
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
const docHeadingSelect = document.getElementById("doc-heading-select");
const docDeleteLineBtn = document.getElementById("doc-delete-line-btn");
const docSaveContentBtn = document.getElementById("doc-save-content-btn");
const docContentStatus = document.getElementById("doc-content-status");

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
let deletedAnchors = new Set();

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

chooseUploadBtn.addEventListener("click", () => {
  uploadArea.hidden = false;
  fileInput.click();
});

chooseBlankBtn.addEventListener("click", () => {
  sourceTempToken = null;
  sourceFilename = null;
  manualFieldEditor.hidden = false;
  docFieldEditor.hidden = true;
  fieldRowsEl.innerHTML = "";
  addFieldRow();
  goToStep2();
});

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
      showToast(`Loaded "${file.name}". Clean it up below, then save — AlignED figures out the fields for you.`);
    } else {
      // Couldn't render this file as a real document (e.g. a scanned/image PDF)
      // — the file is still attached as the reference, but fields must be
      // typed manually since there's no live layout for AI to read.
      manualFieldEditor.hidden = false;
      docFieldEditor.hidden = true;
      fieldRowsEl.innerHTML = "";
      addFieldRow();
      if (data.scan_error) showError(data.scan_error);
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
  snapshotContentState();
}

function normalizeAnchorText(raw) {
  return (raw || "").replace(/ /g, " ").trim();
}

function extractAnchorState(el) {
  const cs = getComputedStyle(el);
  const align = cs.textAlign === "start" ? "left" : cs.textAlign;
  return {
    text: normalizeAnchorText(el.textContent),
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
  deletedAnchors = new Set();
  docBuilderCanvas.querySelectorAll(".doc-preview-h1, .doc-preview-h2, .doc-preview-h3, .doc-preview-bullet, .doc-preview-number, .doc-marked-delete")
    .forEach((el) => el.classList.remove("doc-preview-h1", "doc-preview-h2", "doc-preview-h3", "doc-preview-bullet", "doc-preview-number", "doc-marked-delete"));
  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    contentSnapshot[idx] = extractAnchorState(el);
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
  deletedAnchors.forEach((idx) => edits.push({ anchor_index: idx, action: "delete" }));

  docBuilderCanvas.querySelectorAll("[data-anchor-index]").forEach((el) => {
    const idx = parseInt(el.dataset.anchorIndex, 10);
    if (deletedAnchors.has(idx)) return;

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

    if (Object.keys(patch).length) edits.push({ anchor_index: idx, action: "format", ...patch });
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
      if (deletedAnchors.has(idx)) {
        deletedAnchors.delete(idx);
        el.classList.remove("doc-marked-delete");
      } else {
        deletedAnchors.add(idx);
        el.classList.add("doc-marked-delete");
      }
    });
    updateSaveContentButton();
  });

  docBuilderCanvas.addEventListener("keyup", updateToolbarActiveStates);
  docBuilderCanvas.addEventListener("mouseup", updateToolbarActiveStates);
  docBuilderCanvas.addEventListener("input", updateSaveContentButton);

  docSaveContentBtn.addEventListener("click", async () => {
    const edits = buildContentEdits();
    if (!edits.length) return;

    const deleteCount = edits.filter((e) => e.action === "delete").length;
    const warning = deleteCount
      ? `This permanently deletes ${deleteCount} line${deleteCount === 1 ? "" : "s"} from the document. This can't be undone. Continue?`
      : "Save these changes into the document? This can't be undone.";
    if (!confirm(warning)) return;

    setButtonLoading(docSaveContentBtn, true, "Saving");
    try {
      if (editingFormatId) {
        await Api.editFormatContent(editingFormatId, edits);
        const refreshed = await Api.getFormatTemplateHtml(editingFormatId);
        renderDocCanvas(refreshed.html);
        showToast("Document updated — fields refreshed automatically.");
      } else {
        const data = await Api.editScannedContent(sourceTempToken, edits);
        renderDocCanvas(data.preview_html);
        showToast("Document updated.");
      }
    } catch (err) {
      showError(err.message);
    } finally {
      setButtonLoading(docSaveContentBtn, false);
    }
  });
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

  if (initial) {
    labelInput.value = initial.label || "";
    if (initial.field_type) typeSelect.value = initial.field_type;
    requiredInput.checked = initial.is_required !== false;
    keyPreview.textContent = labelInput.value.trim() ? slugify(labelInput.value) : "—";
  }

  labelInput.addEventListener("input", () => {
    keyPreview.textContent = labelInput.value.trim() ? slugify(labelInput.value) : "—";
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
      await Api.createFormat({
        name,
        is_public: document.getElementById("is-public").checked,
        fields,
        source_temp_token: sourceTempToken || undefined,
        source_filename: sourceFilename || undefined,
      });
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

document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("lesson-plan");

async function enterEditMode(fmt) {
  editingFormatId = fmt.id;
  pageTitle.textContent = "Edit format";
  document.title = "Edit format — AlignED";
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
      renderDocCanvas(data.html);
    } catch (err) {
      // No usable rendering of the reference file (e.g. it was removed from
      // disk) — the format still has its fields, just nothing to edit visually.
      docBuilderCanvas.innerHTML = '<p class="hint">This format\'s reference file couldn\'t be rendered.</p>';
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
