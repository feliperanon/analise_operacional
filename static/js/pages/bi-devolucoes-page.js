(function () {
  "use strict";

  var CHART_SRC = "/static/vendor/chart.umd.min.js";
  var DEBOUNCE_MS = 280;
  var PAGE_SIZE = 28;

  var page = document.querySelector('[data-page="bi-devolucoes"]');
  if (!page) return;

  function parseJson(id) {
    var node = document.getElementById(id);
    if (!node) return {};
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (_err) {
      return {};
    }
  }

  var data = parseJson("bi-devolucoes-data");
  (function mergeEvolucaoChartData() {
    var evNode = document.getElementById("bi-dev-evolucao-data");
    if (!evNode) return;
    try {
      var parsed = JSON.parse((evNode.textContent || "").trim() || "[]");
      if (Array.isArray(parsed)) {
        data.evolucaoDiaria = parsed;
      }
    } catch (_err) {
      /* JSON principal pode falhar; série da evolução vem em script dedicado */
    }
  })();
  var allRows = Array.isArray(data.rowsDetail) ? data.rowsDetail.slice() : [];
  var filteredRows = allRows.slice();
  var cursor = 0;
  var searchTimer = 0;
  var currentQuickFilter = "";
  /** Campo dedicado ao clicar no ranking (motivo / responsabilidade / cliente); evita substring em nomes de cliente. */
  var listSearchField = "";
  var sortKey = null;
  var sortDir = "asc";

  var stateText = document.getElementById("bi-dev-state");
  var tableBody = document.getElementById("bi-dev-table-body");
  var cardsRoot = document.getElementById("bi-dev-cards");
  var moreBtn = document.getElementById("bi-dev-more");
  var searchInput = document.getElementById("bi-dev-search");
  var form = document.getElementById("bi-dev-form");
  var filterCollapsible = page.querySelector("[data-filters-body]");
  var toggleFiltersBtn = page.querySelector("[data-toggle-filters]");
  var advancedToggleBtn = page.querySelector("[data-advanced-filters]");
  var advancedPanel = page.querySelector("[data-filters-advanced]");
  var tableWrap = document.querySelector("#bi-dev-table-panel .bi-dev-table-wrap");
  var tableEmpty = document.getElementById("bi-dev-table-empty");
  var chartSkeleton = document.getElementById("bi-dev-chart-skeleton");
  var chartEmpty = document.getElementById("bi-dev-chart-empty");
  var chartCanvasWrap = document.querySelector(".bi-dev-chart-wrap--main");
  var detailModal = document.getElementById("bi-dev-detail-modal");
  var detailTitle = document.getElementById("bi-dev-detail-title");
  var detailDl = detailModal ? detailModal.querySelector(".bi-dev-detail-dl") : null;
  var respSelect = document.getElementById("bi-dev-resp");

  function syncExportHrefs() {
    var csv = document.querySelector("[data-export-csv]");
    var xlsx = document.querySelector("[data-export-xlsx]");
    if (csv && data.exportCsv) csv.setAttribute("href", data.exportCsv);
    if (xlsx && data.exportXlsx) xlsx.setAttribute("href", data.exportXlsx);
  }

  function fmtMoney(v) {
    return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function fmtPct(v) {
    return Number(v || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
  }

  function isoDateToBr(iso) {
    if (!iso || String(iso).length < 10) return "—";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return iso;
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  function computeStatus(row) {
    if (row.status_operacional) return String(row.status_operacional);
    if ((row.acima_300 || "").toUpperCase() === "SIM") return "Crítica";
    if ((row.source || "").toUpperCase() === "EXCEL") return "Pendente";
    return "Resolvida";
  }

  function rowDataTs(row) {
    var s = String(row.data || "").slice(0, 10);
    if (s.length < 10) return null;
    var t = Date.parse(s + "T12:00:00");
    return Number.isNaN(t) ? null : t;
  }

  function getSortValue(row, key) {
    if (key === "data") return rowDataTs(row);
    if (key === "status") return computeStatus(row);
    if (key === "valor" || key === "pct_impacto") {
      var n = Number(row[key]);
      return Number.isFinite(n) ? n : null;
    }
    if (key === "client_nb") {
      var nb = row.client_nb != null && row.client_nb !== "" ? String(row.client_nb) : String(row.client_nb_fmt || "");
      return nb;
    }
    return row[key] != null && row[key] !== "" ? String(row[key]) : "";
  }

  function cmpVal(va, vb) {
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === "number" && typeof vb === "number") {
      return va < vb ? -1 : va > vb ? 1 : 0;
    }
    return String(va).localeCompare(String(vb), "pt-BR", { sensitivity: "base", numeric: true });
  }

  function compareRows(a, b, key, dir) {
    var mul = dir === "asc" ? 1 : -1;
    var va = getSortValue(a, key);
    var vb = getSortValue(b, key);
    var primary = cmpVal(va, vb) * mul;
    if (primary !== 0) return primary;
    var ida = a.id != null ? Number(a.id) : 0;
    var idb = b.id != null ? Number(b.id) : 0;
    if (ida < idb) return -1;
    if (ida > idb) return 1;
    return 0;
  }

  function applyCurrentSort() {
    if (!sortKey) return;
    filteredRows.sort(function (a, b) {
      return compareRows(a, b, sortKey, sortDir);
    });
  }

  function updateSortHeaders() {
    var heads = page.querySelectorAll("#bi-dev-table thead [data-bi-dev-sort]");
    for (var i = 0; i < heads.length; i += 1) {
      var h = heads[i];
      var k = h.getAttribute("data-bi-dev-sort");
      var ind = h.querySelector(".bi-dev-sort-ind");
      if (sortKey && k === sortKey) {
        h.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
        if (ind) ind.textContent = sortDir === "asc" ? "▲" : "▼";
      } else {
        h.setAttribute("aria-sort", "none");
        if (ind) ind.textContent = "";
      }
    }
  }

  function statusBadgeClass(status) {
    if (status === "Crítica") return "sys-badge sys-badge--critical";
    if (status === "Pendente") return "sys-badge sys-badge--alert";
    return "sys-badge sys-badge--ok";
  }

  function respBadgeClass(resp) {
    var r = (resp || "").toUpperCase();
    if (r.indexOf("COMERCIAL") >= 0) return "bi-dev-resp-badge bi-dev-resp-badge--com";
    if (r.indexOf("LOG") >= 0) return "bi-dev-resp-badge bi-dev-resp-badge--log";
    if (r.indexOf("MERCADO") >= 0) return "bi-dev-resp-badge bi-dev-resp-badge--mer";
    return "bi-dev-resp-badge";
  }

  function setChartVisualState(mode) {
    if (chartSkeleton) {
      chartSkeleton.classList.toggle("is-hidden", mode === "ready" || mode === "empty");
    }
    if (chartEmpty) {
      chartEmpty.classList.toggle("hidden", mode !== "empty");
    }
    if (chartCanvasWrap) {
      chartCanvasWrap.classList.toggle("bi-dev-chart-wrap--short", mode === "empty");
      chartCanvasWrap.classList.toggle("bi-dev-chart-wrap--hidden", mode === "empty");
    }
  }

  function updateQuickFilterButtons() {
    var buttons = page.querySelectorAll("[data-quick-filter]");
    for (var i = 0; i < buttons.length; i += 1) {
      var b = buttons[i];
      var kind = b.getAttribute("data-quick-filter");
      if (kind === "today" || kind === "week" || kind === "month") continue;
      var active = currentQuickFilter === kind;
      b.classList.toggle("filter-btn--active", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
    }
  }

  function openDetail(row) {
    if (!detailModal || !detailTitle || !detailDl) return;
    detailTitle.textContent = row.cliente || "—";
    detailDl.textContent = "";
    function addPair(label, val) {
      var dt = document.createElement("dt");
      dt.textContent = label;
      var dd = document.createElement("dd");
      dd.textContent = val === undefined || val === null || val === "" ? "—" : String(val);
      detailDl.appendChild(dt);
      detailDl.appendChild(dd);
    }
    addPair("Cliente", row.cliente);
    addPair("NB", row.client_nb_fmt || row.client_nb || "—");
    addPair("Data (operacional)", isoDateToBr(row.data));
    if (row.data_competencia && String(row.data_competencia).slice(0, 10) !== String(row.data || "").slice(0, 10)) {
      addPair("Competência (fechamento)", isoDateToBr(row.data_competencia));
    }
    if (row.client_id != null) {
      addPair(
        "Histórico no período (cliente)",
        String(row.hist_rotas_entrega_periodo != null ? row.hist_rotas_entrega_periodo : 0) +
          " rota(s) de entrega · " +
          String(row.hist_devolucoes_cliente_periodo != null ? row.hist_devolucoes_cliente_periodo : 0) +
          " devolução(ões)"
      );
    }
    addPair("Valor", fmtMoney(row.valor));
    addPair("Motivo", row.motivo);
    addPair("Responsabilidade", row.responsabilidade);
    addPair("Vendedor", row.vendedor);
    addPair("Motorista", row.motorista);
    addPair("Observação", row.observacao);
    addPair("Status", computeStatus(row));
    addPair("Classificação de impacto", row.impacto_classificacao || "—");
    addPair("Possível ação corretiva", row.acao_corretiva || "—");
    addPair("% impacto no período", row.pct_impacto != null ? fmtPct(row.pct_impacto) : "—");
    addPair("Peso (rota)", row.peso_kg_fmt || "—");
    addPair("Registrado em", row.registrado_em_br || "—");
    addPair("Origem", row.source);
    detailModal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeDetail() {
    if (!detailModal) return;
    detailModal.classList.add("hidden");
    document.body.style.overflow = "";
  }

  function appendTd(tr, content, opts) {
    var td = document.createElement("td");
    td.className = (opts && opts.className) || "employees-data-table__cell px-2 py-2 align-middle";
    if (opts && opts.right) td.className += " text-right";
    if (typeof content === "string") td.textContent = content;
    else td.appendChild(content);
    tr.appendChild(td);
  }

  function clienteCell(name, clientId) {
    var wrap = document.createElement("div");
    wrap.className = "min-w-0";
    var n = name || "—";
    if (clientId != null && String(clientId).trim() !== "") {
      var a = document.createElement("a");
      a.href = "/clients/" + encodeURIComponent(String(clientId));
      a.className =
        "employees-data-table__name-link block truncate font-medium text-slate-900 transition-colors hover:underline dark:text-slate-100";
      a.title = "Abrir cadastro do cliente";
      a.textContent = n;
      wrap.appendChild(a);
    } else {
      var sp = document.createElement("span");
      sp.className = "block truncate font-medium employees-text-strong";
      sp.textContent = n;
      wrap.appendChild(sp);
    }
    return wrap;
  }

  function isHighImpact(row) {
    return Number(row.valor || 0) > 800;
  }

  function renderChunk(reset) {
    if (!tableBody || !cardsRoot || !moreBtn) return;
    if (reset) {
      cursor = 0;
      tableBody.innerHTML = "";
      cardsRoot.innerHTML = "";
    }
    var end = Math.min(cursor + PAGE_SIZE, filteredRows.length);
    for (var i = cursor; i < end; i += 1) {
      var row = filteredRows[i];
      var status = computeStatus(row);
      var statusEl = document.createElement("span");
      statusEl.className = statusBadgeClass(status);
      statusEl.textContent = status;

      var tr = document.createElement("tr");
      tr.className = "employees-data-table__row transition-colors";
      appendTd(tr, isoDateToBr(row.data), {
        className: "employees-data-table__cell px-3 py-2 pl-5 align-middle whitespace-nowrap tabular-nums",
      });
      appendTd(tr, clienteCell(row.cliente, row.client_id), {
        className: "employees-data-table__cell px-2 py-2 align-middle max-w-[14rem]",
      });
      appendTd(tr, row.client_nb_fmt || row.client_nb || "—", {
        className: "employees-data-table__cell px-2 py-2 align-middle whitespace-nowrap tabular-nums text-xs",
      });
      appendTd(tr, row.vendedor || "—");
      appendTd(tr, row.motorista || "—");
      appendTd(tr, row.motivo || "—");
      var respWrap = document.createElement("span");
      respWrap.className = respBadgeClass(row.responsabilidade);
      respWrap.textContent = row.responsabilidade || "—";
      appendTd(tr, respWrap);
      appendTd(tr, fmtMoney(row.valor), {
        right: true,
        className: "employees-data-table__cell px-2 py-2 align-middle whitespace-nowrap tabular-nums font-semibold text-sky-600 dark:text-sky-300",
      });
      appendTd(tr, row.pct_impacto != null ? fmtPct(row.pct_impacto) : "—", {
        right: true,
        className: "employees-data-table__cell px-2 py-2 align-middle whitespace-nowrap tabular-nums text-right",
      });
      appendTd(tr, statusEl);
      var actionTd = document.createElement("td");
      actionTd.className = "employees-data-table__cell px-2 py-2 pr-5 align-middle text-right";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "employee-action-btn employee-action-btn--edit bi-dev-detail";
      btn.setAttribute("data-idx", String(i));
      btn.setAttribute("title", "Ver detalhes");
      btn.innerHTML =
        '<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>';
      actionTd.appendChild(btn);
      tr.appendChild(actionTd);
      tableBody.appendChild(tr);

      var card = document.createElement("article");
      card.className = "bi-dev-card";
      var h = document.createElement("h4");
      h.className = "bi-dev-card__title";
      if (row.client_id != null && String(row.client_id).trim() !== "") {
        var la = document.createElement("a");
        la.href = "/clients/" + encodeURIComponent(String(row.client_id));
        la.className =
          "bi-dev-card__title-link font-semibold text-slate-900 underline-offset-2 hover:underline dark:text-slate-100";
        la.textContent = row.cliente || "—";
        h.appendChild(la);
      } else {
        h.textContent = row.cliente || "—";
      }
      card.appendChild(h);
      var valP = document.createElement("p");
      valP.className = "bi-dev-card__valor tabular-nums";
      valP.textContent = fmtMoney(row.valor);
      card.appendChild(valP);
      addLine("NB", row.client_nb_fmt || row.client_nb || "—", true);
      if (isHighImpact(row)) {
        var hi = document.createElement("span");
        hi.className = "sys-badge sys-badge--critical bi-dev-card__badge";
        hi.textContent = "Alto impacto";
        card.appendChild(hi);
      }
      function addLine(label, val, muted) {
        var p = document.createElement("p");
        p.className = muted ? "bi-dev-card__row bi-dev-card__row--muted" : "bi-dev-card__row";
        var s = document.createElement("strong");
        s.textContent = label + ": ";
        p.appendChild(s);
        p.appendChild(document.createTextNode(val));
        card.appendChild(p);
      }
      addLine("Motivo", row.motivo || "—");
      var respLine = document.createElement("p");
      respLine.className = "bi-dev-card__row";
      var rs = document.createElement("strong");
      rs.textContent = "Responsabilidade: ";
      respLine.appendChild(rs);
      var rb = document.createElement("span");
      rb.className = respBadgeClass(row.responsabilidade);
      rb.textContent = row.responsabilidade || "—";
      respLine.appendChild(rb);
      card.appendChild(respLine);
      addLine("Vendedor", row.vendedor || "—", true);
      addLine("Motorista", row.motorista || "—", true);
      addLine("Data", isoDateToBr(row.data), true);
      var st = document.createElement("p");
      st.className = "bi-dev-card__row";
      st.appendChild(document.createTextNode("Status: "));
      var sb = document.createElement("span");
      sb.className = statusBadgeClass(status);
      sb.textContent = status;
      st.appendChild(sb);
      card.appendChild(st);
      var act = document.createElement("div");
      act.className = "bi-dev-card__actions";
      var mb = document.createElement("button");
      mb.type = "button";
      mb.className = "sys-btn sys-btn--secondary bi-dev-detail-mobile text-xs px-2 py-1";
      mb.setAttribute("data-idx", String(i));
      mb.textContent = "Detalhes";
      act.appendChild(mb);
      card.appendChild(act);
      cardsRoot.appendChild(card);
    }
    cursor = end;
    if (moreBtn) {
      moreBtn.style.display =
        filteredRows.length === 0 ? "none" : cursor < filteredRows.length ? "inline-flex" : "none";
    }

    var emptyTitle = document.getElementById("bi-dev-table-empty-title");
    var emptySub = document.getElementById("bi-dev-table-empty-sub");
    if (!filteredRows.length) {
      if (tableWrap) tableWrap.classList.add("bi-dev-table-wrap--hidden");
      if (tableEmpty) tableEmpty.classList.remove("hidden");
      if (emptyTitle && emptySub) {
        if (allRows.length === 0) {
          emptyTitle.textContent = "Sem devoluções no período com os filtros aplicados.";
          emptySub.textContent = "Amplie o intervalo de datas ou revise os filtros da página.";
        } else {
          emptyTitle.textContent = "Nenhuma devolução encontrada para os filtros atuais.";
          emptySub.textContent = "Ajuste a busca na lista ou limpe os filtros.";
        }
      }
      if (stateText) {
        stateText.textContent = allRows.length === 0 ? "Lista vazia no período." : "Lista filtrada sem resultados.";
      }
    } else {
      if (tableWrap) tableWrap.classList.remove("bi-dev-table-wrap--hidden");
      if (tableEmpty) tableEmpty.classList.add("hidden");
      if (stateText) {
        stateText.textContent =
          "Exibindo " +
          end.toLocaleString("pt-BR") +
          " de " +
          filteredRows.length.toLocaleString("pt-BR") +
          " registro(s) na lista.";
      }
    }
  }

  function normListTerm(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function rowMatchesListSearch(row, term, field) {
    if (!term) return true;
    if (field === "responsabilidade") {
      return normListTerm(row.responsabilidade) === term;
    }
    if (field === "motivo") {
      return normListTerm(row.motivo) === term;
    }
    if (field === "cliente") {
      return normListTerm(row.cliente) === term;
    }
    var bag = [
      row.cliente,
      row.client_nb,
      row.client_nb_fmt,
      row.vendedor,
      row.motorista,
      row.ajudante,
      row.motivo,
      row.responsabilidade,
      row.source,
      row.cluster
    ]
      .join(" ")
      .toLowerCase();
    return bag.indexOf(term) >= 0;
  }

  function runClientFilters() {
    var term = normListTerm(searchInput && searchInput.value ? searchInput.value : "");
    filteredRows = allRows.filter(function (row) {
      var st = computeStatus(row);
      var stLower = st.toLowerCase();
      if (currentQuickFilter === "pendentes" && stLower !== "pendente") return false;
      if (currentQuickFilter === "criticas" && stLower !== "crítica") return false;
      if (currentQuickFilter === "resolvidas" && stLower !== "resolvida") return false;
      if (currentQuickFilter === "acima_meta") {
        if (Number(row.valor || 0) < 300) return false;
      }
      return rowMatchesListSearch(row, term, listSearchField);
    });
    applyCurrentSort();
    updateSortHeaders();
    updateQuickFilterButtons();
    renderChunk(true);
  }

  function applyDateQuickFilter(kind) {
    if (!form) return;
    var now = new Date();
    var yyyy = now.getFullYear();
    var mm = String(now.getMonth() + 1).padStart(2, "0");
    var dd = String(now.getDate()).padStart(2, "0");
    var startInput = form.querySelector('[name="date_from"]');
    var endInput = form.querySelector('[name="date_to"]');
    if (!startInput || !endInput) return;
    if (kind === "today") {
      startInput.value = yyyy + "-" + mm + "-" + dd;
      endInput.value = yyyy + "-" + mm + "-" + dd;
    } else if (kind === "week") {
      var weekStart = new Date(now);
      weekStart.setDate(now.getDate() - ((now.getDay() + 6) % 7));
      var wmm = String(weekStart.getMonth() + 1).padStart(2, "0");
      var wdd = String(weekStart.getDate()).padStart(2, "0");
      startInput.value = weekStart.getFullYear() + "-" + wmm + "-" + wdd;
      endInput.value = yyyy + "-" + mm + "-" + dd;
    } else if (kind === "month") {
      startInput.value = yyyy + "-" + mm + "-01";
      endInput.value = yyyy + "-" + mm + "-" + dd;
    }
    form.requestSubmit();
  }

  function setRespByKeyword(keyword) {
    if (!respSelect) return false;
    var kw = (keyword || "").toUpperCase();
    for (var i = 0; i < respSelect.options.length; i += 1) {
      var opt = respSelect.options[i];
      if (opt.value && (opt.text || "").toUpperCase().indexOf(kw) >= 0) {
        respSelect.selectedIndex = i;
        return true;
      }
    }
    return false;
  }

  function submitAcimaMetaCriticas(criticas, acimaMeta) {
    if (!form) return;
    var c = form.querySelector('[name="criticas"]');
    var a = form.querySelector('[name="acima_meta"]');
    if (c) c.checked = !!criticas;
    if (a) a.checked = !!acimaMeta;
    form.requestSubmit();
  }

  function loadChartScript(done) {
    if (window.Chart) {
      done();
      return;
    }
    var existing = document.querySelector('script[data-bi-dev-chart="1"]');
    if (existing) {
      existing.addEventListener("load", done);
      return;
    }
    var s = document.createElement("script");
    s.src = CHART_SRC;
    s.async = true;
    s.dataset.biDevChart = "1";
    s.onload = function () {
      done();
    };
    s.onerror = function () {
      var canvas = document.getElementById("bi-dev-chart-evolution");
      if (canvas && canvas.parentElement) {
        var p = document.createElement("p");
        p.className = "text-sm text-amber-700 dark:text-amber-400 px-2";
        p.textContent = "Não foi possível carregar o gráfico. Recarregue a página ou verifique o arquivo estático.";
        canvas.parentElement.replaceChild(p, canvas);
      }
    };
    document.head.appendChild(s);
  }

  function chartPointLimit() {
    return window.matchMedia && window.matchMedia("(max-width: 639px)").matches ? 18 : 46;
  }

  function chartHeightPx() {
    return window.matchMedia && window.matchMedia("(max-width: 639px)").matches ? 240 : 300;
  }

  function lazyLoadChart() {
    var chartCanvas = document.getElementById("bi-dev-chart-evolution");
    if (!chartCanvas) return;

    var mount = function () {
      if (chartCanvas.dataset.ready === "1") return;
      loadChartScript(function () {
        if (!window.Chart || chartCanvas.dataset.ready === "1") return;
        var allDays = Array.isArray(data.evolucaoDiaria) ? data.evolucaoDiaria.slice() : [];
        var lim = chartPointLimit();
        var days = allDays.slice(-lim);
        if (!days.length) {
          var hintEmpty = document.getElementById("bi-dev-chart-export-hint");
          if (hintEmpty) {
            hintEmpty.textContent =
              "Não há série diária para exibir (período vazio ou dados indisponíveis). Verifique as datas e filtros.";
          }
          chartCanvas.dataset.ready = "1";
          setChartVisualState("empty");
          return;
        }
        chartCanvas.parentElement.style.minHeight = chartHeightPx() + "px";

        if (chartCanvas._biDevChart) {
          chartCanvas._biDevChart.destroy();
          chartCanvas._biDevChart = null;
        }

        var metaArr = days.map(function (d) {
          var m = d.meta_2pct_valor;
          return m != null && !isNaN(Number(m)) ? Number(m) : null;
        });
        var hasMeta = metaArr.some(function (x) {
          return x != null && !isNaN(x);
        });
        var receitaArr = days.map(function (d) {
          return Number(d.receita_base || 0);
        });
        var hasReceita = receitaArr.some(function (x) {
          return x > 0;
        });

        var valorArr = days.map(function (d) {
          return Number(d.valor || 0);
        });

        var ds = [
          {
            type: "bar",
            label: "Valor devolvido (R$)",
            data: valorArr,
            borderColor: "#c2410c",
            backgroundColor: "rgba(234, 88, 12, 0.45)",
            borderWidth: 1,
            borderRadius: 3,
            maxBarThickness: 22,
            order: 3,
            yAxisID: "y"
          }
        ];
        if (hasMeta) {
          ds.push({
            type: "line",
            label: "Meta 2% (sobre receita do dia)",
            data: metaArr,
            borderColor: "#15803d",
            backgroundColor: "rgba(22, 101, 52, 0.06)",
            borderWidth: 2,
            borderDash: [4, 3],
            fill: false,
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
            pointHoverRadius: 5,
            order: 2,
            yAxisID: "y"
          });
        }
        if (hasReceita) {
          ds.push({
            type: "line",
            label: "Receita base rotas (R$)",
            data: receitaArr,
            borderColor: "rgba(100, 116, 139, 0.85)",
            backgroundColor: "transparent",
            borderWidth: 1.5,
            borderDash: [2, 4],
            fill: false,
            tension: 0.2,
            pointRadius: 0,
            pointHoverRadius: 4,
            order: 1,
            yAxisID: "y1"
          });
        }

        var ySuggestedMax = (function () {
          var mx = 0;
          var i;
          for (i = 0; i < valorArr.length; i += 1) {
            if (valorArr[i] > mx) mx = valorArr[i];
          }
          for (i = 0; i < metaArr.length; i += 1) {
            if (metaArr[i] != null && !isNaN(metaArr[i]) && metaArr[i] > mx) mx = metaArr[i];
          }
          return mx > 0 ? mx * 1.12 : undefined;
        })();

        var scales = {
          x: {
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: Math.min(lim, 16) },
            grid: { display: false }
          },
          y: {
            id: "y",
            position: "left",
            beginAtZero: true,
            suggestedMax: ySuggestedMax,
            ticks: {
              callback: function (value) {
                return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
              }
            },
            title: { display: true, text: "R$ (devolvido / meta dia)" }
          }
        };
        if (hasReceita) {
          scales.y1 = {
            id: "y1",
            position: "right",
            beginAtZero: true,
            grid: { drawOnChartArea: false },
            ticks: {
              callback: function (value) {
                return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
              }
            },
            title: { display: true, text: "Receita (R$)" }
          };
        }

        try {
          var chart = new window.Chart(chartCanvas, {
            type: "bar",
            data: {
              labels: days.map(function (d) {
                return isoDateToBr(d.data);
              }),
              datasets: ds
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              interaction: { mode: "index", intersect: false },
              stacked: false,
              plugins: {
                legend: {
                  display: true,
                  position: "top",
                  labels: {
                    boxWidth: 12,
                    font: { size: 11 },
                    usePointStyle: true,
                    padding: 10
                  }
                },
                tooltip: {
                  padding: 10,
                  callbacks: {
                    label: function (ctx) {
                      var v = ctx.parsed.y;
                      if (v == null || (typeof v === "number" && isNaN(v))) return (ctx.dataset.label || "") + ": —";
                      return (ctx.dataset.label || "") + ": " + fmtMoney(v);
                    },
                    afterBody: function (items) {
                      if (!items || !items.length) return [];
                      var idx = items[0].dataIndex;
                      var row = days[idx];
                      if (!row) return [];
                      var lines = [];
                      var rec = Number(row.receita_base || 0);
                      if (rec > 0) lines.push("Receita base (rotas): " + fmtMoney(rec));
                      var meta = row.meta_2pct_valor;
                      if (meta != null && !isNaN(Number(meta))) lines.push("Teto meta 2% no dia: " + fmtMoney(meta));
                      var pv = row.pct_devolucao_dia;
                      if (pv != null && !isNaN(Number(pv))) lines.push("% devolução no dia: " + fmtPct(pv));
                      lines.push("Qtd. devoluções: " + String(row.qtd != null ? row.qtd : 0));
                      var evq = Number(row.evitadas_qtd || 0);
                      if (evq > 0) {
                        lines.push("Devoluções evitadas (qtd): " + String(evq));
                        var evv = row.evitadas_valor_est;
                        if (evv != null && !isNaN(Number(evv)) && Number(evv) > 0) {
                          lines.push("Valor estimado evitado no dia: " + fmtMoney(evv));
                        }
                      }
                      return lines;
                    }
                  }
                }
              },
              scales: scales
            }
          });
          chartCanvas._biDevChart = chart;
          chartCanvas.dataset.ready = "1";
          setChartVisualState("ready");
        } catch (_chartErr) {
          var hintErr = document.getElementById("bi-dev-chart-export-hint");
          if (hintErr) {
            hintErr.textContent =
              "Erro ao montar o gráfico. Recarregue a página; se persistir, abra o console (F12) para detalhes.";
          }
          setChartVisualState("empty");
        }
      });
    };

    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(
        function (entries) {
          if (
            entries.some(function (e) {
              return e.isIntersecting;
            })
          ) {
            io.disconnect();
            mount();
          }
        },
        { rootMargin: "120px" }
      );
      io.observe(chartCanvas);
      return;
    }
    mount();
  }

  page.addEventListener(
    "click",
    function (event) {
      var exportCh = event.target.closest("[data-bi-dev-chart-export]");
      if (exportCh) {
        var cv = document.getElementById("bi-dev-chart-evolution");
        var hint = document.getElementById("bi-dev-chart-export-hint");
        var ch = cv && cv._biDevChart;
        if (ch && typeof ch.toBase64Image === "function") {
          var safe = String(data.periodLabel || "periodo")
            .replace(/\s+/g, "-")
            .replace(/[/\\?*:|"<>]/g, "_")
            .slice(0, 80);
          var a = document.createElement("a");
          a.href = ch.toBase64Image("image/png", 1);
          a.download = "bi-devolucoes-evolucao-" + safe + ".png";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          if (hint) hint.textContent = "PNG exportado (use zoom do navegador antes se quiser maior resolução).";
        } else if (hint) {
          hint.textContent = "Gráfico ainda não carregou — role até o gráfico na página.";
        }
        return;
      }

      var causeBtn = event.target.closest("[data-bi-cause-search]");
      if (causeBtn && searchInput) {
        searchInput.value = causeBtn.getAttribute("data-bi-cause-search") || "";
        listSearchField = causeBtn.getAttribute("data-bi-search-field") || "";
        currentQuickFilter = "";
        runClientFilters();
        document.getElementById("bi-dev-table-panel") &&
          document.getElementById("bi-dev-table-panel").scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }

      var sortTh = event.target.closest("[data-bi-dev-sort]");
      if (sortTh && tableBody) {
        var skey = sortTh.getAttribute("data-bi-dev-sort");
        if (skey) {
          if (sortKey === skey) sortDir = sortDir === "asc" ? "desc" : "asc";
          else {
            sortKey = skey;
            sortDir = "asc";
          }
          applyCurrentSort();
          updateSortHeaders();
          renderChunk(true);
        }
        return;
      }

      var detailBtn = event.target.closest(".bi-dev-detail, .bi-dev-detail-mobile");
      if (detailBtn) {
        var idx = Number(detailBtn.getAttribute("data-idx"));
        if (!Number.isNaN(idx) && filteredRows[idx]) openDetail(filteredRows[idx]);
        return;
      }

      if (event.target.closest("[data-bi-dev-detail-close]")) {
        closeDetail();
        return;
      }

      var setRespBtn = event.target.closest("[data-quick-set-resp]");
      if (setRespBtn && form) {
        var key = setRespBtn.getAttribute("data-quick-set-resp");
        if (setRespByKeyword(key)) form.requestSubmit();
        return;
      }

      var quickBtn = event.target.closest("[data-quick-filter]");
      if (quickBtn) {
        var kind = quickBtn.getAttribute("data-quick-filter");
        if (kind === "today" || kind === "week" || kind === "month") {
          applyDateQuickFilter(kind);
        } else if (kind === "acima_meta") {
          submitAcimaMetaCriticas(false, true);
        } else if (kind === "criticas") {
          submitAcimaMetaCriticas(true, false);
        } else {
          currentQuickFilter = currentQuickFilter === kind ? "" : kind;
          runClientFilters();
        }
        return;
      }

      if (event.target.closest("#bi-dev-more")) {
        renderChunk(false);
        return;
      }

      if (event.target.closest('[data-action="refresh"]')) {
        window.location.reload();
        return;
      }
    },
    false
  );

  if (detailModal) {
    detailModal.addEventListener("click", function (e) {
      if (e.target === detailModal) closeDetail();
    });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && detailModal && !detailModal.classList.contains("hidden")) closeDetail();
  });

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      listSearchField = "";
      clearTimeout(searchTimer);
      searchTimer = setTimeout(runClientFilters, DEBOUNCE_MS);
    });
  }

  if (toggleFiltersBtn && filterCollapsible) {
    toggleFiltersBtn.addEventListener("click", function () {
      filterCollapsible.classList.toggle("is-collapsed");
      var collapsed = filterCollapsible.classList.contains("is-collapsed");
      toggleFiltersBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggleFiltersBtn.textContent = collapsed ? "Abrir filtros" : "Ocultar filtros";
    });
  }

  if (advancedToggleBtn && advancedPanel) {
    var syncAdv = function () {
      var open = advancedPanel.classList.contains("is-open");
      advancedToggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
      advancedToggleBtn.textContent = open ? "Ocultar filtros avançados" : "Filtros avançados";
    };
    syncAdv();
    advancedToggleBtn.addEventListener("click", function () {
      advancedPanel.classList.toggle("is-open");
      syncAdv();
    });
  }

  syncExportHrefs();
  runClientFilters();
  lazyLoadChart();
})();
