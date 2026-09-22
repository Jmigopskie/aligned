// Checkbox selection plus the bulk archive bar, shared by the admin's
// accounts table and sections table. Both screens have the same shape — a
// checkbox on every row, one in the header that ticks the whole visible page,
// and a bar that appears only once something is selected — so the behaviour
// lives here once instead of being written twice and drifting apart.
//
// The caller re-renders its own rows whenever it likes and calls sync()
// afterwards; this keeps no copy of the row data, only the set of selected
// ids, so a re-render never invents or loses a selection.

function initBulkSelect({ kind, tbody, selectAllEl, barEl, countEl, archiveBtn, restoreBtn, clearBtn, onApplied }) {
  // Ids stay selected across re-renders (a filter change, a reload) and are
  // pruned in sync() to whatever is actually on screen, so a hidden row can
  // never be archived by a click the admin can't see the target of.
  const selected = new Set();

  function rowBoxes() {
    return Array.from(tbody.querySelectorAll("input[type=checkbox][data-bulk-id]"));
  }

  function selectedIds() {
    return Array.from(selected);
  }

  // Reflects the current selection into the checkboxes, the header box and the
  // bar. Called after every render and every click.
  function sync() {
    const boxes = rowBoxes();
    const visibleIds = new Set(boxes.map((b) => Number(b.dataset.bulkId)));

    // Drop anything no longer on screen.
    Array.from(selected).forEach((id) => {
      if (!visibleIds.has(id)) selected.delete(id);
    });

    boxes.forEach((box) => {
      box.checked = selected.has(Number(box.dataset.bulkId));
      box.closest("tr").classList.toggle("is-selected", box.checked);
    });

    if (selectAllEl) {
      const checkedCount = boxes.filter((b) => b.checked).length;
      selectAllEl.checked = boxes.length > 0 && checkedCount === boxes.length;
      // The header box shows a third state when only some rows are ticked, so
      // it never claims the whole page is selected when it isn't.
      selectAllEl.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
      selectAllEl.disabled = boxes.length === 0;
    }

    const count = selected.size;
    barEl.hidden = count === 0;
    if (countEl) {
      countEl.textContent = `${count} ${count === 1 ? "item" : "items"} selected`;
    }
  }

  function clear() {
    selected.clear();
    sync();
  }

  tbody.addEventListener("change", (event) => {
    const box = event.target.closest("input[type=checkbox][data-bulk-id]");
    if (!box) return;
    const id = Number(box.dataset.bulkId);
    if (box.checked) selected.add(id);
    else selected.delete(id);
    sync();
  });

  if (selectAllEl) {
    selectAllEl.addEventListener("change", () => {
      rowBoxes().forEach((box) => {
        const id = Number(box.dataset.bulkId);
        if (selectAllEl.checked) selected.add(id);
        else selected.delete(id);
      });
      sync();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", clear);
  }

  // Sends one batch and reports honestly: the server can refuse individual
  // ids (archiving yourself, the last admin) while applying the rest, so the
  // message names what it skipped instead of claiming a clean sweep.
  async function apply(isActive, btn) {
    const ids = selectedIds();
    if (!ids.length) return;

    const noun = kind === "sections" ? (ids.length === 1 ? "section" : "sections")
                                     : (ids.length === 1 ? "account" : "accounts");
    const prompt = isActive
      ? `Restore ${ids.length} ${noun}? They will appear in the active lists again.`
      : kind === "sections"
        ? `Archive ${ids.length} ${noun}? Students and submissions are kept, but the ${noun} stop appearing in class lists and can no longer be joined.`
        : `Archive ${ids.length} ${noun}? They keep all of their records but can no longer sign in.`;
    if (!confirm(prompt)) return;

    setButtonLoading(btn, true, isActive ? "Restoring" : "Archiving");
    try {
      const result = await Api.adminBulkArchive(kind, ids, isActive);
      const changed = result.updated_count || 0;
      const skipped = result.skipped || [];

      let message = `${changed} ${changed === 1 ? noun.replace(/s$/, "") : noun} ${isActive ? "restored" : "archived"}.`;
      if (skipped.length) {
        // One distinct reason is worth naming outright; several at once would
        // make the toast unreadable, so those are only counted.
        const reasons = Array.from(new Set(skipped.map((entry) => entry.reason)));
        message += reasons.length === 1
          ? ` ${skipped.length} skipped: ${reasons[0]}`
          : ` ${skipped.length} skipped.`;
      }
      showToast(message, skipped.length > 0 && changed === 0);

      selected.clear();
      if (onApplied) await onApplied();
      sync();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setButtonLoading(btn, false);
    }
  }

  if (archiveBtn) archiveBtn.addEventListener("click", () => apply(false, archiveBtn));
  if (restoreBtn) restoreBtn.addEventListener("click", () => apply(true, restoreBtn));

  return { sync, clear, selectedIds };
}

// The checkbox cell every bulk-selectable row starts with. Kept here so both
// tables render an identical cell and the selector above always matches.
function bulkCheckboxCell(id, label) {
  return `<td class="bulk-cell">
    <input type="checkbox" data-bulk-id="${id}" aria-label="Select ${escapeHtml(label || String(id))}" />
  </td>`;
}
