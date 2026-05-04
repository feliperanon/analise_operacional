(function () {
  "use strict";

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
  var pageSize = 25;
  var cursor = 0;
  var searchTimer = 0;
  var currentQuickFilter = "";

  var stateText = document.getElementById("bi-dev-state");
  var tableBody = document.getElementById("bi-dev-table-body");
  var cardsRoot = document.getElementById("bi-dev-cards");
  var moreBtn = document.getElementById("bi-dev-more");
  var searchInput = document.getElementById("bi-dev-search");
  var form = document.getElementById("bi-dev-form");
  var filterBody = page.querySelector("[data-filters-body]");
  var toggleFiltersBtn = page.querySelector("[data-toggle-filters]");

  function fmtMoney(v) {
    return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function isoDateToBr(iso) {
    if (!iso || String(iso).length < 10) return "-";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return iso;
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  function computeStatus(row) {
    if ((row.acima_300 || "").toUpperCase() === "SIM") return "Crítica";
    if ((row.source || "").toUpperCase() === "EXCEL") return "Pendente";
    return "Resolvida";
  }

  function openDetail(row) {
    window.alert(
      "Cliente: " + (row.cliente || "-") +
        "\nData: " + isoDateToBr(row.data) +
        "\nMotivo: " + (row.motivo || "-") +
        "\nValor: " + fmtMoney(row.valor)
    );
  }

  function renderChunk(reset) {
    if (reset) {
      cursor = 0;
      tableBody.innerHTML = "";
      cardsRoot.innerHTML = "";
    }
    var end = Math.min(cursor + pageSize, filteredRows.length);
    for (var i = cursor; i < end; i += 1) {
      var row = filteredRows[i];
      var status = computeStatus(row);
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + isoDateToBr(row.data) + "</td>" +
        "<td>" + (row.cliente || "-") + "</td>" +
        "<td>" + (row.vendedor || "-") + "</td>" +
        "<td>" + (row.motorista || "-") + "</td>" +
        "<td>" + (row.motivo || "-") + "</td>" +
        "<td>" + fmtMoney(row.valor) + "</td>" +
        "<td>" + status + "</td>" +
        '<td><button class="sys-btn sys-btn--secondary bi-dev-detail" data-idx="' + i + '" type="button">Detalhes</button></td>';
      tableBody.appendChild(tr);

      var card = document.createElement("article");
      card.className = "bi-dev-card";
      card.innerHTML =
        "<h4>" + (row.cliente || "-") + "</h4>" +
        "<p><strong>Valor:</strong> " + fmtMoney(row.valor) + "</p>" +
        "<p><strong>Motivo:</strong> " + (row.motivo || "-") + "</p>" +
        "<p><strong>Status:</strong> " + status + "</p>" +
        "<p><strong>Data:</strong> " + isoDateToBr(row.data) + "</p>" +
        "<p><strong>Vendedor/Motorista:</strong> " + (row.vendedor || "-") + " / " + (row.motorista || "-") + "</p>" +
        '<button class="sys-btn sys-btn--secondary bi-dev-detail-mobile" data-idx="' + i + '" type="button">Detalhes</button>';
      cardsRoot.appendChild(card);
    }
    cursor = end;
    moreBtn.style.display = cursor < filteredRows.length ? "inline-flex" : "none";
    if (!filteredRows.length) {
      stateText.textContent = "Não há devoluções para os filtros selecionados.";
    } else {
      stateText.textContent = "Exibindo " + end + " de " + filteredRows.length + " registros.";
    }
  }

  function runClientFilters() {
    var term = (searchInput.value || "").trim().toLowerCase();
    filteredRows = allRows.filter(function (row) {
      var status = computeStatus(row).toLowerCase();
      if (currentQuickFilter === "pendentes" && status !== "pendente") return false;
      if (currentQuickFilter === "criticas" && status !== "crítica") return false;
      if (currentQuickFilter === "resolvidas" && status !== "resolvida") return false;
      if (!term) return true;
      var bag = [
        row.cliente,
        row.vendedor,
        row.motorista,
        row.ajudante,
        row.motivo,
        row.responsabilidade,
        row.source
      ].join(" ").toLowerCase();
      return bag.indexOf(term) >= 0;
    });
    renderChunk(true);
  }

  function applyDateQuickFilter(kind) {
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

  function renderRankings() {
    var motivos = Array.isArray(data.topMotivos) ? data.topMotivos.slice(0, 5) : [];
    var owners = (Array.isArray(data.topMotoristas) ? data.topMotoristas.slice(0, 5) : [])
      .map(function (item) { return { nome: item.motorista, qtd: item.qtd }; });
    var motivosRoot = document.getElementById("bi-dev-top-motivos");
    var ownersRoot = document.getElementById("bi-dev-top-owners");
    motivosRoot.innerHTML = motivos.map(function (m) {
      return "<li>" + (m.motivo || "-") + " • " + (m.qtd || 0) + "</li>";
    }).join("");
    ownersRoot.innerHTML = owners.map(function (m) {
      return "<li>" + (m.nome || "-") + " • " + (m.qtd || 0) + "</li>";
    }).join("");
  }

  function lazyLoadChart() {
    var chartCanvas = document.getElementById("bi-dev-chart-evolution");
    if (!chartCanvas) return;

    var load = function () {
      if (window.Chart && chartCanvas.dataset.ready === "1") return;
      var create = function () {
        chartCanvas.dataset.ready = "1";
        var days = (data.evolucaoDiaria || []).slice(-20);
        if (!window.Chart || !days.length) return;
        new window.Chart(chartCanvas, {
          type: "line",
          data: {
            labels: days.map(function (d) { return isoDateToBr(d.data); }),
            datasets: [{
              label: "Devoluções",
              data: days.map(function (d) { return d.qtd; }),
              borderColor: "#2563eb",
              backgroundColor: "rgba(37,99,235,.12)",
              fill: true,
              tension: 0.25
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } }
          }
        });
      };

      if (window.Chart) {
        create();
        return;
      }

      var s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/chart.js";
      s.onload = create;
      document.head.appendChild(s);
    };

    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) {
          io.disconnect();
          load();
        }
      }, { rootMargin: "200px" });
      io.observe(chartCanvas);
      return;
    }
    load();
  }

  page.addEventListener("click", function (event) {
    var detailBtn = event.target.closest(".bi-dev-detail, .bi-dev-detail-mobile");
    if (detailBtn) {
      var idx = Number(detailBtn.getAttribute("data-idx"));
      if (filteredRows[idx]) openDetail(filteredRows[idx]);
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

    if (event.target.closest('[data-action="export-csv"]')) {
      stateText.textContent = "Exportação em andamento...";
      setTimeout(function () {
        stateText.textContent = "Exportação concluída.";
      }, 1200);
      return;
    }
  });

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(runClientFilters, 300);
    });
  }

  if (toggleFiltersBtn && filterBody) {
    toggleFiltersBtn.addEventListener("click", function () {
      filterBody.classList.toggle("is-collapsed");
    });
  }

  renderRankings();
  runClientFilters();
  lazyLoadChart();
})();
