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
  var allRows = Array.isArray(data.rowsDetail) ? data.rowsDetail.slice() : [];
  var filteredRows = allRows.slice();
  var cursor = 0;
  var searchTimer = 0;
  var currentQuickFilter = "";

  var stateText = document.getElementById("bi-dev-state");
  var tableBody = document.getElementById("bi-dev-table-body");
  var cardsRoot = document.getElementById("bi-dev-cards");
  var moreBtn = document.getElementById("bi-dev-more");
  var searchInput = document.getElementById("bi-dev-search");
  var form = document.getElementById("bi-dev-form");
  var filterCollapsible = page.querySelector("[data-filters-body]");
  var toggleFiltersBtn = page.querySelector("[data-toggle-filters]");
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

  function statusBadgeClass(status) {
    if (status === "Crítica") return "sys-badge sys-badge--critical";
    if (status === "Pendente") return "sys-badge sys-badge--alert";
    return "sys-badge sys-badge--ok";
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
    addPair("Data", isoDateToBr(row.data));
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
      appendTd(tr, isoDateToBr(row.data), { className: "employees-data-table__cell px-3 py-2 pl-5 align-middle whitespace-nowrap" });
      appendTd(tr, row.cliente || "—");
      appendTd(tr, row.vendedor || "—");
      appendTd(tr, row.motorista || "—");
      appendTd(tr, row.motivo || "—");
      appendTd(tr, row.responsabilidade || "—");
      appendTd(tr, fmtMoney(row.valor), { right: true });
      appendTd(tr, row.pct_impacto != null ? fmtPct(row.pct_impacto) : "—", { right: true });
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
      h.textContent = row.cliente || "—";
      card.appendChild(h);
      var valP = document.createElement("p");
      valP.className = "bi-dev-card__valor";
      valP.textContent = fmtMoney(row.valor);
      card.appendChild(valP);
      if (isHighImpact(row)) {
        var hi = document.createElement("span");
        hi.className = "sys-badge sys-badge--critical bi-dev-card__badge";
        hi.textContent = "Alto impacto";
        card.appendChild(hi);
      }
      function addLine(label, val) {
        var p = document.createElement("p");
        p.className = "bi-dev-card__row";
        var s = document.createElement("strong");
        s.textContent = label + ": ";
        p.appendChild(s);
        p.appendChild(document.createTextNode(val));
        card.appendChild(p);
      }
      addLine("Motivo", row.motivo || "—");
      addLine("Data", isoDateToBr(row.data));
      addLine("Vendedor", row.vendedor || "—");
      addLine("Motorista", row.motorista || "—");
      addLine("Responsabilidade", row.responsabilidade || "—");
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
      mb.className = "sys-btn sys-btn--secondary bi-dev-detail-mobile";
      mb.setAttribute("data-idx", String(i));
      mb.textContent = "Ver detalhes";
      act.appendChild(mb);
      card.appendChild(act);
      cardsRoot.appendChild(card);
    }
    cursor = end;
    moreBtn.style.display = cursor < filteredRows.length ? "inline-flex" : "none";

    if (!filteredRows.length) {
      if (allRows.length === 0) {
        stateText.textContent = "Não há devoluções no período selecionado.";
      } else {
        stateText.textContent = "Nenhum resultado com os filtros atuais. Ajuste a busca ou os atalhos.";
      }
    } else {
      stateText.textContent = "Exibindo " + end + " de " + filteredRows.length + " registro(s) na lista.";
    }
  }

  function runClientFilters() {
    var term = (searchInput && searchInput.value ? searchInput.value : "").trim().toLowerCase();
    filteredRows = allRows.filter(function (row) {
      var st = computeStatus(row);
      var stLower = st.toLowerCase();
      if (currentQuickFilter === "pendentes" && stLower !== "pendente") return false;
      if (currentQuickFilter === "criticas" && stLower !== "crítica") return false;
      if (currentQuickFilter === "resolvidas" && stLower !== "resolvida") return false;
      if (currentQuickFilter === "acima_meta") {
        if (Number(row.valor || 0) < 300) return false;
      }
      if (!term) return true;
      var bag = [
        row.cliente,
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
    });
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
    return window.matchMedia && window.matchMedia("(max-width: 639px)").matches ? 12 : 24;
  }

  function chartHeightPx() {
    return window.matchMedia && window.matchMedia("(max-width: 639px)").matches ? 160 : 220;
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
          chartCanvas.dataset.ready = "1";
          return;
        }
        chartCanvas.dataset.ready = "1";
        chartCanvas.parentElement.style.minHeight = chartHeightPx() + "px";
        var metaRef = data.metaValorDiaRef;
        var metaArr = days.map(function () {
          return metaRef != null ? Number(metaRef) : null;
        });
        var hasMeta = metaRef != null && metaArr.every(function (x) {
          return x != null && !isNaN(x);
        });
        var ds = [
          {
            label: "Valor devolvido (R$)",
            data: days.map(function (d) {
              return Number(d.valor || 0);
            }),
            borderColor: "#ea580c",
            backgroundColor: "rgba(234,88,12,.08)",
            fill: true,
            tension: 0.22,
            yAxisID: "y"
          }
        ];
        if (hasMeta) {
          ds.push({
            label: "Referência 2% (proporcional/dia)",
            data: metaArr,
            borderColor: "#16a34a",
            borderDash: [6, 4],
            fill: false,
            tension: 0,
            pointRadius: 0,
            yAxisID: "y"
          });
        }
        new window.Chart(chartCanvas, {
          type: "line",
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
            plugins: {
              legend: {
                display: true,
                labels: { boxWidth: 10, font: { size: 11 } }
              },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    var v = ctx.parsed.y;
                    if (v == null) return ctx.dataset.label || "";
                    return (ctx.dataset.label || "") + ": " + fmtMoney(v);
                  }
                }
              }
            },
            scales: {
              x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: lim } },
              y: {
                id: "y",
                position: "left",
                beginAtZero: true,
                ticks: {
                  callback: function (value) {
                    return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
                  }
                },
                title: { display: true, text: "R$" }
              }
            }
          }
        });
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
      var causeBtn = event.target.closest("[data-bi-cause-search]");
      if (causeBtn && searchInput) {
        searchInput.value = causeBtn.getAttribute("data-bi-cause-search") || "";
        currentQuickFilter = "";
        runClientFilters();
        document.getElementById("bi-dev-table-panel") &&
          document.getElementById("bi-dev-table-panel").scrollIntoView({ behavior: "smooth", block: "start" });
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
      clearTimeout(searchTimer);
      searchTimer = setTimeout(runClientFilters, DEBOUNCE_MS);
    });
  }

  if (toggleFiltersBtn && filterCollapsible) {
    toggleFiltersBtn.addEventListener("click", function () {
      filterCollapsible.classList.toggle("is-collapsed");
      var collapsed = filterCollapsible.classList.contains("is-collapsed");
      toggleFiltersBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggleFiltersBtn.textContent = collapsed ? "Mostrar filtros" : "Ocultar filtros";
    });
    if (window.matchMedia && window.matchMedia("(min-width: 640px)").matches) {
      filterCollapsible.classList.remove("is-collapsed");
      toggleFiltersBtn.setAttribute("aria-expanded", "true");
      toggleFiltersBtn.textContent = "Ocultar filtros";
    }
  }

  syncExportHrefs();
  runClientFilters();
  lazyLoadChart();
})();
