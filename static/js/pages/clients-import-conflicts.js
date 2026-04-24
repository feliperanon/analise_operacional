/**
 * Conflitos de importação de clientes — lista paginada, debounce na busca,
 * Map como fonte da verdade das ações e sincronização de hiddens só no submit.
 */
(function () {
  "use strict";

  var PAGE_SIZE = 50;
  var DEBOUNCE_MS = 140;

  function el(id) {
    return document.getElementById(id);
  }

  var bootstrapEl = el("import-conflicts-bootstrap");
  if (!bootstrapEl || !bootstrapEl.textContent) return;

  var PAYLOAD = {};
  try {
    PAYLOAD = JSON.parse(bootstrapEl.textContent);
  } catch (e) {
    console.error("import-conflicts: JSON inválido", e);
    return;
  }

  var rows = Array.isArray(PAYLOAD.rows) ? PAYLOAD.rows : [];
  var actions = new Map();
  rows.forEach(function (r) {
    actions.set(r.id, r.default_action || "create");
  });

  var state = {
    search: "",
    searchDebounced: "",
    scope: "all",
    conflictType: "",
    outcomeFilter: "",
    sortKey: "row_index",
    sortDir: 1,
    page: 1,
    debounceTimer: null,
    editingRowId: null,
  };

  function currentAction(r) {
    var a = actions.get(r.id);
    if (a != null && a !== "") return a;
    return r.default_action || "create";
  }

  var CONFLICT_LABELS = {
    fone: "Mesmo telefone",
    razao_bairro: "Razão + bairro",
    endereco: "Mesmo endereço",
    nome: "Nome já existe",
    outro: "Possível duplicado",
  };

  function conflictLabel(t) {
    if (!t) return "Sem conflito";
    return CONFLICT_LABELS[t] || CONFLICT_LABELS.outro;
  }

  function rowHaystack(r) {
    return [
      r.name,
      r.nome_fantasia,
      r.razao_social,
      r.municipio,
      r.bairro,
      r.fone,
      r.nb,
      r.endereco,
      r.setor,
      r.cnpj_cpf,
      r.existing_client_name,
      r.existing_seller_display,
      r.new_seller_raw,
      r.new_seller_resolved,
      r.new_seller_effective,
    ]
      .join(" ")
      .toLowerCase();
  }

  function mergeableOnlyChecked() {
    var c = el("importConflictMergeableOnly");
    return !!(c && c.checked);
  }

  function passesOutcomeFilter(r) {
    var o = state.outcomeFilter || "";
    if (!o) return true;
    var act = currentAction(r);
    if (o === "conflict") return !!r.conflict_type;
    if (o === "create") return act === "create";
    if (o === "merge") return act === "merge";
    if (o === "skip") return act === "skip";
    if (o === "merge_vendor_change") {
      return act === "merge" && r.has_merge && !!r.seller_codes_differ;
    }
    if (o === "merge_vendor_same") {
      return act === "merge" && r.has_merge && !r.seller_codes_differ;
    }
    return true;
  }

  function passesFilters(r) {
    if (state.scope === "conflicts" && !r.conflict_type) return false;
    if (state.scope === "clean" && r.conflict_type) return false;
    if (mergeableOnlyChecked() && (!r.conflict_type || !r.has_merge)) return false;
    if (state.conflictType && r.conflict_type !== state.conflictType) return false;
    if (!passesOutcomeFilter(r)) return false;
    var q = state.searchDebounced.trim().toLowerCase();
    if (q && rowHaystack(r).indexOf(q) === -1) return false;
    return true;
  }

  function sortCompare(a, b) {
    var dir = state.sortDir;
    var ka = state.sortKey;
    if (ka === "name") {
      return dir * String(a.name || "").localeCompare(String(b.name || ""), "pt-BR");
    }
    if (ka === "conflict_type") {
      var ca = a.conflict_type || "\uffff";
      var cb = b.conflict_type || "\uffff";
      if (ca === cb) return dir * (a.row_index - b.row_index);
      return dir * String(ca).localeCompare(String(cb), "pt-BR");
    }
    return dir * (a.row_index - b.row_index);
  }

  function filteredRows() {
    var list = rows.filter(passesFilters);
    list.sort(sortCompare);
    return list;
  }

  function totalPages(n) {
    return Math.max(1, Math.ceil(n / PAGE_SIZE));
  }

  function esc(s) {
    if (s == null || s === "") return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function actionOptionsHtml(r) {
    var cur = currentAction(r);
    var parts = [];
    if (r.has_merge) {
      parts.push('<option value="merge"' + (cur === "merge" ? " selected" : "") + ">Mesclar com existente</option>");
    }
    if (!r.has_merge || r.conflict_type) {
      parts.push('<option value="create"' + (cur === "create" ? " selected" : "") + ">Criar novo</option>");
    }
    if (r.conflict_type || r.has_merge) {
      parts.push('<option value="skip"' + (cur === "skip" ? " selected" : "") + ">Ignorar</option>");
    }
    return parts.join("");
  }

  function statusBadge(r) {
    if (!r.conflict_type) {
      return '<span class="sys-badge sys-badge--ok">Será criado</span>';
    }
    return (
      '<span class="employees-pill employees-pill--status employees-pill--pending">' + esc(conflictLabel(r.conflict_type)) + "</span>"
    );
  }

  function sellerComparisonHtml(r) {
    var act = currentAction(r);
    var prev = r.existing_seller_display || "";
    var newEff = r.new_seller_effective || r.new_seller_raw || "";
    var newRaw = r.new_seller_raw || "";
    var newRes = r.new_seller_resolved || "";
    if (!r.existing_client_id) {
      if (act === "skip") {
        return '<span class="employees-text-muted text-xs">Ignorado</span>';
      }
      var line =
        '<span class="font-mono text-xs employees-text-strong">' + esc(newEff || "—") + "</span>";
      var hint = "";
      if (newRaw && newRes && String(newRaw) !== String(newRes)) {
        hint =
          '<span class="mt-0.5 block text-[10px] employees-text-muted">Planilha ' +
          esc(newRaw) +
          " → STAFF " +
          esc(newRes) +
          "</span>";
      }
      return '<div class="min-w-0 max-w-[15rem]"><span class="text-[10px] font-semibold uppercase tracking-wide employees-text-muted">Novo cadastro</span><div class="mt-0.5">' + line + "</div>" + hint + "</div>";
    }
    var a = esc(prev || "—");
    var b = esc(newEff || "—");
    var arrow = '<span class="mx-0.5 shrink-0 employees-text-muted">→</span>';
    var chip = "";
    if (r.seller_codes_differ) {
      chip =
        '<span class="mt-1 inline-flex rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-900 dark:text-amber-200">Código diferente</span>';
    } else if ((prev || newEff) && act === "merge") {
      chip =
        '<span class="mt-1 inline-flex rounded-full bg-slate-500/10 px-2 py-0.5 text-[10px] font-medium employees-text-muted">Mesmo código</span>';
    }
    var sub = "";
    if (newRaw && newRes && String(newRaw) !== String(newRes)) {
      sub =
        '<span class="mt-0.5 block max-w-[15rem] truncate text-[10px] employees-text-muted" title="Valor na planilha vs código resolvido no sistema">Planilha ' +
        esc(newRaw) +
        " · Resolvido " +
        esc(newRes) +
        "</span>";
    }
    return (
      '<div class="min-w-0 max-w-[15rem]"><div class="flex flex-wrap items-center gap-0.5 text-xs font-mono leading-snug"><span>' +
      a +
      "</span>" +
      arrow +
      "<span>" +
      b +
      "</span></div>" +
      sub +
      chip +
      "</div>"
    );
  }

  function renderTable() {
    var tbody = el("importConflictsTbody");
    var emptyEl = el("import-conflicts-empty");
    var pagerEl = el("import-conflicts-pager");
    if (!tbody) return;

    var list = filteredRows();
    var n = list.length;
    var tp = totalPages(n);
    if (state.page > tp) state.page = tp;

    if (n === 0) {
      tbody.innerHTML = "";
      if (emptyEl) emptyEl.classList.remove("hidden");
      if (pagerEl) pagerEl.classList.add("hidden");
      updatePagerMeta(state.page, tp, n);
      return;
    }
    if (emptyEl) emptyEl.classList.add("hidden");
    if (pagerEl) pagerEl.classList.remove("hidden");

    var start = (state.page - 1) * PAGE_SIZE;
    var slice = list.slice(start, start + PAGE_SIZE);

    var frag = document.createDocumentFragment();
    slice.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.className = "employee-row conflict-row employees-data-table__row transition-colors";
      tr.setAttribute("data-row-id", String(r.id));

      var loc = [r.municipio, r.bairro].filter(Boolean).join(" / ");
      var sub = [
        r.razao_social && "Razão: " + r.razao_social,
        r.nome_fantasia && "Fantasia: " + r.nome_fantasia,
        loc,
        r.fone,
        r.nb && "NB " + r.nb,
      ]
        .filter(Boolean)
        .join(" · ");

      var linkExisting =
        r.existing_client_id && r.existing_client_name
          ? '<a href="/clients/' +
            r.existing_client_id +
            '" target="_blank" rel="noopener" class="employees-data-table__name-link text-xs font-medium">#' +
            r.existing_client_id +
            " · " +
            esc(r.existing_client_name) +
            "</a>"
          : '<span class="employees-text-muted text-xs">—</span>';

      tr.innerHTML =
        '<td class="employee-cell-primary employees-data-table__td--col-name px-3 py-2 pl-5 align-middle" data-label="Cliente">' +
        '<div class="min-w-0">' +
        '<span class="employees-data-table__name-link block truncate font-medium employees-text-strong">' +
        esc(r.name) +
        "</span>" +
        '<p class="employees-text-muted mt-0.5 truncate text-xs">' +
        esc(sub) +
        "</p></div></td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle tabular-nums whitespace-nowrap" data-label="Linha">' +
        esc(r.row_index + 1) +
        "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Local">' +
        esc(loc || "—") +
        "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Conflito">' +
        statusBadge(r) +
        "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Cadastro existente">' +
        linkExisting +
        "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle" data-label="Vendedor (antigo → novo)">' +
        sellerComparisonHtml(r) +
        "</td>" +
        '<td class="employees-data-table__cell px-2 py-2 align-middle min-w-[9rem]" data-label="Decisão">' +
        '<select class="sys-input w-full min-w-0 py-1.5 text-sm import-conflict-action-select" data-row-id="' +
        r.id +
        '" aria-label="Ação para a linha">' +
        actionOptionsHtml(r) +
        "</select></td>" +
        '<td class="employee-actions-cell employees-data-table__td--col-actions px-2 py-2 align-middle" data-label="Ações">' +
        '<div class="employee-actions employees-action-strip flex flex-nowrap items-center gap-1">' +
        '<button type="button" class="employee-action-btn employee-action-btn--edit import-conflict-edit-btn" data-row-id="' +
        r.id +
        '" title="Editar decisão">' +
        '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>' +
        "</button></div></td>";

      frag.appendChild(tr);
    });

    tbody.innerHTML = "";
    tbody.appendChild(frag);

    tbody.querySelectorAll(".import-conflict-action-select").forEach(function (sel) {
      sel.addEventListener("change", function () {
        var id = parseInt(sel.getAttribute("data-row-id"), 10);
        if (!isNaN(id)) actions.set(id, sel.value);
        renderTable();
      });
    });
    tbody.querySelectorAll(".import-conflict-edit-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = parseInt(btn.getAttribute("data-row-id"), 10);
        openEditModal(id);
      });
    });

    updatePagerMeta(state.page, tp, n);
  }

  function updatePagerMeta(page, tp, totalFiltered) {
    var meta = el("import-conflicts-pager-meta");
    if (meta) {
      meta.textContent =
        "Página " + page + " de " + tp + " · " + totalFiltered + " linha(s) neste recorte";
    }
    var prev = el("import-conflicts-prev");
    var next = el("import-conflicts-next");
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= tp;
  }

  function scheduleRender() {
    if (state.debounceTimer) clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(function () {
      state.debounceTimer = null;
      state.searchDebounced = state.search;
      state.page = 1;
      renderTable();
    }, DEBOUNCE_MS);
  }

  function setScope(scope) {
    state.scope = scope;
    document.querySelectorAll("[data-conflict-scope-btn]").forEach(function (b) {
      var on = b.getAttribute("data-scope") === scope;
      b.classList.toggle("filter-btn--active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    state.page = 1;
    renderTable();
  }

  function resetOutcomeFilterUi() {
    state.outcomeFilter = "";
    var of = el("importOutcomeFilter");
    if (of) of.value = "";
  }

  function setSummaryFilter(kind) {
    var mergeCb = el("importConflictMergeableOnly");
    if (kind === "merge_vendor_diff") {
      if (mergeCb) mergeCb.checked = false;
      var ct0 = el("importConflictTypeFilter");
      if (ct0) ct0.value = "";
      state.conflictType = "";
      state.outcomeFilter = "merge_vendor_change";
      var of0 = el("importOutcomeFilter");
      if (of0) of0.value = "merge_vendor_change";
      setScope("conflicts");
      return;
    }
    if (kind === "all") {
      if (mergeCb) mergeCb.checked = false;
      resetOutcomeFilterUi();
      setScope("all");
      return;
    }
    if (kind === "conflicts") {
      if (mergeCb) mergeCb.checked = false;
      resetOutcomeFilterUi();
      setScope("conflicts");
      return;
    }
    if (kind === "clean") {
      if (mergeCb) mergeCb.checked = false;
      resetOutcomeFilterUi();
      setScope("clean");
      return;
    }
    if (kind === "mergeable") {
      if (mergeCb) mergeCb.checked = true;
      resetOutcomeFilterUi();
      setScope("conflicts");
      var ct = el("importConflictTypeFilter");
      if (ct) ct.value = "";
      state.conflictType = "";
      state.page = 1;
      renderTable();
    }
  }

  function openModal(id) {
    var m = el(id);
    if (m) m.classList.remove("hidden");
  }
  function closeModal(id) {
    var m = el(id);
    if (m) m.classList.add("hidden");
  }

  function syncHiddenActions(container) {
    if (!container) return;
    container.innerHTML = "";
    rows.forEach(function (r) {
      var inp = document.createElement("input");
      inp.type = "hidden";
      inp.name = "action_" + r.id;
      inp.value = currentAction(r);
      container.appendChild(inp);
    });
  }

  function countActionsSummary() {
    var m = { create: 0, merge: 0, skip: 0 };
    rows.forEach(function (r) {
      var a = currentAction(r);
      if (m[a] != null) m[a]++;
      else m.create++;
    });
    return m;
  }

  var bypassConfirm = false;

  function wireForm() {
    var form = el("import-confirm-form");
    var hiddenHost = el("import-conflicts-synced-actions");
    if (!form || !hiddenHost) return;

    form.addEventListener("submit", function (e) {
      if (bypassConfirm) {
        bypassConfirm = false;
        syncHiddenActions(hiddenHost);
        return;
      }
      e.preventDefault();
      var c = countActionsSummary();
      var body = el("import-confirm-submit-body");
      if (body) {
        body.innerHTML =
          "<ul class=\"m-0 list-disc space-y-1 pl-4 text-sm employees-text-body\">" +
          "<li><strong>" +
          c.create +
          "</strong> como criar novo</li>" +
          "<li><strong>" +
          c.merge +
          "</strong> mesclagem(ões)</li>" +
          "<li><strong>" +
          c.skip +
          "</strong> ignorada(s)</li></ul>";
      }
      openModal("cicConfirmSubmitModal");
    });
  }

  window.importConflictsFinalizeSubmit = function () {
    closeModal("cicConfirmSubmitModal");
    var form = el("import-confirm-form");
    if (!form) return;
    bypassConfirm = true;
    form.requestSubmit();
  };

  window.importConflictsOpenBulkModal = function () {
    openModal("cicBulkModal");
  };
  window.importConflictsCloseBulkModal = function () {
    closeModal("cicBulkModal");
  };

  window.importConflictsApplyBulk = function () {
    var sel = el("importBulkAction");
    if (!sel) return;
    var val = sel.value;
    filteredRows().forEach(function (r) {
      if (val === "merge" && !r.has_merge) return;
      if (!r.conflict_type && val !== "create") return;
      actions.set(r.id, val);
    });
    closeModal("cicBulkModal");
    renderTable();
  };

  function openEditModal(rowId) {
    var r = null;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].id === rowId) {
        r = rows[i];
        break;
      }
    }
    if (!r) return;
    state.editingRowId = rowId;
    var title = el("importEditModalTitle");
    var sel = el("importEditModalSelect");
    if (title) title.textContent = r.name || "Linha " + (r.row_index + 1);
    if (sel) {
      sel.innerHTML = actionOptionsHtml(r);
      sel.value = currentAction(r);
    }
    openModal("cicEditRowModal");
  }

  window.importConflictsCloseEditModal = function () {
    closeModal("cicEditRowModal");
    state.editingRowId = null;
  };

  window.importConflictsSaveEditModal = function () {
    var sel = el("importEditModalSelect");
    if (!sel || state.editingRowId == null) return;
    actions.set(state.editingRowId, sel.value);
    importConflictsCloseEditModal();
    renderTable();
  };

  window.importConflictsSetSort = function (key) {
    if (state.sortKey === key) state.sortDir *= -1;
    else {
      state.sortKey = key;
      state.sortDir = 1;
    }
    ["row_index", "name", "conflict_type"].forEach(function (k) {
      var icon = el("import-sort-icon-" + k);
      if (!icon) return;
      icon.classList.remove("employees-data-table__sort-icon--active");
    });
    var active = el("import-sort-icon-" + key);
    if (active) active.classList.add("employees-data-table__sort-icon--active");
    state.page = 1;
    renderTable();
  };

  window.importConflictsClearFilters = function () {
    if (state.debounceTimer) {
      clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }
    state.search = "";
    state.searchDebounced = "";
    state.conflictType = "";
    state.outcomeFilter = "";
    state.page = 1;
    var s = el("importConflictSearch");
    if (s) s.value = "";
    var ct = el("importConflictTypeFilter");
    if (ct) ct.value = "";
    var of = el("importOutcomeFilter");
    if (of) of.value = "";
    var mo = el("importConflictMergeableOnly");
    if (mo) mo.checked = false;
    setScope("all");
  };

  window.importConflictsModalBackdrop = function (e, modalId) {
    if (e.target === el(modalId)) closeModal(modalId);
  };

  function bindChrome() {
    var search = el("importConflictSearch");
    if (search) {
      search.addEventListener("input", function () {
        state.search = search.value;
        scheduleRender();
      });
    }
    var ctype = el("importConflictTypeFilter");
    if (ctype) {
      ctype.addEventListener("change", function () {
        state.conflictType = ctype.value;
        state.page = 1;
        renderTable();
      });
    }
    var mergeOnly = el("importConflictMergeableOnly");
    if (mergeOnly) {
      mergeOnly.addEventListener("change", function () {
        state.page = 1;
        renderTable();
      });
    }

    var outcome = el("importOutcomeFilter");
    if (outcome) {
      outcome.addEventListener("change", function () {
        state.outcomeFilter = outcome.value || "";
        state.page = 1;
        renderTable();
      });
    }

    document.querySelectorAll("[data-conflict-scope-btn]").forEach(function (b) {
      b.addEventListener("click", function () {
        var sc = b.getAttribute("data-scope") || "all";
        var mergeCb = el("importConflictMergeableOnly");
        if (mergeCb) mergeCb.checked = false;
        resetOutcomeFilterUi();
        setScope(sc);
      });
    });

    var prev = el("import-conflicts-prev");
    var next = el("import-conflicts-next");
    if (prev)
      prev.addEventListener("click", function () {
        if (state.page > 1) {
          state.page--;
          renderTable();
        }
      });
    if (next)
      next.addEventListener("click", function () {
        var list = filteredRows();
        var tp = totalPages(list.length);
        if (state.page < tp) {
          state.page++;
          renderTable();
        }
      });

    document.querySelectorAll("[data-summary-filter]").forEach(function (card) {
      card.addEventListener("click", function () {
        var kind = card.getAttribute("data-summary-filter");
        if (kind) setSummaryFilter(kind);
      });
    });

    wireForm();
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindChrome();
    var icon = el("import-sort-icon-row_index");
    if (icon) icon.classList.add("employees-data-table__sort-icon--active");
    renderTable();
  });
})();
