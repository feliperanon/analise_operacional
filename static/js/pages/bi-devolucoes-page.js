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

  function syncExportHrefs() {
    var csv = document.querySelector("[data-export-csv]");
    var xlsx = document.querySelector("[data-export-xlsx]");
    if (csv && data.exportCsv) csv.setAttribute("href", data.exportCsv);
    if (xlsx && data.exportXlsx) xlsx.setAttribute("href", data.exportXlsx);
  }

  function fmtMoney(v) {
    return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function isoDateToBr(iso) {
    if (!iso || String(iso).length < 10) return "—";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return iso;
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  function computeStatus(row) {
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
    addPair("Data", isoDateToBr(row.data));
    addPair("Valor", fmtMoney(row.valor));
    addPair("Motivo", row.motivo);
    addPair("Responsabilidade", row.responsabilidade);
    addPair("Vendedor", row.vendedor);
    addPair("Motorista", row.motorista);
    addPair("Ajudante", row.ajudante);
    addPair("Origem", row.source);
    addPair("Cluster", row.cluster);
    addPair("Acima de R$ 300", (row.acima_300 || "").toUpperCase() === "SIM" ? "Sim" : "Não");
    addPair("Status operacional", computeStatus(row));
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
      appendTd(tr, fmtMoney(row.valor), { right: true });
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
      function addLine(label, val) {
        var p = document.createElement("p");
        p.className = "bi-dev-card__row";
        var s = document.createElement("strong");
        s.textContent = label + ": ";
        p.appendChild(s);
        p.appendChild(document.createTextNode(val));
        card.appendChild(p);
      }
      addLine("Valor", fmtMoney(row.valor));
      addLine("Motivo", row.motivo || "—");
      var st = document.createElement("p");
      st.className = "bi-dev-card__row";
      st.appendChild(document.createTextNode("Status: "));
      var sb = document.createElement("span");
      sb.className = statusBadgeClass(status);
      sb.textContent = status;
      st.appendChild(sb);
      card.appendChild(st);
      addLine("Data", isoDateToBr(row.data));
      addLine("Vendedor / Motorista", (row.vendedor || "—") + " · " + (row.motorista || "—"));
      var act = document.createElement("div");
      act.className = "bi-dev-card__actions";
      var mb = document.createElement("button");
      mb.type = "button";
      mb.className = "sys-btn sys-btn--secondary bi-dev-detail-mobile";
      mb.setAttribute("data-idx", String(i));
      mb.textContent = "Detalhes";
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
        stateText.textContent = "Nenhum resultado com os filtros atuais. Ajuste a busca ou as visões rápidas.";
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

  function escapeAttr(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function renderRankings() {
    var motivos = Array.isArray(data.topMotivos) ? data.topMotivos.slice(0, 8) : [];
    var owners = Array.isArray(data.topMotoristas) ? data.topMotoristas.slice(0, 12) : [];
    var motivosRoot = document.getElementById("bi-dev-top-motivos");
    var ownersRoot = document.getElementById("bi-dev-top-owners");
    if (motivosRoot) {
      motivosRoot.innerHTML = motivos.length
        ? motivos
            .map(function (m) {
              return (
                '<li class="bi-dev-rank-item"><span class="bi-dev-rank-item__label">' +
                escapeAttr(m.motivo || "—") +
                '</span><span class="bi-dev-rank-item__meta">' +
                escapeAttr(m.qtd || 0) +
                "</span></li>"
              );
            })
            .join("")
        : '<li class="text-sm text-slate-500 dark:text-slate-400">Sem dados para o período.</li>';
    }
    if (ownersRoot) {
      ownersRoot.innerHTML = owners.length
        ? owners
            .map(function (item) {
              var nome = item.motorista || "—";
              var q = item.qtd || 0;
              return (
                '<li class="bi-dev-rank-item"><span class="bi-dev-rank-item__label">' +
                escapeAttr(nome) +
                '</span><span class="bi-dev-rank-item__meta">' +
                escapeAttr(q) +
                "</span></li>"
              );
            })
            .join("")
        : '<li class="text-sm text-slate-500 dark:text-slate-400">Sem dados para o período.</li>';
    }
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

  function lazyLoadChart() {
    var chartCanvas = document.getElementById("bi-dev-chart-evolution");
    if (!chartCanvas) return;

    var mount = function () {
      if (chartCanvas.dataset.ready === "1") return;
      loadChartScript(function () {
        if (!window.Chart || chartCanvas.dataset.ready === "1") return;
        var days = (data.evolucaoDiaria || []).slice(-20);
        if (!days.length) {
          chartCanvas.dataset.ready = "1";
          return;
        }
        chartCanvas.dataset.ready = "1";
        new window.Chart(chartCanvas, {
          type: "line",
          data: {
            labels: days.map(function (d) {
              return isoDateToBr(d.data);
            }),
            datasets: [
              {
                label: "Devoluções",
                data: days.map(function (d) {
                  return d.qtd;
                }),
                borderColor: "#2563eb",
                backgroundColor: "rgba(37,99,235,.12)",
                fill: true,
                tension: 0.25
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { maxRotation: 0, autoSkip: true } },
              y: { beginAtZero: true, ticks: { precision: 0 } }
            }
          }
        });
      });
    };

    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(
        function (entries) {
          if (entries.some(function (e) {
            return e.isIntersecting;
          })) {
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

      var quickBtn = event.target.closest("[data-quick-filter]");
      if (quickBtn) {
        var kind = quickBtn.getAttribute("data-quick-filter");
        if (kind === "today" || kind === "week" || kind === "month") {
          applyDateQuickFilter(kind);
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
    });
  }

  syncExportHrefs();
  renderRankings();
  runClientFilters();
  lazyLoadChart();
})();
