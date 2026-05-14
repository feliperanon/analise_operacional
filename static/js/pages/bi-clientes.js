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

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
    chartsBound: false,
    rankingTabKey: "maior_compra",
  };

  var RANK_TABS = [
    { key: "maior_compra", label: "Maior compra" },
    { key: "maior_devolucao", label: "Maior devolução" },
    { key: "maior_pct", label: "Maior % devolução" },
    { key: "baixo_volume_pct", label: "Baixo volume · distorção %" },
    { key: "maior_tempo", label: "Maior tempo" },
    { key: "pequeno_alto_impacto", label: "Pequeno alto impacto" },
    { key: "grandes_risco", label: "Grandes com risco" },
    { key: "melhores", label: "Melhores clientes" },
  ];

  function rowClassForClient(r) {
    var c = r.classification_code || "";
    if (c === "CRITICO") return "bi-client-row--critical";
    if (c === "ALTO_VALOR_RISCO" || c === "PEQUENO_ALTO_IMPACTO") return "bi-client-row--warning";
    if (c === "PREMIUM_OPERACIONAL") return "bi-client-row--premium";
    if (c === "ESTAVEL") return "bi-client-row--stable";
    return "";
  }

  function badgeClassForClient(r) {
    var c = r.classification_code || "";
    if (c === "CRITICO") return "sys-badge sys-badge--critical";
    if (c === "ALTO_VALOR_RISCO") return "sys-badge sys-badge--alert";
    if (c === "PEQUENO_ALTO_IMPACTO") return "sys-badge sys-badge--alert";
    if (c === "PREMIUM_OPERACIONAL") return "sys-badge sys-badge--ok";
    if (c === "ESTAVEL") return "sys-badge sys-badge--ok";
    return "sys-badge sys-badge--neutral";
  }

  function buildDiagnosis(row) {
    var rp = Number(row.return_pct_planned || 0);
    var cls = row.classification_code || "";
    var rv = Number(row.returned_value || 0);
    var dv = Number(row.delivered_value || 0);
    var score = Number(row.cliente_score || 0);
    var occ = Number(row.returned_occurrences || 0);

    if (rv <= 0.01 && occ === 0) {
      return "Cliente sem devolução no período. Manter acompanhamento normal.";
    }
    if (cls === "CRITICO") {
      return "Cliente com impacto relevante em devolução. Exige ação imediata e acompanhamento na próxima venda.";
    }
    if (cls === "ALTO_VALOR_RISCO" || (dv >= 15000 && rp > 2)) {
      return "Cliente importante para o faturamento, mas acima da meta. Priorizar validação comercial antes da rota.";
    }
    if (cls === "PEQUENO_ALTO_IMPACTO") {
      return "Cliente de baixo retorno com esforço operacional elevado. Avaliar frequência, janela e confirmação.";
    }
    if ((cls === "PREMIUM_OPERACIONAL" || cls === "ESTAVEL") && rp <= 2 && score >= 72) {
      return "Cliente relevante e estável. Manter padrão atual e monitorar tempo de descarga.";
    }
    if (dv >= 15000 && rp <= 2 && score >= 70) {
      return "Cliente relevante e estável. Manter padrão atual e monitorar tempo de descarga.";
    }
    return "Perfil misto no período — usar motivo líder e responsabilidade para priorizar a próxima ação.";
  }

  function actionBlocksHtml() {
    return (
      "<div class=\"mt-4 grid gap-3 sm:grid-cols-3\">" +
      "<div class=\"rounded-lg border border-slate-200/80 p-3 dark:border-slate-600\">" +
      "<p class=\"text-xs font-semibold text-indigo-600 dark:text-indigo-300\">Comercial</p>" +
      "<ul class=\"mt-2 list-disc space-y-1 pl-4 text-xs text-slate-600 dark:text-slate-300\">" +
      "<li>Confirmar pedido</li><li>Validar forma de pagamento</li><li>Alinhar prazo/preço</li>" +
      "<li>Conversar com cliente recorrente</li><li>Revisar pedido/produto divergente</li></ul></div>" +
      "<div class=\"rounded-lg border border-slate-200/80 p-3 dark:border-slate-600\">" +
      "<p class=\"text-xs font-semibold text-sky-600 dark:text-sky-300\">Logística</p>" +
      "<ul class=\"mt-2 list-disc space-y-1 pl-4 text-xs text-slate-600 dark:text-slate-300\">" +
      "<li>Confirmar janela de entrega</li><li>Ajustar ordem da rota</li><li>Monitorar tempo parado</li>" +
      "<li>Registrar ocorrência</li><li>Validar acesso/descarga</li></ul></div>" +
      "<div class=\"rounded-lg border border-slate-200/80 p-3 dark:border-slate-600\">" +
      "<p class=\"text-xs font-semibold text-amber-600 dark:text-amber-300\">Mercado</p>" +
      "<ul class=\"mt-2 list-disc space-y-1 pl-4 text-xs text-slate-600 dark:text-slate-300\">" +
      "<li>Identificar cliente ausente</li><li>Rever horário de recebimento</li>" +
      "<li>Validar se pedido foi solicitado</li><li>Avaliar ponto fechado recorrente</li></ul></div></div>"
    );
  }

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
        var blob = [r.client_name, r.client_code, r.vendedor_name, r.top_motivo_name, String(r.client_id || "")]
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
      delivered_value: 0,
      returned_value: 0,
      durWeighted: 0,
      durVisits: 0,
    };
    slice.forEach(function (r) {
      t.visits += Number(r.visits || 0);
      t.delivered_value += Number(r.delivered_value || 0);
      t.returned_value += Number(r.returned_value || 0);
      var v = Number(r.visits || 0);
      if (v > 0) {
        t.durWeighted += Number(r.avg_duration_m || 0) * v;
        t.durVisits += v;
      }
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

    var frag = document.createDocumentFragment();
    pageRows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.className = rowClassForClient(r);
      var badgeCls = badgeClassForClient(r);
      tr.innerHTML =
        "<td class=\"max-w-[14rem]\"><div class=\"truncate font-medium\">" +
        escapeHtml(r.client_name) +
        "</div><div class=\"truncate text-[11px] text-slate-500\">" +
        escapeHtml(r.client_code || "—") +
        "</div></td>" +
        "<td class=\"max-w-[10rem] truncate\">" +
        escapeHtml(r.vendedor_name || "—") +
        "</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtMoney(r.delivered_value) +
        "</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtMoney(r.returned_value) +
        "</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtPct(r.return_pct_planned) +
        "</td>" +
        "<td class=\"text-right\">" +
        (r.visits || 0) +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtDur(r.avg_duration_m) +
        "</td>" +
        "<td class=\"max-w-[9rem] truncate text-xs\">" +
        escapeHtml(r.top_motivo_name || "—") +
        "</td>" +
        "<td class=\"max-w-[8rem] truncate text-xs\">" +
        escapeHtml(r.top_responsabilidade_name || "—") +
        "</td>" +
        "<td><span class=\"" +
        badgeCls +
        " text-[10px]\">" +
        escapeHtml(r.classification_title || "—") +
        "</span></td>" +
        "<td class=\"text-right font-semibold tabular-nums\">" +
        (r.cliente_score != null ? r.cliente_score : "—") +
        "</td>" +
        "<td class=\"text-right\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-2 text-xs\" data-bi-cli-open=\"" +
        String(r.client_id) +
        "\">Detalhar</button></td>";
      frag.appendChild(tr);
    });
    tb.innerHTML = "";
    tb.appendChild(frag);

    if (tf) {
      var tt = totals(state.filtered);
      var pctAgg = tt.delivered_value + tt.returned_value > 0 ? (100 * tt.returned_value) / (tt.delivered_value + tt.returned_value) : 0;
      var avgAgg = tt.durVisits ? tt.durWeighted / tt.durVisits : 0;
      tf.innerHTML =
        "<td colspan=\"2\" class=\"font-semibold\">Totais (filtrado)</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtMoney(tt.delivered_value) +
        "</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtMoney(tt.returned_value) +
        "</td>" +
        "<td class=\"text-right tabular-nums\">" +
        fmtPct(pctAgg) +
        "</td>" +
        "<td class=\"text-right\">" +
        tt.visits +
        "</td>" +
        "<td class=\"text-right\">" +
        fmtDur(avgAgg) +
        "</td>" +
        "<td colspan=\"5\"></td>";
    }

    if (cards) {
      var cfrag = document.createDocumentFragment();
      pageRows.forEach(function (r) {
        var d = document.createElement("article");
        d.className = "bi-client-mobile-card";
        var bcls = badgeClassForClient(r);
        d.innerHTML =
          "<div class=\"flex items-start justify-between gap-2\">" +
          "<div class=\"min-w-0\">" +
          "<strong class=\"leading-tight\">" +
          escapeHtml(r.client_name) +
          "</strong>" +
          "<p class=\"employees-text-muted text-xs\">Cód. " +
          escapeHtml(r.client_code || "—") +
          " · " +
          escapeHtml(r.vendedor_name || "—") +
          "</p></div></div>" +
          "<div class=\"bi-client-mobile-metrics mt-2 grid grid-cols-2 gap-2 text-xs\">" +
          "<span>Entregue <strong class=\"tabular-nums\">" +
          fmtMoney(r.delivered_value) +
          "</strong></span>" +
          "<span>Devolvido <strong class=\"tabular-nums\">" +
          fmtMoney(r.returned_value) +
          "</strong></span>" +
          "<span>% Dev. <strong class=\"tabular-nums\">" +
          fmtPct(r.return_pct_planned) +
          "</strong></span>" +
          "<span>Tempo <strong>" +
          fmtDur(r.avg_duration_m) +
          "</strong></span></div>" +
          "<div class=\"mt-2\"><span class=\"" +
          bcls +
          " text-[11px]\">" +
          escapeHtml(r.classification_title || "—") +
          "</span></div>" +
          "<div class=\"mt-3\"><button type=\"button\" class=\"sys-btn sys-btn--primary w-full justify-center text-sm\" data-bi-cli-open=\"" +
          String(r.client_id) +
          "\">Ver detalhe</button></div>";
        cfrag.appendChild(d);
      });
      cards.innerHTML = "";
      cards.appendChild(cfrag);
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
        " · " +
        (row.city || "—") +
        " · " +
        (row.status_operacional || "—") +
        " · " +
        (row.classification_title || "") +
        " · Score " +
        (row.cliente_score != null ? row.cliente_score : "—");
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
        "<p class=\"rounded-lg border border-slate-200/80 bg-slate-50/80 p-3 text-sm leading-snug dark:border-slate-600 dark:bg-slate-800/40\"><strong>Diagnóstico:</strong> " +
        escapeHtml(buildDiagnosis(row)) +
        "</p>" +
        "<div class=\"mt-3 grid grid-cols-2 gap-2 text-sm\">" +
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
        "<div><span class=\"employees-text-muted text-xs\">Paradas / entregues / devoluções</span><br><strong>" +
        (row.visits || 0) +
        " / " +
        (row.delivered_visits || 0) +
        " / " +
        (row.returned_occurrences || 0) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Tempo médio / maior</span><br><strong>" +
        fmtDur(row.avg_duration_m) +
        " / " +
        fmtDur(row.max_duration_m) +
        "</strong></div>" +
        "<div><span class=\"employees-text-muted text-xs\">Reaberturas</span><br><strong>" +
        (row.reopen_count || 0) +
        "</strong></div>" +
        "<div class=\"col-span-2\"><span class=\"employees-text-muted text-xs\">Motivo / responsabilidade</span><br><strong>" +
        escapeHtml(row.top_motivo_name || "—") +
        " · " +
        escapeHtml(row.top_responsabilidade_name || "—") +
        "</strong></div></div>" +
        actionBlocksHtml();
    } else if (tab === "historico") {
      if (!hist.length) {
        body.innerHTML =
          "<p class=\"employees-text-muted text-sm\">Sem linhas de rota na amostra leve. Refine filtros ou use exportação.</p>";
        return;
      }
      var html =
        "<div class=\"sys-table-wrap sys-table-wrap--x-scroll\"><table class=\"sys-data-table text-xs\"><thead><tr><th>Data</th><th>Pedido</th><th>Motivo</th><th>Resp.</th><th class=\"text-right\">R$</th><th>Status</th></tr></thead><tbody>";
      hist.forEach(function (h) {
        html +=
          "<tr><td>" +
          escapeHtml(h.date || "") +
          "</td><td>" +
          escapeHtml(h.order_number || "—") +
          "</td><td class=\"max-w-[8rem] truncate\">" +
          escapeHtml(h.motivo || "—") +
          "</td><td class=\"max-w-[6rem] truncate\">" +
          escapeHtml(h.responsabilidade || "—") +
          "</td><td class=\"text-right\">" +
          fmtMoney(h.planned_value) +
          "</td><td>" +
          escapeHtml(h.status || "") +
          "</td></tr>";
      });
      html += "</tbody></table></div>";
      body.innerHTML = html;
    } else if (tab === "devolucoes") {
      var devs = hist.filter(function (h) {
        return String(h.status || "").toLowerCase().indexOf("devol") !== -1 || Number(h.returned_value || 0) > 0;
      });
      if (!devs.length) {
        body.innerHTML = "<p class=\"employees-text-muted text-sm\">Sem devoluções na amostra de paradas.</p>";
        return;
      }
      var h2 =
        "<div class=\"sys-table-wrap sys-table-wrap--x-scroll\"><table class=\"sys-data-table text-xs\"><thead><tr><th>Data</th><th>Pedido</th><th>Motivo</th><th>Resp.</th><th class=\"text-right\">R$ dev.</th></tr></thead><tbody>";
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
          "</td></tr>";
      });
      h2 += "</tbody></table></div>";
      body.innerHTML = h2;
    } else if (tab === "tempos") {
      body.innerHTML =
        "<ul class=\"space-y-1 text-sm\">" +
        "<li><strong>Tempo médio (cadastro cliente):</strong> " +
        fmtDur(row.avg_duration_m) +
        "</li>" +
        "<li><strong>Maior tempo (pico):</strong> " +
        fmtDur(row.max_duration_m) +
        "</li>" +
        "<li><strong>Tempo total operacional:</strong> " +
        fmtDur(row.total_duration_m) +
        "</li></ul>";
    } else if (tab === "volume") {
      body.innerHTML =
        "<ul class=\"space-y-1 text-sm\">" +
        "<li><strong>KG planejado / entregue / devolvido:</strong> " +
        fmtKg(row.planned_kg) +
        " / " +
        fmtKg(row.delivered_kg) +
        " / " +
        fmtKg(row.returned_kg) +
        "</li>" +
        "<li><strong>R$ planejado / entregue / devolvido:</strong> " +
        fmtMoney(row.planned_value) +
        " / " +
        fmtMoney(row.delivered_value) +
        " / " +
        fmtMoney(row.returned_value) +
        "</li></ul>";
    } else {
      body.innerHTML =
        "<p class=\"text-sm\"><strong>Recomendado:</strong> " +
        escapeHtml(row.action_recommendation || "Manter monitoramento.") +
        "</p>" +
        actionBlocksHtml() +
        "<div class=\"mt-3 flex flex-wrap gap-2\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-2 text-xs\" id=\"bi-cli-wa-btn\">Copiar resumo</button>" +
        "<a class=\"sys-btn sys-btn--secondary h-8 px-2 text-xs\" href=\"/bi/devolucoes\">BI Devoluções</a></div>";
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
    }
  }

  function waText(row) {
    var fq = document.getElementById("bi-clientes-root") && document.getElementById("bi-clientes-root").getAttribute("data-filters-query");
    var form = document.getElementById("bi-cli-filters-form");
    var df = form && form.querySelector("[name=date_from]");
    var dt = form && form.querySelector("[name=date_to]");
    var period = df && dt && df.value && dt.value ? df.value + " a " + dt.value : "(ver filtros)";
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
      "\nDiagnóstico: " +
      buildDiagnosis(row) +
      "\nAção sugerida: " +
      (row.action_recommendation || "") +
      (fq ? "\nURL: " + location.origin + "/bi/clientes?" + fq : "")
    );
  }

  function mountCharts() {
    if (state.chartsBound || typeof Chart === "undefined") return;
    var payload = readJson("bi-cli-chart-json");
    if (!payload) return;
    var common = { responsive: true, maintainAspectRatio: false };

    var elD = document.getElementById("biCliChartDaily");
    if (elD && payload.daily_delivered_vs_returned && payload.daily_delivered_vs_returned.length) {
      var d = payload.daily_delivered_vs_returned;
      new Chart(elD, {
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

    var elP = document.getElementById("biCliChartParetoMotivos");
    var paretoM = payload.pareto_motivos && payload.pareto_motivos.length ? payload.pareto_motivos : payload.pareto_returns_top;
    if (elP && paretoM && paretoM.length) {
      var p = paretoM.slice(0, 12);
      new Chart(elP, {
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

    var elM = document.getElementById("biCliChartMatrix");
    if (elM && payload.matrix_impact_x_compra && payload.matrix_impact_x_compra.length) {
      var m = payload.matrix_impact_x_compra;
      new Chart(elM, {
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

    var elR = document.getElementById("biCliChartResp");
    if (elR && payload.macro_loss && payload.macro_loss.labels && payload.macro_loss.labels.length) {
      new Chart(elR, {
        type: "doughnut",
        data: {
          labels: payload.macro_loss.labels,
          datasets: [{ data: payload.macro_loss.values }],
        },
        options: common,
      });
    }
    state.chartsBound = true;
  }

  function initChartsIfNeeded() {
    var mount = document.getElementById("bi-cli-charts-mount");
    if (!mount) return;
    var isMd = typeof window.matchMedia !== "undefined" && window.matchMedia("(min-width: 768px)").matches;
    if (isMd) {
      mount.classList.remove("hidden");
      mountCharts();
    }
  }

  function renderRankingPanel() {
    var tabsEl = document.getElementById("bi-cli-rank-tabs");
    var panel = document.getElementById("bi-cli-rank-panel");
    if (!tabsEl || !panel) return;
    var data = readJson("bi-cli-ranking-tabs-json") || {};
    if (!tabsEl.dataset.bound) {
      tabsEl.dataset.bound = "1";
      RANK_TABS.forEach(function (t, idx) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "bi-client-tab" + (idx === 0 ? " is-active" : "");
        b.setAttribute("data-rank-tab", t.key);
        b.textContent = t.label;
        b.addEventListener("click", function () {
          state.rankingTabKey = t.key;
          tabsEl.querySelectorAll(".bi-client-tab").forEach(function (x) {
            x.classList.toggle("is-active", x.getAttribute("data-rank-tab") === t.key);
          });
          renderRankingPanel();
        });
        tabsEl.appendChild(b);
      });
    }
    var rows = data[state.rankingTabKey] || [];
    var hint =
      state.rankingTabKey === "maior_pct"
        ? "<p class=\"employees-text-muted mb-2 text-xs\">Apenas clientes com entregue ≥ R$ 2.500 (evita distorção de microvolume).</p>"
        : state.rankingTabKey === "baixo_volume_pct"
          ? "<p class=\"employees-text-muted mb-2 text-xs\">Clientes abaixo do piso de volume com % alto — analisar com cautela; não comparar diretamente com grandes contas.</p>"
          : "";
    if (!rows.length) {
      panel.innerHTML = hint + "<p class=\"employees-text-muted text-sm\">Sem dados nesta aba para o recorte.</p>";
      return;
    }
    var h =
      hint +
      "<div class=\"sys-table-wrap sys-table-wrap--x-scroll\"><table class=\"sys-data-table text-xs\"><thead><tr>" +
      "<th>Cliente</th><th>Código</th><th class=\"text-right\">Entregue</th><th class=\"text-right\">Devolvido</th>" +
      "<th class=\"text-right\">% Dev.</th><th class=\"text-right\">Tempo médio</th><th>Classificação</th><th></th></tr></thead><tbody>";
    rows.forEach(function (r) {
      var cid = r.client_id != null ? String(r.client_id) : "";
      h +=
        "<tr><td class=\"max-w-[12rem] truncate font-medium\">" +
        escapeHtml(r.client_name || "—") +
        "</td><td>" +
        escapeHtml(r.client_code || "—") +
        "</td><td class=\"text-right tabular-nums\">" +
        fmtMoney(r.delivered_value) +
        "</td><td class=\"text-right tabular-nums\">" +
        fmtMoney(r.returned_value) +
        "</td><td class=\"text-right tabular-nums\">" +
        fmtPct(r.return_pct_planned) +
        "</td><td class=\"text-right\">" +
        fmtDur(r.avg_duration_m) +
        "</td><td class=\"max-w-[8rem] truncate\">" +
        escapeHtml(r.classification_title || "—") +
        "</td><td class=\"text-right\">" +
        (cid
          ? "<button type=\"button\" class=\"sys-btn sys-btn--secondary h-7 px-2 text-[11px]\" data-bi-cli-open=\"" +
            escapeHtml(cid) +
            "\">Detalhar</button>"
          : "") +
        "</td></tr>";
    });
    h += "</tbody></table></div>";
    panel.innerHTML = h;
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

    var prev = document.getElementById("bi-cli-prev");
    var next = document.getElementById("bi-cli-next");
    if (prev) {
      prev.onclick = function () {
        if (state.page > 1) {
          state.page--;
          renderTable();
        }
      };
    }
    if (next) {
      next.onclick = function () {
        var maxPage = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
        if (state.page < maxPage) {
          state.page++;
          renderTable();
        }
      };
    }

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
          "<p class=\"employees-text-muted py-6 text-center text-sm\">Nenhum cliente com impacto evitável neste recorte.</p>";
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
              "</p></div></div>" +
              (motivos
                ? "<ul class=\"mt-1 text-xs\">" + motivos + "</ul>"
                : "") +
              (hints
                ? "<ol class=\"mt-2 list-decimal pl-4 text-xs text-slate-700 dark:text-slate-300\">" + hints + "</ol>"
                : "") +
              (cid
                ? "<div class=\"mt-3\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-3 text-xs\" data-bi-cli-open=\"" +
                  escapeHtml(cid) +
                  "\">Abrir ficha</button></div>"
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

    function closeInsightModal() {
      var m = document.getElementById("bi-cli-insight-modal");
      if (!m) return;
      m.classList.add("hidden");
      m.setAttribute("aria-hidden", "true");
      var sub = document.getElementById("bi-cli-insight-sub");
      if (sub) {
        sub.textContent = "";
        sub.classList.add("hidden");
      }
    }

    function openInsightModal(title, html, subtext) {
      var m = document.getElementById("bi-cli-insight-modal");
      var t = document.getElementById("bi-cli-insight-title");
      var body = document.getElementById("bi-cli-insight-body");
      var sub = document.getElementById("bi-cli-insight-sub");
      if (!m || !t || !body) return;
      t.textContent = title || "Detalhe";
      body.innerHTML = html || "";
      if (sub) {
        if (subtext) {
          sub.textContent = subtext;
          sub.classList.remove("hidden");
        } else {
          sub.textContent = "";
          sub.classList.add("hidden");
        }
      }
      m.classList.remove("hidden");
      m.setAttribute("aria-hidden", "false");
    }

    function readJsonArray(id) {
      var v = readJson(id);
      return Array.isArray(v) ? v : [];
    }

    function renderOlLines(lines) {
      if (!lines || !lines.length) return "";
      return (
        "<ol class=\"mt-1 list-decimal space-y-1.5 pl-4 text-xs leading-snug text-slate-700 dark:text-slate-300\">" +
        lines
          .map(function (x) {
            return "<li>" + escapeHtml(x) + "</li>";
          })
          .join("") +
        "</ol>"
      );
    }

    function openCriticalListModal() {
      var rows = readJsonArray("bi-cli-critical-json");
      if (!rows.length) {
        openInsightModal("Clientes críticos", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum cliente crítico neste recorte.</p>", null);
        return;
      }
      var html = rows
        .map(function (row) {
          var cid = row.client_id != null ? String(row.client_id) : "";
          return (
            "<article class=\"mb-4 rounded-xl border border-red-200/60 bg-red-50/30 p-3 last:mb-0 dark:border-red-900/40 dark:bg-red-950/20\">" +
            "<div class=\"flex flex-wrap justify-between gap-2\">" +
            "<div class=\"min-w-0\"><p class=\"font-semibold leading-tight\">" +
            escapeHtml(row.client_name || "—") +
            "</p><p class=\"employees-text-muted mt-0.5 text-xs\">" +
            escapeHtml(row.client_code || "") +
            (row.vendedor_name ? " · " + escapeHtml(row.vendedor_name) : "") +
            "</p></div>" +
            "<div class=\"text-right text-xs\"><span class=\"font-semibold text-red-700 dark:text-red-300\">Risco " +
            escapeHtml(String(row.risk_score != null ? row.risk_score : "—")) +
            "</span></div></div>" +
            "<p class=\"mt-2 text-xs text-slate-600 dark:text-slate-400\">" +
            escapeHtml(row.classification_title || "") +
            " · % dev. " +
            Number(row.return_pct_planned || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) +
            "% · " +
            fmtMoney(row.returned_value) +
            "</p>" +
            "<p class=\"mt-2 text-xs font-semibold\">Contexto</p>" +
            renderOlLines(row.context || []) +
            "<p class=\"mt-2 text-xs font-semibold\">Sugestões</p>" +
            renderOlLines(row.hints || []) +
            (cid
              ? "<div class=\"mt-3\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-3 text-xs\" data-bi-cli-open=\"" +
                escapeHtml(cid) +
                "\">Abrir ficha</button></div>"
              : "") +
            "</article>"
          );
        })
        .join("");
      openInsightModal("Clientes críticos (" + rows.length + ")", html, null);
    }

    function openLargeRiskListModal() {
      var rows = readJsonArray("bi-cli-large-risk-json");
      if (!rows.length) {
        openInsightModal("Alto valor com risco", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum caso neste recorte.</p>", null);
        return;
      }
      var html = rows
        .map(function (row) {
          var cid = row.client_id != null ? String(row.client_id) : "";
          return (
            "<article class=\"mb-3 rounded-lg border border-amber-200/70 bg-amber-50/25 p-3 dark:border-amber-900/40 dark:bg-amber-950/15\">" +
            "<p class=\"font-semibold\">" +
            escapeHtml(row.client_name || "—") +
            "</p>" +
            "<p class=\"employees-text-muted text-xs\">" +
            escapeHtml(row.client_code || "") +
            " · % dev. " +
            Number(row.return_pct_planned || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) +
            "% · " +
            fmtMoney(row.returned_value) +
            "</p>" +
            renderOlLines(row.context || []) +
            (cid
              ? "<div class=\"mt-2\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-3 text-xs\" data-bi-cli-open=\"" +
                escapeHtml(cid) +
                "\">Abrir ficha</button></div>"
              : "") +
            "</article>"
          );
        })
        .join("");
      openInsightModal("Alto valor com risco (" + rows.length + ")", html, null);
    }

    function openSmallHighListModal() {
      var rows = readJsonArray("bi-cli-small-high-json");
      if (!rows.length) {
        openInsightModal("Pequeno cliente, grande impacto", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum caso neste recorte.</p>", null);
        return;
      }
      var html = rows
        .map(function (row) {
          var cid = row.client_id != null ? String(row.client_id) : "";
          return (
            "<article class=\"mb-3 rounded-lg border border-violet-200/70 bg-violet-50/20 p-3 dark:border-violet-900/35 dark:bg-violet-950/15\">" +
            "<p class=\"font-semibold\">" +
            escapeHtml(row.client_name || "—") +
            "</p>" +
            "<p class=\"employees-text-muted text-xs\">Impacto " +
            Number(row.operational_impact || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) +
            " · tempo médio " +
            fmtDur(row.avg_duration_m) +
            "</p>" +
            renderOlLines(row.hints || row.context || []) +
            (cid
              ? "<div class=\"mt-2\"><button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 px-3 text-xs\" data-bi-cli-open=\"" +
                escapeHtml(cid) +
                "\">Abrir ficha</button></div>"
              : "") +
            "</article>"
          );
        })
        .join("");
      openInsightModal("Pequeno cliente, grande impacto", html, null);
    }

    function openGoodListModal() {
      var rows = readJsonArray("bi-cli-good-json");
      if (!rows.length) {
        openInsightModal("Clientes bons", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum cliente neste perfil.</p>", null);
        return;
      }
      var html = rows
        .map(function (row) {
          var cid = row.client_id != null ? String(row.client_id) : "";
          return (
            "<article class=\"mb-3 flex flex-wrap items-start justify-between gap-2 rounded-lg border border-emerald-200/60 bg-emerald-50/25 px-3 py-2 dark:border-emerald-900/35 dark:bg-emerald-950/15\">" +
            "<div class=\"min-w-0 flex-1\">" +
            "<p class=\"font-medium leading-tight\">" +
            escapeHtml(row.client_name || "—") +
            "</p>" +
            "<p class=\"employees-text-muted mt-0.5 text-xs\">" +
            escapeHtml(row.summary || "") +
            "</p></div>" +
            (cid
              ? "<button type=\"button\" class=\"sys-btn sys-btn--secondary h-8 shrink-0 px-2 text-xs\" data-bi-cli-open=\"" +
                escapeHtml(cid) +
                "\">Ficha</button>"
              : "") +
            "</article>"
          );
        })
        .join("");
      openInsightModal("Melhores clientes (lista)", html, null);
    }

    document.querySelectorAll("[data-bi-cli-insight-close]").forEach(function (b) {
      b.addEventListener("click", closeInsightModal);
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      var ins = document.getElementById("bi-cli-insight-modal");
      if (ins && !ins.classList.contains("hidden")) {
        closeInsightModal();
        return;
      }
      var modal = document.getElementById("bi-cli-treatable-modal");
      if (modal && !modal.classList.contains("hidden")) closeTreatableModal();
    });

    document.querySelectorAll(".js-bi-cli-action").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var act = btn.getAttribute("data-action");
        if (act === "critical") openCriticalListModal();
        else if (act === "large_risk") openLargeRiskListModal();
        else if (act === "small_high") openSmallHighListModal();
        else if (act === "treatable") openTreatableModal();
      });
    });

    var kpiCrit = document.getElementById("bi-cli-kpi-critical-open");
    if (kpiCrit) {
      kpiCrit.addEventListener("click", openCriticalListModal);
      kpiCrit.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openCriticalListModal();
        }
      });
    }
    var kpiGood = document.getElementById("bi-cli-kpi-good-open");
    if (kpiGood) {
      kpiGood.addEventListener("click", openGoodListModal);
      kpiGood.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openGoodListModal();
        }
      });
    }

    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-bi-cli-open]");
      if (!el) return;
      var treat = document.getElementById("bi-cli-treatable-modal");
      if (treat && !treat.classList.contains("hidden") && treat.contains(el)) closeTreatableModal();
      var ins = document.getElementById("bi-cli-insight-modal");
      if (ins && !ins.classList.contains("hidden") && ins.contains(el)) closeInsightModal();
      var cid = el.getAttribute("data-bi-cli-open");
      openDrawer(cid);
    });

    var chartsBtn = document.getElementById("bi-cli-charts-load-btn");
    var chartsMount = document.getElementById("bi-cli-charts-mount");
    if (chartsBtn && chartsMount) {
      chartsBtn.addEventListener("click", function () {
        chartsMount.classList.remove("hidden");
        chartsBtn.classList.add("hidden");
        mountCharts();
      });
    }

    renderRankingPanel();
    renderTable();
    initChartsIfNeeded();

    if (typeof window.matchMedia !== "undefined") {
      window.matchMedia("(min-width: 768px)").addEventListener("change", function (ev) {
        if (ev.matches && chartsMount && !chartsMount.classList.contains("hidden")) mountCharts();
      });
    }
  }

  window.BiClientesPage = { boot: boot };
})();
