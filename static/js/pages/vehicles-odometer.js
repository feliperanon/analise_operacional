/**
 * /vehicles/odometer
 * Render leve: debounce + paginacao + DOM incremental.
 */
(function () {
  const PAGE_SIZE = 50;
  const SEARCH_DEBOUNCE_MS = 200;

  let data = [];
  let filtered = [];
  let sortKey = "km";
  let sortDir = -1;
  let search = "";
  let summaryFilter = "all";
  const typeFilters = new Set();
  const selected = new Set();
  let page = 0;
  let timer = null;

  function esc(v) {
    const d = document.createElement("div");
    d.textContent = v == null ? "" : String(v);
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

  function statusHtml(v) {
    if (v.sold_at) return '<span class="sys-badge sys-badge--neutral">Vendido</span>';
    if (!v.is_active) return '<span class="sys-badge sys-badge--critical">Inativo</span>';
    if (v.in_workshop) return '<span class="employees-pill employees-pill--status employees-pill--pending">Oficina</span>';
    if (v.odometer_km == null) return '<span class="employees-pill employees-pill--status employees-pill--vacation">Sem KM</span>';
    return '<span class="sys-badge sys-badge--ok">Operando</span>';
  }

  function matchSummary(v) {
    if (summaryFilter === "all") return true;
    if (summaryFilter === "with_km") return v.odometer_km != null;
    if (summaryFilter === "without_km") return v.odometer_km == null;
    if (summaryFilter === "high_km") return Number(v.odometer_km || 0) >= 300000;
    if (summaryFilter === "workshop") return !!v.in_workshop && !v.sold_at;
    return true;
  }

  function matchType(v) {
    if (!typeFilters.size) return true;
    return typeFilters.has(v.vehicle_type || "");
  }

  function matchSearch(v) {
    if (!search) return true;
    const s = search.toLowerCase();
    const hay = [
      v.placa, v.vehicle_type, v.marca, v.modelo, v.renavam, v.chassi, v.crv_number, v.ano,
    ].join(" ").toLowerCase();
    return hay.includes(s);
  }

  function sortData() {
    filtered.sort((a, b) => {
      let av;
      let bv;
      switch (sortKey) {
        case "placa": av = (a.placa || "").toLowerCase(); bv = (b.placa || "").toLowerCase(); break;
        case "type": av = typeLabel(a.vehicle_type); bv = typeLabel(b.vehicle_type); break;
        case "marca": av = `${a.marca || ""} ${a.modelo || ""}`.toLowerCase(); bv = `${b.marca || ""} ${b.modelo || ""}`.toLowerCase(); break;
        case "updated": av = a.updated_at || ""; bv = b.updated_at || ""; break;
        case "status": av = statusKind(a); bv = statusKind(b); break;
        case "km":
        default:
          av = a.odometer_km == null ? -1 : Number(a.odometer_km);
          bv = b.odometer_km == null ? -1 : Number(b.odometer_km);
          break;
      }
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      return 0;
    });
  }

  function syncSortIcons() {
    document.querySelectorAll("[data-sort-icon]").forEach((el) => {
      el.classList.remove("employees-data-table__sort-icon--active");
    });
    const active = document.querySelector(`[data-sort-icon="${sortKey}"]`);
    if (active) active.classList.add("employees-data-table__sort-icon--active");
  }

  function syncFilterButtons() {
    document.querySelectorAll(".odo-filter-btn").forEach((b) => {
      const key = b.dataset.filter;
      const on = key === summaryFilter;
      b.classList.toggle("filter-btn--active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll("[data-summary-filter]").forEach((kpi) => {
      const key = kpi.dataset.summaryFilter;
      const on = key === summaryFilter;
      kpi.classList.toggle("ops-card--selected", on);
      kpi.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function syncTypeLabel() {
    const el = document.getElementById("odoTypeFilterLabel");
    if (!el) return;
    if (!typeFilters.size) {
      el.textContent = "Tipos: todos";
      return;
    }
    el.textContent = "Tipos: " + Array.from(typeFilters).map(typeLabel).join(", ");
  }

  function renderPagination(total) {
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page < 0) page = 0;
    if (page > pages - 1) page = pages - 1;
    const start = total ? page * PAGE_SIZE + 1 : 0;
    const end = total ? Math.min(total, (page + 1) * PAGE_SIZE) : 0;
    const meta = document.getElementById("odometerPaginationMeta");
    if (meta) meta.textContent = total ? `Mostrando ${start}-${end} de ${total}` : "0 resultados";
    const prev = document.getElementById("odoPagePrev");
    const next = document.getElementById("odoPageNext");
    if (prev) prev.disabled = page <= 0;
    if (next) next.disabled = page >= pages - 1;
  }

  function syncSelected() {
    const el = document.getElementById("odoSelectedCount");
    if (el) el.textContent = String(selected.size);
  }

  function renderTable() {
    const tbody = document.getElementById("odometerTableBody");
    if (!tbody) return;
    const start = page * PAGE_SIZE;
    const rows = filtered.slice(start, start + PAGE_SIZE);
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="px-5 py-12 text-center text-sm employees-text-muted">Nenhum veículo encontrado para os filtros aplicados.</td></tr>';
      renderPagination(filtered.length);
      syncSelected();
      return;
    }
    const frag = document.createDocumentFragment();
    for (const v of rows) {
      const tr = document.createElement("tr");
      tr.className = "odometer-row employees-data-table__row transition-colors";
      const km = v.odometer_km == null ? "—" : `${Math.round(Number(v.odometer_km)).toLocaleString("pt-BR")} km`;
      const checked = selected.has(v.id) ? " checked" : "";
      tr.innerHTML = `
        <td class="veh-col-check px-2 py-2 pl-3 align-middle" data-label=""><input type="checkbox" class="odo-row-check h-4 w-4 rounded border-slate-300 accent-indigo-600"${checked} aria-label="Selecionar ${esc(v.placa)}"></td>
        <td class="odo-cell-primary odo-col-plate px-2 py-2 align-middle" data-label="Placa"><a href="/vehicles/${v.id}/history" class="employees-data-table__name-link block font-mono uppercase">${esc(v.placa || "—")}</a></td>
        <td class="employees-data-table__cell odo-col-type px-2 py-2 align-middle" data-label="Tipo">${esc(typeLabel(v.vehicle_type))}</td>
        <td class="employees-data-table__cell odo-col-brand px-2 py-2 align-middle" data-label="Marca/Modelo"><span class="employees-data-table__role-ellipsis">${esc((v.marca || "—") + " — " + (v.modelo || "—"))}</span></td>
        <td class="employees-data-table__cell odo-col-km px-2 py-2 align-middle whitespace-nowrap" data-label="KM">${esc(km)}</td>
        <td class="employees-data-table__cell odo-col-updated px-2 py-2 align-middle whitespace-nowrap" data-label="Atualizado">${esc(v.updated_at_br || "—")}</td>
        <td class="odo-col-status px-2 py-2 align-middle whitespace-nowrap" data-label="Status">${statusHtml(v)}</td>
        <td class="odo-actions-cell odo-col-actions px-2 py-2 align-middle" data-label="Ações">
          <div class="odo-actions employees-action-strip flex flex-nowrap items-center gap-1">
            <a href="/vehicles/${v.id}/history" class="employee-action-btn employee-action-btn--vacation" title="Histórico">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            </a>
            <a href="/vehicles/${v.id}" class="employee-action-btn employee-action-btn--edit" title="Editar">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            </a>
            <form action="/vehicles/${v.id}/workshop" method="post" class="inline">
              <input type="hidden" name="return_to" value="/vehicles/odometer">
              <button type="submit" class="employee-action-btn employee-action-btn--away" title="Alternar oficina">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              </button>
            </form>
            <button type="button" class="employee-action-btn employee-action-btn--delete odo-del-btn" title="Excluir">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
          </div>
        </td>`;
      tr.querySelector(".odo-row-check")?.addEventListener("change", (e) => {
        if (e.target.checked) selected.add(v.id);
        else selected.delete(v.id);
        syncSelected();
      });
      tr.querySelector(".odo-del-btn")?.addEventListener("click", () => {
        const modal = document.getElementById("odoDeleteModal");
        const form = document.getElementById("odoDeleteForm");
        const plate = document.getElementById("odoDeletePlate");
        if (!modal || !form || !plate) return;
        plate.textContent = v.placa || "—";
        form.action = `/vehicles/${v.id}/delete`;
        modal.classList.remove("hidden");
      });
      frag.appendChild(tr);
    }
    tbody.innerHTML = "";
    tbody.appendChild(frag);
    renderPagination(filtered.length);
    syncSelected();
  }

  function applyAll() {
    filtered = data.filter((v) => matchSummary(v) && matchType(v) && matchSearch(v));
    sortData();
    page = 0;
    syncFilterButtons();
    syncSortIcons();
    renderTable();
  }

  window.setOdoFilter = function (k) {
    summaryFilter = k || "all";
    applyAll();
  };

  window.clearOdoTypeFilters = function () {
    typeFilters.clear();
    document.querySelectorAll(".odo-type-checkbox").forEach((c) => { c.checked = false; });
    syncTypeLabel();
    applyAll();
  };

  window.sortOdoTable = function (k) {
    if (sortKey === k) sortDir *= -1;
    else {
      sortKey = k;
      sortDir = 1;
    }
    sortData();
    syncSortIcons();
    renderTable();
  };

  window.odoPageNext = function () {
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (page < pages - 1) {
      page += 1;
      renderTable();
    }
  };

  window.odoPagePrev = function () {
    if (page > 0) {
      page -= 1;
      renderTable();
    }
  };

  window.odoSelectPage = function () {
    const start = page * PAGE_SIZE;
    filtered.slice(start, start + PAGE_SIZE).forEach((v) => selected.add(v.id));
    renderTable();
  };

  window.odoClearSelection = function () {
    selected.clear();
    renderTable();
  };

  window.runOdoBulk = async function () {
    const action = document.getElementById("odoBulkAction")?.value;
    if (!action) {
      window.alert("Selecione uma operação.");
      return;
    }
    const allFiltered = document.getElementById("odoBulkApplyFiltered")?.checked;
    const ids = allFiltered ? filtered.map((v) => v.id) : Array.from(selected);
    if (!ids.length) {
      window.alert("Nenhum veículo selecionado.");
      return;
    }
    if (!window.confirm(`Confirmar operação em ${ids.length} veículo(s)?`)) return;
    try {
      const r = await fetch("/api/vehicles/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ids }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.success) window.location.reload();
      else window.alert(d.error || "Falha ao executar operação.");
    } catch (e) {
      console.error(e);
      window.alert("Erro de conexão.");
    }
  };

  window.openOdoAddModal = function () {
    document.getElementById("odoAddModal")?.classList.remove("hidden");
  };

  function init() {
    const raw = document.getElementById("vehicles-odometer-data")?.textContent || "[]";
    try {
      data = JSON.parse(raw);
    } catch (e) {
      console.error(e);
      data = [];
    }
    document.getElementById("odoSearchInput")?.addEventListener("input", (e) => {
      if (timer) clearTimeout(timer);
      const value = e.target.value || "";
      timer = setTimeout(() => {
        search = value.trim().toLowerCase();
        applyAll();
      }, SEARCH_DEBOUNCE_MS);
    });
    document.querySelectorAll(".odo-type-checkbox").forEach((c) => {
      c.addEventListener("change", () => {
        typeFilters.clear();
        document.querySelectorAll(".odo-type-checkbox:checked").forEach((el) => typeFilters.add(el.value));
        syncTypeLabel();
        applyAll();
      });
    });
    syncTypeLabel();
    applyAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
