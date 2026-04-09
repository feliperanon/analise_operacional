(() => {
  const byId = (id) => document.getElementById(id);
  const qs = (s) => document.querySelector(s);
  const qsa = (s) => Array.from(document.querySelectorAll(s));
  const state = window.__biState;
  const renderDrill = window.__biRenderDrill;

  if (!state || !renderDrill || typeof Chart === 'undefined') return;

  const chartIds = ["trendChart", "motivosChart", "respChart", "clusterChart", "driverChart", "driverRespChart", "driverClientCorrChart", "diaSemanaChart"];
  const chartTitles = {
    trendChart: "Tendência diária",
    diaSemanaChart: "Dia da semana × Devoluções",
    motivosChart: "Motivos de devolução",
    respChart: "Responsabilidade",
    clusterChart: "Cluster x Valor",
    driverChart: "Eficiência por motorista",
    driverRespChart: "Motorista x Responsabilidade x Valor",
    driverClientCorrChart: "Correlação motorista x cliente x devoluções"
  };
  const chartAllowedTypes = {
    trendChart: ["line", "bar"],
    diaSemanaChart: ["bar", "line"],
    motivosChart: ["bar", "doughnut"],
    respChart: ["doughnut", "bar"],
    clusterChart: ["bar", "doughnut"],
    driverChart: ["bar", "line"],
    driverRespChart: ["bar", "line"],
    driverClientCorrChart: ["bubble", "scatter"]
  };

  const kpiDefs = {
    "Paradas Planejadas": ["Volume previsto de paradas no período.", "Σ rotas planejadas", ">=95% realização"],
    "Paradas Entregues": ["Paradas concluídas no período.", "Σ concluídas ÷ Σ planejadas", "SLA >= 90%"],
    "Taxa Devolução": ["Legado: taxa sobre paradas planejadas.", "(devoluções ÷ planejadas) x 100", "Ver também % rotas"],
    "Taxa Devolucao": ["Legado: taxa sobre paradas planejadas.", "(devoluções ÷ planejadas) x 100", "Ver também % rotas"],
    "Devolução % (rotas)": [
      "Indicador operacional oficial (Central, TV, informativo).",
      "(rotas devolução ÷ rotas concluídas: entregue + devolução) × 100; exclui encerramento tardio automático como devolução",
      "Meta operacional ≤ 2%",
    ],
    "Valor Devolvido": ["Impacto financeiro das devoluções.", "Σ valor devolvido", "Tendência de queda"],
    "Devolução % Valor": ["Percentual financeiro devolvido sobre o valor planejado.", "(valor devolvido ÷ valor planejado) x 100", "< 2%"],
    "% Acima de R$300": ["Risco financeiro por ticket alto.", "(devoluções>=300 ÷ total) x 100", "< 35%"],
    "Tempo Médio": ["Agilidade de conclusão de rotas.", "Média de duração das rotas", "< 120 min"],
    "Risco Próx. Turno": ["Risco preditivo operacional.", "Sinal derivado de tendência + anomalias", "Controlado"]
    ,"Risco Prox. Turno": ["Risco preditivo operacional.", "Sinal derivado de tendência + anomalias", "Controlado"]
  };

  let fullscreenChart = null;
  let fullscreenChartId = null;
  let compareWindow = null;
  let kpiSparklineChart = null;
  let respMotivosChart = null;
  let fullscreenIndex = 0;
  let execModeMemory = false;

  function modalOpen(id) {
    const m = byId(id);
    if (!m) return;
    m.classList.remove("hidden");
    m.classList.add("flex");
    m.setAttribute("aria-hidden", "false");
  }

  function modalClose(id) {
    const m = byId(id);
    if (!m) return;
    m.classList.add("hidden");
    m.classList.remove("flex");
    m.setAttribute("aria-hidden", "true");
    if (id === "chartFullscreenModal") {
      destroyFullscreenChart();
      fullscreenChartId = null;
      compareWindow = null;
    }
    if (id === "respMotivosModal" && respMotivosChart) {
      respMotivosChart.destroy();
      respMotivosChart = null;
    }
  }

  function getChart(id) {
    const canvas = byId(id);
    if (!canvas) return null;
    return Chart.getChart(canvas);
  }

  function toNum(v) {
    if (typeof v === "number") return v;
    const s = String(v ?? "").replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", ".");
    return Number(s) || 0;
  }

  function sparklineSeries(title) {
    const trend = window.__biChartData?.trend || { valor: [], qtd: [] };
    if (title === "Valor Devolvido") return trend.valor || [];
    if (title === "Taxa Devolução" || title === "Taxa Devolucao" || title === "Devolução % (rotas)") return trend.qtd || [];
    if (title === "Devolução % Valor") return trend.valor || [];
    return trend.valor || trend.qtd || [];
  }

  function createSparkline(series) {
    const canvas = byId("kpiSparkline");
    if (!canvas) return;
    if (kpiSparklineChart) kpiSparklineChart.destroy();
    kpiSparklineChart = new Chart(canvas, {
      type: "line",
      data: { labels: series.map((_, i) => i + 1), datasets: [{ data: series, borderColor: "#3b82f6", pointRadius: 0, tension: 0.3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } }
    });
  }

  function buildKpiTrend(series) {
    if (!series || series.length < 2) return "Sem histórico suficiente.";
    const a = Number(series.at(-1) || 0);
    const b = Number(series.at(-2) || 0);
    if (!b) return a ? "Sinal inicial de tendência de alta." : "Sem oscilação relevante.";
    const d = ((a - b) / Math.abs(b)) * 100;
    const s = d >= 0 ? "alta" : "queda";
    return `Último período indica ${s} de ${Math.abs(d).toFixed(1)}%.`;
  }

  function openKpiModal(card) {
    const title = card.dataset.kpiTitle || "KPI";
    const value = card.dataset.kpiValue || "-";
    const [meaning, formula, benchmark] = kpiDefs[title] || ["Indicador estratégico.", "Cálculo interno", "Meta interna"];
    byId("kpiModalTitle").textContent = title;
    byId("kpiModalTag").textContent = `Valor atual: ${value}`;
    byId("kpiMeaning").textContent = meaning;
    byId("kpiFormula").textContent = formula;
    byId("kpiBenchmark").textContent = benchmark;
    const series = sparklineSeries(title);
    byId("kpiTrend").textContent = buildKpiTrend(series);
    createSparkline(series);

    const alerts = [];
    if ((title === "Taxa Devolução" || title === "Taxa Devolucao") && toNum(value) >= 10) alerts.push("Taxa sobre planejadas acima do limite recomendado (indicador auxiliar).");
    if (title === "Devolução % (rotas)" && toNum(value) >= 2) alerts.push("Percentual operacional acima da meta de 2% (rotas concluídas).");
    if (title === "Devolução % Valor" && toNum(value) >= 2) alerts.push("Percentual de devolução em valor acima da meta de 2%.");
    if (title === "Tempo Médio" && toNum(value) >= 120) alerts.push("Tempo médio acima da janela executiva.");
    if (!alerts.length) alerts.push("Sem alertas críticos para este indicador.");
    byId("kpiAlerts").innerHTML = alerts.map((x) => `<div class="insight-row insight-warning">${x}</div>`).join("");

    modalOpen("kpiDetailModal");
  }

  function clipData(data, n) {
    if (!n) return data;
    return {
      labels: (data.labels || []).slice(-n),
      datasets: (data.datasets || []).map((ds) => ({ ...ds, data: (ds.data || []).slice(-n) }))
    };
  }

  function cloneChartData(data) {
    const out = JSON.parse(JSON.stringify(data || { labels: [], datasets: [] }));
    if (out.labels && Array.isArray(out.labels)) {
      out.labels = out.labels.map(v => (v == null || typeof v === 'object' ? "" : String(v)));
    }
    if (out.datasets && Array.isArray(out.datasets)) {
      out.datasets = out.datasets.map(ds => {
        const d = { ...ds };
        if (d.label != null) d.label = String(d.label);
        if (Array.isArray(d.data)) {
          d.data = d.data.map((v) => {
            if (v == null) return null;
            if (typeof v === "number") return v;
            if (typeof v === "object") return { ...v };
            return Number(v) || 0;
          });
        }
        if (d.borderColor) d.borderColor = String(d.borderColor);
        if (d.backgroundColor && typeof d.backgroundColor === 'string') d.backgroundColor = String(d.backgroundColor);
        return d;
      });
    }
    return out;
  }

  function buildTrendPercentSeries(data) {
    const labels = Array.isArray(data?.labels) ? data.labels : [];
    const ds = Array.isArray(data?.datasets) ? data.datasets : [];
    if (!labels.length || !ds.length) return [];

    const valorDs = ds.find((d) => String(d?.label || "").toLowerCase().includes("valor devolvido")) || ds[1] || ds[0];
    const metaDs = ds.find((d) => String(d?.label || "").toLowerCase().includes("meta 2%"));
    const valor = Array.isArray(valorDs?.data) ? valorDs.data.map((v) => Number(v) || 0) : [];
    const meta2pct = Array.isArray(metaDs?.data) ? metaDs.data.map((v) => Number(v) || 0) : [];
    if (!valor.length || !meta2pct.length || valor.length !== labels.length || meta2pct.length !== labels.length) return [];

    const pctSeries = valor.map((v, i) => {
      const m2 = Number(meta2pct[i] || 0);
      if (m2 <= 0) return null;
      // meta_2pct = 2% do valor planejado => pct_real = (valor_devolvido / valor_planejado) * 100
      return Number(((v * 2) / m2).toFixed(3));
    });
    return [{
      type: "line",
      label: "% Devolução (valor)",
      data: pctSeries,
      borderColor: "#a855f7",
      backgroundColor: "transparent",
      borderDash: [6, 4],
      borderWidth: 2.5,
      tension: 0.35,
      yAxisID: "y2",
      pointRadius: 5,
      pointHoverRadius: 8,
      pointBackgroundColor: "#a855f7",
      pointBorderColor: "#c4b5fd",
      pointBorderWidth: 1.5,
      pointStyle: "circle",
      spanGaps: true
    }];
  }

  function enrichFullscreenData(chartId, data) {
    const out = cloneChartData(data || { labels: [], datasets: [] });
    if (chartId !== "trendChart") return out;
    const pctDataset = buildTrendPercentSeries(out);
    if (pctDataset.length) {
      out.datasets = (out.datasets || []).filter((d) => !String(d?.label || "").toLowerCase().includes("% devolucao (valor)"));
      out.datasets.push(...pctDataset);
    }
    return out;
  }

  function normalizeDataForType(type, data) {
    const out = cloneChartData(data || { labels: [], datasets: [] });
    const isCartesian = type !== "doughnut" && type !== "pie" && type !== "polarArea";
    if (!Array.isArray(out.datasets)) return out;
    out.datasets = out.datasets.map((ds) => {
      const d = { ...ds };
      if (!isCartesian) {
        delete d.yAxisID;
        delete d.xAxisID;
        delete d.stack;
      }
      if (Array.isArray(d.data)) {
        if (type === "bubble" || type === "scatter") {
          d.data = d.data.map((v) => {
            if (!v || typeof v !== "object") return { x: 0, y: 0, r: 4 };
            return {
              ...v,
              x: Number(v.x || 0),
              y: Number(v.y || 0),
              r: Number(v.r || 4)
            };
          });
        } else {
          d.data = d.data.map((v) => (v == null ? null : Number(v) || 0));
        }
      }
      return d;
    });
    return out;
  }

  function buildFullscreenOptions(type, data) {
    const isCartesian = type !== "doughnut" && type !== "pie" && type !== "polarArea";
    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: {
          labels: {
            color: "#94a3b8",
            font: { size: 12 },
            padding: 16,
            usePointStyle: true
          }
        },
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(15, 23, 42, 0.95)",
          titleColor: "#f1f5f9",
          bodyColor: "#cbd5e1",
          borderColor: "rgba(148, 163, 184, 0.3)",
          borderWidth: 1,
          padding: 12,
          displayColors: true,
          boxPadding: 6
        }
      }
    };
    if (isCartesian) {
      const ds = (data && data.datasets) || [];
      const needsY1 = ds.some(function (d) { return d.yAxisID === "y1"; });
      const needsY2 = ds.some(function (d) { return d.yAxisID === "y2"; });
      options.scales = {
        x: { display: true, ticks: { color: "#94a3b8", maxRotation: 45 }, grid: { color: "rgba(148,163,184,0.2)" } },
        y: { display: true, position: "left", ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.2)" } }
      };
      if (needsY1) {
        options.scales.y1 = { display: true, position: "right", ticks: { color: "#94a3b8" }, grid: { display: false } };
      }
      if (needsY2) {
        options.scales.y2 = {
          display: true,
          position: "right",
          offset: true,
          ticks: {
            color: "#a855f7",
            callback: function (value) { return `${Number(value || 0).toFixed(1).replace(".", ",")}%`; }
          },
          grid: { display: false },
          title: { display: true, text: "% Devolução", color: "#a855f7" }
        };
      }
      options.plugins.tooltip.callbacks = {
        label: function (ctx) {
          const label = ctx?.dataset?.label || "";
          const raw = Number(ctx?.raw || 0);
          if (ctx?.dataset?.yAxisID === "y2") {
            return `${label}: ${raw.toFixed(2).replace(".", ",")}%`;
          }
          if (String(label).toLowerCase().includes("valor") || ctx?.dataset?.yAxisID === "y1") {
            return `${label}: ${raw.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`;
          }
          return `${label}: ${raw.toLocaleString("pt-BR")}`;
        }
      };
    }
    return options;
  }

  function generateInsightsFromDataset(chartId, data) {
    const out = [];
    const labels = data?.labels || [];
    const ds = data?.datasets || [];
    const fmtMoeda = (v) => (v != null && Number.isFinite(Number(v))) ? Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "—";
    const fmtPct = (v) => (v != null && Number.isFinite(Number(v))) ? `${Number(v).toFixed(1).replace(".", ",")}%` : "—";
    if (!ds.length) return ["Sem dados suficientes para gerar insights."];
    if (chartId === "diaSemanaChart") {
      const qtd = (ds[0]?.data || []).map(Number);
      const valor = (ds[1]?.data || []).map(Number);
      const sumQtd = qtd.reduce((a, b) => a + b, 0);
      const sumValor = valor.reduce((a, b) => a + b, 0);
      if (labels.length && (sumQtd > 0 || sumValor > 0)) {
        const iMax = qtd.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0);
        out.push(`Total: ${sumQtd} devoluções e ${fmtMoeda(sumValor)} no período.`);
        out.push(`Dia com mais devoluções: ${labels[iMax] || "-"} (${qtd[iMax] || 0} un).`);
      } else {
        out.push("Sem devoluções no período.");
      }
    } else if (chartId === "trendChart") {
      const values = ds[1]?.data || ds[0]?.data || [];
      const recent = values.slice(-7).reduce((a, b) => a + Number(b || 0), 0);
      const prev = values.slice(-14, -7).reduce((a, b) => a + Number(b || 0), 0);
      if (Math.abs(prev) < 0.0001) {
        out.push("Últimos 7 dias sem base anterior para comparação.");
      } else {
        const delta = ((recent - prev) / Math.abs(prev)) * 100;
        out.push(`Últimos 7 dias: ${delta >= 0 ? "alta" : "queda"} de ${Math.abs(delta).toFixed(1)}% em relação à semana anterior.`);
      }
      const p = values.reduce((best, v, i, arr) => Number(v || 0) > Number(arr[best] || 0) ? i : best, 0);
      const labelP = labels[p] != null ? String(labels[p]) : "";
      out.push(`Pico no período em ${labelP}: ${Number(values[p] || 0).toLocaleString("pt-BR")}.`);
    } else if (chartId === "motivosChart") {
      const md = (window.__biChartData?.motivos_detailed || []);
      if (!md.length) return ["Sem dados suficientes para gerar insights."];
      const totalQtd = md.reduce((a, m) => a + (m.qtd || 0), 0) || 1;
      const totalValor = md.reduce((a, m) => a + (m.valor || 0), 0) || 1;
      const topQtd = md.reduce((best, m, i, arr) => (m.qtd || 0) > (arr[best]?.qtd || 0) ? i : best, 0);
      const topValor = md.reduce((best, m, i, arr) => (m.valor || 0) > (arr[best]?.valor || 0) ? i : best, 0);
      out.push(`${md[topQtd]?.motivo || "Motivo"} lidera em quantidade com ${(((md[topQtd]?.qtd || 0) / totalQtd) * 100).toFixed(1).replace(".", ",")}% das ocorrências.`);
      out.push(`${md[topValor]?.motivo || "Motivo"} concentra ${(((md[topValor]?.valor || 0) / totalValor) * 100).toFixed(1).replace(".", ",")}% do valor devolvido.`);
    } else if (chartId === "driverClientCorrChart") {
      const points = (ds[0]?.data || []).filter((p) => p && typeof p === "object");
      if (!points.length) return ["Sem dados suficientes para gerar insights."];
      const topValor = points.reduce((best, p, i, arr) => Number(p.valor || 0) > Number(arr[best]?.valor || 0) ? i : best, 0);
      const topPct = points.reduce((best, p, i, arr) => Number(p.pct_valor_real || 0) > Number(arr[best]?.pct_valor_real || 0) ? i : best, 0);
      const a = points[topValor];
      const b = points[topPct];
      out.push(`Maior impacto financeiro: ${a.driver || "-"} x ${a.client || "-"} com ${fmtMoeda(a.valor)}.`);
      out.push(`Maior risco (% valor): ${b.driver || "-"} x ${b.client || "-"} com ${fmtPct(b.pct_valor_real)}.`);
    } else if (chartId === "driverChart") {
      const eff = (ds[0]?.data || []).map(Number);
      const devValor = (ds[2]?.data || ds[1]?.data || []).map(Number);
      if (!labels.length) return ["Sem dados suficientes para gerar insights."];
      const iBestEff = eff.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0);
      const iWorstDev = devValor.length ? devValor.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0) : -1;
      out.push(`Maior eficiência: ${labels[iBestEff] || "-"} com ${fmtPct(eff[iBestEff])}.`);
      if (iWorstDev >= 0 && devValor[iWorstDev] > 0) {
        out.push(`Maior taxa de devolução em valor: ${labels[iWorstDev] || "-"} com ${fmtPct(devValor[iWorstDev])} (meta ≤ 2%).`);
      }
    } else if (chartId === "respChart" || chartId === "clusterChart") {
      const values = (ds[0]?.data || []).map(Number);
      const sum = values.reduce((a, b) => a + b, 0) || 1;
      const top = values.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0);
      const labelStr = labels[top] != null ? String(labels[top]) : "";
      const pct = ((values[top] / sum) * 100).toFixed(1).replace(".", ",");
      out.push(`${labelStr} concentra ${pct}% do valor total devolvido.`);
    } else if (chartId === "driverRespChart") {
      const dr = (window.__biChartData?.driver_resp_valor || {});
      const drivers = dr.drivers || labels || [];
      const datasets = dr.datasets || ds;
      if (!datasets.length || !drivers.length) return ["Sem dados suficientes para gerar insights."];
      const totalPorDriver = drivers.map((_, i) =>
        datasets.reduce((s, d) => s + Number((d.data || [])[i] || 0), 0)
      );
      const topIdx = totalPorDriver.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0);
      out.push(`Maior valor devolvido: ${drivers[topIdx] || "-"} com ${fmtMoeda(totalPorDriver[topIdx])}.`);
    } else {
      const values = (ds[0]?.data || []).map(Number);
      const sum = values.reduce((a, b) => a + b, 0) || 1;
      if (sum <= 0) return ["Sem dados numéricos para gerar insights."];
      const top = values.reduce((best, v, i, arr) => v > (arr[best] || 0) ? i : best, 0);
      const labelStr = labels[top] != null ? String(labels[top]) : "";
      const pct = ((values[top] / sum) * 100).toFixed(1).replace(".", ",");
      out.push(`${labelStr} concentra ${pct}% do valor total.`);
    }
    return out;
  }

  function bindChartClickDrill(id) {
    const canvas = byId(id);
    if (!canvas) return;
    const c = getChart(id);
    if (!c) return;
    canvas.addEventListener("click", (evt) => {
      const elements = c.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false);
      if (!elements?.length) return;
      const idx = elements[0].index;
      const datasetIdx = elements[0].datasetIndex || 0;
      const point = c.data?.datasets?.[datasetIdx]?.data?.[idx];
      const label = id === "motivosChart"
        ? ((point && typeof point === "object" && point.motivo) ? point.motivo : c.data.labels?.[idx])
        : c.data.labels?.[idx];
      let fn = null;
      let crumbLabel = label;
      if (id !== "driverClientCorrChart" && label == null) return;
      if (id === "trendChart") fn = (r) => r.date === label;
      if (id === "motivosChart") fn = (r) => r.motivo === String(label);
      if (id === "respChart") fn = (r) => r.responsabilidade === label;
      if (id === "clusterChart") fn = (r) => r.cluster === label;
      if (id === "driverChart") fn = (r) => r.driver_name === label;
      if (id === "driverRespChart") fn = (r) => r.driver_name === label;
      if (id === "driverClientCorrChart" && point && typeof point === "object") {
        const driver = String(point.driver || "").trim();
        const client = String(point.client || "").trim();
        fn = (r) =>
          String(r.driver_name || "").trim() === driver &&
          String(r.client_name || "").trim() === client;
        crumbLabel = `${driver} x ${client}`;
      }
      if (!fn) return;
      if (id === "respChart") openResponsibilityMotivosModal(label);
      state.drillStack.push({ label: `${chartTitles[id]}: ${crumbLabel}`, fn });
      state.externalFilter = fn;
      state.page = 1;
      renderDrill();
      refreshBreadcrumb();
      byId("drilldown-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function destroyFullscreenChart() {
    try {
      if (fullscreenChart) {
        fullscreenChart.destroy();
        fullscreenChart = null;
      }
      const canvas = byId("fullscreenChartCanvas");
      if (canvas) {
        const existing = Chart.getChart(canvas);
        if (existing) existing.destroy();
      }
    } catch (e) { /* ignore */ }
  }

  function toAmount(v) {
    if (typeof v === "number") return v;
    const n = Number(String(v ?? "").replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", "."));
    return Number.isFinite(n) ? n : 0;
  }

  function aggregateClientsByResponsibility(responsabilidade) {
    const rows = (state?.rows || []).filter((r) => String(r?.responsabilidade || "").trim() === String(responsabilidade || "").trim());
    const acc = new Map();
    rows.forEach((r) => {
      const client = String(r?.client_name || "Sem cliente").trim() || "Sem cliente";
      const item = acc.get(client) || { qtd: 0, valor: 0 };
      item.qtd += 1;
      item.valor += toAmount(r?.returned_value);
      acc.set(client, item);
    });
    const totalValor = Array.from(acc.values()).reduce((sum, x) => sum + x.valor, 0) || 1;
    return Array.from(acc.entries())
      .map(([client, x]) => ({
        client,
        qtd: x.qtd,
        valor: x.valor,
        pctValor: (x.valor / totalValor) * 100
      }))
      .sort((a, b) => b.valor - a.valor);
  }

  function renderResponsibilityClientsList(responsabilidade) {
    const wrap = byId("respClientsList");
    if (!wrap) return;
    const ranked = aggregateClientsByResponsibility(responsabilidade).slice(0, 12);
    if (!ranked.length) {
      wrap.innerHTML = `<div class="insight-row">Sem clientes para ${responsabilidade}.</div>`;
      return;
    }
    wrap.innerHTML = ranked.map((r) => {
      const pct = Number(r.pctValor || 0).toFixed(1).replace(".", ",");
      return `<div class="insight-row">${r.qtd} - ${r.client} - ${pct}% do valor</div>`;
    }).join("");
  }

  function openResponsibilityMotivosModal(responsabilidade) {
    const canvas = byId("respMotivosCanvas");
    if (!canvas) return;
    const rows = (state?.rows || []).filter((r) => String(r?.responsabilidade || "").trim() === String(responsabilidade || "").trim());
    const acc = new Map();
    rows.forEach((r) => {
      const motivo = String(r?.motivo || "Sem motivo").trim() || "Sem motivo";
      const item = acc.get(motivo) || { qtd: 0, valor: 0 };
      item.qtd += 1;
      item.valor += toAmount(r?.returned_value);
      acc.set(motivo, item);
    });

    const motivos = Array.from(acc.entries())
      .map(([motivo, v]) => ({ motivo, qtd: v.qtd, valor: v.valor }))
      .sort((a, b) => b.valor - a.valor)
      .slice(0, 12);

    byId("respMotivosTitle").textContent = `Motivos de devolucao | ${responsabilidade}`;

    if (respMotivosChart) {
      respMotivosChart.destroy();
      respMotivosChart = null;
    }
    respMotivosChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: motivos.map((m) => String(m.motivo ?? "")),
        datasets: [
          {
            label: "Quantidade",
            data: motivos.map((m) => m.qtd),
            backgroundColor: "rgba(245, 158, 11, 0.65)",
            borderColor: "#f59e0b",
            borderWidth: 1,
            yAxisID: "y"
          },
          {
            label: "Valor devolvido (R$)",
            data: motivos.map((m) => m.valor),
            backgroundColor: "rgba(239, 68, 68, 0.55)",
            borderColor: "#ef4444",
            borderWidth: 1,
            yAxisID: "y1"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#94a3b8" } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const label = ctx.dataset.label || "";
                const val = Number(ctx.raw || 0);
                if (ctx.dataset.yAxisID === "y1") {
                  return `${label}: ${val.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`;
                }
                return `${label}: ${val.toLocaleString("pt-BR")}`;
              }
            }
          }
        },
        scales: {
          x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.2)" } },
          y: { position: "left", ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.2)" }, title: { display: true, text: "Quantidade", color: "#94a3b8" } },
          y1: { position: "right", ticks: { color: "#94a3b8" }, grid: { drawOnChartArea: false }, title: { display: true, text: "Valor (R$)", color: "#94a3b8" } }
        }
      }
    });
    renderResponsibilityClientsList(responsabilidade);
    modalOpen("respMotivosModal");
  }

  function populateFullscreenDevolucaoStrip() {
    const k = window.__biChartData?.kpis;
    if (!k) return;
    const fmtMoeda = (v) => (v != null && Number.isFinite(Number(v))) ? Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "—";
    const fmtPct = (v) => (v != null && Number.isFinite(Number(v))) ? `${Number(v).toFixed(2)}%` : "—";
    byId("fullscreenPctValor").textContent = fmtPct(k.return_rate_value);
    byId("fullscreenValorDevolvido").textContent = fmtMoeda(k.valor_total_devolvido);
    byId("fullscreenQtdDevolucoes").textContent = (k.total_devolucoes != null && Number.isInteger(Number(k.total_devolucoes))) ? String(k.total_devolucoes) : "—";
    const mesAnt = [];
    if (k.devolucao_mes_anterior_qtd != null && Number.isInteger(Number(k.devolucao_mes_anterior_qtd))) mesAnt.push(`${k.devolucao_mes_anterior_qtd} un`);
    if (k.devolucao_mes_anterior_valor != null && Number.isFinite(Number(k.devolucao_mes_anterior_valor))) mesAnt.push(fmtMoeda(k.devolucao_mes_anterior_valor));
    byId("fullscreenDevolucaoMesAnt").textContent = mesAnt.length ? mesAnt.join(" · ") : "—";
  }

  function openChartFullscreen(chartId) {
    const src = getChart(chartId);
    if (!src) return;
    fullscreenChartId = chartId;
    fullscreenIndex = Math.max(0, chartIds.indexOf(chartId));
    const allowed = chartAllowedTypes[chartId] || [src.config.type];
    const currentType = src.config.type;
    byId("fullChartTitle").textContent = chartTitles[chartId] || "Gráfico";
    byId("fullChartTag").textContent = "Use setas para navegar entre gráficos.";
    destroyFullscreenChart();
    const clipped = normalizeDataForType(currentType, enrichFullscreenData(chartId, clipData(src.data, compareWindow)));
    const opts = buildFullscreenOptions(currentType, clipped);
    try {
      fullscreenChart = new Chart(byId("fullscreenChartCanvas"), {
        type: currentType,
        data: clipped,
        options: opts
      });
    } catch (err) {
      console.warn("BI fullscreen chart error:", err);
      byId("fullscreenInsights").innerHTML = "<div class=\"insight-row insight-warning\">Não foi possível exibir o gráfico expandido. Tente outro gráfico.</div>";
    }
    byId("chartTypeToggleBtn").dataset.allowed = JSON.stringify(allowed);
    byId("chartTypeToggleBtn").dataset.current = currentType;
    const insights = generateInsightsFromDataset(chartId, clipped);
    if (fullscreenChart) byId("fullscreenInsights").innerHTML = insights.map((x) => `<div class="insight-row">${x}</div>`).join("");
    populateFullscreenDevolucaoStrip();
    modalOpen("chartFullscreenModal");
  }

  function toggleExecutiveMode(force) {
    const page = qs(".bi-page");
    const btn = byId("execModeToggle");
    if (!page || !btn) return;
    const next = typeof force === "boolean" ? force : !page.classList.contains("executive-mode");
    page.classList.toggle("executive-mode", next);
    btn.textContent = next ? "Operacional" : "Executivo";
    btn.setAttribute("aria-pressed", next ? "true" : "false");
    execModeMemory = !!next;
  }

  function refreshBreadcrumb() {
    const wrap = byId("drillBreadcrumb");
    const back = byId("drillBackBtn");
    if (!wrap || !back) return;
    if (!state.drillStack.length) {
      wrap.classList.add("hidden");
      back.classList.add("hidden");
      wrap.innerHTML = "";
      return;
    }
    wrap.classList.remove("hidden");
    back.classList.remove("hidden");
    wrap.innerHTML = state.drillStack.map((x, i) => `<span class="crumb">${i + 1}. ${x.label}</span>`).join('<span class="crumb-sep">›</span>');
  }

  byId("drillBackBtn")?.addEventListener("click", () => {
    state.drillStack.pop();
    state.externalFilter = state.drillStack.length ? state.drillStack[state.drillStack.length - 1].fn : null;
    state.page = 1;
    renderDrill();
    refreshBreadcrumb();
  });

  byId("execModeToggle")?.addEventListener("click", () => toggleExecutiveMode());
  toggleExecutiveMode(execModeMemory);

  qsa(".kpi-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e?.target?.closest('button[title="Ajuda"]')) return;
      openKpiModal(card);
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openKpiModal(card);
      }
    });
  });

  qsa("[data-chart-expand]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openChartFullscreen(btn.dataset.chartExpand);
    });
  });
  qsa(".chart-card canvas").forEach((canvas) => canvas.addEventListener("dblclick", () => openChartFullscreen(canvas.id)));

  qsa("[data-close-modal]").forEach((btn) => btn.addEventListener("click", () => modalClose(btn.dataset.closeModal)));
  byId("kpiDetailModal")?.addEventListener("click", (e) => { if (e.target.id === "kpiDetailModal") modalClose("kpiDetailModal"); });
  byId("chartFullscreenModal")?.addEventListener("click", (e) => { if (e.target.id === "chartFullscreenModal") modalClose("chartFullscreenModal"); });
  byId("respMotivosModal")?.addEventListener("click", (e) => { if (e.target.id === "respMotivosModal") modalClose("respMotivosModal"); });

  byId("chartTypeToggleBtn")?.addEventListener("click", () => {
    if (!fullscreenChartId) return;
    const src = getChart(fullscreenChartId);
    if (!src) return;
    const allowed = JSON.parse(byId("chartTypeToggleBtn").dataset.allowed || "[]");
    const current = byId("chartTypeToggleBtn").dataset.current;
    const idx = allowed.indexOf(current);
    const next = allowed[(idx + 1) % allowed.length] || current;
    byId("chartTypeToggleBtn").dataset.current = next;
    const clipped = normalizeDataForType(next, clipData(src.data, compareWindow));
    const enriched = enrichFullscreenData(fullscreenChartId, clipped);
    destroyFullscreenChart();
    fullscreenChart = new Chart(byId("fullscreenChartCanvas"), { type: next, data: enriched, options: buildFullscreenOptions(next, enriched) });
  });

  byId("chartCompare7Btn")?.addEventListener("click", () => { compareWindow = 7; if (fullscreenChartId) openChartFullscreen(fullscreenChartId); });
  byId("chartCompare30Btn")?.addEventListener("click", () => { compareWindow = 30; if (fullscreenChartId) openChartFullscreen(fullscreenChartId); });
  byId("chartCompareAllBtn")?.addEventListener("click", () => { compareWindow = null; if (fullscreenChartId) openChartFullscreen(fullscreenChartId); });
  byId("chartResetZoomBtn")?.addEventListener("click", () => fullscreenChart?.resetZoom?.());
  byId("chartExportPngBtn")?.addEventListener("click", () => {
    if (!fullscreenChart) return;
    const a = document.createElement("a");
    a.href = fullscreenChart.toBase64Image("image/png", 1);
    a.download = `bi-delivery-${fullscreenChartId || "chart"}.png`;
    a.click();
  });

  document.addEventListener("keydown", (e) => {
    const isOpen = !byId("chartFullscreenModal")?.classList.contains("hidden");
    if (e.key === "Escape") {
      modalClose("kpiDetailModal");
      modalClose("chartFullscreenModal");
      modalClose("respMotivosModal");
      return;
    }
    if (!isOpen) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      fullscreenIndex = (fullscreenIndex + (e.key === "ArrowRight" ? 1 : -1) + chartIds.length) % chartIds.length;
      openChartFullscreen(chartIds[fullscreenIndex]);
    }
  });

  chartIds.forEach(bindChartClickDrill);
  refreshBreadcrumb();

  window.openKpiModal = openKpiModal;
  window.openChartFullscreen = openChartFullscreen;
  window.generateInsightsFromDataset = generateInsightsFromDataset;
  window.toggleExecutiveMode = toggleExecutiveMode;
})();

