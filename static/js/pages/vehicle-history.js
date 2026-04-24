/**
 * /vehicles/{id}/history - filtro com debounce + paginação local por painel.
 */
(function () {
  "use strict";

  var PAGE_SIZE = 14;
  var DEBOUNCE_MS = 220;
  var activePanel = "all";
  var searchText = "";
  var debounceTimer = null;
  var pages = { delivery: 1, checklists: 1 };

  function norm(v) {
    return (v || "").toString().toLowerCase().trim();
  }

  function getRows(panel) {
    return Array.prototype.slice.call(
      document.querySelectorAll('.vehicle-history-row[data-history-panel="' + panel + '"]')
    );
  }

  function panelVisible(panel) {
    if (activePanel === "all") return true;
    return activePanel === panel;
  }

  function filterRows(panel) {
    var rows = getRows(panel);
    return rows.filter(function (row) {
      if (!panelVisible(panel)) return false;
      if (!searchText) return true;
      return norm(row.getAttribute("data-search")).indexOf(searchText) !== -1;
    });
  }

  function renderPanel(panel) {
    var visible = filterRows(panel);
    var allRows = getRows(panel);
    var maxPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
    if (pages[panel] > maxPages) pages[panel] = maxPages;

    var start = (pages[panel] - 1) * PAGE_SIZE;
    var end = start + PAGE_SIZE;
    var allowed = new Set(visible.slice(start, end));

    allRows.forEach(function (row) {
      row.classList.toggle("hidden", !allowed.has(row));
    });

    var countEl = document.getElementById(panel === "delivery" ? "deliveryVisibleCount" : "checklistVisibleCount");
    if (countEl) countEl.textContent = String(visible.length);

    var prevBtn = document.getElementById(panel === "delivery" ? "deliveryPrevBtn" : "checklistPrevBtn");
    var nextBtn = document.getElementById(panel === "delivery" ? "deliveryNextBtn" : "checklistNextBtn");
    if (prevBtn) prevBtn.disabled = pages[panel] <= 1;
    if (nextBtn) nextBtn.disabled = pages[panel] >= maxPages;
  }

  function renderAll() {
    renderPanel("delivery");
    renderPanel("checklists");
    var deliveryPanel = document.getElementById("vehicle-delivery-panel");
    var checklistPanel = document.getElementById("vehicle-checklist-panel");
    if (deliveryPanel) deliveryPanel.classList.toggle("hidden", !panelVisible("delivery"));
    if (checklistPanel) checklistPanel.classList.toggle("hidden", !panelVisible("checklists"));
  }

  function setPanel(panel) {
    activePanel = panel || "all";
    pages.delivery = 1;
    pages.checklists = 1;
    document.querySelectorAll("[data-history-panel-filter]").forEach(function (btn) {
      var isActive = btn.getAttribute("data-history-panel-filter") === activePanel;
      btn.classList.toggle("filter-btn--active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
    renderAll();
  }

  function wireButtons() {
    document.querySelectorAll("[data-history-panel-filter]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setPanel(btn.getAttribute("data-history-panel-filter"));
      });
    });
    var clear = document.getElementById("vehicleHistoryClearFilters");
    if (clear) {
      clear.addEventListener("click", function () {
        var input = document.getElementById("vehicleHistorySearchInput");
        if (input) input.value = "";
        searchText = "";
        setPanel("all");
      });
    }
  }

  function wirePagination() {
    var dPrev = document.getElementById("deliveryPrevBtn");
    var dNext = document.getElementById("deliveryNextBtn");
    var cPrev = document.getElementById("checklistPrevBtn");
    var cNext = document.getElementById("checklistNextBtn");
    if (dPrev) dPrev.addEventListener("click", function () { pages.delivery -= 1; renderPanel("delivery"); });
    if (dNext) dNext.addEventListener("click", function () { pages.delivery += 1; renderPanel("delivery"); });
    if (cPrev) cPrev.addEventListener("click", function () { pages.checklists -= 1; renderPanel("checklists"); });
    if (cNext) cNext.addEventListener("click", function () { pages.checklists += 1; renderPanel("checklists"); });
  }

  function wireSearch() {
    var input = document.getElementById("vehicleHistorySearchInput");
    if (!input) return;
    input.addEventListener("input", function () {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        searchText = norm(input.value);
        pages.delivery = 1;
        pages.checklists = 1;
        if (typeof requestAnimationFrame === "function") requestAnimationFrame(renderAll);
        else renderAll();
      }, DEBOUNCE_MS);
    }, { passive: true });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireButtons();
    wirePagination();
    wireSearch();
    renderAll();
  });
})();
