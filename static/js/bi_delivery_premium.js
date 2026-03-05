(() => {
  const byId = (id) => document.getElementById(id);
  const qs = (s) => document.querySelector(s);
  const qsa = (s) => Array.from(document.querySelectorAll(s));
  const state = window.__biState;
  const renderDrill = window.__biRenderDrill;

  if (!state || !renderDrill || typeof Chart === 'undefined') return;

  const chartIds = ["trendChart", "motivosChart", "respChart", "clusterChart", "driverChart"];
  const chartTitles = {
    trendChart: "Tendência diária",
    motivosChart: "Motivos de devolução",
    respChart: "Responsabilidade",
    clusterChart: "Cluster x Valor",
    driverChart: "Eficiência por motorista"
  };
  const chartAllowedTypes = {
    trendChart: ["line", "bar"],
    motivosChart: ["bar", "doughnut"],
    respChart: ["doughnut", "bar"],
    clusterChart: ["bar", "doughnut"],
    driverChart: ["bar", "line"]
  };

  const kpiDefs = {
    "Paradas Planejadas": ["Volume previsto de paradas no período.", "Σ rotas planejadas", ">=95% realização"],
    "Paradas Realizadas": ["Paradas concluídas no período.", "Σ concluídas ÷ Σ planejadas", "SLA >= 90%"],
    "Taxa Devolução": ["Incidência de devoluções na operação.", "(devoluções ÷ planejadas) x 100", "< 7%"],
    "Valor Devolvido": ["Impacto financeiro das devoluções.", "Σ valor devolvido", "Tendência de queda"],
    "% Acima de R$300": ["Risco financeiro por ticket alto.", "(devoluções>=300 ÷ total) x 100", "< 35%"],
    "Tempo Médio": ["Agilidade de conclusão de rotas.", "Média de duração das rotas", "< 120 min"],
    "Risco Próx. Turno": ["Risco preditivo operacional.", "Sinal derivado de tendência + anomalias", "Controlado"]
  };

  let fullscreenChart = null;
  let fullscreenChartId = null;
  let compareWindow = null;
  let kpiSparklineChart = null;
  let respMotivosChart = null;
  let fullscreenIndex = 0;

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
    if (title === "Taxa Devolução") return trend.qtd || [];
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
    if (title === "Taxa Devolução" && toNum(value) >= 10) alerts.push("Taxa de devolução acima do limite recomendado.");
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
        if (Array.isArray(d.data)) d.data = d.data.map(v => (v == null ? null : typeof v === 'number' ? v : (Number(v) || 0)));
        if (d.borderColor) d.borderColor = String(d.borderColor);
        if (d.backgroundColor && typeof d.backgroundColor === 'string') d.backgroundColor = String(d.backgroundColor);
        return d;
      });
    }
    return out;
  }

  function buildFullscreenOptions(type, data) {
    const isCartesian = type !== "doughnut" && type !== "pie" && type !== "polarArea";
    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 420 },
      plugins: {
        legend: { labels: { color: "#94a3b8" } },
        tooltip: { enabled: true }
      }
    };
    if (isCartesian) {
      const ds = (data && data.datasets) || [];
      const needsY1 = ds.some(function (d) { return d.yAxisID === "y1"; });
      options.scales = {
        x: { display: true, ticks: { color: "#94a3b8", maxRotation: 45 }, grid: { color: "rgba(148,163,184,0.2)" } },
        y: { display: true, position: "left", ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.2)" } }
      };
      if (needsY1) {
        options.scales.y1 = { display: true, position: "right", ticks: { color: "#94a3b8" }, grid: { display: false } };
      }
    }
    return options;
  }

  function generateInsightsFromDataset(chartId, data) {
    const out = [];
    const labels = data?.labels || [];
    const ds = data?.datasets || [];
    if (!ds.length) return ["Sem dados suficientes para storytelling."];
    if (chartId === "trendChart") {
      const values = ds[1]?.data || ds[0]?.data || [];
      const recent = values.slice(-7).reduce((a, b) => a + Number(b || 0), 0);
      const prev = values.slice(-14, -7).reduce((a, b) => a + Number(b || 0), 0) || 1;
      const delta = ((recent - prev) / Math.abs(prev)) * 100;
      out.push(`Últimos 7 dias mostram ${delta >= 0 ? "alta" : "queda"} de ${Math.abs(delta).toFixed(1)}%.`);
      const p = values.reduce((best, v, i, arr) => Number(v || 0) > Number(arr[best] || 0) ? i : best, 0);
      const labelP = labels[p] != null ? String(labels[p]) : '';
      out.push(`Pico no período em ${labelP}: ${Number(values[p] || 0).toLocaleString("pt-BR")}.`);
    } else if (chartId === "motivosChart") {
      const md = (window.__biChartData?.motivos_detailed || []);
      if (!md.length) return ["Sem dados suficientes para storytelling."];
      const totalQtd = md.reduce((a, m) => a + (m.qtd || 0), 0) || 1;
      const totalValor = md.reduce((a, m) => a + (m.valor || 0), 0) || 1;
      const topQtd = md.reduce((best, m, i, arr) => (m.qtd || 0) > (arr[best]?.qtd || 0) ? i : best, 0);
      const topValor = md.reduce((best, m, i, arr) => (m.valor || 0) > (arr[best]?.valor || 0) ? i : best, 0);
      out.push(`${md[topQtd]?.motivo || "Motivo"} lidera em volume com ${(((md[topQtd]?.qtd || 0) / totalQtd) * 100).toFixed(1)}% das ocorrencias.`);
      out.push(`${md[topValor]?.motivo || "Motivo"} concentra ${(((md[topValor]?.valor || 0) / totalValor) * 100).toFixed(1)}% do valor devolvido.`);
    } else {
      const values = (ds[0]?.data || []).map(Number);
      const sum = values.reduce((a, b) => a + b, 0) || 1;
      const top = values.reduce((best, v, i, arr) => v > arr[best] ? i : best, 0);
      const labelStr = labels[top] != null ? String(labels[top]) : '';
      out.push(`${labelStr} concentra ${((values[top] / sum) * 100).toFixed(1)}% do total.`);
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
      if (label == null) return;
      let fn = null;
      if (id === "trendChart") fn = (r) => r.date === label;
      if (id === "motivosChart") fn = (r) => r.motivo === String(label);
      if (id === "respChart") fn = (r) => r.responsabilidade === label;
      if (id === "clusterChart") fn = (r) => r.cluster === label;
      if (id === "driverChart") fn = (r) => r.driver_name === label;
      if (!fn) return;
      if (id === "respChart") openResponsibilityMotivosModal(label);
      state.drillStack.push({ label: `${chartTitles[id]}: ${label}`, fn });
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
    const clipped = cloneChartData(clipData(src.data, compareWindow));
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
    try { localStorage.setItem("bi_exec_mode", next ? "1" : "0"); } catch { }
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

  const safeStorage = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { } } };
  byId("execModeToggle")?.addEventListener("click", () => toggleExecutiveMode());
  toggleExecutiveMode(safeStorage.get("bi_exec_mode") === "1");

  qsa(".kpi-card").forEach((card) => {
    card.addEventListener("click", () => openKpiModal(card));
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
    const clipped = cloneChartData(clipData(src.data, compareWindow));
    destroyFullscreenChart();
    fullscreenChart = new Chart(byId("fullscreenChartCanvas"), { type: next, data: clipped, options: buildFullscreenOptions(next, clipped) });
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
