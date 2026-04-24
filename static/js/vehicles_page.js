/**
 * Frota /vehicles — filtros, ordenação leve, paginação e debounce na busca.
 */
(function () {
  "use strict";

  var DEBOUNCE_MS = 260;
  var PAGE_SIZE = 48;

  var typeFilter = "all";
  var statusFilter = "all";
  var searchText = "";
  var debounceTimer = null;
  var currentPage = 1;
  var sortKey = "placa";
  var sortDir = 1;

  function norm(s) {
    return (s || "").toString().toLowerCase().trim();
  }

  function getRows() {
    var tb = document.getElementById("vehiclesTableBody");
    if (!tb) return [];
    return Array.prototype.slice.call(tb.querySelectorAll("tr.vehicle-page-row"));
  }

  function rowStatusKey(row) {
    if (row.getAttribute("data-sold") === "1") return "sold";
    if (row.getAttribute("data-workshop") === "1") return "workshop";
    if (row.getAttribute("data-active") === "0") return "inactive";
    return "active";
  }

  function rowMatches(row) {
    var vtype = row.getAttribute("data-type") || "";
    if (typeFilter !== "all" && vtype !== typeFilter) return false;

    var sk = rowStatusKey(row);
    if (statusFilter === "active" && sk !== "active") return false;
    if (statusFilter === "workshop" && sk !== "workshop") return false;
    if (statusFilter === "sold" && sk !== "sold") return false;
    if (statusFilter === "inactive" && sk !== "inactive") return false;

    if (!searchText) return true;
    var hay = norm(row.getAttribute("data-search"));
    return hay.indexOf(searchText) !== -1;
  }

  function sortRowsInDom(rows) {
    var tb = document.getElementById("vehiclesTableBody");
    if (!tb || !rows.length) return;

    var decorated = rows.map(function (row, idx) {
      var placa = norm(row.getAttribute("data-placa"));
      var tipo = norm(row.getAttribute("data-type"));
      var marca = norm(row.getAttribute("data-marca"));
      var modelo = norm(row.getAttribute("data-modelo"));
      var key;
      if (sortKey === "type") key = tipo;
      else if (sortKey === "brand") key = marca + " " + modelo;
      else key = placa;
      return { row: row, key: key, idx: idx };
    });

    decorated.sort(function (a, b) {
      var c = a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
      if (c === 0) c = a.idx - b.idx;
      return c * sortDir;
    });

    var frag = document.createDocumentFragment();
    decorated.forEach(function (d) {
      frag.appendChild(d.row);
    });
    tb.appendChild(frag);
    var emptyFilter = document.getElementById("vehiclesEmptyFilterRow");
    if (emptyFilter) {
      tb.appendChild(emptyFilter);
    }
  }

  function computeVisibleIndices(rows) {
    var ix = [];
    for (var i = 0; i < rows.length; i++) {
      if (rowMatches(rows[i])) ix.push(i);
    }
    return ix;
  }

  function renderTable() {
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

    var countEl = document.getElementById("vehiclesVisibleCount");
    var pageEl = document.getElementById("vehiclesPageLabel");
    if (countEl) countEl.textContent = String(totalVis);
    if (pageEl) pageEl.textContent = "Página " + currentPage + " / " + pages;

    var prev = document.getElementById("vehiclesPrevPage");
    var next = document.getElementById("vehiclesNextPage");
    if (prev) {
      prev.disabled = currentPage <= 1;
      prev.classList.toggle("opacity-50", currentPage <= 1);
    }
    if (next) {
      next.disabled = currentPage >= pages;
      next.classList.toggle("opacity-50", currentPage >= pages);
    }

    var empty = document.getElementById("vehiclesEmptyFilterRow");
    if (empty) {
      empty.classList.toggle("hidden", totalVis > 0);
    }
  }

  function scheduleRender() {
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(renderTable);
    } else {
      renderTable();
    }
  }

  window.vehiclesSetTypeFilter = function (t) {
    typeFilter = t || "all";
    currentPage = 1;
    document.querySelectorAll("[data-veh-type-filter]").forEach(function (btn) {
      var v = btn.getAttribute("data-veh-type-filter");
      var on = v === typeFilter;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("filter-btn--active", on);
    });
    scheduleRender();
  };

  window.vehiclesSetStatusFilter = function (s) {
    statusFilter = s || "all";
    currentPage = 1;
    document.querySelectorAll("[data-veh-status-filter]").forEach(function (btn) {
      var v = btn.getAttribute("data-veh-status-filter");
      var on = v === statusFilter;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("filter-btn--active", on);
    });
    scheduleRender();
  };

  window.vehiclesClearFilters = function () {
    var inp = document.getElementById("vehiclesSearchInput");
    if (inp) inp.value = "";
    searchText = "";
    currentPage = 1;
    vehiclesSetTypeFilter("all");
    vehiclesSetStatusFilter("all");
  };

  window.vehiclesPrevPage = function () {
    if (currentPage > 1) {
      currentPage--;
      scheduleRender();
    }
  };

  window.vehiclesNextPage = function () {
    currentPage++;
    scheduleRender();
  };

  window.vehiclesToggleSort = function (key) {
    if (sortKey === key) sortDir = -sortDir;
    else {
      sortKey = key;
      sortDir = 1;
    }
    currentPage = 1;
    sortRowsInDom(getRows());
    scheduleRender();
  };

  window.vehiclesOpenCreateModal = function () {
    var m = document.getElementById("createVehicleModal");
    if (m) m.classList.remove("hidden");
  };
  window.vehiclesCloseCreateModal = function () {
    var m = document.getElementById("createVehicleModal");
    if (m) m.classList.add("hidden");
  };
  window.vehiclesOpenImportModal = function () {
    var m = document.getElementById("importVehicleModal");
    if (m) m.classList.remove("hidden");
  };
  window.vehiclesCloseImportModal = function () {
    var m = document.getElementById("importVehicleModal");
    if (m) m.classList.add("hidden");
  };
  window.vehiclesOpenBulkModal = function () {
    var m = document.getElementById("bulkVehicleModal");
    if (m) m.classList.remove("hidden");
  };
  window.vehiclesCloseBulkModal = function () {
    var m = document.getElementById("bulkVehicleModal");
    if (m) m.classList.add("hidden");
  };

  function fmtBrNumber(n) {
    if (n == null || n === "") return "";
    var x = Number(n);
    if (isNaN(x)) return "";
    return x.toFixed(2).replace(".", ",");
  }

  window.vehiclesOpenEditModal = function (raw) {
    var m = document.getElementById("editVehicleModal");
    var form = document.getElementById("editVehicleForm");
    if (!m || !form) return;
    var v;
    try {
      v = typeof raw === "string" ? JSON.parse(raw) : raw;
    } catch (e) {
      return;
    }
    var id = v.id;
    if (!id) return;
    form.action = "/vehicles/" + id + "/update";
    document.getElementById("edit_placa").value = (v.placa || "").toString();
    document.getElementById("edit_vehicle_type").value = v.vehicle_type || "carro";
    document.getElementById("edit_marca").value = v.marca || "";
    document.getElementById("edit_modelo").value = v.modelo || "";
    document.getElementById("edit_renavam").value = v.renavam || "";
    document.getElementById("edit_ano").value = v.ano || "";
    document.getElementById("edit_crv").value = v.crv_number || "";
    document.getElementById("edit_chassi").value = v.chassi || "";
    var odoWrap = document.getElementById("edit_odometer_wrap");
    var odoInput = document.getElementById("edit_odometer_km");
    if (odoWrap && odoInput) {
      var isTruck = (v.vehicle_type || "") === "caminhao";
      odoWrap.classList.toggle("hidden", !isTruck);
      odoInput.value =
        v.odometer_km != null && v.odometer_km !== ""
          ? String(v.odometer_km).replace(".", ",")
          : "";
    }
    var ws = document.getElementById("edit_in_workshop");
    if (ws) ws.checked = !!v.in_workshop;
    var sv = document.getElementById("edit_sale_value");
    if (sv) sv.value = v.sale_value != null ? fmtBrNumber(v.sale_value) : "";
    var sd = document.getElementById("edit_sold_at");
    if (sd) {
      var sold = v.sold_at;
      if (sold && typeof sold === "string" && sold.indexOf("T") !== -1) {
        sd.value = sold.slice(0, 10);
      } else if (sold && typeof sold === "string") {
        sd.value = sold.slice(0, 10);
      } else {
        sd.value = "";
      }
    }
    m.classList.remove("hidden");
  };

  window.vehiclesCloseEditModal = function () {
    var m = document.getElementById("editVehicleModal");
    if (m) m.classList.add("hidden");
  };

  window.vehiclesConfirmBulkDelete = function () {
    var any = Array.prototype.some.call(
      document.querySelectorAll(".vehicle-row-checkbox"),
      function (cb) {
        return cb.checked;
      }
    );
    if (!any) {
      vehiclesCloseBulkModal();
      return;
    }
    if (!confirm("Excluir permanentemente os veículos selecionados? Esta ação não pode ser desfeita.")) {
      return;
    }
    var form = document.getElementById("bulkVehicleDeleteForm");
    if (form) form.submit();
  };

  function wireSelectAll() {
    var sa = document.getElementById("vehiclesSelectAll");
    var form = document.getElementById("bulkVehicleDeleteForm");
    if (!sa || !form) return;
    sa.addEventListener(
      "change",
      function () {
        form.querySelectorAll(".vehicle-row-checkbox").forEach(function (cb) {
          cb.checked = sa.checked;
        });
      },
      { passive: true }
    );
  }

  function wireSearch() {
    var inp = document.getElementById("vehiclesSearchInput");
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
    sortRowsInDom(getRows());
    vehiclesSetTypeFilter("all");
    vehiclesSetStatusFilter("all");
  });
})();
