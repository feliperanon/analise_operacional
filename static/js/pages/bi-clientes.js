/* global Chart */
(function () {
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function fmtMoney(v) {
    return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }
  function fmtPct(v) {
    return Number(v || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  }
  function fmtKg(v) {
    return Number(v || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " kg";
  }
  function fmtDur(m) {
    var n = Math.max(0, Math.round(Number(m) || 0));
    if (n < 60) return n + " min";
    var h = Math.floor(n / 60),
      mn = n % 60;
    return mn === 0 ? h + " h" : h + " h " + mn + " min";
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var ctx = this,
        args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  var state = {
    rows: [],
    routes: [],
    filtered: [],
    sortKey: "delivered_value",
    sortDir: -1,
    page: 1,
    pageSize: 25,
    search: "",
  };

  function mergeIntelWithRanking(intel, ranking) {
    var map = {};
    (intel || []).forEach(function (r) {
      map[String(r.client_id)] = r;
    });
    return (ranking || []).map(function (row) {
      var k = String(row.client_id);
      var i = map[k] || {};
      return Object.assign({}, row, i);
    });
  }

  function applyFilterSort() {
    var q = (state.search || "").toLowerCase().trim();
    var base = state.rows.slice();
    if (q) {
      base = base.filter(function (r) {
        var blob = [
          r.client_name,
          r.client_code,
          r.vendedor_name,
          r.top_motivo_name,
          String(r.client_id || ""),
        ]
          .join(" ")
          .toLowerCase();
        return blob.indexOf(q) !== -1;
      });
    }
    base.sort(function (a, b) {
      var ka = a[state.sortKey],
        kb = b[state.sortKey];
      if (typeof ka === "string") {
        ka = ka.toLowerCase();
        kb = (kb || "").toLowerCase();
      }
      if (ka === kb) return 0;
      if (ka == null) return 1;
      if (kb == null) return -1;
      return ka < kb ? -state.sortDir : ka > kb ? state.sortDir : 0;
    });
    state.filtered = base;
    var maxPage = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
    if (state.page > maxPage) state.page = maxPage;
  }

  function totals(slice) {
    var t = {
      visits: 0,
      delivered_visits: 0,
      returned_occurrences: 0,
      planned_value: 0,
      delivered_value: 0,
      returned_value: 0,
      planned_kg: 0,
      delivered_kg: 0,
      returned_kg: 0,
      reopen_count: 0,
    };
    slice.forEach(function (r) {
      t.visits += Number(r.visits || 0);
      t.delivered_visits += Number(r.delivered_visits || 0);
      t.returned_occurrences += Number(r.returned_occurrences || 0);
      t.planned_value += Number(r.planned_value || 0);
      t.delivered_value += Number(r.delivered_value || 0);
      t.returned_value += Number(r.returned_value || 0);
      t.planned_kg += Number(r.planned_kg || 0);
      t.delivered_kg += Number(r.delivered_kg || 0);
      t.returned_kg += Number(r.returned_kg || 0);
      t.reopen_count += Number(r.reopen_count || 0);
    });
    return t;
  }

  function renderTable() {
    var tb = document.getElementById("bi-cli-tbody");
    var tf = document.getElementById("bi-cli-tfoot");
    var cards = document.getElementById("bi-cli-cards-mobile");
    var meta = document.getElementById("bi-cli-page-meta");
    if (!tb) return;
    applyFilterSort();
    var start = (state.page - 1) * state.pageSize;
    var pageRows = state.filtered.slice(start, start + state.pageSize);
    tb.innerHTML = "";
    pageRows.forEach(function (r) {
      var tr = document.createElement("tr");
      var cls = "";
      if (r.classification_code === "PREMIUM_OPERACIONAL") cls = "bi-cli-row--premium";
      if (r.classification_code === "CRITICO" || r.classification_code === "ALTO_VALOR_RISCO") cls = "bi-cli-row--critical";
      tr.className = cls;
      tr.innerHTML =
        "<td class=\"max-w-[14rem] truncate\">" +
        escapeHtml(r.client_name) +
        "</td>" +
        "<td>" +
        escapeHtml(r.client_code || "—") +
        "</td>" +
        "<td class=\"max-w-[10rem] truncate\">" +
        escapeHtml(r.vendedor_name || "—") +
        "</td>" +
        "<td class=\"text-right\">" +
        (r.visits || 0) +
        "</td>" +
        "<td class=\"text-right\">" +
        (r.delivered_visits || 0) +
        "</td>" +
        "<td class=\"text-right\">" +
        (r.returned_occurrences || 0) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtPct(r.return_rate_qtd) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(r.planned_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(r.delivered_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(r.returned_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtPct(r.return_pct_planned) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(r.planned_kg) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(r.delivered_kg) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(r.returned_kg) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtDur(r.avg_duration_m) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtDur(r.max_duration_m) +
        "</td>" +
        "<td class=\"text-right\">" +
        (r.reopen_count || 0) +
        "</td>" +
        "<td class=\"max-w-[10rem] truncate text-xs\">" +
        escapeHtml(r.top_motivo_name || "—") +
        "</td>" +
        "<td class=\"max-w-[8rem] truncate text-xs\">" +
        escapeHtml(r.top_responsabilidade_name || "—") +
        "</td>" +
        "<td><span class=\"sys-badge sys-badge--neutral text-[10px]\">" +
        escapeHtml(r.classification_title || "—") +
        "</span></td>" +
        "<td class=\"text-right font-semibold\">" +
        (r.cliente_score != null ? r.cliente_score : "—") +
        "</td>" +
        "<td class=\"text-right\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-2 text-xs\" data-bi-cli-open=\"" +
        String(r.client_id) +
        "\">Ver detalhe</button></td>";
      tb.appendChild(tr);
    });

    if (tf) {
      var tt = totals(state.filtered);
      var pctStops = tt.visits ? (100 * tt.returned_occurrences) / tt.visits : 0;
      var pctVal = tt.planned_value ? (100 * tt.returned_value) / tt.planned_value : 0;
      tf.innerHTML =
        "<td colspan=\"3\" class=\"font-semibold\">Totais (filtrado)</td>" +
        "<td class=\"text-right\">" +
        tt.visits +
        "</td>" +
        "<td class=\"text-right\">" +
        tt.delivered_visits +
        "</td>" +
        "<td class=\"text-right\">" +
        tt.returned_occurrences +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtPct(pctStops) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(tt.planned_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(tt.delivered_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtMoney(tt.returned_value) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtPct(pctVal) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(tt.planned_kg) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(tt.delivered_kg) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtKg(tt.returned_kg) +
        "</td>" +
        "<td colspan=\"6\"></td>";
    }

    if (cards) {
      cards.innerHTML = "";
      pageRows.forEach(function (r) {
        var d = document.createElement("div");
        d.className = "bi-cli-mobile-card";
        d.innerHTML =
          "<div class=\"flex items-start justify-between gap-2\">" +
          "<div class=\"min-w-0\">" +
          "<p class=\"font-semibold leading-tight\">" +
          escapeHtml(r.client_name) +
          "</p>" +
          "<p class=\"employees-text-muted text-xs\">" +
          escapeHtml(r.client_code || "") +
          " · " +
          escapeHtml(r.vendedor_name || "") +
          "</p></div>" +
          "<span class=\"sys-badge sys-badge--neutral shrink-0 text-[10px]\">" +
          escapeHtml(r.classification_title || "") +
          "</span></div>" +
          "<div class=\"mt-2 grid grid-cols-2 gap-2 text-xs\">" +
          "<div><span class=\"employees-text-muted\">Entregue</span><br><strong>" +
          fmtMoney(r.delivered_value) +
          "</strong></div>" +
          "<div><span class=\"employees-text-muted\">Devolvido</span><br><strong>" +
          fmtMoney(r.returned_value) +
          "</strong></div>" +
          "<div><span class=\"employees-text-muted\">% dev.</span><br><strong>" +
          fmtPct(r.return_pct_planned) +
          "</strong></div>" +
          "<div><span class=\"employees-text-muted\">Tempo médio</span><br><strong>" +
          fmtDur(r.avg_duration_m) +
          "</strong></div></div>" +
          "<p class=\"employees-text-muted mt-2 text-xs\">Motivo: " +
          escapeHtml(r.top_motivo_name || "—") +
          "</p>" +
          "<div class=\"mt-3\"><button type=\"button\" class=\"sys-btn sys-btn--primary w-full justify-center text-sm\" data-bi-cli-open=\"" +
          String(r.client_id) +
          "\">Ver detalhe</button></div>";
        cards.appendChild(d);
      });
    }

    if (meta) {
      meta.textContent =
        "Mostrando " +
        (state.filtered.length === 0 ? 0 : start + 1) +
        "–" +
        Math.min(start + state.pageSize, state.filtered.length) +
        " de " +
        state.filtered.length +
        " · página " +
        state.page +
        " / " +
        Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
    }
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function openDrawer(clientId) {
    var id = String(clientId);
    var row = state.rows.find(function (r) {
      return String(r.client_id) === id;
    });
    if (!row) return;
    var drawer = document.getElementById("bi-cli-drawer");
    var title = document.getElementById("bi-cli-d-title");
    var sub = document.getElementById("bi-cli-d-sub");
    if (title) title.textContent = row.client_name || "Cliente";
    if (sub)
      sub.textContent =
        (row.client_code || "—") +
        " · " +
        (row.vendedor_name || "—") +
        " · Score " +
        (row.cliente_score != null ? row.cliente_score : "—") +
        " · " +
        (row.classification_title || "");
    setTab("visao", row);
    document.querySelectorAll(".bi-cli-drawer__tab").forEach(function (btn) {
      btn.onclick = function () {
        setTab(btn.getAttribute("data-tab"), row);
      };
    });
    if (drawer) {
      drawer.classList.remove("hidden");
      drawer.setAttribute("aria-hidden", "false");
    }
  }

  function closeDrawer() {
    var drawer = document.getElementById("bi-cli-drawer");
    if (drawer) {
      drawer.classList.add("hidden");
      drawer.setAttribute("aria-hidden", "true");
    }
  }

  function routesForClient(cid) {
    return (state.routes || []).filter(function (r) {
      return String(r.client_id) === String(cid);
    });
  }

  function setTab(tab, row) {
    var body = document.getElementById("bi-cli-d-body");
    if (!body || !row) return;
    document.querySelectorAll(".bi-cli-drawer__tab").forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-tab") === tab);
    });
    var cid = row.client_id;
    var hist = routesForClient(cid);
    if (tab === "visao") {
      body.innerHTML =
        "<div class=\"grid grid-cols-2 gap-2\">" +
        "<div><span class=\"employees-text-muted text-xs\">Planejado</span><br><strong>" +
        fmtMoney(row.planned_value) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Entregue</span><br><strong>" +
        fmtMoney(row.delivered_value) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Devolvido</span><br><strong>" +
        fmtMoney(row.returned_value) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">% dev. valor</span><br><strong>" +
        fmtPct(row.return_pct_planned) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">% dev. qtd</span><br><strong>" +
        fmtPct(row.return_rate_qtd) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Eficiência entregas</span><br><strong>" +
        fmtPct(row.delivery_efficiency_pct) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Visitas</span><br><strong>" +
        (row.visits || 0) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Reaberturas</span><br><strong>" +
        (row.reopen_count || 0) +
        "</strong></div>" +
        "<div class=\"col-span-2\"><span class=\"employees-text-muted text-xs\">Motivo principal</span><br><strong>" +
        escapeHtml(row.top_motivo_name || "—") +
        "</strong></div>" +
        "<div class=\"col-span-2\"><span class=\"employees-text-muted text-xs\">Responsabilidade principal</span><br><strong>" +
        escapeHtml(row.top_responsabilidade_name || "—") +
        "</strong></div>" +
        "</div>";
    } else if (tab === "historico") {
      if (!hist.length) {
        body.innerHTML =
          "<p class=\"employees-text-muted text-sm\">Sem linhas de rota no recorte leve (amostra). Use exportação ou filtre o cliente na URL com drill-through.</p>";
        return;
      }
      var html =
        "<div class=\"sys-table-wrap sys-table-wrap--x-scroll\"><table class=\"sys-data-table text-xs\"><thead><tr><th>Data</th><th>Pedido</th><th>Motorista</th><th>Placa</th><th>Status</th><th class=\"text-right\">Valor</th><th class=\"text-right\">KG</th><th class=\"text-right\">Min</th><th class=\"text-right\">Reab.</th></tr></thead><tbody>";
      hist.forEach(function (h) {
        html +=
          "<tr><td>" +
          escapeHtml(h.date || "") +
          "</td><td>" +
          escapeHtml(h.order_number || "—") +
          "</td><td class=\"max-w-[8rem] truncate\">" +
          escapeHtml(h.driver_name || "") +
          "</td><td>" +
          escapeHtml(h.plate || "") +
          "</td><td>" +
          escapeHtml(h.status || "") +
          "</td><td class=\"text-right\">" +
          fmtMoney(h.planned_value) +
          "</td><td class=\"text-right\">" +
          fmtKg(h.planned_kg) +
          "</td><td class=\"text-right\">" +
          (h.duration_m != null ? fmtDur(h.duration_m) : "—") +
          "</td><td class=\"text-right\">" +
          (h.reopen_count || 0) +
          "</td></tr>";
      });
      html += "</tbody></table></div>";
      body.innerHTML = html;
    } else if (tab === "devolucoes") {
      var devs = hist.filter(function (h) {
        return String(h.status || "").toLowerCase().indexOf("devol") !== -1 || Number(h.returned_value || 0) > 0;
      });
      if (!devs.length) {
        body.innerHTML = "<p class=\"employees-text-muted text-sm\">Sem devoluções registradas nas paradas da amostra.</p>";
        return;
      }
      var h2 =
        "<div class=\"sys-table-wrap sys-table-wrap--x-scroll\"><table class=\"sys-data-table text-xs\"><thead><tr><th>Data</th><th>Pedido</th><th>Motivo</th><th>Resp.</th><th class=\"text-right\">R$ dev.</th><th>Motorista</th></tr></thead><tbody>";
      devs.forEach(function (h) {
        h2 +=
          "<tr><td>" +
          escapeHtml(h.date || "") +
          "</td><td>" +
          escapeHtml(h.order_number || "—") +
          "</td><td class=\"max-w-[10rem] truncate\">" +
          escapeHtml(h.motivo || "—") +
          "</td><td class=\"max-w-[8rem] truncate\">" +
          escapeHtml(h.responsabilidade || "—") +
          "</td><td class=\"text-right\">" +
          fmtMoney(h.returned_value) +
          "</td><td class=\"max-w-[8rem] truncate\">" +
          escapeHtml(h.driver_name || "") +
          "</td></tr>";
      });
      h2 += "</tbody></table></div>";
      body.innerHTML = h2;
    } else if (tab === "tempos") {
      var mins = hist.map(function (h) {
        return h.duration_m;
      }).filter(function (x) {
        return x != null;
      });
      var avg = mins.length ? mins.reduce(function (a, b) {
        return a + b;
      }, 0) / mins.length : 0;
      var mx = mins.length ? Math.max.apply(null, mins) : 0;
      var mn = mins.length ? Math.min.apply(null, mins) : 0;
      body.innerHTML =
        "<ul class=\"space-y-1 text-sm\">" +
        "<li><strong>Tempo médio (amostra paradas):</strong> " +
        fmtDur(avg) +
        "</li>" +
        "<li><strong>Maior tempo:</strong> " +
        fmtDur(mx) +
        "</li>" +
        "<li><strong>Menor tempo:</strong> " +
        fmtDur(mn) +
        "</li>" +
        "<li class=\"employees-text-muted text-xs\">Comparação com média geral do período está nos KPIs do topo.</li>" +
        "</ul>";
    } else if (tab === "volume") {
      body.innerHTML =
        "<ul class=\"space-y-1 text-sm\">" +
        "<li><strong>KG planejado:</strong> " +
        fmtKg(row.planned_kg) +
        "</li>" +
        "<li><strong>KG entregue:</strong> " +
        fmtKg(row.delivered_kg) +
        "</li>" +
        "<li><strong>KG devolvido:</strong> " +
        fmtKg(row.returned_kg) +
        "</li>" +
        "<li><strong>R$ planejado / entregue / devolvido:</strong> " +
        fmtMoney(row.planned_value) +
        " / " +
        fmtMoney(row.delivered_value) +
        " / " +
        fmtMoney(row.returned_value) +
        "</li>" +
        "</ul>";
    } else {
      var html =
        "<ul class=\"list-disc pl-4 text-sm\">" +
        "<li>" +
        escapeHtml(row.action_recommendation || "Manter monitoramento.") +
        "</li>" +
        "<li>Abrir <a class=\"text-sky-600 underline\" href=\"/bi/devolucoes\">BI Devoluções</a> filtrando o cliente no cadastro financeiro.</li>" +
        "<li>Abrir <a class=\"text-sky-600 underline\" href=\"/bi/delivery\">BI Entregas</a> para ver paradas por motorista neste período.</li>" +
        "</ul>" +
        "<div class=\"mt-3 flex flex-wrap gap-2\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-2 text-xs\" id=\"bi-cli-wa-btn\">Copiar resumo WhatsApp</button>" +
        "</div>";
      body.innerHTML = html;
      var waBtn = document.getElementById("bi-cli-wa-btn");
      if (waBtn) {
        waBtn.onclick = function () {
          var txt = waText(row);
          navigator.clipboard.writeText(txt).then(
            function () {
              waBtn.textContent = "Copiado!";
            },
            function () {
              waBtn.textContent = "Erro ao copiar";
            }
          );
        };
      }
      return;
    }
  }

  function waText(row) {
    var fq = document.getElementById("bi-clientes-root") && document.getElementById("bi-clientes-root").getAttribute("data-filters-query");
    var form = document.getElementById("bi-cli-filters-form");
    var df = form && form.querySelector("[name=date_from]");
    var dt = form && form.querySelector("[name=date_to]");
    var period =
      df && dt && df.value && dt.value
        ? df.value + " a " + dt.value
        : "(ver filtros na tela)";
    return (
      "Cliente: " +
      (row.client_name || "") +
      "\nVendedor: " +
      (row.vendedor_name || "") +
      "\nPeríodo: " +
      period +
      "\nValor entregue: " +
      fmtMoney(row.delivered_value) +
      "\nValor devolvido: " +
      fmtMoney(row.returned_value) +
      "\nÍndice devolução: " +
      fmtPct(row.return_pct_planned) +
      "\nMotivo principal: " +
      (row.top_motivo_name || "") +
      "\nClassificação: " +
      (row.classification_title || "") +
      "\nAção sugerida: " +
      (row.action_recommendation || "") +
      (fq ? "\nURL: " + location.origin + "/bi/clientes?" + fq : "")
    );
  }

  function initCharts() {
    var payload = readJson("bi-cli-chart-json");
    if (!payload || typeof Chart === "undefined") return;
    var common = { responsive: true, maintainAspectRatio: false };
    if (payload.daily_delivered_vs_returned && payload.daily_delivered_vs_returned.length) {
      var d = payload.daily_delivered_vs_returned;
      new Chart(document.getElementById("biCliChartDaily"), {
        type: "line",
        data: {
          labels: d.map(function (x) {
            return x.date;
          }),
          datasets: [
            { label: "Entregue", data: d.map(function (x) { return x.delivered; }), borderColor: "rgb(16,185,129)", tension: 0.2 },
            { label: "Devolvido", data: d.map(function (x) { return x.returned; }), borderColor: "rgb(239,68,68)", tension: 0.2 },
          ],
        },
        options: Object.assign({ scales: { x: { ticks: { maxRotation: 0 } } } }, common),
      });
    }
    if (payload.pareto_returns_top && payload.pareto_returns_top.length) {
      var p = payload.pareto_returns_top.slice(0, 12);
      new Chart(document.getElementById("biCliChartPareto"), {
        type: "bar",
        data: {
          labels: p.map(function (x) {
            return x.name;
          }),
          datasets: [{ label: "R$ devolvido", data: p.map(function (x) { return x.value; }), backgroundColor: "rgb(248,113,113)" }],
        },
        options: Object.assign({ indexAxis: "y", plugins: { legend: { display: false } } }, common),
      });
    }
    if (payload.matrix_impact_x_compra && payload.matrix_impact_x_compra.length) {
      var m = payload.matrix_impact_x_compra;
      new Chart(document.getElementById("biCliChartMatrix"), {
        type: "bubble",
        data: {
          datasets: [
            {
              label: "Clientes",
              data: m.map(function (pt) {
                return { x: pt.x, y: pt.y, r: Math.min(18, Math.max(4, Math.sqrt(pt.r) * 2)) };
              }),
            },
          ],
        },
        options: Object.assign(
          {
            scales: {
              x: { title: { display: true, text: "R$ entregue" } },
              y: { title: { display: true, text: "% devolução s/ planejado" } },
            },
          },
          common
        ),
      });
    }
    if (payload.time_rank && payload.time_rank.labels && payload.time_rank.labels.length) {
      new Chart(document.getElementById("biCliChartTime"), {
        type: "bar",
        data: {
          labels: payload.time_rank.labels.slice(0, 12),
          datasets: [{ label: "Tempo médio (min)", data: (payload.time_rank.avg_minutes || []).slice(0, 12), backgroundColor: "rgb(96,165,250)" }],
        },
        options: Object.assign({ indexAxis: "y", plugins: { legend: { display: false } } }, common),
      });
    }
    if (payload.macro_loss && payload.macro_loss.labels && payload.macro_loss.labels.length) {
      new Chart(document.getElementById("biCliChartResp"), {
        type: "doughnut",
        data: {
          labels: payload.macro_loss.labels,
          datasets: [{ data: payload.macro_loss.values }],
        },
        options: common,
      });
    }
  }

  function boot() {
    state.rows = readJson("bi-cli-intel-json") || [];
    state.routes = readJson("bi-cli-routes-json") || [];
    state.page = 1;

    document.querySelectorAll("[data-sort]").forEach(function (th) {
      th.style.cursor = "pointer";
      th.addEventListener("click", function () {
        var k = th.getAttribute("data-sort");
        if (state.sortKey === k) state.sortDir *= -1;
        else {
          state.sortKey = k;
          state.sortDir = -1;
        }
        state.page = 1;
        renderTable();
      });
    });

    var loc = document.getElementById("bi-cli-search-local");
    if (loc) {
      loc.addEventListener(
        "input",
        debounce(function () {
          state.search = loc.value;
          state.page = 1;
          renderTable();
        }, 280)
      );
    }

    document.getElementById("bi-cli-prev").onclick = function () {
      if (state.page > 1) {
        state.page--;
        renderTable();
      }
    };
    document.getElementById("bi-cli-next").onclick = function () {
      var maxPage = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
      if (state.page < maxPage) {
        state.page++;
        renderTable();
      }
    };

    document.querySelectorAll("[data-bi-cli-close]").forEach(function (b) {
      b.addEventListener("click", closeDrawer);
    });

    function closeTreatableModal() {
      var m = document.getElementById("bi-cli-treatable-modal");
      if (!m) return;
      m.classList.add("hidden");
      m.setAttribute("aria-hidden", "true");
    }

    function openTreatableModal() {
      var m = document.getElementById("bi-cli-treatable-modal");
      var body = document.getElementById("bi-cli-treatable-body");
      if (!m || !body) return;
      var rows = readJson("bi-cli-treatable-json");
      if (!Array.isArray(rows)) rows = [];
      if (!rows.length) {
        body.innerHTML =
          "<p class=\"employees-text-muted py-6 text-center text-sm\">Nenhum cliente com impacto evitável neste recorte (ou valor zerado).</p>";
      } else {
        body.innerHTML = rows
          .map(function (row) {
            var cid = row.client_id != null ? String(row.client_id) : "";
            var motivos = (row.treatable_motivos || [])
              .map(function (x) {
                return (
                  "<li class=\"flex justify-between gap-2 border-b border-slate-100 py-1 dark:border-slate-800\"><span class=\"min-w-0 truncate\">" +
                  escapeHtml(x.motivo) +
                  "</span><span class=\"shrink-0 tabular-nums text-slate-600 dark:text-slate-300\">" +
                  fmtMoney(x.value) +
                  "</span></li>"
                );
              })
              .join("");
            var hints = (row.hints || [])
              .map(function (h) {
                return "<li class=\"mt-1.5 leading-snug\">" + escapeHtml(h) + "</li>";
              })
              .join("");
            return (
              "<article class=\"mb-4 rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 last:mb-0 dark:border-slate-700 dark:bg-slate-800/40\">" +
              "<div class=\"flex flex-wrap items-start justify-between gap-2\">" +
              "<div class=\"min-w-0\">" +
              "<p class=\"font-semibold leading-tight\">" +
              escapeHtml(row.client_name || "—") +
              "</p>" +
              "<p class=\"employees-text-muted mt-0.5 text-xs\">" +
              escapeHtml(row.client_code || "") +
              (row.vendedor_name ? " · " + escapeHtml(row.vendedor_name) : "") +
              "</p></div>" +
              "<div class=\"text-right\">" +
              "<p class=\"text-xs text-violet-700 dark:text-violet-300\">Evitável</p>" +
              "<p class=\"tabular-nums font-semibold text-violet-800 dark:text-violet-200\">" +
              fmtMoney(row.treatable_returned_value) +
              "</p>" +
              "<p class=\"employees-text-muted text-[11px]\">dev. total " +
              fmtMoney(row.returned_value) +
              "</p></div></div>" +
              (row.classification_title
                ? "<p class=\"employees-text-muted mt-2 text-xs\">Classificação: " + escapeHtml(row.classification_title) + "</p>"
                : "") +
              (motivos
                ? "<p class=\"mt-2 text-xs font-medium text-slate-700 dark:text-slate-200\">Motivos tratáveis (valor)</p><ul class=\"mt-1 text-xs\">" +
                  motivos +
                  "</ul>"
                : "") +
              (hints
                ? "<p class=\"mt-3 text-xs font-medium text-slate-700 dark:text-slate-200\">Sugestões automáticas</p><ol class=\"list-decimal pl-4 text-xs text-slate-700 dark:text-slate-300\">" +
                  hints +
                  "</ol>"
                : "") +
              (cid
                ? "<div class=\"mt-3\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-3 text-xs\" data-bi-cli-open=\"" +
                  escapeHtml(cid) +
                  "\">Abrir ficha do cliente</button></div>"
                : "") +
              "</article>"
            );
          })
          .join("");
      }
      m.classList.remove("hidden");
      m.setAttribute("aria-hidden", "false");
    }

    var kpiTreat = document.getElementById("bi-cli-kpi-treatable-open");
    if (kpiTreat) {
      kpiTreat.addEventListener("click", openTreatableModal);
      kpiTreat.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openTreatableModal();
        }
      });
    }
    document.querySelectorAll("[data-bi-cli-treatable-close]").forEach(function (b) {
      b.addEventListener("click", closeTreatableModal);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      var modal = document.getElementById("bi-cli-treatable-modal");
      if (modal && !modal.classList.contains("hidden")) closeTreatableModal();
    });

    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-bi-cli-open]");
      if (!el) return;
      var modal = document.getElementById("bi-cli-treatable-modal");
      if (modal && !modal.classList.contains("hidden") && modal.contains(el)) closeTreatableModal();
      var cid = el.getAttribute("data-bi-cli-open");
      openDrawer(cid);
    });
    renderTable();
    initCharts();
  }

  window.BiClientesPage = { boot: boot };
})();
