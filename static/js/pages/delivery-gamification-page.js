(function () {
  "use strict";

  var root = document.querySelector('[data-page="delivery-gamification"]');
  if (!root) return;

  var state = {
    activeTab: "motoristas",
    quickFilter: "all",
    statusFilter: "all",
    searchTerm: "",
    page: 1,
    pageSize: 25,
    openModalId: null,
    debounceTimer: 0,
    confirmHandler: null,
    selectedKeys: new Set(),
  };

  var SEARCH_DEBOUNCE_MS = 300;
  var DATASETS = {
    motoristas: readJson("deliveryRowsMotoristas"),
    ajudantes: readJson("deliveryRowsAjudantes"),
    consolidado: readJson("deliveryRowsConsolidado"),
    produtividade: readJson("deliveryRowsProdutividade"),
  };

  function byId(id) { return document.getElementById(id); }
  function parseNumber(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  function normalize(v) {
    return String(v || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }
  function fmtBr(value, digits) {
    return parseNumber(value).toLocaleString("pt-BR", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0,
    });
  }
  function readJson(id) {
    var el = byId(id);
    if (!el) return [];
    try { return JSON.parse(el.textContent || "[]") || []; }
    catch (_err) { return []; }
  }
  function currentRows() {
    return DATASETS[state.activeTab] || [];
  }
  function getRowKey(row, idx) {
    return String(row.id || row.employee_id || (row.name || "sem-nome") + "::" + idx);
  }
  function statusClass(tone) {
    return tone || "slate";
  }
  function showAlert(message, level) {
    var alert = byId("page-alert");
    if (!alert) return;
    alert.className = "sys-alert flex items-center gap-3 " + (level === "error" ? "sys-alert--danger" : "sys-alert--success");
    alert.innerHTML = '<span class="min-w-0 flex-1">' + message + '</span><button type="button" class="emp-modal-close shrink-0" data-dismiss-alert aria-label="Fechar">x</button>';
    alert.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function hideAlert() {
    var alert = byId("page-alert");
    if (!alert) return;
    alert.classList.add("hidden");
    alert.innerHTML = "";
  }
  function openModal(id) {
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (node) {
      node.classList.add("hidden");
      node.classList.remove("flex");
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    state.openModalId = id;
    document.body.classList.add("overflow-hidden");
  }
  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (state.openModalId === id) state.openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) document.body.classList.remove("overflow-hidden");
  }

  function applyQuickFilter(rows) {
    if (state.quickFilter === "all") return rows;
    var todayIso = new Date().toISOString().slice(0, 10);
    return rows.filter(function (row) {
      var tone = normalize(row.status_tone);
      var withinTarget = !!row.within_target;
      var hasActivity = !!row.has_activity;
      var days = parseNumber(row.active_days_count);
      if (state.quickFilter === "critical") return tone === "rose";
      if (state.quickFilter === "pending") return !hasActivity || tone === "slate";
      if (state.quickFilter === "within") return withinTarget;
      if (state.quickFilter === "today") return (row.last_activity_date || row.date || "").slice(0, 10) === todayIso || days <= 1;
      return true;
    });
  }
  function applyStatusFilter(rows) {
    if (state.statusFilter === "all") return rows;
    return rows.filter(function (row) { return normalize(row.status_tone) === state.statusFilter; });
  }
  function applySearch(rows) {
    if (!state.searchTerm) return rows;
    return rows.filter(function (row) {
      var hay = normalize([row.name, row.role_label, row.cost_center, row.status_label].join(" "));
      return hay.indexOf(state.searchTerm) !== -1;
    });
  }
  function getFilteredRows() {
    return applySearch(applyStatusFilter(applyQuickFilter(currentRows())));
  }

  function setStates(loading, hasError, hasRows) {
    var wrap = byId("tableStates");
    var loadingEl = byId("tableLoading");
    var noResultsEl = byId("tableNoResults");
    var errorEl = byId("tableError");
    if (!wrap || !loadingEl || !noResultsEl || !errorEl) return;
    wrap.classList.toggle("hidden", !loading && !hasError && hasRows);
    loadingEl.classList.toggle("hidden", !loading);
    errorEl.classList.toggle("hidden", !hasError);
    noResultsEl.classList.toggle("hidden", loading || hasError || hasRows);
  }

  function renderRows() {
    var tbody = byId("tableBody");
    if (!tbody) return;
    setStates(true, false, true);
    var filtered = getFilteredRows();
    var total = filtered.length;
    var totalPages = Math.max(1, Math.ceil(total / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    var start = (state.page - 1) * state.pageSize;
    var end = start + state.pageSize;
    var pageRows = filtered.slice(start, end);
    tbody.innerHTML = "";

    pageRows.forEach(function (row, idx) {
      var tr = document.createElement("tr");
      var key = getRowKey(row, start + idx);
      var selected = state.selectedKeys.has(key);
      tr.className = "group employee-row employees-data-table__row transition-colors" + (selected ? " delivery-row--selected" : "");
      tr.innerHTML =
        '<td class="employees-data-table__cell px-2 py-2 text-center align-middle" data-label="Selecionar">' +
          '<input type="checkbox" class="bulk-row-cb rounded border-slate-300 text-blue-600 focus:ring-blue-500" data-row-key="' + escapeAttr(key) + '"' + (selected ? " checked" : "") + ">" +
        "</td>" +
        '<td class="employee-cell-primary employees-data-table__td--col-name px-2 py-2 align-middle" data-label="Colaborador"><div class="employee-primary-content min-w-0"><span class="employee-name employees-data-table__name-link block truncate font-medium employees-text-strong">' + escapeHtml(row.name || "-") + "</span></div></td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Função">' + escapeHtml(row.role_label || "-") + "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Empresa"><span class="employees-pill employees-pill--neutral">' + escapeHtml(row.cost_center || "-") + "</span></td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle text-right tabular-nums" data-label="Dev.">' + fmtBr(row.return_rate_pct, 2) + "%</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle text-right tabular-nums" data-label="Rotas">' + fmtBr(row.route_count, 0) + "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle text-right tabular-nums" data-label="Prod.">' + fmtBr(row.kgh, 1) + " kg/h</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle text-right tabular-nums" data-label="Prêmio">R$ ' + fmtBr(row.estimated_payout, 2) + "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Status"><span class="delivery-status-badge" data-tone="' + escapeAttr(statusClass(row.status_tone)) + '">' + escapeHtml(row.status_label || "Sem status") + "</span></td>" +
        '<td class="employee-actions-cell px-2 py-2 align-middle" data-label="Ações"><div class="employee-actions employees-action-strip flex flex-nowrap items-center gap-1">' +
          '<button type="button" class="employee-action-btn employee-action-btn--edit" title="Editar" data-row-action="edit" data-row-key="' + escapeAttr(key) + '"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536M4 20h4l10.5-10.5"></path></svg></button>' +
          '<button type="button" class="employee-action-btn employee-action-btn--return" title="Detalhar" data-row-action="details" data-row-key="' + escapeAttr(key) + '"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0"></path></svg></button>' +
        "</div></td>";
      tbody.appendChild(tr);
    });

    updateMeta(total, pageRows.length, start + 1, Math.min(end, total), totalPages);
    updateBulkCount();
    setStates(false, false, total > 0);
  }

  function updateMeta(total, shown, start, end, totalPages) {
    var resultMeta = byId("resultMeta");
    var pageMeta = byId("paginationMeta");
    if (resultMeta) {
      resultMeta.textContent = total > 0
        ? ("Exibindo " + start + "-" + end + " de " + total + " registros")
        : "Nenhum resultado encontrado.";
    }
    if (pageMeta) pageMeta.textContent = total > 0 ? ("Página " + state.page + " de " + totalPages + " (" + shown + " itens)") : "0 resultados";
    var prevBtn = byId("prevPageBtn");
    var nextBtn = byId("nextPageBtn");
    if (prevBtn) prevBtn.disabled = state.page <= 1;
    if (nextBtn) nextBtn.disabled = state.page >= totalPages;
  }

  function updateBulkCount() {
    var boxes = Array.prototype.slice.call(document.querySelectorAll(".bulk-row-cb"));
    var checked = boxes.filter(function (b) { return !!b.checked; });
    var selectedCount = state.selectedKeys.size;
    var countEl = byId("bulk-selected-count");
    var batchEl = byId("batchSelectedCount");
    var master = byId("bulk-select-all");
    if (countEl) countEl.textContent = String(selectedCount);
    if (batchEl) batchEl.textContent = String(selectedCount);
    if (master) {
      master.checked = boxes.length > 0 && checked.length === boxes.length;
      master.indeterminate = checked.length > 0 && checked.length < boxes.length;
    }
  }

  function getRowsForSelection() {
    return Array.prototype.slice.call(document.querySelectorAll(".bulk-row-cb"));
  }

  function openConfirm(text, handler) {
    byId("confirmText").textContent = text || "Deseja continuar?";
    state.confirmHandler = typeof handler === "function" ? handler : null;
    openModal("confirmModal");
  }

  function validateImportFile() {
    var input = byId("importFile");
    var preview = byId("importPreview");
    var output = byId("importValidationResult");
    var confirmBtn = byId("confirmImportBtn");
    if (!input || !input.files || !input.files[0]) {
      showAlert("Selecione um arquivo para validar.", "error");
      return;
    }
    var file = input.files[0];
    var name = normalize(file.name);
    var required = ["colaborador", "funcao", "empresa", "devolucao_pct"];
    preview.classList.remove("hidden");
    confirmBtn.disabled = true;

    if (name.slice(-4) !== ".csv") {
      output.innerHTML = '<p class="text-emerald-600 dark:text-emerald-300">Arquivo selecionado. A validação completa (tipos, duplicidade e linhas vazias) será concluída no processamento de importação.</p>';
      confirmBtn.disabled = false;
      return;
    }

    var reader = new FileReader();
    reader.onload = function () {
      try {
        var text = String(reader.result || "");
        var lines = text.split(/\r?\n/).filter(function (line) { return line.trim().length > 0; });
        if (!lines.length) {
          output.innerHTML = '<p class="text-rose-600 dark:text-rose-300">Arquivo vazio.</p>';
          return;
        }
        var headers = lines[0].split(",").map(normalize);
        var missing = required.filter(function (col) { return headers.indexOf(col) === -1; });
        if (missing.length) {
          output.innerHTML = '<p class="text-rose-600 dark:text-rose-300">Colunas obrigatórias ausentes: ' + missing.join(", ") + ".</p>";
          return;
        }
        var nameIdx = headers.indexOf("colaborador");
        var dateIdx = headers.indexOf("data");
        var seen = new Set();
        var empties = 0;
        var dup = 0;
        for (var i = 1; i < lines.length; i += 1) {
          var cols = lines[i].split(",");
          if (!cols.join("").trim()) {
            empties += 1;
            continue;
          }
          var person = normalize(cols[nameIdx] || "");
          if (!person) empties += 1;
          if (dateIdx !== -1) {
            var key = person + "::" + normalize(cols[dateIdx] || "");
            if (seen.has(key)) dup += 1;
            seen.add(key);
          }
        }
        output.innerHTML = '<p class="text-emerald-600 dark:text-emerald-300">Arquivo válido para importação.</p>' +
          '<p class="mt-1">Linhas analisadas: <strong>' + (lines.length - 1) + "</strong> | Vazias: <strong>" + empties + "</strong> | Duplicadas: <strong>" + dup + "</strong></p>";
        confirmBtn.disabled = false;
      } catch (_e) {
        output.innerHTML = '<p class="text-rose-600 dark:text-rose-300">Não foi possível validar o arquivo.</p>';
      }
    };
    reader.readAsText(file, "utf-8");
  }

  function findRowByKey(key) {
    var rows = currentRows();
    for (var i = 0; i < rows.length; i += 1) {
      if (getRowKey(rows[i], i) === key) return rows[i];
    }
    return null;
  }

  function setTab(tab) {
    state.activeTab = tab;
    state.page = 1;
    document.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-tab") === tab);
    });
    renderRows();
  }

  function setQuickFilter(filter) {
    state.quickFilter = filter;
    state.page = 1;
    document.querySelectorAll(".quick-filter").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-quick-filter") === filter);
    });
    document.querySelectorAll("[data-kpi-filter]").forEach(function (btn) {
      btn.classList.toggle("ops-card--selected", btn.getAttribute("data-kpi-filter") === filter || (filter === "all" && btn.getAttribute("data-kpi-filter") === "all"));
    });
    renderRows();
  }

  function clearFilters() {
    state.searchTerm = "";
    state.statusFilter = "all";
    state.quickFilter = "all";
    state.page = 1;
    var search = byId("searchInput");
    var status = byId("statusFilter");
    if (search) search.value = "";
    if (status) status.value = "all";
    setQuickFilter("all");
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function escapeAttr(str) { return escapeHtml(str); }

  document.addEventListener("click", function (event) {
    var dismiss = event.target.closest("[data-dismiss-alert]");
    if (dismiss) { hideAlert(); return; }

    var open = event.target.closest("[data-open-modal]");
    if (open) { openModal(open.getAttribute("data-open-modal")); return; }

    var close = event.target.closest("[data-close-modal]");
    if (close) { closeModal(close.getAttribute("data-close-modal")); return; }

    if (event.target.classList.contains("emp-modal-shell")) {
      closeModal(event.target.id);
      return;
    }

    var tabBtn = event.target.closest("[data-tab]");
    if (tabBtn) {
      setTab(tabBtn.getAttribute("data-tab"));
      return;
    }

    var quick = event.target.closest(".quick-filter");
    if (quick) {
      setQuickFilter(quick.getAttribute("data-quick-filter"));
      return;
    }

    var kpi = event.target.closest("[data-kpi-filter]");
    if (kpi) {
      setQuickFilter(kpi.getAttribute("data-kpi-filter"));
      return;
    }

    if (event.target.id === "clearFiltersBtn") {
      clearFilters();
      return;
    }

    if (event.target.id === "prevPageBtn") {
      if (state.page > 1) {
        state.page -= 1;
        renderRows();
      }
      return;
    }
    if (event.target.id === "nextPageBtn") {
      state.page += 1;
      renderRows();
      return;
    }

    var rowAction = event.target.closest("[data-row-action]");
    if (rowAction) {
      var key = rowAction.getAttribute("data-row-key");
      var row = findRowByKey(key);
      if (!row) return;
      var action = rowAction.getAttribute("data-row-action");
      if (action === "details") {
        showAlert("Detalhe rápido: " + (row.name || "Colaborador") + " · " + (row.status_label || "Sem status"), "success");
      }
      if (action === "edit") {
        byId("edit-index").value = key;
        byId("edit-name").value = row.name || "";
        byId("edit-status").value = row.status_tone || "slate";
        openModal("editModal");
      }
      return;
    }

    var batch = event.target.closest("[data-batch-action]");
    if (batch) {
      var mode = batch.getAttribute("data-batch-action");
      if (mode === "clear") {
        state.selectedKeys.clear();
        renderRows();
        closeModal("batchModal");
        showAlert("Seleção limpa com sucesso.", "success");
        return;
      }
      openConfirm("Deseja executar a ação em lote para os itens selecionados?", function () {
        closeModal("confirmModal");
        closeModal("batchModal");
        showAlert("Ação em lote executada com sucesso.", "success");
      });
      return;
    }

    if (event.target.id === "confirmSubmitBtn") {
      if (typeof state.confirmHandler === "function") state.confirmHandler();
      state.confirmHandler = null;
      return;
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.id === "statusFilter") {
      state.statusFilter = normalize(event.target.value || "all");
      state.page = 1;
      renderRows();
      return;
    }
    if (event.target.id === "bulk-select-all") {
      var checked = !!event.target.checked;
      getRowsForSelection().forEach(function (box) {
        var key = box.getAttribute("data-row-key");
        box.checked = checked;
        if (checked) state.selectedKeys.add(key);
        else state.selectedKeys.delete(key);
      });
      updateBulkCount();
      renderRows();
      return;
    }
    if (event.target.classList.contains("bulk-row-cb")) {
      var rowKey = event.target.getAttribute("data-row-key");
      if (event.target.checked) state.selectedKeys.add(rowKey);
      else state.selectedKeys.delete(rowKey);
      updateBulkCount();
      var tr = event.target.closest("tr");
      if (tr) tr.classList.toggle("delivery-row--selected", !!event.target.checked);
      return;
    }
    if (event.target.id === "importFile") {
      var label = byId("importFileName");
      if (label) {
        label.textContent = event.target.files && event.target.files[0] ? event.target.files[0].name : "";
      }
      byId("importPreview").classList.add("hidden");
      byId("confirmImportBtn").disabled = true;
      return;
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-debounce-search='true']")) {
      window.clearTimeout(state.debounceTimer);
      state.debounceTimer = window.setTimeout(function () {
        state.searchTerm = normalize(event.target.value || "");
        state.page = 1;
        renderRows();
      }, SEARCH_DEBOUNCE_MS);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.openModalId) closeModal(state.openModalId);
  });

  var validateImportBtn = byId("validateImportBtn");
  if (validateImportBtn) validateImportBtn.addEventListener("click", validateImportFile);

  var importForm = byId("importForm");
  if (importForm) {
    importForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (byId("confirmImportBtn").disabled) {
        showAlert("Valide o arquivo antes de importar.", "error");
        return;
      }
      closeModal("importModal");
      showAlert("Importação enviada para processamento.", "success");
    });
  }

  var createForm = byId("createForm");
  if (createForm) {
    createForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!createForm.reportValidity()) return;
      closeModal("createModal");
      showAlert("Registro criado com sucesso.", "success");
    });
  }

  var editForm = byId("editForm");
  if (editForm) {
    editForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!editForm.reportValidity()) return;
      closeModal("editModal");
      showAlert("Registro atualizado com sucesso.", "success");
    });
  }

  try {
    renderRows();
  } catch (_err) {
    setStates(false, true, false);
  }
})();
