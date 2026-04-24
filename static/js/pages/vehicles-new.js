/**
 * Frota /vehicles/new — lista client-side com debounce, paginação e render incremental.
 */
(function () {
  const PAGE_SIZE = 50;
  const DEBOUNCE_MS = 200;

  let rawData = [];
  let filtered = [];
  let sortKey = "placa";
  let sortDir = 1;
  let page = 0;
  let searchNeedle = "";
  let summaryFilter = "all";
  /** @type {Set<string>} */
  let typeFilters = new Set();
  /** @type {Set<number>} */
  let selectedIds = new Set();
  let debounceTimer = null;

  function escapeHtml(s) {
    if (s == null || s === "") return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function typeLabel(t) {
    if (t === "caminhao") return "Caminhão";
    if (t === "moto") return "Moto";
    if (t === "carro") return "Carro";
    return t || "—";
  }

  function statusKind(v) {
    if (v.sold_at) return "sold";
    if (!v.is_active) return "inactive";
    if (v.in_workshop) return "workshop";
    return "active";
  }

  function statusBadgeHtml(kind) {
    if (kind === "sold") return '<span class="sys-badge sys-badge--neutral">Vendido</span>';
    if (kind === "inactive") return '<span class="sys-badge sys-badge--critical">Inativo</span>';
    if (kind === "workshop") return '<span class="employees-pill employees-pill--status employees-pill--pending">Oficina</span>';
    return '<span class="sys-badge sys-badge--ok">Ativo</span>';
  }

  function matchesSearch(v, needle) {
    if (!needle) return true;
    const n = needle;
    const hay = [
      v.placa,
      v.marca,
      v.modelo,
      v.ano,
      v.renavam,
      v.chassi,
      v.crv_number,
      typeLabel(v.vehicle_type),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(n);
  }

  function matchesSummary(v, key) {
    if (key === "all") return true;
    const k = statusKind(v);
    if (key === "road") return v.is_active && !v.sold_at && !v.in_workshop;
    if (key === "workshop") return v.in_workshop;
    if (key === "sold") return !!v.sold_at;
    if (key === "inactive") return !v.is_active;
    if (key === "caminhao" || key === "moto" || key === "carro") return (v.vehicle_type || "") === key;
    return true;
  }

  function matchesTypeMulti(v) {
    if (typeFilters.size === 0) return true;
    return typeFilters.has(v.vehicle_type || "");
  }

  function applyFilters() {
    const needle = searchNeedle.trim().toLowerCase();
    filtered = rawData.filter(
      (v) => matchesSummary(v, summaryFilter) && matchesTypeMulti(v) && matchesSearch(v, needle)
    );
    sortFiltered();
    page = 0;
    renderAll();
  }

  function sortFiltered() {
    const dir = sortDir;
    const key = sortKey;
    filtered.sort((a, b) => {
      let av;
      let bv;
      switch (key) {
        case "type":
          av = typeLabel(a.vehicle_type);
          bv = typeLabel(b.vehicle_type);
          break;
        case "marca":
          av = (a.marca || "").toLowerCase();
          bv = (b.marca || "").toLowerCase();
          break;
        case "modelo":
          av = (a.modelo || "").toLowerCase();
          bv = (b.modelo || "").toLowerCase();
          break;
        case "ano":
          av = a.ano || "";
          bv = b.ano || "";
          break;
        case "km":
          av = a.odometer_km != null ? Number(a.odometer_km) : -1;
          bv = b.odometer_km != null ? Number(b.odometer_km) : -1;
          break;
        case "status":
          av = statusKind(a);
          bv = statusKind(b);
          break;
        default:
          av = (a.placa || "").toLowerCase();
          bv = (b.placa || "").toLowerCase();
      }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }

  function updateSortIcons() {
    document.querySelectorAll("[data-sort-icon]").forEach((svg) => {
      svg.classList.remove("employees-data-table__sort-icon--active");
    });
    const active = document.querySelector(`[data-sort-icon="${sortKey}"]`);
    if (active) active.classList.add("employees-data-table__sort-icon--active");
  }

  window.sortVehiclesTable = function (col) {
    if (sortKey === col) sortDir *= -1;
    else {
      sortKey = col;
      sortDir = 1;
    }
    sortFiltered();
    renderTableBody();
    updateSortIcons();
  };

  function renderTableBody() {
    const tbody = document.getElementById("vehiclesTableBody");
    if (!tbody) return;

    const total = filtered.length;
    const start = page * PAGE_SIZE;
    const slice = filtered.slice(start, start + PAGE_SIZE);

    if (total === 0) {
      tbody.innerHTML =
        '<tr><td colspan="9" class="px-5 py-12 text-center text-sm employees-text-muted">Nenhum veículo nesta visão. Ajuste busca ou filtros.</td></tr>';
      updatePaginationUI(total);
      return;
    }

    const frag = document.createDocumentFragment();
    for (const v of slice) {
      const tr = document.createElement("tr");
      tr.className = "vehicle-row employees-data-table__row transition-colors";
      tr.dataset.id = String(v.id);
      const kind = statusKind(v);
      const km =
        v.vehicle_type === "caminhao" && v.odometer_km != null
          ? String(Math.round(Number(v.odometer_km)))
          : "—";
      const checked = selectedIds.has(v.id) ? " checked" : "";

      tr.innerHTML = `
        <td class="veh-col-check px-2 py-2 pl-3 align-middle" data-label="">
          <input type="checkbox" class="veh-row-check h-4 w-4 rounded border-slate-300 accent-indigo-600"${checked} aria-label="Selecionar ${escapeHtml(v.placa)}" />
        </td>
        <td class="vehicle-cell-primary veh-col-plate px-3 py-2 align-middle" data-label="Placa">
          <a href="/vehicles/${v.id}" class="vehicle-plate-link employees-data-table__name-link font-mono uppercase">${escapeHtml(v.placa)}</a>
        </td>
        <td class="employees-data-table__cell veh-col-type px-2 py-2 align-middle employees-text-body" data-label="Tipo">${escapeHtml(typeLabel(v.vehicle_type))}</td>
        <td class="employees-data-table__cell veh-col-brand px-2 py-2 align-middle" data-label="Marca">${escapeHtml(v.marca || "—")}</td>
        <td class="employees-data-table__cell veh-col-model px-2 py-2 align-middle" data-label="Modelo"><span class="employees-data-table__role-ellipsis">${escapeHtml(v.modelo || "—")}</span></td>
        <td class="employees-data-table__cell veh-col-year px-2 py-2 align-middle employees-text-body whitespace-nowrap" data-label="Ano">${escapeHtml(v.ano || "—")}</td>
        <td class="employees-data-table__cell veh-col-km px-2 py-2 align-middle employees-text-body whitespace-nowrap" data-label="KM">${escapeHtml(km)}</td>
        <td class="veh-col-status px-2 py-2 align-middle whitespace-nowrap" data-label="Status">${statusBadgeHtml(kind)}</td>
        <td class="vehicle-actions-cell veh-col-actions px-2 py-2 align-middle" data-label="Ações">
          <div class="vehicle-actions employees-action-strip flex flex-nowrap items-center gap-1">
            <button type="button" class="employee-action-btn employee-action-btn--edit veh-act-edit" title="Editar" data-id="${v.id}">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            </button>
            <form action="/vehicles/${v.id}/workshop" method="post" class="inline">
              <input type="hidden" name="return_to" value="/vehicles/new" />
              <button type="submit" class="employee-action-btn employee-action-btn--away" title="Alternar oficina">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
            </button>
            </form>
            <a href="/vehicles/${v.id}/history" class="employee-action-btn employee-action-btn--vacation" title="Histórico (caminhão)">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            </a>
            <button type="button" class="employee-action-btn employee-action-btn--delete veh-act-del" title="Excluir" data-id="${v.id}" data-placa="${escapeHtml(v.placa)}">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
          </div>
        </td>`;

      tr.querySelector(".veh-row-check")?.addEventListener("change", (e) => {
        const id = v.id;
        if (e.target.checked) selectedIds.add(id);
        else selectedIds.delete(id);
        updateSelectionCount();
      });
      tr.querySelector(".veh-act-edit")?.addEventListener("click", () => openEditModal(v));
      tr.querySelector(".veh-act-del")?.addEventListener("click", () => openDeleteModal(v));

      frag.appendChild(tr);
    }
    tbody.innerHTML = "";
    tbody.appendChild(frag);
    updatePaginationUI(total);
    updateSelectionCount();
  }

  function updatePaginationUI(total) {
    const el = document.getElementById("vehiclesPaginationMeta");
    const prev = document.getElementById("vehiclesPagePrev");
    const next = document.getElementById("vehiclesPageNext");
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page >= pages) page = pages - 1;
    if (page < 0) page = 0;
    const start = total === 0 ? 0 : page * PAGE_SIZE + 1;
    const end = Math.min(total, (page + 1) * PAGE_SIZE);
    if (el) el.textContent = total ? `Mostrando ${start}–${end} de ${total}` : "0 resultados";
    if (prev) {
      prev.disabled = page <= 0;
      prev.classList.toggle("opacity-50", page <= 0);
    }
    if (next) {
      next.disabled = page >= pages - 1;
      next.classList.toggle("opacity-50", page >= pages - 1);
    }
  }

  function updateSelectionCount() {
    const el = document.getElementById("vehiclesSelectedCount");
    if (el) el.textContent = String(selectedIds.size);
  }

  function renderAll() {
    renderTableBody();
    updateSortIcons();
    syncFilterButtons();
    syncSummaryCards();
  }

  function syncFilterButtons() {
    document.querySelectorAll(".veh-filter-btn").forEach((btn) => {
      const f = btn.getAttribute("data-filter");
      const on = f === summaryFilter;
      btn.classList.toggle("filter-btn--active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function syncSummaryCards() {
    document.querySelectorAll("[data-summary-filter]").forEach((el) => {
      const f = el.getAttribute("data-summary-filter");
      const on = f === summaryFilter;
      el.classList.toggle("ops-card--selected", on);
      el.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  window.setVehicleFilter = function (key) {
    summaryFilter = key || "all";
    applyFilters();
  };

  window.clearVehicleTypeFilters = function () {
    typeFilters.clear();
    document.querySelectorAll(".veh-type-checkbox").forEach((c) => {
      c.checked = false;
    });
    updateTypeFilterLabel();
    applyFilters();
  };

  window.filterVehicleTypeOptions = function () {
    const q = (document.getElementById("typeFilterSearch")?.value || "").trim().toLowerCase();
    document.querySelectorAll(".veh-type-row").forEach((row) => {
      const label = (row.getAttribute("data-type-label") || "").toLowerCase();
      row.classList.toggle("hidden", q.length > 0 && !label.includes(q));
    });
  };

  function updateTypeFilterLabel() {
    const el = document.getElementById("typeFilterLabel");
    if (!el) return;
    if (typeFilters.size === 0) {
      el.textContent = "Tipos: todos";
      return;
    }
    const parts = Array.from(typeFilters).map(typeLabel);
    el.textContent = "Tipos: " + parts.join(", ");
  }

  function onTypeCheckboxChange() {
    typeFilters.clear();
    document.querySelectorAll(".veh-type-checkbox:checked").forEach((c) => {
      typeFilters.add(c.value);
    });
    updateTypeFilterLabel();
    applyFilters();
  }

  window.vehiclesSearchInput = function (value) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      searchNeedle = value;
      applyFilters();
    }, DEBOUNCE_MS);
  };

  window.openVehicleAddModal = function () {
    document.getElementById("vehicleAddModal")?.classList.remove("hidden");
  };

  function openEditModal(v) {
    const m = document.getElementById("vehicleEditModal");
    const form = document.getElementById("vehicleEditForm");
    if (!m || !form) return;
    form.action = "/vehicles/" + v.id + "/update";
    const set = (name, val) => {
      const i = m.querySelector(`[name="${name}"]`);
      if (i) i.value = val != null ? val : "";
    };
    set("placa", v.placa);
    set("vehicle_type", v.vehicle_type);
    set("marca", v.marca);
    set("modelo", v.modelo);
    set("ano", v.ano);
    set("renavam", v.renavam);
    set("crv_number", v.crv_number);
    set("chassi", v.chassi);
    set("is_active", v.is_active ? "1" : "0");
    const hw = m.querySelector("#vehicle_edit_in_workshop");
    const cb = m.querySelector("#edit_in_workshop_cb");
    if (hw && cb) {
      cb.checked = !!v.in_workshop;
      hw.value = v.in_workshop ? "1" : "0";
      cb.onchange = () => {
        hw.value = cb.checked ? "1" : "0";
      };
    }
    const sv = m.querySelector('[name="sale_value"]');
    if (sv)
      sv.value =
        v.sale_value != null ? String(v.sale_value).replace(".", ",") : "";
    set("sold_at", v.sold_at || "");
    const km = m.querySelector('[name="odometer_km"]');
    const kmWrap = m.querySelector("#edit-odometer-wrap");
    if (km) {
      km.value =
        v.odometer_km != null ? String(Math.round(Number(v.odometer_km))) : "";
    }
    if (kmWrap) {
      kmWrap.classList.toggle("hidden", v.vehicle_type !== "caminhao");
    }
    m.classList.remove("hidden");
  }

  function openDeleteModal(v) {
    const m = document.getElementById("vehicleDeleteModal");
    const f = document.getElementById("vehicleDeleteForm");
    if (!m || !f) return;
    f.action = "/vehicles/" + v.id + "/delete";
    const t = m.querySelector("#vehicleDeletePlate");
    if (t) t.textContent = v.placa;
    m.classList.remove("hidden");
  }

  window.vehiclesPageNext = function () {
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (page < pages - 1) {
      page++;
      renderTableBody();
    }
  };

  window.vehiclesPagePrev = function () {
    if (page > 0) {
      page--;
      renderTableBody();
    }
  };

  window.vehiclesSelectPage = function () {
    const start = page * PAGE_SIZE;
    const slice = filtered.slice(start, start + PAGE_SIZE);
    slice.forEach((v) => selectedIds.add(v.id));
    renderTableBody();
  };

  window.vehiclesClearSelection = function () {
    selectedIds.clear();
    renderTableBody();
  };

  window.runVehicleBulk = async function () {
    const sel = document.getElementById("bulkVehicleAction");
    const action = sel?.value;
    if (!action) {
      alert("Escolha uma operação.");
      return;
    }
    const useFiltered = document.getElementById("bulkApplyFiltered")?.checked;
    let ids;
    if (useFiltered) {
      ids = filtered.map((v) => v.id);
    } else {
      ids = Array.from(selectedIds);
    }
    if (!ids.length) {
      alert("Nenhum veículo na seleção. Marque linhas ou use a opção da lista filtrada.");
      return;
    }
    if (!confirm(`Confirmar operação em ${ids.length} veículo(s)?`)) return;
    try {
      const res = await fetch("/api/vehicles/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ids }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        window.location.reload();
      } else {
        alert(data.error || "Falha na operação.");
      }
    } catch (e) {
      console.error(e);
      alert("Erro de conexão.");
    }
  };

  function bindTypeFilterOptions() {
    document.querySelectorAll(".veh-type-checkbox").forEach((cb) => {
      cb.addEventListener("change", onTypeCheckboxChange);
    });
  }

  function bindEditModalTypeChange() {
    const sel = document.querySelector("#vehicleEditModal select[name=\"vehicle_type\"]");
    const wrap = document.getElementById("edit-odometer-wrap");
    if (!sel || !wrap) return;
    sel.addEventListener("change", function () {
      wrap.classList.toggle("hidden", this.value !== "caminhao");
    });
  }

  function init() {
    const el = document.getElementById("vehicles-page-data");
    if (!el) return;
    try {
      rawData = JSON.parse(el.textContent || "[]");
    } catch (e) {
      console.error(e);
      rawData = [];
    }
    bindTypeFilterOptions();
    bindEditModalTypeChange();
    document.getElementById("searchInput")?.addEventListener("input", (e) => {
      window.vehiclesSearchInput(e.target.value);
    });
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
