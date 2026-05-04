/**
 * Lista de saídas: busca com debounce, visões rápidas e paginação client-side
 * (evita recalcular no servidor e mantém o DOM enxuto na viewport).
 */
(function () {
  var PAGE_SIZE = 25;
  var DEBOUNCE_MS = 220;

  var debounceTimer = null;
  var currentQuick = "all";
  var currentPage = 0;

  function getRows() {
    return Array.prototype.slice.call(
      document.querySelectorAll("#turnoverExitsTable tbody tr.turnover-exit-row")
    );
  }

  function rowMatchesQuick(tr) {
    var st = tr.getAttribute("data-exit-status") || "";
    var pend = tr.getAttribute("data-exit-pending") === "1";
    var tenure = parseInt(tr.getAttribute("data-tenure-months") || "0", 10);
    switch (currentQuick) {
      case "fired":
        return st === "fired";
      case "away":
        return st === "away";
      case "pending":
        return pend;
      case "critical":
        return tenure < 6;
      default:
        return true;
    }
  }

  function updateQuickButtons() {
    var wrap = document.getElementById("turnoverQuickFilters");
    if (!wrap) return;
    var buttons = wrap.querySelectorAll("[data-turnover-quick]");
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      var v = b.getAttribute("data-turnover-quick");
      if (v === currentQuick) {
        b.classList.add("filter-btn--active");
        b.setAttribute("aria-pressed", "true");
      } else {
        b.classList.remove("filter-btn--active");
        b.setAttribute("aria-pressed", "false");
      }
    }
  }

  function updatePagerUI(totalFiltered, totalPages) {
    var meta = document.getElementById("turnoverPagerMeta");
    var prev = document.getElementById("turnoverPagerPrev");
    var next = document.getElementById("turnoverPagerNext");
    if (meta) {
      var start = totalFiltered === 0 ? 0 : currentPage * PAGE_SIZE + 1;
      var end = Math.min((currentPage + 1) * PAGE_SIZE, totalFiltered);
      meta.textContent =
        totalFiltered === 0
          ? "Nenhum registro nesta visão"
          : "Mostrando " + start + "–" + end + " de " + totalFiltered;
    }
    if (prev) {
      prev.disabled = currentPage <= 0;
    }
    if (next) {
      next.disabled = currentPage >= totalPages - 1 || totalPages <= 1;
    }
  }

  function applyFilters() {
    var input = document.getElementById("turnoverSearchInput");
    var q = (input && input.value ? input.value : "").trim().toLowerCase();
    var rows = getRows();
    var nRows = rows.length;
    var filtered = [];
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (!rowMatchesQuick(tr)) continue;
      if (q) {
        var hay = (tr.getAttribute("data-search") || "").toLowerCase();
        if (hay.indexOf(q) === -1) continue;
      }
      filtered.push(tr);
    }

    var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    currentPage = Math.min(currentPage, totalPages - 1);

    for (var j = 0; j < rows.length; j++) {
      rows[j].classList.add("turnover-exit-row--hidden");
    }

    var start = currentPage * PAGE_SIZE;
    for (var k = start; k < start + PAGE_SIZE && k < filtered.length; k++) {
      filtered[k].classList.remove("turnover-exit-row--hidden");
    }

    var empty = document.getElementById("turnoverFilteredEmpty");
    if (empty) {
      if (filtered.length === 0 && nRows > 0) {
        empty.removeAttribute("hidden");
        empty.classList.remove("hidden");
      } else {
        empty.setAttribute("hidden", "");
        empty.classList.add("hidden");
      }
    }

    updatePagerUI(filtered.length, totalPages);
  }

  function scheduleApply() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      applyFilters();
    }, DEBOUNCE_MS);
  }

  function bind() {
    if (!document.getElementById("turnoverExitsTable")) {
      return;
    }
    var search = document.getElementById("turnoverSearchInput");
    if (search) {
      search.addEventListener("input", function () {
        currentPage = 0;
        scheduleApply();
      });
    }

    var quickWrap = document.getElementById("turnoverQuickFilters");
    if (quickWrap) {
      quickWrap.addEventListener("click", function (e) {
        var t = e.target;
        while (t && t !== quickWrap && !t.getAttribute("data-turnover-quick")) {
          t = t.parentElement;
        }
        if (!t || !t.getAttribute("data-turnover-quick")) return;
        e.preventDefault();
        currentQuick = t.getAttribute("data-turnover-quick") || "all";
        currentPage = 0;
        updateQuickButtons();
        applyFilters();
      });
    }

    var prev = document.getElementById("turnoverPagerPrev");
    var next = document.getElementById("turnoverPagerNext");
    if (prev) {
      prev.addEventListener("click", function () {
        if (currentPage > 0) {
          currentPage--;
          applyFilters();
        }
      });
    }
    if (next) {
      next.addEventListener("click", function () {
        currentPage++;
        applyFilters();
      });
    }

    updateQuickButtons();
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
