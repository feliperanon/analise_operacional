/* global Chart */
(function () {
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent.trim());
    } catch (e) {
      console.warn("[bi-clientes] JSON inválido em #" + id, e);
      return null;
    }
  }

  function fmtMoney(v) {
    return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }
  function fmtPct(v) {
    return Number(v || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  }

  function fmtDeltaPp(delta) {
    var n = Number(delta);
    if (!isFinite(n)) return "\u2014";
    return (n > 0 ? "+" : "") + n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " p.p.";
  }

  function fmtDeltaPctChange(current, previous) {
    var c = Number(current) || 0;
    var p = Number(previous) || 0;
    if (p <= 0) return c <= 0 ? "\u2014" : "+100%";
    var pct = ((c - p) / p) * 100;
    return (pct >= 0 ? "+" : "") + pct.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  }

  function periodLabels() {
    var root = document.getElementById("bi-clientes-root");
    return {
      current: (root && root.getAttribute("data-period-current")) || "Per\u00edodo atual",
      previous: (root && root.getAttribute("data-period-previous")) || "Per\u00edodo anterior",
    };
  }

  function deltaToneClass(delta, invert) {
    var n = Number(delta);
    if (!isFinite(n) || n === 0) return "bi-cli-delta--neutral";
    var bad = invert ? n < 0 : n > 0;
    return bad ? "bi-cli-delta--bad" : "bi-cli-delta--good";
  }

  function periodCompareHtml(row) {
    if (!row.has_previous_data) {
      return '<p class="employees-text-muted mt-3 text-xs">Sem base do per\u00edodo anterior equivalente para comparar.</p>';
    }
    var periods = periodLabels();
    var items = [
      {
        label: "Valor entregue",
        current: fmtMoney(row.delivered_value),
        previous: fmtMoney(row.previous_delivered_value),
        delta: fmtDeltaPctChange(row.delivered_value, row.previous_delivered_value),
        deltaClass: deltaToneClass(row.delta_delivered_value, false),
      },
      {
        label: "Valor devolvido",
        current: fmtMoney(row.returned_value),
        previous: fmtMoney(row.previous_returned_value),
        delta: fmtDeltaPctChange(row.returned_value, row.previous_returned_value),
        deltaClass: deltaToneClass(row.delta_returned_value, true),
      },
      {
        label: "\u00cdndice devolu\u00e7\u00e3o (valor)",
        current: fmtPct(row.return_pct_planned),
        previous: fmtPct(row.previous_return_rate_value),
        delta: fmtDeltaPp(row.delta_return_rate_value),
        deltaClass: deltaToneClass(row.delta_return_rate_value, true),
      },
    ];
    var cells = items
      .map(function (it) {
        return (
          '<div class="bi-cli-period-compare__item">' +
          '<p class="employees-text-muted text-xs">' +
          escapeHtml(it.label) +
          "</p>" +
          '<p class="mt-0.5 font-semibold tabular-nums">' +
          escapeHtml(it.current) +
          ' <span class="bi-cli-delta ' +
          it.deltaClass +
          ' text-xs font-medium">(' +
          escapeHtml(it.delta) +
          ")</span></p>" +
          '<p class="employees-text-muted text-[11px]">Antes: ' +
          escapeHtml(it.previous) +
          "</p></div>"
        );
      })
      .join("");
    return (
      '<section class="bi-cli-period-compare mt-3 rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-600 dark:bg-slate-800/35" aria-label="Comparativo com per\u00edodo anterior">' +
      '<p class="text-xs font-semibold text-slate-700 dark:text-slate-200">Comparativo \u00b7 ' +
      escapeHtml(periods.previous) +
      " \u2192 " +
      escapeHtml(periods.current) +
      '</p><div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">' +
      cells +
      "</div></section>"
    );
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

  /** YYYY-MM-DD (ou início de ISO) → dd/mm/aaaa; texto inesperado devolvido sem alterar (use escapeHtml no uso). */
  function fmtDateIsoToBr(s) {
    if (s == null || s === "") return "—";
    var t = String(s).trim();
    var m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return t;
    return m[3] + "/" + m[2] + "/" + m[1];
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

  function motTitle(s) {
    return escapeHtml(String(s || "—")).replace(/"/g, "&quot;");
  }

  var MODAL_LIST_CHUNK = 25;

  function syncBiModalOpenState() {
    var ins = document.getElementById("bi-cli-insight-modal");
    var tr = document.getElementById("bi-cli-treatable-modal");
    var dr = document.getElementById("bi-cli-drawer");
    var open =
      (ins && !ins.classList.contains("hidden")) ||
      (tr && !tr.classList.contains("hidden")) ||
      (dr && !dr.classList.contains("hidden"));
    if (open) document.body.classList.add("bi-modal-open");
    else document.body.classList.remove("bi-modal-open");
  }

  function truncateOneLine(s, max) {
    s = String(s || "").replace(/\s+/g, " ").trim();
    max = max || 140;
    if (!s) return "";
    if (s.length <= max) return s;
    return s.slice(0, max - 1) + "…";
  }

  function modalActionLine(row) {
    if (row.summary) return truncateOneLine(row.summary, 160);
    var h = row.hints;
    if (Array.isArray(h) && h[0]) return truncateOneLine(h[0], 160);
    var c = row.context;
    if (Array.isArray(c) && c[0]) return truncateOneLine(c[0], 160);
    if (row.action_recommendation) return truncateOneLine(row.action_recommendation, 160);
    return "Abrir ficha para ver contexto e sugestões completas.";
  }

  function fmtPctFromDeliveredReturned(row) {
    if (row.return_pct_planned != null && row.return_pct_planned !== "") return fmtPct(row.return_pct_planned);
    var d = Number(row.delivered_value || 0) + Number(row.returned_value || 0);
    if (d <= 0) return "—";
    return fmtPct((100 * Number(row.returned_value || 0)) / d);
  }

  function renderModalClientRow(row, profile) {
    var cid = row.client_id != null ? String(row.client_id) : "";
    var name = escapeHtml(row.client_name || "—");
    var sub =
      "NB " +
      escapeHtml(String(row.client_code || "—").trim() || "—") +
      " · " +
      escapeHtml(row.vendedor_name || "—");
    var cls = escapeHtml(row.classification_title || "—");
    var pct = fmtPctFromDeliveredReturned(row);
    var retMoney = fmtMoney(row.returned_value != null ? row.returned_value : 0);
    var motivo = escapeHtml(String(row.top_motivo_name || "—").trim() || "—");
    var actionSmall = escapeHtml(modalActionLine(row));

    var riskHtml = "";
    if (profile === "critical") {
      var rs = row.risk_score != null ? String(row.risk_score) : "—";
      riskHtml =
        '<span class="sys-badge sys-badge--critical shrink-0" title="Score de risco">Risco ' + escapeHtml(rs) + "</span>";
    } else if (profile === "large_risk") {
      riskHtml =
        '<span class="sys-badge sys-badge--alert shrink-0" title="% devolução (valor)">' + escapeHtml(pct) + "</span>";
    } else if (profile === "small_high") {
      var imp = Number(row.operational_impact || 0).toLocaleString("pt-BR", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
      riskHtml =
        '<span class="sys-badge sys-badge--alert shrink-0" title="Impacto operacional">Impacto ' + escapeHtml(imp) + "</span>";
    } else if (profile === "good") {
      var sc = row.cliente_score != null ? String(row.cliente_score) : "—";
      riskHtml = '<span class="sys-badge sys-badge--ok shrink-0">Score ' + escapeHtml(sc) + "</span>";
    } else if (profile === "treatable") {
      riskHtml =
        '<span class="sys-badge shrink-0 border-violet-300 bg-violet-50 text-violet-800 dark:border-violet-700 dark:bg-violet-950/50 dark:text-violet-200" title="Valor evitável (tratável)">' +
        escapeHtml(fmtMoney(row.treatable_returned_value || 0)) +
        "</span>";
    }

    var retChip = profile === "good" ? fmtMoney(row.delivered_value || 0) : retMoney;
    var retLabel = profile === "good" ? "Entregue" : "Devolv.";

    var openBtn = cid
      ? '<button type="button" class="sys-btn sys-btn--secondary bi-client-card-detail-btn shrink-0" data-bi-cli-open="' +
        escapeHtml(cid) +
        '">Abrir ficha</button>'
      : "";

    return (
      '<article class="bi-modal-client-row">' +
      '<div class="bi-modal-client-row__top">' +
      "<strong class=\"min-w-0 truncate\">" +
      name +
      "</strong>" +
      riskHtml +
      "</div>" +
      '<p class="bi-modal-client-row__sub">' +
      sub +
      "</p>" +
      '<div class="bi-modal-client-row__metrics">' +
      "<span title=\"Classificação\">" +
      cls +
      "</span>" +
      '<span title="% devolução (valor)">' +
      escapeHtml(pct) +
      "</span>" +
      '<span title="' +
      escapeHtml(retLabel) +
      '">' +
      escapeHtml(retChip) +
      "</span>" +
      '<span title="Motivo líder">' +
      motivo +
      "</span></div>" +
      '<div class="bi-modal-client-row__footer">' +
      "<small>" +
      actionSmall +
      "</small>" +
      openBtn +
      "</div></article>"
    );
  }

  function renderModalListInto(bodyEl, allRows, profile, shownCount) {
    if (!bodyEl) return;
    var limit =
      typeof shownCount === "number" && shownCount > 0 ? shownCount : MODAL_LIST_CHUNK;
    limit = Math.min(Math.max(limit, 0), allRows.length);
    var slice = allRows.slice(0, limit);
    var html = '<div class="bi-modal-client-list">';
    slice.forEach(function (row) {
      html += renderModalClientRow(row, profile);
    });
    html += "</div>";
    if (allRows.length > limit) {
      html +=
        '<div class="bi-modal-load-more flex justify-center pt-2">' +
        '<button type="button" class="sys-btn sys-btn--secondary h-8 px-3 text-xs" data-bi-cli-modal-more="1">Mostrar mais</button></div>';
    }
    bodyEl.innerHTML = html;
    var moreBtn = bodyEl.querySelector("[data-bi-cli-modal-more]");
    if (moreBtn) {
      moreBtn.addEventListener("click", function () {
        renderModalListInto(bodyEl, allRows, profile, limit + MODAL_LIST_CHUNK);
      });
    }
  }

  function isNarrowViewport() {
    return typeof window.matchMedia !== "undefined" && window.matchMedia("(max-width: 767px)").matches;
  }

  function isMobileView() {
    return isNarrowViewport();
  }

  function clearMobileCards() {
    var mobile = document.getElementById("bi-cli-cards-mobile");
    if (mobile) mobile.innerHTML = "";
  }

  function clearDesktopTableRows() {
    var tbody = document.getElementById("bi-cli-tbody");
    var tfoot = document.getElementById("bi-cli-tfoot");
    if (tbody) tbody.innerHTML = "";
    if (tfoot) tfoot.innerHTML = "";
  }

  function getEffectivePageSize() {
    if (typeof window.matchMedia === "undefined") return 25;
    return isNarrowViewport() ? 10 : 25;
  }

  function rankInitialVisible() {
    return isNarrowViewport() ? 5 : 12;
  }

  var RANK_MORE_STEP = 5;

  function syncPageSize() {
    var ps = getEffectivePageSize();
    if (state.pageSize === ps) return;
    state.pageSize = ps;
    var maxPage = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
    if (state.page > maxPage) state.page = maxPage;
    if (state.page < 1) state.page = 1;
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
    rankingVisibleCount: null,
    _lastNarrow: null,
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

  function returnCountOf(r) {
    if (r.return_count != null && r.return_count !== "") return Number(r.return_count) || 0;
    return Number(r.returned_occurrences) || 0;
  }

  function priorityBadgeClass(tone) {
    if (tone === "danger") return "sys-badge sys-badge--critical bi-cli-priority-badge";
    if (tone === "warn") return "sys-badge sys-badge--alert bi-cli-priority-badge";
    if (tone === "ok") return "sys-badge sys-badge--ok bi-cli-priority-badge";
    return "sys-badge sys-badge--neutral bi-cli-priority-badge";
  }

  function priorityBadgeHtml(r) {
    var label = r.priority_label || r.classification_title || "—";
    var tone = r.priority_tone || "neutral";
    return (
      '<span class="' +
      priorityBadgeClass(tone) +
      '" title="' +
      motTitle(label) +
      '">' +
      escapeHtml(label) +
      "</span>"
    );
  }

  function recurrencePctOf(r) {
    var visits = Number(r.visits) || 0;
    var rc = returnCountOf(r);
    var pct = Number(r.return_recurrence_pct);
    if (!isFinite(pct) && visits > 0) pct = (rc / visits) * 100;
    return isFinite(pct) ? pct : 0;
  }

  function recurrenceCellHtml(r) {
    var visits = Number(r.visits) || 0;
    var rc = returnCountOf(r);
    var label = r.recurrence_label || rc + " de " + visits + " visitas";
    var pct = recurrencePctOf(r);
    return (
      '<div class="bi-cli-recurrence">' +
      '<span class="block text-xs font-medium text-slate-800 dark:text-slate-100">' +
      escapeHtml(label) +
      "</span>" +
      (visits > 0
        ? '<span class="employees-text-muted block text-[10px] tabular-nums">' +
          escapeHtml(fmtPct(pct)) +
          " recorrência</span>"
        : '<span class="employees-text-muted block text-[10px]">—</span>') +
      "</div>"
    );
  }

  var RANK_TAB_SHOWS_TIME = { maior_tempo: true };
  var RANK_TAB_SHOWS_RECURRENCE = {
    maior_devolucao: true,
    maior_pct: true,
    baixo_volume_pct: true,
    pequeno_alto_impacto: true,
    grandes_risco: true,
    maior_compra: true,
    maior_tempo: true,
  };

  function detailBtnHtml(cid, compact) {
    if (!cid) return "";
    var cls = compact
      ? "sys-btn sys-btn--secondary bi-client-card-detail-btn shrink-0 h-7 px-2 text-[11px]"
      : "sys-btn sys-btn--secondary bi-client-card-detail-btn shrink-0";
    return (
      '<button type="button" class="' +
      cls +
      '" data-bi-cli-open="' +
      escapeHtml(String(cid)) +
      '">Detalhar</button>'
    );
  }

  function rankLeaderReason(r) {
    return r.leader_reason || r.top_motivo_name || "—";
  }

  function rankDominantResp(r) {
    return r.dominant_responsibility || r.top_responsabilidade_name || "—";
  }

  function buildRankMobileCard(r) {
    var cid = r.client_id != null ? String(r.client_id) : "";
    var visits = Number(r.visits) || 0;
    var rc = returnCountOf(r);
    return (
      '<article class="bi-rank-mobile-card">' +
      '<div class="bi-rank-mobile-card__head">' +
      '<div class="min-w-0 flex-1">' +
      '<strong class="bi-rank-mobile-card__name truncate">' +
      escapeHtml(r.client_name || "—") +
      "</strong>" +
      '<p class="bi-rank-mobile-card__code employees-text-muted">Cód. ' +
      escapeHtml(String(r.client_code || "—")) +
      "</p></div>" +
      priorityBadgeHtml(r) +
      "</div>" +
      '<div class="bi-rank-mobile-card__metrics" role="list">' +
      '<div class="bi-rank-mobile-card__metric" role="listitem"><span class="bi-cli-metric-lbl">Entregue</span><strong class="tabular-nums">' +
      fmtMoney(r.delivered_value) +
      "</strong></div>" +
      '<div class="bi-rank-mobile-card__metric" role="listitem"><span class="bi-cli-metric-lbl">Devolvido</span><strong class="tabular-nums">' +
      fmtMoney(r.returned_value) +
      "</strong></div>" +
      '<div class="bi-rank-mobile-card__metric" role="listitem"><span class="bi-cli-metric-lbl">% Dev.</span><strong class="tabular-nums">' +
      fmtPct(r.return_pct_planned) +
      "</strong></div>" +
      '<div class="bi-rank-mobile-card__metric" role="listitem"><span class="bi-cli-metric-lbl">Visitas</span><strong class="tabular-nums">' +
      visits +
      "</strong></div>" +
      '<div class="bi-rank-mobile-card__metric" role="listitem"><span class="bi-cli-metric-lbl">Devoluções</span><strong class="tabular-nums">' +
      rc +
      "</strong></div>" +
      '<div class="bi-rank-mobile-card__metric bi-rank-mobile-card__metric--wide" role="listitem"><span class="bi-cli-metric-lbl">Recorrência</span><strong class="text-xs font-medium">' +
      escapeHtml(r.recurrence_label || rc + " de " + visits + " visitas") +
      (visits > 0 ? ' <span class="employees-text-muted font-normal">' + fmtPct(recurrencePctOf(r)) + "</span>" : "") +
      "</strong></div></div>" +
      '<div class="bi-rank-mobile-card__foot">' +
      '<p class="bi-rank-mobile-card__meta truncate"><span class="bi-cli-metric-lbl">Motivo</span> ' +
      escapeHtml(rankLeaderReason(r)) +
      "</p>" +
      '<p class="bi-rank-mobile-card__meta truncate"><span class="bi-cli-metric-lbl">Responsável</span> ' +
      escapeHtml(rankDominantResp(r)) +
      "</p>" +
      (cid ? detailBtnHtml(cid, true) : "") +
      "</div></article>"
    );
  }

  function buildClientMobileCard(r) {
    var bcls = badgeClassForClient(r);
    var clsT = r.classification_title || "—";
    var visits = Number(r.visits) || 0;
    var rc = returnCountOf(r);
    var mot = r.top_motivo_name || "—";
    var resp = r.top_responsabilidade_name || "—";
    return (
      '<div class="bi-client-mobile-card__row1">' +
      '<strong class="bi-client-mobile-card__name truncate">' +
      escapeHtml(r.client_name) +
      "</strong>" +
      '<span class="bi-client-mobile-card__badge ' +
      bcls +
      ' max-w-[42%] shrink-0 truncate" title="' +
      motTitle(clsT) +
      '">' +
      escapeHtml(clsT) +
      "</span></div>" +
      '<p class="bi-client-mobile-card__sub employees-text-muted">Cód. ' +
      escapeHtml(r.client_code || "—") +
      " · " +
      escapeHtml(r.vendedor_name || "—") +
      "</p>" +
      '<div class="bi-client-mobile-card__metrics bi-client-mobile-card__metrics--consult" role="list">' +
      '<span role="listitem"><span class="bi-cli-metric-lbl">Entregue</span> ' +
      fmtMoney(r.delivered_value) +
      "</span>" +
      '<span role="listitem"><span class="bi-cli-metric-lbl">Devolvido</span> ' +
      fmtMoney(r.returned_value) +
      "</span>" +
      '<span role="listitem"><span class="bi-cli-metric-lbl">% Dev.</span> ' +
      fmtPct(r.return_pct_planned) +
      " " +
      trendBadgeHtml(r) +
      "</span>" +
      '<span role="listitem"><span class="bi-cli-metric-lbl">Visitas</span> ' +
      visits +
      "</span>" +
      '<span role="listitem"><span class="bi-cli-metric-lbl">Devoluções</span> ' +
      rc +
      "</span>" +
      '<span role="listitem" class="bi-client-mobile-card__metric-wide"><span class="bi-cli-metric-lbl">Recorrência</span> ' +
      escapeHtml(r.recurrence_label || rc + " de " + visits + " visitas") +
      (visits > 0 ? " · " + fmtPct(recurrencePctOf(r)) : "") +
      "</span>" +
      '<span role="listitem" class="bi-client-mobile-card__metric-wide"><span class="bi-cli-metric-lbl">Motivo</span> ' +
      escapeHtml(mot) +
      "</span>" +
      '<span role="listitem" class="bi-client-mobile-card__metric-wide"><span class="bi-cli-metric-lbl">Responsável</span> ' +
      escapeHtml(resp) +
      "</span>" +
      '<span role="listitem"><span class="bi-cli-metric-lbl">Score</span> ' +
      (r.cliente_score != null ? r.cliente_score : "—") +
      "</span></div>" +
      '<div class="bi-client-mobile-card__foot">' +
      detailBtnHtml(r.client_id, false) +
      "</div>"
    );
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

  function buildAutoActionSuggestion(row) {
    var parts = [];
    var motivo = String(row.top_motivo_name || "").trim();
    var occ = Number(row.returned_occurrences) || 0;
    var rv = Number(row.returned_value) || 0;
    var rp = Number(row.return_pct_planned) || 0;
    var avg = Number(row.avg_duration_m) || 0;
    var cls = String(row.classification_code || "").toUpperCase();
    if (motivo && motivo !== "\u2014" && occ > 0 && rv > 0) {
      parts.push(
        "Este cliente registrou " +
          occ +
          ' devolu\u00e7\u00e3o(\u00f5es) com motivo l\u00edder "' +
          motivo +
          '", totalizando ' +
          fmtMoney(rv) +
          " no per\u00edodo."
      );
    }
    if (row.suggested_action) parts.push(String(row.suggested_action).trim());
    if (rp > 5) parts.push("Agendar liga\u00e7\u00e3o comercial para alinhamento de expectativas (\u00edndice acima de 5%).");
    if (avg > 90) parts.push("Avaliar janela de entrega e sequ\u00eancia na rota (tempo m\u00e9dio acima de 90 min).");
    if (/pedido/i.test(motivo) && /err/i.test(motivo)) {
      parts.push("Revisar processo de separa\u00e7\u00e3o e confirmar o pedido 24h antes da entrega.");
    }
    if (cls === "CRITICO" || rp > 8) {
      parts.push("Avaliar viabilidade de manuten\u00e7\u00e3o na carteira com Comercial e Opera\u00e7\u00f5es.");
    }
    if (!parts.length) parts.push(row.action_recommendation || "Manter monitoramento e revisar na pr\u00f3xima rota.");
    return parts.join(" ");
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
    if (!tb && !cards) return;
    applyFilterSort();
    syncPageSize();
    var start = (state.page - 1) * state.pageSize;
    var pageRows = state.filtered.slice(start, start + state.pageSize);

    if (isMobileView()) {
      if (!cards) return;
      clearDesktopTableRows();

      var cfrag = document.createDocumentFragment();
      pageRows.forEach(function (r) {
        var d = document.createElement("article");
        d.className = "bi-client-mobile-card";
        d.innerHTML = buildClientMobileCard(r);
        cfrag.appendChild(d);
      });
      cards.innerHTML = "";
      cards.appendChild(cfrag);
    } else {
      if (!tb) return;
      clearMobileCards();

      var frag = document.createDocumentFragment();
      pageRows.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.className = rowClassForClient(r);
        var badgeCls = badgeClassForClient(r);
        var mot = r.top_motivo_name || "—";
        var resp = r.top_responsabilidade_name || "—";
        var clsTitle = r.classification_title || "—";
        tr.innerHTML =
          "<td class=\"max-w-[14rem]\"><div class=\"truncate font-medium\">" +
          escapeHtml(r.client_name) +
          "</div><div class=\"truncate text-[11px] text-slate-500\">" +
          escapeHtml(r.client_code || "—") +
          "</div></td>" +
          "<td class=\"max-w-[10rem] truncate\" title=\"" +
          motTitle(r.vendedor_name) +
          "\">" +
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
          " " +
          trendBadgeHtml(r) +
          "</td>" +
          "<td class=\"text-right tabular-nums\">" +
          (r.visits || 0) +
          "</td>" +
          "<td class=\"text-right tabular-nums\">" +
          returnCountOf(r) +
          "</td>" +
          "<td class=\"max-w-[9rem] truncate text-xs\" title=\"" +
          motTitle(mot) +
          "\">" +
          escapeHtml(mot) +
          "</td>" +
          "<td class=\"max-w-[8rem] truncate text-xs\" title=\"" +
          motTitle(resp) +
          "\">" +
          escapeHtml(resp) +
          "</td>" +
          "<td><span class=\"" +
          badgeCls +
          " bi-client-classification-badge max-w-[10rem] truncate text-[10px]\" title=\"" +
          motTitle(clsTitle) +
          "\">" +
          escapeHtml(clsTitle) +
          "</span></td>" +
          "<td class=\"text-right font-semibold tabular-nums\">" +
          (r.cliente_score != null ? r.cliente_score : "—") +
          "</td>" +
          "<td class=\"text-right\"><button type=\"button\" class=\"sys-btn sys-btn--secondary bi-client-card-detail-btn\" data-bi-cli-open=\"" +
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
          "<td class=\"text-right tabular-nums\">" +
          tt.visits +
          "</td>" +
          "<td></td>" +
          "<td colspan=\"5\"></td>";
      }
    }

    var metaText =
      "Mostrando " +
      (state.filtered.length === 0 ? 0 : start + 1) +
      " a " +
      Math.min(start + state.pageSize, state.filtered.length) +
      " de " +
      state.filtered.length +
      " · página " +
      state.page +
      " / " +
      Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
    document.querySelectorAll(".bi-cli-page-meta").forEach(function (el) {
      el.textContent = metaText;
    });
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
    if (sub) {
      var trend = trendBadgeHtml(row);
      sub.innerHTML =
        escapeHtml(row.client_code || "—") +
        " · " +
        escapeHtml(row.vendedor_name || "—") +
        " · " +
        escapeHtml(row.city || "—") +
        " · " +
        escapeHtml(row.status_operacional || "—") +
        " · " +
        escapeHtml(row.classification_title || "") +
        " · Score " +
        escapeHtml(row.cliente_score != null ? String(row.cliente_score) : "—") +
        (trend ? " · " + trend : "");
    }
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
    syncBiModalOpenState();
  }

  function closeDrawer() {
    var drawer = document.getElementById("bi-cli-drawer");
    if (drawer) {
      drawer.classList.add("hidden");
      drawer.setAttribute("aria-hidden", "true");
    }
    syncBiModalOpenState();
  }

  function routesForClient(cid) {
    return (state.routes || []).filter(function (r) {
      return String(r.client_id) === String(cid);
    });
  }

  function hasReturnTrendUp(row) {
    var hist = routesForClient(row.client_id)
      .slice()
      .sort(function (a, b) {
        return String(a.date || "").localeCompare(String(b.date || ""));
      });
    if (hist.length < 3) return false;
    var last3 = hist.slice(-3);
    var v0 = Number(last3[0].returned_value) || 0;
    var v1 = Number(last3[1].returned_value) || 0;
    var v2 = Number(last3[2].returned_value) || 0;
    return v0 < v1 && v1 < v2 && v2 > 0;
  }

  function trendBadgeHtml(row) {
    if (!hasReturnTrendUp(row)) return "";
    return '<span class="bi-cli-trend-badge" title="Devolu\u00e7\u00e3o crescente nas \u00faltimas 3 paradas da amostra">\u2191 Tend\u00eancia</span>';
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
        periodCompareHtml(row) +
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
          escapeHtml(fmtDateIsoToBr(h.date)) +
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
          escapeHtml(fmtDateIsoToBr(h.date)) +
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
        "<p class=\"bi-cli-auto-action rounded-lg border border-indigo-200/70 bg-indigo-50/50 p-3 text-sm leading-snug dark:border-indigo-800/50 dark:bg-indigo-950/30\">" +
        escapeHtml(buildAutoActionSuggestion(row)) +
        "</p>" +
        "<p class=\"mt-2 text-xs employees-text-muted\"><strong>Classifica\u00e7\u00e3o:</strong> " +
        escapeHtml(row.classification_title || "\u2014") +
        " \u00b7 <strong>Recomenda\u00e7\u00e3o:</strong> " +
        escapeHtml(row.action_recommendation || "Manter monitoramento.") +
        "</p>" +
        actionBlocksHtml() +
        '<div class="mt-3 flex flex-wrap gap-2">' +
        '<button type="button" class="sys-btn sys-btn--secondary h-8 px-2 text-xs" id="bi-cli-wa-btn">Copiar resumo</button>' +
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
    var period =
      df && dt && df.value && dt.value
        ? fmtDateIsoToBr(df.value) + " a " + fmtDateIsoToBr(dt.value)
        : "(ver filtros)";
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
    var mount = document.getElementById("bi-cli-charts-mount");
    if (!mount || window.getComputedStyle(mount).display === "none") return;
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
            return fmtDateIsoToBr(x.date);
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
              y: { title: { display: true, text: "% devolução sobre o planejado" } },
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
    requestAnimationFrame(function () {
      ["biCliChartDaily", "biCliChartParetoMotivos", "biCliChartMatrix", "biCliChartResp"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el && Chart.getChart) {
          var ch = Chart.getChart(el);
          if (ch) ch.resize();
        }
      });
    });
  }

  function scheduleMountCharts() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        mountCharts();
      });
    });
  }

  function revealChartsMount() {
    var mount = document.getElementById("bi-cli-charts-mount");
    if (!mount) return;
    mount.classList.add("is-loaded");
    mount.classList.remove("hidden");
  }

  function initChartsIfNeeded() {
    var isMd = typeof window.matchMedia !== "undefined" && window.matchMedia("(min-width: 768px)").matches;
    if (!isMd) return;
    revealChartsMount();
    scheduleMountCharts();
  }

  function initChartsWhenVisible() {
    var section = document.getElementById("bi-cli-visual-section");
    if (!section || typeof IntersectionObserver === "undefined") {
      initChartsIfNeeded();
      return;
    }
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          revealChartsMount();
          scheduleMountCharts();
          observer.disconnect();
        });
      },
      { rootMargin: "120px 0px", threshold: 0.05 }
    );
    observer.observe(section);
    var rect = section.getBoundingClientRect();
    if (rect.top < window.innerHeight + 120 && rect.bottom > -120) {
      revealChartsMount();
      scheduleMountCharts();
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
          state.rankingVisibleCount = rankInitialVisible();
          tabsEl.querySelectorAll(".bi-client-tab").forEach(function (x) {
            x.classList.toggle("is-active", x.getAttribute("data-rank-tab") === t.key);
          });
          renderRankingPanel();
        });
        tabsEl.appendChild(b);
      });
    }
    if (state.rankingVisibleCount == null) state.rankingVisibleCount = rankInitialVisible();
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
    var total = rows.length;
    var visible = Math.min(total, Math.max(1, state.rankingVisibleCount));
    var slice = rows.slice(0, visible);
    var meta =
      '<p class="bi-cli-rank-shown-meta employees-text-muted mb-2 text-xs tabular-nums">Mostrando ' +
      visible +
      " de " +
      total +
      "</p>";
    var mobile = isNarrowViewport();
    var bodyHtml = "";

    if (mobile) {
      bodyHtml += '<div class="bi-cli-rank-mobile-list">';
      slice.forEach(function (r) {
        bodyHtml += buildRankMobileCard(r);
      });
      bodyHtml += "</div>";
    } else {
      var showTime = !!RANK_TAB_SHOWS_TIME[state.rankingTabKey];
      bodyHtml +=
        '<div class="sys-table-wrap"><table class="sys-data-table text-xs bi-cli-rank-table"><thead><tr>' +
        "<th>Cliente</th>" +
        '<th class="text-right">Entregue</th>' +
        '<th class="text-right">Devolvido</th>' +
        '<th class="text-right">% Dev.</th>' +
        '<th class="text-right">Visitas</th>' +
        '<th class="text-right">Devoluções</th>' +
        "<th>Recorrência</th>" +
        (showTime ? '<th class="text-right">Tempo médio</th>' : "") +
        "<th>Motivo líder</th>" +
        "<th>Responsável</th>" +
        '<th class="text-right bi-cli-rank-table__action">Ação</th>' +
        "</tr></thead><tbody>";
      slice.forEach(function (r) {
        var cid = r.client_id != null ? String(r.client_id) : "";
        var visits = Number(r.visits) || 0;
        var rc = returnCountOf(r);
        bodyHtml +=
          "<tr>" +
          '<td class="bi-cli-rank-table__client max-w-[11rem]">' +
          '<div class="truncate font-medium">' +
          escapeHtml(r.client_name || "—") +
          "</div>" +
          '<div class="truncate text-[10px] text-slate-500">' +
          escapeHtml(String(r.client_code || "—")) +
          "</div>" +
          '<div class="mt-1">' +
          priorityBadgeHtml(r) +
          "</div></td>" +
          '<td class="text-right tabular-nums whitespace-nowrap">' +
          fmtMoney(r.delivered_value) +
          "</td>" +
          '<td class="text-right tabular-nums whitespace-nowrap">' +
          fmtMoney(r.returned_value) +
          "</td>" +
          '<td class="text-right tabular-nums whitespace-nowrap">' +
          fmtPct(r.return_pct_planned) +
          "</td>" +
          '<td class="text-right tabular-nums">' +
          visits +
          "</td>" +
          '<td class="text-right tabular-nums">' +
          rc +
          "</td>" +
          '<td class="max-w-[8rem]">' +
          recurrenceCellHtml(r) +
          "</td>" +
          (showTime
            ? '<td class="text-right tabular-nums whitespace-nowrap">' + fmtDur(r.avg_duration_m) + "</td>"
            : "") +
          '<td class="max-w-[9rem] truncate text-xs" title="' +
          motTitle(rankLeaderReason(r)) +
          '">' +
          escapeHtml(rankLeaderReason(r)) +
          "</td>" +
          '<td class="max-w-[8rem] truncate text-xs" title="' +
          motTitle(rankDominantResp(r)) +
          '">' +
          escapeHtml(rankDominantResp(r)) +
          "</td>" +
          '<td class="text-right bi-cli-rank-table__action">' +
          (cid ? detailBtnHtml(cid, true) : "") +
          "</td></tr>";
      });
      bodyHtml += "</tbody></table></div>";

    }

    var moreHtml = "";
    if (visible < total) {
      moreHtml =
        '<div class="mt-3 flex justify-center">' +
        '<button type="button" class="bi-cli-rank-more sys-btn sys-btn--secondary h-8 px-3 text-xs">Ver mais do ranking</button></div>';
    }

    panel.innerHTML = hint + meta + bodyHtml + moreHtml;
    var moreBtn = panel.querySelector(".bi-cli-rank-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", function () {
        state.rankingVisibleCount = Math.min(total, visible + RANK_MORE_STEP);
        renderRankingPanel();
      });
    }
  }

  function boot() {
    state.rows = readJson("bi-cli-intel-json") || [];
    state.routes = readJson("bi-cli-routes-json") || [];
    state.page = 1;
    state.pageSize = getEffectivePageSize();
    state._lastNarrow = isNarrowViewport();
    state.rankingVisibleCount = rankInitialVisible();

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

    function goPrev() {
      if (state.page > 1) {
        state.page--;
        renderTable();
      }
    }
    function goNext() {
      var maxPage = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
      if (state.page < maxPage) {
        state.page++;
        renderTable();
      }
    }
    document.querySelectorAll(".bi-cli-prev").forEach(function (el) {
      el.onclick = goPrev;
    });
    document.querySelectorAll(".bi-cli-next").forEach(function (el) {
      el.onclick = goNext;
    });

    var onResize = debounce(function () {
      var beforePs = state.pageSize;
      var beforeNarrow = state._lastNarrow;
      syncPageSize();
      var narrow = isNarrowViewport();
      var listNeedsRerender = narrow !== beforeNarrow || beforePs !== state.pageSize;
      if (narrow !== beforeNarrow) {
        state._lastNarrow = narrow;
        state.rankingVisibleCount = rankInitialVisible();
        renderRankingPanel();
        state.page = 1;
      }
      if (listNeedsRerender) renderTable();
      if (!narrow) initChartsIfNeeded();
    }, 150);
    window.addEventListener("resize", onResize);

    document.querySelectorAll("[data-bi-cli-close]").forEach(function (b) {
      b.addEventListener("click", closeDrawer);
    });

    function readJsonArray(id) {
      var v = readJson(id);
      return Array.isArray(v) ? v : [];
    }

    function closeTreatableModal() {
      var m = document.getElementById("bi-cli-treatable-modal");
      if (!m) return;
      m.classList.add("hidden");
      m.setAttribute("aria-hidden", "true");
      syncBiModalOpenState();
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
        renderModalListInto(body, rows, "treatable");
      }
      m.classList.remove("hidden");
      m.setAttribute("aria-hidden", "false");
      syncBiModalOpenState();
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
      syncBiModalOpenState();
    }

    function openInsightModal(title, html, subtext) {
      var m = document.getElementById("bi-cli-insight-modal");
      var t = document.getElementById("bi-cli-insight-title");
      var body = document.getElementById("bi-cli-insight-body");
      var sub = document.getElementById("bi-cli-insight-sub");
      if (!m || !t || !body) return;
      t.textContent = title || "Detalhe";
      if (typeof html === "function") html(body);
      else body.innerHTML = html || "";
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
      syncBiModalOpenState();
    }

    function openCriticalListModal() {
      var rows = readJsonArray("bi-cli-critical-json");
      if (!rows.length) {
        openInsightModal("Clientes críticos", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum cliente crítico neste recorte.</p>", null);
        return;
      }
      openInsightModal("Clientes críticos (" + rows.length + ")", function (body) {
        renderModalListInto(body, rows, "critical");
      }, null);
    }

    function openLargeRiskListModal() {
      var rows = readJsonArray("bi-cli-large-risk-json");
      if (!rows.length) {
        openInsightModal("Alto valor com risco", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum caso neste recorte.</p>", null);
        return;
      }
      openInsightModal("Alto valor com risco (" + rows.length + ")", function (body) {
        renderModalListInto(body, rows, "large_risk");
      }, null);
    }

    function openSmallHighListModal() {
      var rows = readJsonArray("bi-cli-small-high-json");
      if (!rows.length) {
        openInsightModal("Pequeno cliente, grande impacto", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum caso neste recorte.</p>", null);
        return;
      }
      openInsightModal("Pequeno cliente, grande impacto (" + rows.length + ")", function (body) {
        renderModalListInto(body, rows, "small_high");
      }, null);
    }

    function openGoodListModal() {
      var rows = readJsonArray("bi-cli-good-json");
      if (!rows.length) {
        openInsightModal("Clientes bons", "<p class=\"employees-text-muted py-4 text-center text-sm\">Nenhum cliente neste perfil.</p>", null);
        return;
      }
      openInsightModal("Melhores clientes (" + rows.length + ")", function (body) {
        renderModalListInto(body, rows, "good");
      }, null);
    }

    document.querySelectorAll("[data-bi-cli-insight-close]").forEach(function (b) {
      b.addEventListener("click", closeInsightModal);
    });

    function wireListModalLayerDismiss() {
      function wire(shellId, closeFn) {
        var shell = document.getElementById(shellId);
        if (!shell) return;
        var layer = shell.querySelector(".bi-cli-modal-shell__layer--list");
        if (!layer) return;
        layer.addEventListener("click", function (e) {
          if (e.target !== layer) return;
          closeFn();
        });
      }
      wire("bi-cli-treatable-modal", closeTreatableModal);
      wire("bi-cli-insight-modal", closeInsightModal);
    }
    wireListModalLayerDismiss();

    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      var ins = document.getElementById("bi-cli-insight-modal");
      if (ins && !ins.classList.contains("hidden")) {
        closeInsightModal();
        return;
      }
      var modal = document.getElementById("bi-cli-treatable-modal");
      if (modal && !modal.classList.contains("hidden")) {
        closeTreatableModal();
        return;
      }
      var dr = document.getElementById("bi-cli-drawer");
      if (dr && !dr.classList.contains("hidden")) closeDrawer();
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
        revealChartsMount();
        chartsBtn.classList.add("hidden");
        scheduleMountCharts();
      });
    }

    var rankCollapse = document.getElementById("bi-cli-rank-collapse-btn");
    var rankBody = document.getElementById("bi-cli-rank-body");
    if (rankCollapse && rankBody) {
      rankCollapse.addEventListener("click", function () {
        var collapsed = rankBody.classList.toggle("bi-cli-rank-body--collapsed");
        rankCollapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
        rankCollapse.textContent = collapsed ? "Expandir ranking" : "Recolher ranking";
      });
    }

    renderRankingPanel();
    renderTable();
    initChartsWhenVisible();

    if (typeof window.matchMedia !== "undefined") {
      window.matchMedia("(min-width: 768px)").addEventListener("change", function (ev) {
        if (!chartsMount) return;
        if (ev.matches) {
          revealChartsMount();
          if (!state.chartsBound) scheduleMountCharts();
        }
      });
    }
  }

  window.BiClientesPage = { boot: boot };
})();
