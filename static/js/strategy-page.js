/* global Chart */
/**
 * Cockpit /strategy — dados via /api/strategy, layout alinhado à employees.
 * PDF (jsPDF + autotable) e Chart.js carregados sob demanda.
 */
(function () {
  'use strict';

  /** Turno fixo na UI: API continua aceitando o parâmetro `shift`. */
  var STRATEGY_SHIFT_ALL = 'Todos';

  var prodChartInstance = null;
  var currentData = null;
  var productivityData = [];
  var helperProductivityData = [];
  var teamProductivityData = [];
  var abcDataFull = [];
  var strategyKpiFilter = null;
  var abcSearchQuery = '';
  var abcVisibleCount = 20;
  var chartJsPromise = null;
  var pdfLibsPromise = null;
  var chartObserver = null;
  var chartReady = false;

  var CHART_CDN = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
  var JSPDF_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
  var AUTOTABLE_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js';

  function $(id) {
    return document.getElementById(id);
  }

  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;');
  }

  function showToast(message, type) {
    type = type || 'info';
    var toast = document.createElement('div');
    toast.className =
      'fixed bottom-4 right-4 px-4 py-3 rounded-lg shadow-lg z-[200] transition-all transform translate-y-0 ' +
      (type === 'error'
        ? 'bg-red-600 text-white'
        : type === 'success'
          ? 'bg-emerald-600 text-white'
          : 'bg-slate-700 text-white');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.classList.add('translate-y-20', 'opacity-0');
      setTimeout(function () {
        toast.remove();
      }, 300);
    }, 3000);
  }

  function fmt(n) {
    if (n === null || n === undefined) return '0,00';
    return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatIntBr(n) {
    if (n === null || n === undefined || n === '') return '—';
    var x = typeof n === 'string' ? parseInt(n, 10) : Math.round(Number(n));
    if (isNaN(x)) return String(n);
    return x.toLocaleString('pt-BR');
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = resolve;
      s.onerror = function () {
        reject(new Error('Falha ao carregar ' + src));
      };
      document.head.appendChild(s);
    });
  }

  function ensureChartJs() {
    if (typeof Chart !== 'undefined') return Promise.resolve();
    if (!chartJsPromise) chartJsPromise = loadScript(CHART_CDN);
    return chartJsPromise;
  }

  function ensurePdfLibs() {
    if (!pdfLibsPromise) {
      pdfLibsPromise = loadScript(JSPDF_CDN).then(function () {
        if (!window.jspdf || !window.jspdf.jsPDF) throw new Error('jsPDF indisponível');
        return loadScript(AUTOTABLE_CDN);
      });
    }
    return pdfLibsPromise;
  }

  function setSkeletonLoading(on) {
    var root = $('strategy-cockpit');
    if (root) root.setAttribute('aria-busy', on ? 'true' : 'false');
    document.querySelectorAll('.skeleton-text').forEach(function (el) {
      if (on) el.classList.add('strategy-skeleton-line');
      else el.classList.remove('strategy-skeleton-line');
    });
  }

  function scrollToId(id) {
    var el = $(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function strategyClearKpiFilter() {
    strategyKpiFilter = null;
    document.querySelectorAll('.strategy-kpi-card').forEach(function (el) {
      el.classList.remove('is-active');
    });
    if (currentData) {
      renderABC();
      renderDriverTableForState();
      if (currentData.sla_ranking) renderSLA(currentData.sla_ranking);
    }
  }

  function strategyApplyKpiFilter(key) {
    if (strategyKpiFilter === key) {
      strategyClearKpiFilter();
      return;
    }
    strategyKpiFilter = key;
    document.querySelectorAll('.strategy-kpi-card').forEach(function (el) {
      el.classList.toggle('is-active', el.getAttribute('data-strategy-kpi') === key);
    });

    if (!currentData) return;

    if (key === 'abc-a' || key === 'abc-b' || key === 'abc-c') {
      var cls = key.replace('abc-', '').toUpperCase();
      abcSearchQuery = '';
      var inp = $('abc-search');
      if (inp) inp.value = '';
      renderABC(cls);
      scrollToId('strategy-panel-abc');
      renderDriverTableForState();
    } else if (key === 'sla-critical') {
      renderABC();
      renderDriverTableForState();
      scrollToId('strategy-panel-sla');
    } else {
      renderABC();
      renderDriverTableForState();
      scrollToId('strategy-panel-drivers');
    }

    if (currentData.sla_ranking) renderSLA(currentData.sla_ranking);
  }

  function countAbcByClass(rows, cls) {
    if (!rows || !rows.length) return 0;
    return rows.filter(function (r) {
      return r.class === cls;
    }).length;
  }

  function renderExecutiveSummary(kpi, abcRows, shiftLabel) {
    var el = $('strategy-exec-summary');
    if (!el) return;
    var a = countAbcByClass(abcRows, 'A');
    var b = countAbcByClass(abcRows, 'B');
    var c = countAbcByClass(abcRows, 'C');
    var date = $('strategy-date') && $('strategy-date').value;
    var shiftRaw = shiftLabel || STRATEGY_SHIFT_ALL;
    var shiftDisplay = shiftRaw === 'Todos' ? 'todos os turnos' : 'turno ' + shiftRaw;
    var routes = kpi.routes_count != null ? kpi.routes_count : '—';
    var vol = kpi.total_vol != null ? kpi.total_vol : '—';
    var emp = kpi.employees_count != null ? kpi.employees_count : '—';
    var meta = kpi.meta_percent != null ? Math.round(kpi.meta_percent) : '—';
    el.textContent =
      'Em ' +
      (date || '—') +
      ' · ' +
      shiftDisplay +
      ', a operação registrou ' +
      routes +
      ' rotas e ' +
      vol +
      ' kg com ' +
      emp +
      ' colaboradores em rota. Produtividade média de motoristas: ' +
      (kpi.global_kgh || '—') +
      ' kg/h (' +
      meta +
      '% da meta). Na curva ABC (30 dias): ' +
      a +
      ' clientes classe A, ' +
      b +
      ' classe B e ' +
      c +
      ' classe C — concentre revisões de janela e SLA nos que puxam o Pareto.';
  }

  function normalizeAlertIcon(icon) {
    if (!icon || icon.length > 4) return '•';
    if (icon.indexOf('[') === 0) return '▸';
    return icon;
  }

  function bucketAlerts(alerts, slaList, productivityList, kpi) {
    var critical = [];
    var attention = [];
    var opportunity = [];

    function pushBucket(item, bucket) {
      if (bucket === 'critical') critical.push(item);
      else if (bucket === 'attention') attention.push(item);
      else opportunity.push(item);
    }

    (alerts || []).forEach(function (a) {
      var b = 'opportunity';
      if (a.type === 'danger' || a.severity === 'high') b = 'critical';
      else if (a.type === 'warning' || a.severity === 'medium') b = 'attention';
      pushBucket({ icon: normalizeAlertIcon(a.icon), message: a.message, source: 'alert' }, b);
    });

    var slaCrit = (slaList || []).filter(function (s) {
      return s.sla_min > 60;
    });
    if (slaCrit.length && !critical.some(function (x) {
      return x.message && x.message.indexOf('SLA') !== -1;
    })) {
      var top = slaCrit[0];
      pushBucket(
        {
          icon: '🚨',
          message: top.name + ' exige revisão de janela — SLA médio acima de 1h.',
          source: 'synthetic',
        },
        'critical'
      );
    }

    var highIdle = (productivityList || []).filter(function (p) {
      return p.idle_hours > 2;
    }).length;
    if (highIdle > 1 && !attention.some(function (x) {
      return x.message && x.message.indexOf('ociosidade') !== -1;
    })) {
      pushBucket(
        {
          icon: '⏱',
          message: highIdle + ' motoristas com ociosidade acima de 2h no turno — redistribuir rotas ou ajustar batida.',
          source: 'synthetic',
        },
        'attention'
      );
    }

    var elite = (productivityList || []).filter(function (p) {
      return p.kgh > 300;
    }).length;
    var hasEliteAlert = (alerts || []).some(function (a) {
      return String(a.message || '').indexOf('300') !== -1 || String(a.message || '').toLowerCase().indexOf('elite') !== -1;
    });
    if (elite > 0 && !hasEliteAlert) {
      pushBucket(
        {
          icon: '★',
          message: elite + ' perfil(is) elite (>300 kg/h) sustentando a média — usar como referência de roteiro.',
          source: 'synthetic',
        },
        'opportunity'
      );
    }

    var meta = kpi && kpi.meta_percent != null ? kpi.meta_percent : 0;
    if (meta < 70 && meta > 0) {
      pushBucket(
        {
          icon: '!',
          message: 'Produtividade do conjunto abaixo de 70% da meta — priorizar correção operacional hoje.',
          source: 'synthetic',
        },
        'attention'
      );
    }

    return { critical: critical, attention: attention, opportunity: opportunity };
  }

  function renderPriorities(alerts, slaList, productivityList, kpi) {
    var host = $('strategy-priority-columns');
    if (!host) return;
    var buckets = bucketAlerts(alerts, slaList, productivityList, kpi);

    function col(title, cls, items) {
      var html =
        '<div class="strategy-priority-column strategy-priority-column--' +
        cls +
        '">' +
        '<p class="strategy-priority-column__title">' +
        title +
        '</p>';
      if (!items.length) {
        html +=
          '<p class="employees-text-muted text-xs m-0 px-1">Nada registrado nesta faixa.</p>';
      } else {
        items.forEach(function (it) {
          html +=
            '<div class="strategy-priority-item">' +
            '<span class="strategy-priority-item__icon" aria-hidden="true">' +
            escapeAttr(it.icon) +
            '</span>' +
            '<p class="strategy-priority-item__text">' +
            escapeAttr(it.message) +
            '</p></div>';
        });
      }
      html += '</div>';
      return html;
    }

    host.innerHTML =
      col('Crítico', 'critical', buckets.critical) +
      col('Atenção', 'attention', buckets.attention) +
      col('Oportunidade', 'opportunity', buckets.opportunity);
  }

  function renderKPIs(kpi, abcRows, slaList, productivityList) {
    $('kpi-global-kgh').textContent = kpi.global_kgh;
    $('kpi-avg-idle').textContent = kpi.avg_idle;
    $('kpi-routes').textContent = formatIntBr(kpi.routes_count != null ? kpi.routes_count : 0);
    $('kpi-employees').textContent = formatIntBr(kpi.employees_count != null ? kpi.employees_count : 0);
    $('kpi-vol-day').textContent = kpi.total_vol + ' kg';
    $('total-vol').textContent = kpi.total_vol + ' kg';
    $('total-vol').dataset.val = kpi.total_vol_raw || 0;

    var chipR = $('strategy-chip-routes');
    if (chipR) chipR.textContent = formatIntBr(kpi.routes_count != null ? kpi.routes_count : null) + ' rotas no dia';
    var chipV = $('strategy-chip-volume');
    if (chipV) chipV.textContent = (kpi.total_vol || '—') + ' kg movimentados';
    var chipM = $('strategy-chip-meta');
    if (chipM) chipM.textContent = Math.round(kpi.meta_percent || 0) + '% da meta de produtividade';

    var metaPercent = Math.min(kpi.meta_percent || 0, 100);
    $('kpi-meta-bar').style.width = metaPercent + '%';
    $('kpi-meta-bar').className =
      'h-full transition-all duration-500 ' +
      (metaPercent >= 100 ? 'bg-emerald-500' : metaPercent >= 70 ? 'bg-amber-500' : 'bg-red-500');
    $('kpi-meta-text').textContent = Math.round(metaPercent) + '% da meta';

    var kghChange = kpi.kgh_change || 0;
    var changeEl = $('kpi-kgh-change');
    var changeTextEl = $('kpi-kgh-change-text');
    if (kghChange !== 0) {
      changeEl.classList.remove('hidden');
      if (kghChange > 0) {
        changeEl.className =
          'text-xs font-bold px-2 py-1 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-400';
        changeTextEl.textContent = '▲ ' + kghChange.toFixed(1) + '%';
      } else {
        changeEl.className =
          'text-xs font-bold px-2 py-1 rounded bg-red-500/15 text-red-700 dark:text-red-400';
        changeTextEl.textContent = '▼ ' + Math.abs(kghChange).toFixed(1) + '%';
      }
    } else {
      changeEl.classList.add('hidden');
    }

    var a = countAbcByClass(abcRows, 'A');
    var b = countAbcByClass(abcRows, 'B');
    var c = countAbcByClass(abcRows, 'C');
    var slaCrit = (slaList || []).filter(function (s) {
      return s.sla_min > 60;
    }).length;
    var elite = (productivityList || []).filter(function (p) {
      return p.kgh > 300;
    }).length;
    var below = (productivityList || []).filter(function (p) {
      return p.kgh > 0 && p.kgh < 150;
    }).length;

    function setText(id, v) {
      var n = $(id);
      if (n) n.textContent = v;
    }
    setText('kpi-abc-a', formatIntBr(a));
    setText('kpi-abc-b', formatIntBr(b));
    setText('kpi-abc-c', formatIntBr(c));
    setText('kpi-sla-critical', formatIntBr(slaCrit));
    setText('kpi-elite', formatIntBr(elite));
    setText('kpi-below-meta', formatIntBr(below));

    calcCost();
  }

  function getFilteredAbcRows(classFilter) {
    var q = (abcSearchQuery || '').trim().toLowerCase();
    var rows = abcDataFull.slice();
    if (classFilter) rows = rows.filter(function (r) {
      return r.class === classFilter;
    });
    if (q) rows = rows.filter(function (r) {
      return String(r.name || '')
        .toLowerCase()
        .indexOf(q) !== -1;
    });
    return rows;
  }

  function renderABC(classFilter) {
    var tbody = $('abc-table-body');
    if (!tbody) return;
    var cf = classFilter;
    if (!cf && strategyKpiFilter && strategyKpiFilter.indexOf('abc-') === 0) {
      cf = strategyKpiFilter.replace('abc-', '').toUpperCase();
    }
    var rows = getFilteredAbcRows(cf);
    var slice = rows.slice(0, abcVisibleCount);
    var moreBtn = $('abc-load-more');

    if (!slice.length) {
      tbody.innerHTML =
        '<tr><td colspan="5" class="p-8 text-center employees-text-muted text-sm">Sem linhas neste recorte.</td></tr>';
      if (moreBtn) moreBtn.classList.add('hidden');
      updateAbcDrill(null);
      return;
    }

    tbody.innerHTML = slice
      .map(function (row) {
        var badgeClass = 'employees-pill employees-pill--neutral';
        var barColor = 'bg-slate-400';
        var label = 'Classe C';
        if (row.class === 'A') {
          badgeClass = 'employees-pill employees-pill--emerald';
          barColor = 'bg-emerald-500';
          label = 'Classe A';
        } else if (row.class === 'B') {
          badgeClass = 'employees-pill employees-pill--status employees-pill--pending';
          barColor = 'bg-amber-500';
          label = 'Classe B';
        }
        var val = row.tonnage || 0;
        var share = row.share || 0;
        var name = row.name || 'Desconhecido';
        var count = row.count != null ? row.count : '—';
        var cum = row.cumulative_share != null ? row.cumulative_share.toFixed(1) : '—';
        return (
          '<tr class="employees-data-table__row strategy-abc-row transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.04] cursor-pointer" tabindex="0" ' +
          'data-abc-name="' +
          escapeAttr(name) +
          '" data-abc-class="' +
          escapeAttr(row.class) +
          '" data-abc-tonnage="' +
          escapeAttr(fmt(val)) +
          '" data-abc-share="' +
          escapeAttr(share.toFixed(1)) +
          '" data-abc-cumulative="' +
          escapeAttr(cum) +
          '" data-abc-count="' +
          escapeAttr(count) +
          '">' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle"><span class="' +
          badgeClass +
          ' text-xs font-semibold">' +
          label +
          '</span></td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle employees-text-strong">' +
          escapeAttr(name) +
          '</td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle tabular-nums employees-text-body">' +
          fmt(val) +
          ' kg</td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle tabular-nums employees-text-muted">' +
          share.toFixed(1) +
          '% <span class="text-[10px]">acum. ' +
          cum +
          '%</span></td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle w-48">' +
          '<div class="w-full rounded-full h-1.5 overflow-hidden bg-slate-200 dark:bg-slate-700">' +
          '<div class="h-full ' +
          barColor +
          '" style="width:' +
          Math.min(share, 100) +
          '%"></div></div></td>' +
          '</tr>'
        );
      })
      .join('');

    if (moreBtn) {
      if (rows.length > abcVisibleCount) moreBtn.classList.remove('hidden');
      else moreBtn.classList.add('hidden');
    }

    var sumEl = $('abc-summary-pareto');
    if (sumEl && abcDataFull.length) {
      var topShare = abcDataFull[0] && abcDataFull[0].share != null ? abcDataFull[0].share.toFixed(1) : '—';
      sumEl.textContent =
        formatIntBr(abcDataFull.length) +
        ' clientes · maior cliente ' +
        topShare +
        '% do volume (30d)';
    }
  }

  function updateAbcDrill(tr) {
    var panel = $('abc-drill-panel');
    var body = $('abc-drill-body');
    if (!panel || !body) return;
    document.querySelectorAll('tr.strategy-abc-row').forEach(function (r) {
      r.classList.remove('strategy-abc-row--selected');
      r.removeAttribute('aria-selected');
    });
    if (!tr) {
      panel.classList.add('strategy-abc-drill--placeholder');
      body.className =
        'strategy-abc-drill__body strategy-abc-drill__body--hint m-0 text-sm employees-text-muted';
      body.textContent =
        'Clique em uma linha da tabela para ver volume, participação e rotas.';
      return;
    }
    panel.classList.remove('strategy-abc-drill--placeholder');
    body.className = 'strategy-abc-drill__body m-0 text-sm employees-text-body';
    tr.classList.add('strategy-abc-row--selected');
    tr.setAttribute('aria-selected', 'true');
    var name = tr.dataset.abcName || '';
    var cls = tr.dataset.abcClass || '';
    body.innerHTML =
      '<strong class="employees-text-strong">' +
      escapeAttr(name) +
      '</strong> · classe ' +
      escapeAttr(cls) +
      ' · volume ' +
      escapeAttr(tr.dataset.abcTonnage || '') +
      ' kg · ' +
      escapeAttr(tr.dataset.abcShare || '') +
      '% do total · acumulado ' +
      escapeAttr(tr.dataset.abcCumulative || '') +
      '% · ' +
      escapeAttr(tr.dataset.abcCount || '') +
      ' rotas (amostra no período).';
  }

  function setupAbcTableDelegation() {
    var tbody = $('abc-table-body');
    if (!tbody || tbody.dataset.delegationBound) return;
    tbody.dataset.delegationBound = '1';
    tbody.addEventListener('click', function (e) {
      var tr = e.target.closest('tr.strategy-abc-row');
      if (tr) updateAbcDrill(tr);
    });
    tbody.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var tr = e.target.closest('tr.strategy-abc-row');
      if (tr) {
        e.preventDefault();
        updateAbcDrill(tr);
      }
    });
  }

  function setChartUiState(mode, message) {
    var statusEl = $('strategy-chart-status');
    var wrap = $('strategy-chart-canvas-wrap');
    if (mode === 'ready') {
      if (statusEl) {
        statusEl.textContent = '';
        statusEl.classList.add('hidden');
      }
      if (wrap) {
        wrap.classList.remove('opacity-0');
        wrap.classList.remove('pointer-events-none');
      }
    } else if (mode === 'message') {
      if (statusEl) {
        statusEl.textContent = message || '';
        statusEl.classList.remove('hidden');
      }
      if (wrap) {
        wrap.classList.add('opacity-0', 'pointer-events-none');
      }
    } else {
      if (statusEl) {
        statusEl.textContent = message || '';
        statusEl.classList.remove('hidden');
      }
      if (wrap) wrap.classList.add('opacity-0', 'pointer-events-none');
    }
  }

  function requestChartRender(labels, values, target) {
    var mount = $('strategy-chart-mount');
    if (!mount) return;

    function run() {
      chartReady = true;
      setChartUiState('ready');
      renderChart(labels, values, target);
    }

    if (!labels || !labels.length) {
      setChartUiState('message', 'Nenhum dia com entrega e tempo de rota válido nos últimos 30 dias.');
      if (prodChartInstance) {
        prodChartInstance.destroy();
        prodChartInstance = null;
      }
      return;
    }

    ensureChartJs()
      .then(run)
      .catch(function () {
        setChartUiState('message', 'Não foi possível carregar o gráfico.');
      });
  }

  function observeChartMount(labels, values, target) {
    var mount = $('strategy-chart-mount');
    if (!mount) return;
    if (chartObserver) chartObserver.disconnect();
    chartReady = false;
    setChartUiState('loading', 'Carregando visualização…');

    if (typeof Chart !== 'undefined') {
      requestChartRender(labels, values, target);
      return;
    }

    chartObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && !chartReady) {
            requestChartRender(labels, values, target);
          }
        });
      },
      { rootMargin: '80px', threshold: 0.08 }
    );
    chartObserver.observe(mount);
  }

  function renderChart(labels, values, target) {
    var canvas = $('prodChart');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var tgt = $('chart-target-label');
    if (tgt) tgt.textContent = target || 0;

    if (prodChartInstance) prodChartInstance.destroy();

    var targetLine = new Array(labels.length).fill(target || 0);

    prodChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Produtividade (Kg/h)',
            data: values,
            borderColor: 'rgb(16 185 129)',
            backgroundColor: 'rgba(16, 185, 129, 0.12)',
            borderWidth: 2,
            tension: 0.35,
            pointBackgroundColor: 'rgb(5 150 105)',
            pointRadius: 2,
            pointHoverRadius: 5,
            fill: true,
          },
          {
            label: 'Meta',
            data: targetLine,
            borderColor: 'rgb(245 158 11)',
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgb(15 23 42)',
            titleColor: '#fff',
            bodyColor: 'rgb(203 213 225)',
            borderColor: 'rgb(51 65 85)',
            borderWidth: 1,
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgb(226 232 240 / 0.35)' },
            ticks: { color: 'rgb(100 116 139)' },
            title: { display: true, text: 'Kg/h', color: 'rgb(100 116 139)' },
          },
          x: {
            grid: { display: false },
            ticks: { color: 'rgb(100 116 139)', maxRotation: 45, minRotation: 0 },
          },
        },
      },
    });
  }

  function renderProductivityTable(tbodyId, prodList, targetKgh, options) {
    options = options || {};
    var tbody = $(tbodyId);
    if (!tbody) return;
    if (!prodList || !prodList.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="p-8 text-center employees-text-muted text-sm">' +
        (options.emptyMessage || 'Sem dados de movimentação.') +
        '</td></tr>';
      return;
    }

    var target = targetKgh || 200;
    var rowClass = options.rowClass || 'productivity-row';

    tbody.innerHTML = prodList
      .map(function (row, index) {
        var kgh = row.kgh;
        var kghClass =
          kgh > 250 ? 'text-emerald-600 dark:text-emerald-400' : kgh < 150 ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400';

        var idleH = Math.floor(row.idle_hours);
        var idleM = Math.floor((row.idle_hours - idleH) * 60);
        var idleClass = row.idle_hours > 2 ? 'text-red-600 dark:text-red-400' : 'employees-text-body';

        var activeH = Math.floor(row.active_hours);
        var activeM = Math.floor((row.active_hours - activeH) * 60);

        var progress = Math.min((kgh / target) * 100, 100);
        var progressColor = progress >= 100 ? 'bg-emerald-500' : progress >= 70 ? 'bg-amber-500' : 'bg-red-500';

        var roleLabel = row.role_label || 'Motorista';
        var roleClass = 'employees-pill employees-pill--neutral text-[10px]';
        if (roleLabel === 'Ajudante') roleClass = 'employees-pill employees-pill--cyan text-[10px]';
        else if (roleLabel === 'Misto') roleClass = 'employees-pill employees-pill--status employees-pill--pending text-[10px]';
        else if (roleLabel === 'Motorista') roleClass = 'employees-pill employees-pill--cyan text-[10px]';

        var statusBadge = '<span class="sys-badge sys-badge--neutral text-[10px]">Normal</span>';
        if (kgh > 300) statusBadge = '<span class="sys-badge sys-badge--ok text-[10px]">Elite</span>';
        else if (row.idle_hours > 2)
          statusBadge = '<span class="sys-badge sys-badge--alert text-[10px]">Ocioso</span>';

        var rankBadge = '<span class="employees-text-muted tabular-nums">' + (index + 1) + '</span>';
        if (index === 0) rankBadge = '<span class="text-amber-500 font-bold">1º</span>';
        else if (index === 1) rankBadge = '<span class="employees-text-muted font-bold">2º</span>';
        else if (index === 2) rankBadge = '<span class="text-amber-700 dark:text-amber-600 font-bold">3º</span>';

        return (
          '<tr class="employees-data-table__row ' +
          rowClass +
          ' transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.04]" data-name="' +
          escapeAttr((row.name || '').toLowerCase()) +
          '">' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle tabular-nums">' +
          rankBadge +
          '</td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle">' +
          '<div class="min-w-0">' +
          '<div class="employees-text-strong truncate">' +
          escapeAttr(row.name) +
          '</div>' +
          '<div class="flex flex-wrap items-center gap-2 mt-1">' +
          '<span class="' +
          roleClass +
          ' font-semibold uppercase tracking-wide">' +
          escapeAttr(roleLabel) +
          '</span>' +
          '<span class="text-[10px] employees-text-muted">' +
          (row.route_count || 0) +
          ' rota(s)</span></div></div></td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle tabular-nums">' +
          '<span class="font-semibold ' +
          kghClass +
          '">' +
          Math.round(kgh) +
          ' <span class="text-xs font-normal employees-text-muted">kg/h</span></span></td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle w-36">' +
          '<div class="flex items-center gap-2">' +
          '<div class="flex-1 rounded-full h-2 overflow-hidden bg-slate-200 dark:bg-slate-700">' +
          '<div class="h-full ' +
          progressColor +
          ' transition-all" style="width:' +
          progress +
          '%"></div></div>' +
          '<span class="text-[10px] employees-text-muted tabular-nums">' +
          Math.round(progress) +
          '%</span></div></td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle tabular-nums employees-text-body">' +
          activeH +
          'h ' +
          activeM +
          'm</td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle tabular-nums">' +
          '<span class="font-medium ' +
          idleClass +
          '">' +
          idleH +
          'h ' +
          idleM +
          'm</span></td>' +
          '<td class="employees-data-table__cell px-3 py-2 align-middle whitespace-nowrap">' +
          statusBadge +
          '</td></tr>'
        );
      })
      .join('');
  }

  function renderSLA(slaList) {
    var tbody = $('sla-table-body');
    if (!tbody) return;
    var filterCritical = strategyKpiFilter === 'sla-critical';
    if (!slaList || !slaList.length) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="p-8 text-center employees-text-muted text-sm">Sem dados.</td></tr>';
      return;
    }

    tbody.innerHTML = slaList
      .map(function (row) {
        var isCrit = row.sla_min > 60;
        var isAtt = row.sla_min > 30 && row.sla_min <= 60;
        var rowHighlight = filterCritical && isCrit ? ' ring-1 ring-red-500/40 bg-red-500/5' : '';
        var impact = '<span class="sys-badge sys-badge--ok text-[10px]">OK</span>';
        if (isCrit) impact = '<span class="sys-badge sys-badge--critical text-[10px]">Crítico &gt;1h</span>';
        else if (isAtt) impact = '<span class="sys-badge sys-badge--alert text-[10px]">Atenção</span>';

        return (
          '<tr class="employees-data-table__row transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.04]' +
          rowHighlight +
          '">' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle employees-text-strong">' +
          escapeAttr(row.name) +
          '</td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle tabular-nums employees-text-body">' +
          escapeAttr(row.sla_fmt) +
          '</td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle tabular-nums employees-text-muted">' +
          (row.count || 0) +
          ' rotas</td>' +
          '<td class="employees-data-table__cell px-4 py-3 align-middle">' +
          impact +
          '</td></tr>'
        );
      })
      .join('');
  }

  function renderAll(data) {
    abcDataFull = data.abc_data || [];
    abcVisibleCount = 20;

    renderKPIs(data.kpi, abcDataFull, data.sla_ranking, data.productivity || []);
    renderExecutiveSummary(data.kpi, abcDataFull, data.selected_shift);
    renderPriorities(data.alerts, data.sla_ranking, data.productivity || [], data.kpi);
    renderABC();
    setupAbcTableDelegation();
    updateAbcDrill(null);

    if (chartObserver) chartObserver.disconnect();
    chartObserver = null;
    observeChartMount(data.prod_chart_labels, data.prod_chart_data, data.prod_chart_target);

    renderDriverTableForState();
    renderProductivityTable('helper-productivity-table-body', helperProductivityData, data.kpi.target_kgh, {
      emptyMessage: 'Nenhum ajudante vinculado às rotas deste período.',
      rowClass: 'helper-productivity-row',
    });
    renderProductivityTable('team-productivity-table-body', teamProductivityData, data.kpi.target_kgh, {
      emptyMessage: 'Sem dados consolidados da equipe.',
      rowClass: 'team-productivity-row',
    });
    renderSLA(data.sla_ranking);

    document.querySelectorAll('.strategy-kpi-card').forEach(function (el) {
      el.classList.toggle('is-active', !!strategyKpiFilter && el.getAttribute('data-strategy-kpi') === strategyKpiFilter);
    });
  }

  function loadStrategyData() {
    var date = $('strategy-date').value;
    var shift = STRATEGY_SHIFT_ALL;
    var refreshIcon = $('refresh-icon');
    var refreshBtn = $('refresh-btn');
    if (refreshIcon) refreshIcon.classList.add('animate-spin');
    if (refreshBtn) refreshBtn.classList.add('is-loading');
    document.body.style.cursor = 'wait';
    setSkeletonLoading(true);

    fetch('/api/strategy?date=' + encodeURIComponent(date) + '&shift=' + encodeURIComponent(shift))
      .then(function (r) {
        if (!r.ok) throw new Error('Falha ao carregar dados');
        return r.json();
      })
      .then(function (data) {
        currentData = data;
        productivityData = [].concat(data.productivity || []);
        helperProductivityData = [].concat(data.helper_productivity || []);
        teamProductivityData = [].concat(data.team_productivity || []);
        renderAll(data);
      })
      .catch(function (err) {
        console.error(err);
        showToast('Erro ao carregar dados da API.', 'error');
      })
      .finally(function () {
        document.body.style.cursor = 'default';
        if (refreshIcon) refreshIcon.classList.remove('animate-spin');
        if (refreshBtn) refreshBtn.classList.remove('is-loading');
        setSkeletonLoading(false);
      });
  }

  function getDriverRowsForFilter(key) {
    var list = productivityData;
    if (!key || key === 'prod' || key === 'routes' || key === 'employees') return list;
    if (key.indexOf('abc-') === 0 || key === 'sla-critical') return list;
    if (key === 'elite') return list.filter(function (p) {
      return p.kgh > 300;
    });
    if (key === 'below-meta') return list.filter(function (p) {
      return p.kgh > 0 && p.kgh < 150;
    });
    if (key === 'idle-high') return list.filter(function (p) {
      return p.idle_hours > 2;
    });
    return list;
  }

  function emptyMessageForDriverFilter(key) {
    if (key === 'elite') return 'Nenhum motorista elite neste recorte.';
    if (key === 'below-meta') return 'Ninguém abaixo da meta neste recorte.';
    if (key === 'idle-high') return 'Nenhum motorista com ociosidade alta neste recorte.';
    return 'Sem dados de movimentação.';
  }

  function renderDriverTableForState() {
    if (!currentData) return;
    var key = strategyKpiFilter;
    var filtered = getDriverRowsForFilter(key);
    renderProductivityTable('productivity-table-body', filtered, currentData.kpi.target_kgh, {
      emptyMessage: emptyMessageForDriverFilter(key),
      rowClass: 'driver-productivity-row',
    });
    filterProductivityTable();
  }

  function filterProductivityTable() {
    var searchEl = $('productivity-search');
    var search = (searchEl && searchEl.value.toLowerCase().trim()) || '';
    document.querySelectorAll('.driver-productivity-row').forEach(function (row) {
      var name = row.dataset.name || '';
      row.style.display = name.indexOf(search) !== -1 ? '' : 'none';
    });
  }

  function syncProductivitySortAria(activeBtn) {
    document.querySelectorAll('.strategy-sort-btn').forEach(function (b) {
      b.setAttribute('aria-pressed', b === activeBtn ? 'true' : 'false');
    });
  }

  function sortProductivity(field) {
    var btn = document.querySelector('.strategy-sort-btn[data-sort="' + field + '"]');
    if (!btn || !currentData) return;
    var dir = btn.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
    btn.setAttribute('data-dir', dir);
    document.querySelectorAll('.strategy-sort-btn').forEach(function (b) {
      b.classList.toggle('is-active', b === btn);
    });
    syncProductivitySortAria(btn);
    var icon = btn.querySelector('.sort-icon');
    if (icon) icon.style.transform = dir === 'asc' ? 'rotate(180deg)' : 'rotate(0deg)';

    productivityData.sort(function (a, b) {
      var valA;
      var valB;
      if (field === 'kgh') {
        valA = a.kgh;
        valB = b.kgh;
      } else if (field === 'idle') {
        valA = a.idle_hours;
        valB = b.idle_hours;
      } else if (field === 'name') {
        valA = (a.name || '').toLowerCase();
        valB = (b.name || '').toLowerCase();
      } else return 0;
      if (typeof valA === 'string') {
        return dir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      return dir === 'asc' ? valA - valB : valB - valA;
    });

    renderDriverTableForState();
  }

  function calcCost() {
    var payroll = parseFloat($('payroll-input').value) || 0;
    var volStr = $('total-vol').textContent || '';
    volStr = volStr.replace(/\./g, '').replace(' kg', '').replace(',', '.');
    var vol = parseFloat(volStr) || 1;
    var tons = vol / 1000;
    var out = $('cost-result');
    if (tons > 0 && payroll > 0 && out) {
      out.textContent = 'R$ ' + (payroll / tons).toFixed(2).replace('.', ',');
    } else if (out) {
      out.textContent = 'R$ —';
    }
  }

  function exportReport() {
    if (!currentData) {
      showToast('Carregue os dados primeiro.', 'error');
      return;
    }
    showToast('Preparando PDF…', 'info');
    ensurePdfLibs()
      .then(function () {
        var jsPDF = window.jspdf.jsPDF;
        var doc = new jsPDF();
        var date = $('strategy-date').value;

        doc.setFontSize(18);
        doc.setTextColor(30, 41, 59);
        doc.text('Relatório de Estratégia e Inteligência', 14, 20);
        doc.setFontSize(10);
        doc.setTextColor(100, 116, 139);
        doc.text('Data: ' + date + ' | Todos os turnos', 14, 28);
        doc.text('Gerado em: ' + new Date().toLocaleString('pt-BR'), 14, 34);

        doc.setFontSize(14);
        doc.setTextColor(30, 41, 59);
        doc.text('Indicadores principais', 14, 46);

        var kpi = currentData.kpi;
        doc.setFontSize(10);
        doc.setTextColor(71, 85, 105);
        doc.text('Produtividade média: ' + kpi.global_kgh + ' kg/h', 14, 54);
        doc.text('Ociosidade média: ' + kpi.avg_idle, 14, 60);
        doc.text('Rotas concluídas: ' + kpi.routes_count, 14, 66);
        doc.text('Colaboradores ativos: ' + kpi.employees_count, 14, 72);
        doc.text('Volume total: ' + kpi.total_vol + ' kg', 14, 78);

        if (currentData.productivity && currentData.productivity.length > 0) {
          doc.setFontSize(14);
          doc.setTextColor(30, 41, 59);
          doc.text('Produtividade dos motoristas', 14, 92);
          var prodTableData = currentData.productivity.slice(0, 15).map(function (p, i) {
            return [
              i + 1,
              p.name,
              Math.round(p.kgh) + ' kg/h',
              Math.floor(p.active_hours) + 'h ' + Math.floor((p.active_hours % 1) * 60) + 'm',
              Math.floor(p.idle_hours) + 'h ' + Math.floor((p.idle_hours % 1) * 60) + 'm',
            ];
          });
          doc.autoTable({
            startY: 98,
            head: [['#', 'Colaborador', 'Produtividade', 'Tempo ativo', 'Ociosidade']],
            body: prodTableData,
            theme: 'striped',
            headStyles: { fillColor: [30, 41, 59] },
            styles: { fontSize: 8 },
          });
        }

        if (currentData.helper_productivity && currentData.helper_productivity.length > 0) {
          var startY = doc.lastAutoTable ? doc.lastAutoTable.finalY + 15 : 150;
          doc.setFontSize(14);
          doc.setTextColor(30, 41, 59);
          doc.text('Produtividade dos ajudantes', 14, startY);
          var helperTableData = currentData.helper_productivity.slice(0, 15).map(function (p, i) {
            return [
              i + 1,
              p.name,
              Math.round(p.kgh) + ' kg/h',
              Math.floor(p.active_hours) + 'h ' + Math.floor((p.active_hours % 1) * 60) + 'm',
              Math.floor(p.idle_hours) + 'h ' + Math.floor((p.idle_hours % 1) * 60) + 'm',
            ];
          });
          doc.autoTable({
            startY: startY + 6,
            head: [['#', 'Ajudante', 'Produtividade', 'Tempo ativo', 'Ociosidade']],
            body: helperTableData,
            theme: 'striped',
            headStyles: { fillColor: [8, 145, 178] },
            styles: { fontSize: 8 },
          });
        }

        if (currentData.team_productivity && currentData.team_productivity.length > 0) {
          var startY2 = doc.lastAutoTable ? doc.lastAutoTable.finalY + 15 : 190;
          doc.setFontSize(14);
          doc.setTextColor(30, 41, 59);
          doc.text('Visão geral da equipe', 14, startY2);
          var teamTableData = currentData.team_productivity.slice(0, 15).map(function (p, i) {
            return [
              i + 1,
              p.name,
              p.role_label || '-',
              Math.round(p.kgh) + ' kg/h',
              Math.floor(p.active_hours) + 'h ' + Math.floor((p.active_hours % 1) * 60) + 'm',
            ];
          });
          doc.autoTable({
            startY: startY2 + 6,
            head: [['#', 'Colaborador', 'Papel', 'Produtividade', 'Tempo ativo']],
            body: teamTableData,
            theme: 'striped',
            headStyles: { fillColor: [79, 70, 229] },
            styles: { fontSize: 8 },
          });
        }

        if (currentData.sla_ranking && currentData.sla_ranking.length > 0) {
          var startY3 = doc.lastAutoTable ? doc.lastAutoTable.finalY + 15 : 150;
          doc.setFontSize(14);
          doc.setTextColor(30, 41, 59);
          doc.text('SLA de atendimento', 14, startY3);
          var slaTableData = currentData.sla_ranking.map(function (s) {
            return [
              s.name,
              s.sla_fmt,
              s.count || 0,
              s.sla_min > 60 ? 'Crítico' : s.sla_min > 30 ? 'Atenção' : 'OK',
            ];
          });
          doc.autoTable({
            startY: startY3 + 6,
            head: [['Cliente', 'Tempo médio', 'Rotas', 'Status']],
            body: slaTableData,
            theme: 'striped',
            headStyles: { fillColor: [30, 41, 59] },
            styles: { fontSize: 8 },
          });
        }

        doc.save('relatorio_estrategia_' + date + '.pdf');
        showToast('Relatório exportado.', 'success');
      })
      .catch(function () {
        showToast('Falha ao carregar bibliotecas de PDF.', 'error');
      });
  }

  function onAbcSearchInput() {
    var inp = $('abc-search');
    abcSearchQuery = inp ? inp.value : '';
    abcVisibleCount = 20;
    renderABC();
  }

  function onAbcLoadMore() {
    abcVisibleCount += 25;
    renderABC();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var dateInput = $('strategy-date');
    if (dateInput && !dateInput.value) {
      dateInput.value = new Date().toISOString().split('T')[0];
    }
    if ($('strategy-date')) $('strategy-date').addEventListener('change', loadStrategyData);
    var abcSearch = $('abc-search');
    if (abcSearch) {
      var t;
      abcSearch.addEventListener('input', function () {
        clearTimeout(t);
        t = setTimeout(onAbcSearchInput, 160);
      });
    }
    var more = $('abc-load-more');
    if (more) more.addEventListener('click', onAbcLoadMore);

    var prodSearch = $('productivity-search');
    if (prodSearch) {
      var prodT;
      prodSearch.addEventListener('input', function () {
        clearTimeout(prodT);
        prodT = setTimeout(filterProductivityTable, 120);
      });
    }

    loadStrategyData();
  });

  window.loadStrategyData = loadStrategyData;
  window.exportReport = exportReport;
  window.filterProductivityTable = filterProductivityTable;
  window.sortProductivity = sortProductivity;
  window.calcCost = calcCost;
  window.strategyApplyKpiFilter = strategyApplyKpiFilter;
  window.strategyClearKpiFilter = strategyClearKpiFilter;
})();
