/**
 * Configurações de checklists — filtros/paginação leves (sem re-render pesado).
 */
(function () {
  "use strict";

  var DEBOUNCE_MS = 260;
  var PAGE_SIZE = 48;

  var filterStatus = "all";
  var searchText = "";
  var debounceTimer = null;
  var currentPage = 1;

  function norm(s) {
    return (s || "").toString().toLowerCase().trim();
  }

  function getRows() {
    var tb = document.getElementById("equipmentTableBody");
    if (!tb) return [];
    return Array.prototype.slice.call(tb.querySelectorAll("tr.equipment-settings-row"));
  }

  function rowMatches(row) {
    var st = row.getAttribute("data-status") || "";
    if (filterStatus !== "all" && st !== filterStatus) return false;
    if (!searchText) return true;
    var code = norm(row.getAttribute("data-code"));
    return code.indexOf(searchText) !== -1;
  }

  function computeVisibleIndices(rows) {
    var ix = [];
    for (var i = 0; i < rows.length; i++) {
      if (rowMatches(rows[i])) ix.push(i);
    }
    return ix;
  }

  function renderEquipmentTable() {
    var rows = getRows();
    var visibleIx = computeVisibleIndices(rows);
    var totalVis = visibleIx.length;
    var pages = Math.max(1, Math.ceil(totalVis / PAGE_SIZE));
    if (currentPage > pages) currentPage = pages;

    var start = (currentPage - 1) * PAGE_SIZE;
    var allowed = {};
    for (var j = start; j < Math.min(start + PAGE_SIZE, totalVis); j++) {
      allowed[visibleIx[j]] = true;
    }

    for (var r = 0; r < rows.length; r++) {
      var passes = rowMatches(rows[r]);
      var show = passes && allowed[r] === true;
      rows[r].classList.toggle("hidden", !show);
    }

    var countEl = document.getElementById("equipmentVisibleCount");
    var pageEl = document.getElementById("equipmentPageLabel");
    if (countEl) countEl.textContent = String(totalVis);
    if (pageEl) pageEl.textContent = "Página " + currentPage + " / " + pages;

    var prev = document.getElementById("equipmentPrevPage");
    var next = document.getElementById("equipmentNextPage");
    if (prev) {
      prev.disabled = currentPage <= 1;
      prev.classList.toggle("opacity-50", currentPage <= 1);
    }
    if (next) {
      next.disabled = currentPage >= pages;
      next.classList.toggle("opacity-50", currentPage >= pages);
    }
  }

  function scheduleRender() {
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(renderEquipmentTable);
    } else {
      renderEquipmentTable();
    }
  }

  window.chkSettingsSetFilter = function (status) {
    filterStatus = status || "all";
    currentPage = 1;

    document.querySelectorAll("[data-equip-filter]").forEach(function (btn) {
      var v = btn.getAttribute("data-equip-filter");
      var on = v === filterStatus;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("filter-btn--active", on);
    });

    scheduleRender();
  };

  window.chkSettingsClearSearch = function () {
    var inp = document.getElementById("equipmentSearchInput");
    if (inp) inp.value = "";
    searchText = "";
    currentPage = 1;
    chkSettingsSetFilter("all");
  };

  window.chkSettingsEquipmentPrev = function () {
    if (currentPage > 1) {
      currentPage--;
      scheduleRender();
    }
  };

  window.chkSettingsEquipmentNext = function () {
    currentPage++;
    scheduleRender();
  };

  window.chkSettingsOpenCreateModal = function () {
    var m = document.getElementById("createEquipmentModal");
    if (m) m.classList.remove("hidden");
  };
  window.chkSettingsCloseCreateModal = function () {
    var m = document.getElementById("createEquipmentModal");
    if (m) m.classList.add("hidden");
  };
  window.chkSettingsOpenImportModal = function () {
    var m = document.getElementById("importEquipmentModal");
    if (m) m.classList.remove("hidden");
  };
  window.chkSettingsCloseImportModal = function () {
    var m = document.getElementById("importEquipmentModal");
    if (m) m.classList.add("hidden");
  };
  window.chkSettingsOpenBulkModal = function () {
    var m = document.getElementById("bulkEquipmentModal");
    if (m) m.classList.remove("hidden");
  };
  window.chkSettingsCloseBulkModal = function () {
    var m = document.getElementById("bulkEquipmentModal");
    if (m) m.classList.add("hidden");
  };
  window.chkSettingsOpenAddEmailModal = function () {
    var m = document.getElementById("addEmailModal");
    if (m) m.classList.remove("hidden");
  };
  window.chkSettingsCloseAddEmailModal = function () {
    var m = document.getElementById("addEmailModal");
    if (m) m.classList.add("hidden");
  };

  window.chkSettingsOpenEditModal = function (id, code, status, usage) {
    var m = document.getElementById("editEquipmentModal");
    if (!m) return;
    var idEl = document.getElementById("editEquipmentId");
    if (idEl) idEl.value = id;
    var form = document.getElementById("editEquipmentForm");
    if (form) form.action = "/admin/routine/checklists/settings/equipment/" + id + "/update-code";
    var codeInput = document.getElementById("editEquipmentCode");
    codeInput.value = code || "";
    codeInput.disabled = Number(usage) > 0;
    document.getElementById("editEquipmentUsageHint").textContent =
      Number(usage) > 0
        ? "Este equipamento possui checklists — o código não pode ser alterado."
        : "Sem checklists — você pode ajustar o código com segurança.";
    m.classList.remove("hidden");
  };
  window.chkSettingsCloseEditModal = function () {
    var m = document.getElementById("editEquipmentModal");
    if (m) m.classList.add("hidden");
  };

  window.chkSettingsOpenBlockModal = function (id, code) {
    var m = document.getElementById("blockEquipmentModal");
    if (!m) return;
    var form = document.getElementById("blockEquipmentForm");
    if (form) form.action = "/admin/routine/checklists/settings/equipment/" + id + "/block";
    document.getElementById("blockEquipmentCodeLabel").textContent = code || "";
    var reason = document.getElementById("blockEquipmentReason");
    if (reason) reason.value = "";
    m.classList.remove("hidden");
  };
  window.chkSettingsCloseBlockModal = function () {
    var m = document.getElementById("blockEquipmentModal");
    if (m) m.classList.add("hidden");
  };

  window.chkSettingsOpenForceDeleteModal = function (id, code) {
    var m = document.getElementById("forceDeleteEquipmentModal");
    var f = document.getElementById("forceDeleteEquipmentForm");
    var c = document.getElementById("forceDeleteEquipmentCode");
    if (f) f.action = "/admin/routine/checklists/settings/equipment/" + id + "/delete";
    if (c) c.textContent = code || "";
    if (m) m.classList.remove("hidden");
  };

  window.chkSettingsConfirmBulkDelete = function () {
    var checked = Array.prototype.some.call(
      document.querySelectorAll(".equipment-row-checkbox"),
      function (cb) {
        return cb.checked;
      }
    );
    if (!checked) {
      chkSettingsCloseBulkModal();
      return;
    }
    if (!confirm("Remover permanentemente os equipamentos selecionados (sem histórico e não bloqueados)?")) {
      return;
    }
    var form = document.getElementById("bulkEquipmentDeleteForm");
    if (form) form.submit();
  };

  function wireSelectAll() {
    var sa = document.getElementById("equipmentSelectAll");
    var form = document.getElementById("bulkEquipmentDeleteForm");
    if (!sa || !form) return;
    sa.addEventListener(
      "change",
      function () {
        form.querySelectorAll(".equipment-row-checkbox").forEach(function (cb) {
          cb.checked = sa.checked;
        });
      },
      { passive: true }
    );
  }

  function wireSearch() {
    var inp = document.getElementById("equipmentSearchInput");
    if (!inp) return;
    inp.addEventListener(
      "input",
      function () {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          searchText = norm(inp.value);
          currentPage = 1;
          scheduleRender();
        }, DEBOUNCE_MS);
      },
      { passive: true }
    );
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireSearch();
    wireSelectAll();
    chkSettingsSetFilter("all");
  });
})();
