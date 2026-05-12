(function () {
  "use strict";

  var root = document.querySelector('[data-page="vacation-planning"]');
  if (!root) return;

  var INITIAL_TABLE_LIMIT = 16;
  var employeeOptionsFull = [];
  var cachedRows = [];
  var activeFilter = "critical";
  var showAllRows = false;
  var queueSearchRaw = "";
  var queueSearchDebounced = "";
  var queueSearchTimer = null;
  var SEARCH_DEBOUNCE_MS = 280;
  var queueRowClickBound = false;
  var immediateActionIdSet = new Set();

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function historyCadastroLabel(h) {
    if (h && h.cadastro_sync_label) {
      var s = String(h.cadastro_sync_label);
      if (/histórico|importação|planilha/i.test(s) && !/^sim/i.test(s)) return "Histórico";
      return s;
    }
    return h && h.employee_vacation_synced
      ? "Sim — cadastro atualizado"
      : "Não — apenas planejamento";
  }

  /** yyyy-mm-dd ou prefixo → dd/mm/aaaa */
  function formatDateBR(iso) {
    if (!iso || typeof iso !== "string") return "—";
    var d = iso.slice(0, 10);
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
    if (!m) return iso;
    return m[3] + "/" + m[2] + "/" + m[1];
  }

  /** ISO datetime → dd/mm/aaaa às HH:mm */
  function formatDateTimeBR(iso) {
    if (!iso || typeof iso !== "string") return "—";
    var t = iso.replace("T", " ").replace(/\.\d{3}Z?$/, "").trim();
    var datePart = t.slice(0, 10);
    var timePart = t.slice(11, 16);
    if (timePart && /^\d{2}:\d{2}$/.test(timePart)) {
      return formatDateBR(datePart) + " às " + timePart;
    }
    return formatDateBR(datePart);
  }

  function displayVacationStatusPt(code) {
    var s = String(code || "").trim().toLowerCase();
    if (s === "approved") return "Aprovado";
    if (s === "suggested") return "Sugerido";
    if (s === "cancelled" || s === "canceled") return "Cancelado";
    if (s === "pending") return "Pendente";
    return code ? String(code) : "—";
  }

  function displayVacationSourcePt(code) {
    var s = String(code || "").trim().toLowerCase();
    if (s === "planilha") return "Planilha";
    if (s === "manual") return "Manual";
    if (s === "system") return "Sistema";
    return code ? String(code) : "—";
  }

  function formatMonthYearBR(year, month) {
    var names = [
      "",
      "Janeiro",
      "Fevereiro",
      "Março",
      "Abril",
      "Maio",
      "Junho",
      "Julho",
      "Agosto",
      "Setembro",
      "Outubro",
      "Novembro",
      "Dezembro",
    ];
    var mi = parseInt(month, 10) || 1;
    var y = parseInt(year, 10);
    if (isNaN(y)) return "—";
    return (names[mi] || String(mi)) + "/" + y;
  }

  function fmtIntPt(v) {
    if (v == null || v === "") return "—";
    var n = Number(v);
    if (isNaN(n)) return String(v);
    return String(Math.round(n));
  }

  /** Dias corridos entre início e fim (inclusive). */
  function inclusiveCalendarDays(startIso, endIso) {
    if (!startIso || !endIso) return null;
    var a = new Date(startIso + "T12:00:00");
    var b = new Date(endIso + "T12:00:00");
    if (isNaN(a.getTime()) || isNaN(b.getTime()) || b < a) return null;
    return Math.round((b - a) / 864e5) + 1;
  }

  /** yyyy-mm-dd a partir de Date em fuso local (evita deslocar dia com toISOString/UTC). */
  function toIsoDateLocal(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  /** Primeiro dia do mês em foco na página (vp-year / vp-month); fallback hoje. */
  function defaultVacationStartIsoFromOverview() {
    var yEl = byId("vp-year");
    var mEl = byId("vp-month");
    var y = parseInt(yEl && yEl.value, 10);
    var m = parseInt(mEl && mEl.value, 10);
    if (!y || isNaN(y) || !m || isNaN(m) || m < 1 || m > 12) {
      return toIsoDateLocal(new Date());
    }
    return y + "-" + String(m).padStart(2, "0") + "-01";
  }

  /** Soma dias corridos a uma data ISO (yyyy-mm-dd). */
  function addCalendarDaysIso(iso, deltaDays) {
    var d = new Date(iso + "T12:00:00");
    if (isNaN(d.getTime())) return "";
    d.setDate(d.getDate() + deltaDays);
    return toIsoDateLocal(d);
  }

  function updateVacationLegalHint() {
    var startEl = byId("vp-sim-start");
    var endEl = byId("vp-sim-end");
    var panel = byId("vp-vacation-legal-hint");
    var wrap = byId("vp-abono-wrap");
    var cb = byId("vp-abono-10");
    if (!panel || !startEl || !endEl) return;
    var start = startEl.value;
    var end = endEl.value;
    var days = inclusiveCalendarDays(start, end);
    panel.classList.remove(
      "vp-vacation-legal-hint--ok",
      "vp-vacation-legal-hint--warn",
      "vp-vacation-legal-hint--info"
    );
    if (days == null) {
      panel.classList.add("hidden");
      panel.innerHTML = "";
      if (wrap) wrap.classList.add("hidden");
      if (cb) cb.checked = false;
      updateLaunchDaysLine();
      return;
    }
    var rem = 30 - days;
    if (cb && rem !== 10) cb.checked = false;
    if (wrap) wrap.classList.toggle("hidden", rem !== 10);

    if (days > 30) {
      panel.classList.remove("hidden");
      panel.classList.add("vp-vacation-legal-hint--info");
      panel.innerHTML =
        "<strong>" +
        escapeHtml(String(days)) +
        " dias corridos.</strong> Acima dos 30 dias padrão de férias (CLT); confirme com RH/DP (coletivas, regime diferenciado, etc.).";
      updateLaunchDaysLine();
      return;
    }
    if (days === 30) {
      panel.classList.remove("hidden");
      panel.classList.add("vp-vacation-legal-hint--ok");
      panel.innerHTML =
        "<strong>30 dias corridos.</strong> Equivale ao gozo integral típico (sem venda da 1ª fração de 1/3 como abono pecuniário).";
      updateLaunchDaysLine();
      return;
    }
    panel.classList.remove("hidden");
    panel.classList.add("vp-vacation-legal-hint--warn");
    var html =
      "<strong>" +
      escapeHtml(String(days)) +
      " dias corridos.</strong> Faltam <strong>" +
      escapeHtml(String(rem)) +
      "</strong> dia(s) para completar os <strong>30 dias</strong> de férias previstos na CLT.";
    if (rem === 10) {
      html +=
        " Em geral, esses <strong>10 dias</strong> são tratados como <strong>abono pecuniário</strong> (conversão em dinheiro / venda de 1/3) e o gozo efetivo fica em <strong>20 dias</strong> corridos. Marque a opção abaixo se for este o caso, após acordo formal e orientação de RH/DP.";
    } else {
      html +=
        " Ajuste a data final, trate <strong>fracionamento de férias</strong> ou alinhe com RH/DP (o abono pecuniário na 1ª parcela é limitado a <strong>10 dias</strong>).";
    }
    panel.innerHTML = html;
    updateLaunchDaysLine();
  }

  function updateLaunchDaysLine() {
    var el = byId("vp-launch-days-line");
    var stEl = byId("vp-sim-start");
    var enEl = byId("vp-sim-end");
    if (!el || !stEl || !enEl) return;
    var start = stEl.value;
    var end = enEl.value;
    if (!start || !end) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    var d1 = new Date(start + "T12:00:00");
    var d2 = new Date(end + "T12:00:00");
    if (isNaN(d1.getTime()) || isNaN(d2.getTime()) || d2 < d1) {
      el.classList.remove("hidden");
      el.textContent = "Período inválido: a data fim deve ser igual ou posterior ao início.";
      el.classList.add("text-rose-600", "dark:text-rose-300");
      return;
    }
    el.classList.remove("text-rose-600", "dark:text-rose-300");
    var days = inclusiveCalendarDays(start, end);
    if (days == null) {
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    el.textContent = "Resumo: " + days + " dias corridos";
  }

  function buildScheduleReasonFromForm() {
    var base = (byId("vp-schedule-reason") && byId("vp-schedule-reason").value) || "";
    base = base.trim();
    var parts = [];
    if (base) parts.push(base);
    var cb = byId("vp-abono-10");
    if (cb && cb.checked) {
      parts.push(
        "Abono pecuniário (10 dias / 1/3): declarado neste lançamento — conforme acordo com colaborador e CLT/RH."
      );
    }
    return parts.length ? parts.join(" | ") : null;
  }

  function showAlert(msg, level) {
    var el = byId("vp-alert");
    if (!el) return;
    el.className =
      "sys-alert flex items-center gap-3 " +
      (level === "error" ? "sys-alert--danger" : "sys-alert--success");
    el.textContent = msg;
    el.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function hideAlert() {
    var el = byId("vp-alert");
    if (!el) return;
    el.classList.add("hidden");
    el.textContent = "";
  }

  function currentYear() {
    return new Date().getFullYear();
  }

  function currentMonth() {
    return new Date().getMonth() + 1;
  }

  function qs() {
    var y = byId("vp-year").value || currentYear();
    var cc = byId("vp-cost-center").value || "Todos";
    var m = parseInt(byId("vp-month").value, 10) || currentMonth();
    return { year: y, cost_center: cc, month: m };
  }

  function statusClass(c) {
    if (c === "green") return "vp-status-dot vp-status-dot--green";
    if (c === "red") return "vp-status-dot vp-status-dot--red";
    return "vp-status-dot vp-status-dot--yellow";
  }

  function windowColorLabelPt(c) {
    if (c === "green") return "Verde";
    if (c === "red") return "Vermelho";
    if (c === "yellow") return "Amarelo";
    return c ? String(c) : "—";
  }

  function stripClassForColor(c) {
    var strip = byId("vp-month-strip");
    if (!strip) return;
    strip.classList.remove("vp-month-strip--green", "vp-month-strip--yellow", "vp-month-strip--red");
    if (c === "green") strip.classList.add("vp-month-strip--green");
    else if (c === "red") strip.classList.add("vp-month-strip--red");
    else strip.classList.add("vp-month-strip--yellow");
  }

  function renderMonthStrip(data) {
    var m = qs().month;
    var sit = data.month_situation;
    if (!sit) {
      sit = buildMonthSituationFallback(data, m);
    }
    var color = sit.status_color || "yellow";
    stripClassForColor(color);
    var hl = document.getElementById("vp-strip-headline");
    if (hl) {
      hl.textContent =
        (sit.month_name || String(m)) +
        "/" +
        (sit.year != null ? sit.year : data.year || qs().year);
    }
    var stl = document.getElementById("vp-strip-decision");
    if (stl) {
      stl.textContent =
        "Status: " + (sit.operational_headline || sit.decision_label || "—");
    }
    byId("vp-strip-risk").textContent = fmtIntPt(sit.operational_risk);
    byId("vp-strip-cap").textContent = fmtIntPt(sit.capacity_hint);
    var schedShow =
      sit.scheduled_gozo_count != null ? sit.scheduled_gozo_count : sit.scheduled_count;
    byId("vp-strip-sched").textContent = fmtIntPt(schedShow);
    var dueEl = document.getElementById("vp-strip-due");
    if (dueEl) dueEl.textContent = fmtIntPt(sit.due_deadlines_in_month);
    var critEl = document.getElementById("vp-strip-critical");
    if (critEl) critEl.textContent = fmtIntPt(sit.critical_roles_count);
    byId("vp-strip-guidance").textContent =
      sit.guidance_text || "Sem orientação para este mês.";
  }

  function buildMonthSituationFallback(data, calMonth) {
    var monthly = data.monthly || [];
    var mr = monthly[calMonth - 1] || {};
    var k = data.kpis || {};
    var cap = Math.max(1, parseInt(mr.capacity_hint, 10) || 1);
    var sched = parseInt(mr.scheduled_count, 10) || 0;
    var load = sched / cap;
    var base = mr.status_color || "yellow";
    var situation = base;
    if (load >= 1) situation = "red";
    else if (load >= 0.82 && base === "green") situation = "yellow";
    var decision_key = "aprovado";
    if (base === "red" || situation === "red") decision_key = "nao_recomendado";
    else if (base === "yellow" || situation === "yellow" || load >= 0.72) decision_key = "atencao";
    var labels = { aprovado: "Recomendado", atencao: "Atenção", nao_recomendado: "Não recomendado" };
    var mn = mr.month_name || String(calMonth);
    var y = data.year || qs().year;
    var g =
      (decision_key === "aprovado"
        ? mn + "/" + y + " tende a ser favorável."
        : decision_key === "atencao"
          ? mn + "/" + y + " exige atenção à cobertura."
          : mn + "/" + y + " é desafiador para novas férias.") +
      " Capacidade ~" +
      cap +
      "; " +
      sched +
      " programadas.";
    var opHead =
      decision_key === "nao_recomendado" || load >= 1
        ? "Travado"
        : decision_key === "atencao" || load >= 0.72
          ? "Atenção"
          : "Livre";
    return {
      month: calMonth,
      month_name: mn,
      year: y,
      status_color: situation,
      decision_key: decision_key,
      decision_label: labels[decision_key] || decision_key,
      operational_headline: opHead,
      operational_risk: k.operational_risk_month,
      capacity_hint: cap,
      scheduled_count: sched,
      due_deadlines_in_month: parseInt(mr.due_deadlines_count, 10) || 0,
      scheduled_gozo_count: sched,
      scheduled_unique_employees: sched,
      critical_roles_count: 0,
      guidance_text: g,
    };
  }

  function renderYearGrid(data) {
    var grid = byId("vp-year-grid");
    if (!grid) return;
    var sel = qs().month;
    var bestM =
      data.month_situation && data.month_situation.best_month != null
        ? parseInt(data.month_situation.best_month, 10)
        : null;
    grid.innerHTML = "";
    (data.monthly || []).forEach(function (row) {
      var m = row.month;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "vp-month-card";
      if (m === sel) btn.classList.add("vp-month-card--selected");
      if (bestM && m === bestM && m !== sel) btn.classList.add("vp-month-card--best");
      var st = row.status_color || "yellow";
      var stLabel = st === "green" ? "Verde" : st === "red" ? "Vermelho" : "Amarelo";
      var dueN = row.due_deadlines_count != null ? row.due_deadlines_count : "—";
      var rlim = row.roles_at_limit_count != null ? row.roles_at_limit_count : "—";
      btn.innerHTML =
        '<span class="vp-month-card__name-row">' +
        '<span class="vp-month-card__name">' +
        escapeHtml(row.month_name) +
        "</span>" +
        (bestM && m === bestM
          ? '<span class="vp-month-card__best">Melhor opção</span>'
          : "") +
        "</span>" +
        '<p class="vp-month-card__demand">' +
        escapeHtml(row.demand_label || "") +
        " demanda</p>" +
        '<p class="vp-month-card__nums tabular-nums">' +
        (row.scheduled_count != null ? row.scheduled_count : "—") +
        "/" +
        (row.capacity_hint != null ? row.capacity_hint : "—") +
        " programadas · " +
        escapeHtml(String(dueN)) +
        " venc. no mês · " +
        escapeHtml(String(rlim)) +
        " funções no limite</p>" +
        '<span class="vp-month-card__status"><span class="' +
        statusClass(st) +
        '"></span>' +
        escapeHtml(stLabel) +
        "</span>";
      btn.addEventListener("click", function () {
        byId("vp-month").value = String(m);
        loadOverview();
      });
      grid.appendChild(btn);
    });
  }

  function renderImmediateBlocks(data) {
    var list = byId("vp-action-list");
    var empty = byId("vp-action-empty");
    if (!list) return;
    var items = data.immediate_actions || [];
    list.innerHTML = "";
    if (!items.length) {
      if (empty) empty.classList.remove("hidden");
      return;
    }
    if (empty) empty.classList.add("hidden");
    items.forEach(function (a) {
      var row = document.createElement("div");
      row.className = "vp-action-card";
      var risk = a.risk_level || "baixo";
      var riskClass =
        risk === "alto"
          ? "vp-action-risk vp-action-risk--high"
          : risk === "medio"
            ? "vp-action-risk vp-action-risk--mid"
            : "vp-action-risk vp-action-risk--low";
      var d = a.days_until_deadline;
      var prazo =
        d == null
          ? "—"
          : d < 0
            ? "Vencido há " + Math.min(Math.abs(d), 999) + "d"
            : "Vence em " + d + "d";
      row.innerHTML =
        "<div class=\"vp-action-card__grid\">" +
        "<div class=\"vp-action-card__main\">" +
        "<div class=\"vp-action-card__row1\">" +
        "<strong class=\"vp-action-card__name\">" +
        escapeHtml(a.name || "") +
        "</strong>" +
        "<span class=\"" +
        riskClass +
        "\">" +
        escapeHtml(
          risk === "alto" ? "Risco alto" : risk === "medio" ? "Risco médio" : "Risco baixo",
        ) +
        "</span></div>" +
        "<p class=\"vp-action-card__meta\">" +
        escapeHtml(a.role || "—") +
        " · " +
        escapeHtml(a.sector || "—") +
        "</p>" +
        "<p class=\"vp-action-card__prazo\"><span class=\"text-slate-500\">Prazo:</span> " +
        escapeHtml(prazo) +
        "</p>" +
        "<p class=\"vp-action-card__hint\"><span class=\"text-slate-500\">Último gozo:</span> " +
        escapeHtml(a.last_vacation_end ? formatDateBR(a.last_vacation_end) : "—") +
        " · <span class=\"text-slate-500\">Janela sugerida:</span> " +
        escapeHtml(a.best_period_hint || "—") +
        "</p></div>" +
        "<div class=\"vp-action-card__actions\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--primary text-xs px-3 py-2 vp-action-launch\" data-eid=\"" +
        escapeHtml(String(a.employee_id)) +
        "\">Lançar</button>" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary text-xs px-3 py-2 vp-action-sim\" data-eid=\"" +
        escapeHtml(String(a.employee_id)) +
        "\">Simular</button>" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary text-xs px-2 py-2 vp-action-det\" data-eid=\"" +
        escapeHtml(String(a.employee_id)) +
        "\">Detalhes</button></div></div>";
      list.appendChild(row);
    });
    list.querySelectorAll(".vp-action-launch").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = parseInt(btn.getAttribute("data-eid"), 10);
        if (id) openLaunchModal(id, { clearDates: true, focusStart: true });
      });
    });
    list.querySelectorAll(".vp-action-sim").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = parseInt(btn.getAttribute("data-eid"), 10);
        if (id) openLaunchModal(id, { clearDates: true, focusStart: true });
      });
    });
    list.querySelectorAll(".vp-action-det").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = parseInt(btn.getAttribute("data-eid"), 10);
        var found = (cachedRows || []).find(function (r) {
          return r.employee_id === id;
        });
        if (found) openDetailModal(found);
      });
    });
  }

  function scheduledCadastroShort(r) {
    if (r && r.employee_vacation_synced) return "Sim";
    var src = (r && r.source) ? String(r.source).toLowerCase() : "";
    if (src === "planilha") return "Histórico";
    return "Não";
  }

  function renderScheduledInMonth(data) {
    var tb = byId("vp-scheduled-body");
    var cap = byId("vp-scheduled-caption");
    var empty = byId("vp-scheduled-empty");
    if (!tb) return;
    var rows = data.scheduled_in_month_detail || [];
    var stats = data.scheduled_in_month_stats || {};
    var q = qs();
    if (cap) {
      cap.textContent =
        "Gozos aprovados em " + formatMonthYearBR(q.year, q.month) + " (sem duplicatas de período).";
    }
    var gEl = byId("vp-sched-st-gozos");
    if (gEl) gEl.textContent = String(stats.gozo_count != null ? stats.gozo_count : rows.length);
    var pEl = byId("vp-sched-st-people");
    if (pEl) pEl.textContent = String(stats.unique_employees != null ? stats.unique_employees : "—");
    var rEl = byId("vp-sched-st-roles");
    if (rEl) rEl.textContent = String(stats.unique_roles != null ? stats.unique_roles : "—");
    var aEl = byId("vp-sched-st-avg");
    if (aEl) aEl.textContent = stats.avg_days != null ? String(stats.avg_days) : "—";
    var sEl = byId("vp-sched-st-src");
    if (sEl) {
      var br = stats.sources_breakdown || {};
      var parts = Object.keys(br).map(function (k) {
        return displayVacationSourcePt(k) + ": " + br[k];
      });
      sEl.textContent = parts.length ? parts.join(" · ") : "—";
    }
    tb.innerHTML = "";
    if (!rows.length) {
      if (empty) empty.classList.remove("hidden");
      return;
    }
    if (empty) empty.classList.add("hidden");
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.className =
        "employees-data-table__row border-b border-slate-100 dark:border-slate-800";
      var cad = scheduledCadastroShort(r);
      var eid = r.employee_id != null ? String(r.employee_id) : "";
      tr.innerHTML =
        "<td class=\"employees-data-table__cell px-3 py-2\">" +
        escapeHtml(r.name || "") +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-xs\">" +
        escapeHtml(r.role || "") +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-xs whitespace-nowrap\">" +
        escapeHtml(formatDateBR(r.start)) +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-xs whitespace-nowrap\">" +
        escapeHtml(formatDateBR(r.end)) +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-right text-xs tabular-nums\">" +
        escapeHtml(String(r.days != null ? r.days : "—")) +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-xs\">" +
        escapeHtml(displayVacationSourcePt(r.source)) +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-xs\">" +
        escapeHtml(cad) +
        "</td>" +
        "<td class=\"employees-data-table__cell px-2 py-2 text-right whitespace-nowrap\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary px-2 py-1 text-[10px] opacity-50\" disabled title=\"Em breve\">Editar</button> " +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary px-2 py-1 text-[10px] opacity-50\" disabled title=\"Em breve\">Cancelar</button> " +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary px-2 py-1 text-[10px] vp-sched-det\" data-eid=\"" +
        escapeHtml(eid) +
        "\">Detalhes</button></td>";
      tb.appendChild(tr);
    });
    tb.querySelectorAll(".vp-sched-det").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = parseInt(btn.getAttribute("data-eid"), 10);
        var found = (cachedRows || []).find(function (row) {
          return row.employee_id === id;
        });
        if (found) openDetailModal(found);
      });
    });
  }

  function renderDataQualityBlock(data) {
    var dq = data.data_quality || {};
    var ok = byId("vp-data-quality-ok");
    var groupsEl = byId("vp-data-quality-groups");
    var ul = byId("vp-data-quality-list");
    var wrap = byId("vp-data-quality");
    if (!wrap) return;
    var hasIssues = !!dq.has_issues;
    var groups = dq.groups || {};
    if (groupsEl) {
      groupsEl.innerHTML = "";
      var any = false;
      Object.keys(groups).forEach(function (key) {
        var g = groups[key];
        var c = parseInt(g.count, 10) || 0;
        if (c <= 0) return;
        any = true;
        var card = document.createElement("div");
        card.className =
          "rounded-lg border border-slate-200 bg-slate-50/80 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/40";
        card.innerHTML =
          "<p class=\"text-[11px] font-semibold uppercase tracking-wide text-slate-500\">" +
          escapeHtml(g.label || key) +
          "</p>" +
          "<p class=\"mt-1 text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-50\">" +
          c +
          "</p>";
        groupsEl.appendChild(card);
      });
      groupsEl.classList.toggle("hidden", !any);
    }
    if (ul) {
      ul.innerHTML = "";
      var flat = dq.alerts || [];
      if (flat.length && groupsEl && groupsEl.classList.contains("hidden")) {
        flat.forEach(function (t) {
          var li = document.createElement("li");
          li.textContent = t;
          ul.appendChild(li);
        });
        ul.classList.remove("hidden");
      } else {
        ul.classList.add("hidden");
      }
    }
    if (ok) {
      ok.classList.toggle("hidden", hasIssues);
      if (!hasIssues) ok.textContent = "Sem pendências críticas encontradas.";
    }
  }

  function rowNeedsAttention(row) {
    if (row.vacation_status === "scheduled_coverage") return false;
    if (row.vacation_status === "expired") return true;
    var d = row.days_until_deadline;
    if (d != null && d <= 90) return true;
    var wc = row.window_color;
    if (wc === "red" || wc === "yellow") return true;
    var c = (row.criticality || "").toLowerCase();
    if (c === "alta" || c === "muito_alta") return true;
    if ((row.priority_index || 0) >= 48) return true;
    return false;
  }

  function rowMatchesFilter(row, filter) {
    var d = row.days_until_deadline;
    var subEmpty = !row.substitute || row.substitute === "—";
    var c = (row.criticality || "").toLowerCase();

    if (filter === "all") return true;
    if (filter === "critical")
      return (
        !!row.operational_queue &&
        rowNeedsAttention(row) &&
        !immediateActionIdSet.has(row.employee_id)
      );
    if (filter === "expired")
      return row.vacation_status === "expired" && row.deadline_bucket === "ok";
    if (filter === "d30")
      return d != null && d >= 0 && d <= 30 && row.deadline_bucket === "ok";
    if (filter === "d6090") return d != null && d > 30 && d <= 90 && row.deadline_bucket === "ok";
    if (filter === "no_sub") return !!row.show_substitute_badge && subEmpty;
    if (filter === "on_leave") return !!row.on_vacation_today;
    if (filter === "return7") return !!row.returning_within_7d;
    if (filter === "scheduled_month") return !!row.scheduled_in_focus_month;
    if (filter === "high_pri")
      return c === "alta" || c === "muito_alta" || (row.priority_index || 0) >= 50;
    return true;
  }

  function rowMatchesSearch(row, q) {
    if (!q) return true;
    var t = q.toLowerCase();
    return (
      (row.name && row.name.toLowerCase().indexOf(t) >= 0) ||
      (row.role && row.role.toLowerCase().indexOf(t) >= 0)
    );
  }

  function filterRows(rows, filter, search) {
    var sq = (search || "").trim();
    return rows.filter(function (r) {
      return rowMatchesFilter(r, filter) && rowMatchesSearch(r, sq);
    });
  }

  function scheduleQueueSearchRender() {
    if (queueSearchTimer) clearTimeout(queueSearchTimer);
    queueSearchTimer = setTimeout(function () {
      queueSearchTimer = null;
      queueSearchDebounced = queueSearchRaw.trim();
      showAllRows = false;
      renderQueueTable(cachedRows);
    }, SEARCH_DEBOUNCE_MS);
  }

  function updateHeroChips() {
    var q = qs();
    var monthNames = [
      "",
      "Jan",
      "Fev",
      "Mar",
      "Abr",
      "Mai",
      "Jun",
      "Jul",
      "Ago",
      "Set",
      "Out",
      "Nov",
      "Dez",
    ];
    var pel = byId("vp-hero-chip-period");
    var cel = byId("vp-hero-chip-company");
    var qel = byId("vp-hero-chip-queue");
    if (pel)
      pel.textContent =
        "Período: " + (monthNames[q.month] || "") + "/" + String(q.year);
    if (cel) cel.textContent = "Empresa: " + (q.cost_center || "Todos");
    if (qel) {
      var n = cachedRows ? cachedRows.length : 0;
      var f = filterRows(cachedRows || [], activeFilter, queueSearchDebounced);
      qel.textContent =
        "Fila (auditoria): " + f.length + (n ? " de " + n + " carregados" : "");
    }
  }

  function prazoLabelHuman(row) {
    var b = row.deadline_bucket;
    if (row.vacation_status === "scheduled_coverage") return "Gozo aprovado no concessivo";
    if (b === "incomplete") return "Cadastro incompleto";
    if (b === "invalid_data") return "Datas inconsistentes";
    var d = row.days_until_deadline;
    if (d == null) return "—";
    var cap = 999;
    if (d < 0) return "Vencida há " + Math.min(Math.abs(d), cap) + " dias";
    if (d === 0) return "Vence hoje";
    if (d === 1) return "Vence amanhã";
    return "Vence em " + d + " dias";
  }

  function displayStatusTitle(row) {
    var st = row.vacation_status || "";
    if (st === "invalid") return "Datas inconsistentes — revisar cadastro";
    if (st === "incomplete") return "Cadastro incompleto";
    if (st === "scheduled_coverage") return "Gozo no concessivo";
    if (st === "expired") return "Férias vencidas";
    if (st === "urgent_30") return "Vence em até 30 dias";
    if (st === "urgent_60") return "Vence em até 60 dias";
    if (st === "urgent_90") return "Vence em até 90 dias";
    var lbl = (row.vacation_status_label || "").trim();
    if (!lbl) return "Em dia";
    if (/sem prazo/i.test(lbl)) return lbl;
    return lbl
      .replace(/\s*\(concessivo\)\s*/gi, "")
      .replace(/^A vencer em (\d+)d$/i, "Vence em $1 dias");
  }

  function statusBadgeClass(row) {
    var st = row.vacation_status || "";
    if (st === "scheduled_coverage")
      return "vp-status-badge vp-status-badge--ok vp-status-badge--compact";
    if (st === "invalid") return "vp-status-badge vp-status-badge--amber vp-status-badge--compact";
    if (st === "incomplete") return "vp-status-badge vp-status-badge--neutral vp-status-badge--compact";
    if (st === "expired") return "vp-status-badge vp-status-badge--danger vp-status-badge--compact";
    if (st === "urgent_30") return "vp-status-badge vp-status-badge--amber vp-status-badge--compact";
    if (st === "urgent_60" || st === "urgent_90")
      return "vp-status-badge vp-status-badge--blue vp-status-badge--compact";
    return "vp-status-badge vp-status-badge--neutral vp-status-badge--compact";
  }

  /** Texto curto do selo na fila (detalhes completos no modal). */
  function statusBadgeShort(row) {
    var st = row.vacation_status || "";
    if (st === "invalid") return "Revisar datas";
    if (st === "incomplete") return "Incompleto";
    if (st === "scheduled_coverage") return "No concessivo";
    if (st === "expired") return "Vencida";
    if (st === "urgent_30") return "≤30 d";
    if (st === "urgent_60") return "≤60 d";
    if (st === "urgent_90") return "≤90 d";
    var lbl = (row.vacation_status_label || "").trim();
    if (!lbl) return "Em dia";
    if (/sem prazo/i.test(lbl)) return "Sem prazo";
    if (/^A vencer em (\d+)d$/i.test(lbl)) return lbl.replace(/^A vencer em/i, "Vence");
    if (lbl.length > 22) return lbl.slice(0, 21) + "…";
    return lbl.replace(/\s*\(concessivo\)\s*/gi, "").trim() || "Em dia";
  }

  function isCriticalityHigh(row) {
    var c = (row.criticality || "").toLowerCase();
    return c === "alta" || c === "muito_alta";
  }

  function truncateChip(s, max) {
    max = max || 48;
    s = (s || "").trim();
    if (!s) return "";
    if (s.length <= max) return s;
    return s.slice(0, Math.max(0, max - 1)) + "…";
  }

  function rowAlertChipHtml(row) {
    var wc = row.window_color;
    var hint = (row.window_hint || "").trim();
    if (wc === "red") {
      return (
        "<span class=\"vp-card-meta-chip vp-card-meta-chip--danger\" title=\"" +
        escapeHtml(hint) +
        "\">" +
        escapeHtml(truncateChip(hint || "Janela adversa no mês", 40)) +
        "</span>"
      );
    }
    if (wc === "yellow") {
      return (
        "<span class=\"vp-card-meta-chip vp-card-meta-chip--warn\" title=\"" +
        escapeHtml(hint) +
        "\">" +
        escapeHtml(truncateChip(hint || "Atenção no mês", 40)) +
        "</span>"
      );
    }
    return "";
  }

  function decisionRowToneClass(row) {
    var st = row.vacation_status || "";
    if (st === "scheduled_coverage") return "vp-decision-row--scheduled";
    if (st === "invalid" || st === "incomplete") return "vp-decision-row--ok";
    if (
      row.vacation_status === "expired" ||
      (row.days_until_deadline != null && row.days_until_deadline < 0)
    ) {
      return "vp-decision-row--expired";
    }
    var d = row.days_until_deadline;
    if (d != null && d >= 0 && d <= 30) return "vp-decision-row--warning";
    if (row.window_color === "yellow") return "vp-decision-row--warning";
    if (d != null && d > 30 && d <= 90) return "vp-decision-row--info";
    if (row.window_color === "red") return "vp-decision-row--warning";
    return "vp-decision-row--ok";
  }

  function isHighPriority(row) {
    var c = (row.criticality || "").toLowerCase();
    return c === "alta" || c === "muito_alta" || (row.priority_index || 0) >= 50;
  }

  function priorityMarkup(row) {
    var p = row.priority_index != null ? String(row.priority_index) : "—";
    return (
      "<span class=\"vp-priority-pill vp-priority-pill--compact" +
      (isHighPriority(row) ? " vp-priority-pill--strong" : "") +
      "\" title=\"Prioridade na fila\"><span class=\"tabular-nums\">" +
      escapeHtml(p) +
      "</span></span>"
    );
  }

  function updateLaunchSummaryFromIds(employeeId) {
    var wrap = byId("vp-launch-summary");
    if (!wrap) return;
    var id = parseInt(employeeId, 10);
    if (!id) {
      wrap.innerHTML = "";
      return;
    }
    var row = (cachedRows || []).find(function (r) {
      return r.employee_id === id;
    });
    if (!row) {
      wrap.innerHTML =
        "<p class=\"font-semibold text-slate-800 dark:text-slate-100\">Colaborador #" +
        escapeHtml(String(id)) +
        "</p>";
      return;
    }
    wrap.innerHTML =
      "<p class=\"font-semibold text-slate-800 dark:text-slate-100\">" +
      escapeHtml(row.name || "—") +
      "</p>" +
      "<p class=\"mt-1 text-slate-600 dark:text-slate-400\">" +
      escapeHtml(row.role || "—") +
      " · " +
      escapeHtml(displayStatusTitle(row)) +
      "</p>";
  }

  function openLaunchModal(employeeId, opts) {
    opts = opts || {};
    var m = byId("vp-launch-modal");
    if (!m || !employeeId) return;
    rebuildEmployeeSelects(byId("vp-p-search") ? byId("vp-p-search").value : "");
    var sim = byId("vp-sim-employee");
    if (sim) {
      sim.value = String(employeeId);
      sim.dispatchEvent(new Event("change", { bubbles: true }));
    }
    var st = byId("vp-sim-start");
    var en = byId("vp-sim-end");
    if (opts.clearDates) {
      if (st) st.value = "";
      if (en) en.value = "";
    }
    if (opts.suggestedStart && st) st.value = opts.suggestedStart;
    if (opts.suggestedEnd && en) en.value = opts.suggestedEnd;
    var hi = byId("vp-sim-highlight");
    var pre = byId("vp-sim-result");
    if (hi) hi.classList.add("hidden");
    if (pre) {
      pre.classList.add("hidden");
      pre.textContent = "";
    }
    updateLaunchSummaryFromIds(employeeId);
    updateVacationLegalHint();
    updateLaunchDaysLine();
    updateQueueRowSelection();
    m.classList.remove("hidden");
    if (opts.focusStart !== false) {
      window.setTimeout(function () {
        var ste = byId("vp-sim-start");
        if (ste) {
          try {
            ste.focus();
            if (typeof ste.select === "function") ste.select();
          } catch (e2) {}
        }
      }, 140);
    }
  }

  function closeLaunchModal() {
    var m = byId("vp-launch-modal");
    if (m) m.classList.add("hidden");
  }

  function openDetailModal(row) {
    var modal = byId("vp-detail-modal");
    var body = byId("vp-detail-body");
    var title = byId("vp-detail-title");
    if (!modal || !body || !title) return;
    title.textContent = row.name || "Colaborador";
    var hint = row.window_hint || "";
    var wc = row.window_color || "";
    var best = row.best_period_hint || "—";
    var alerts = [];
    if (hint) alerts.push(hint);
    if (wc && wc !== "green")
      alerts.push("Janela no mês focado: " + windowColorLabelPt(wc));
    var ctxLine = [
      row.window_hint ? "Demanda no mês: " + row.window_hint : "",
      wc ? "Indicador da janela: " + windowColorLabelPt(wc) : "",
    ]
      .filter(function (x) {
        return x && String(x).trim();
      })
      .join(" · ");
    body.innerHTML =
      "<dl class=\"vp-detail-dl\">" +
      "<dt>Função</dt><dd>" +
      escapeHtml(row.role || "—") +
      "</dd>" +
      "<dt>Status</dt><dd>" +
      escapeHtml(displayStatusTitle(row)) +
      "</dd>" +
      "<dt>Prazo</dt><dd>" +
      escapeHtml(prazoLabelHuman(row)) +
      "</dd>" +
      "<dt>Prioridade</dt><dd class=\"tabular-nums\">" +
      escapeHtml(row.priority_index != null ? String(row.priority_index) : "—") +
      (isHighPriority(row) ? " <span class=\"text-rose-600 dark:text-rose-300 text-xs font-semibold\">Alta</span>" : "") +
      "</dd>" +
      "<dt>Melhor janela</dt><dd>" +
      escapeHtml(best) +
      "</dd>" +
      "<dt>Criticidade</dt><dd>" +
      escapeHtml(
        ({ baixa: "Baixa", media: "Média", alta: "Alta", muito_alta: "Muito alta" }[
          String(row.criticality || "").toLowerCase()
        ] || row.criticality || "—")
      ) +
      "</dd>" +
      "<dt>Substituto</dt><dd>" +
      escapeHtml(row.substitute || "—") +
      (row.substitute_trained ? " (treinado)" : "") +
      "</dd>" +
      "<dt>Data de admissão</dt><dd>" +
      escapeHtml(row.admission_date ? formatDateBR(row.admission_date) : "—") +
      "</dd>" +
      "<dt>Prazo concessivo (cadastro)</dt><dd>" +
      escapeHtml(row.concessive_deadline ? formatDateBR(row.concessive_deadline) : "—") +
      "</dd>" +
      "<dt>Origem do prazo</dt><dd class=\"text-xs leading-snug\">" +
      escapeHtml(row.deadline_basis_label || "—") +
      "</dd>" +
      "<dt>Janela no mês focado</dt><dd><span class=\"" +
      statusClass(wc) +
      "\">" +
      escapeHtml(windowColorLabelPt(wc)) +
      "</span>" +
      (hint ? " — " + escapeHtml(hint) : "") +
      "</dd>" +
      "<dt>Setor / rota</dt><dd>" +
      escapeHtml(
        (row.sector || "") + (row.route_team ? " · " + row.route_team : "") || "—"
      ) +
      "</dd>" +
      (alerts.length
        ? "<dt>Alertas</dt><dd class=\"text-xs leading-relaxed\">" +
          escapeHtml(alerts.join(" · ")) +
          "</dd>"
        : "") +
      "<dt>Contexto da recomendação</dt><dd class=\"text-xs leading-snug\">" +
      escapeHtml(ctxLine || "—") +
      "</dd>" +
      "</dl>" +
      "<div id=\"vp-detail-history-slot\" class=\"mt-4 border-t border-slate-200 pt-3 dark:border-slate-700\">" +
      "<p class=\"text-[11px] font-bold uppercase tracking-wide text-slate-400\">Últimos lançamentos (planejamento)</p>" +
      "<p id=\"vp-detail-history-loading\" class=\"mt-2 text-xs text-slate-500\">Carregando…</p>" +
      "</div>";
    modal.classList.remove("hidden");
    var eid = row.employee_id;
    fetch("/api/vacation-planning/history?limit=12&employee_id=" + encodeURIComponent(eid), {
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Falha ao carregar histórico do colaborador.");
        return r.json();
      })
      .then(function (data) {
        var slot = byId("vp-detail-history-slot");
        var loading = byId("vp-detail-history-loading");
        if (loading) loading.remove();
        if (!slot) return;
        var items = (data && data.items) || [];
        if (!items.length) {
          slot.innerHTML +=
            "<p class=\"mt-2 text-xs text-slate-500\">Nenhum registro neste histórico para este colaborador.</p>";
          return;
        }
        var html = items
          .map(function (h) {
            var sync = historyCadastroLabel(h);
            return (
              "<div class=\"mt-2 rounded-md border border-slate-100 px-2 py-2 text-xs dark:border-slate-700\">" +
              "<p class=\"font-medium text-slate-800 dark:text-slate-100\">" +
              formatDateBR(h.start) +
              " até " +
              formatDateBR(h.end) +
              "</p>" +
              "<p class=\"mt-0.5 text-slate-500\">" +
              escapeHtml(displayVacationStatusPt(h.status)) +
              " · " +
              escapeHtml(sync) +
              (h.approved_by ? " · por " + escapeHtml(h.approved_by) : "") +
              " · " +
              escapeHtml(formatDateTimeBR(h.created_at || "")) +
              "</p></div>"
            );
          })
          .join("");
        slot.innerHTML =
          "<p class=\"text-[11px] font-bold uppercase tracking-wide text-slate-400\">Últimos lançamentos (planejamento)</p>" +
          html;
      })
      .catch(function () {
        var loading = byId("vp-detail-history-loading");
        if (loading) loading.textContent = "Não foi possível carregar o histórico.";
      });
  }

  function closeDetailModal() {
    var modal = byId("vp-detail-modal");
    if (modal) modal.classList.add("hidden");
  }

  function updateQueueRowSelection() {
    var sim = byId("vp-sim-employee");
    var cur = sim && sim.value ? String(sim.value) : "";
    var list = byId("vp-decision-list");
    if (!list) return;
    list.querySelectorAll(".vp-decision-row").forEach(function (r) {
      var eid = r.getAttribute("data-eid") || "";
      r.classList.toggle("vp-decision-row--selected", cur !== "" && eid === cur);
    });
  }

  function renderQueueTable(rows) {
    var rb = byId("vp-decision-list");
    var empty = byId("vp-queue-empty");
    var countEl = byId("vp-queue-count");
    var btnAll = byId("vp-queue-show-all");
    if (!rb) return;

    var searchQ = queueSearchDebounced;
    var filtered = filterRows(rows, activeFilter, searchQ);
    var limited = showAllRows ? filtered : filtered.slice(0, INITIAL_TABLE_LIMIT);

    rb.innerHTML = "";
    if (filtered.length === 0) {
      if (empty) empty.classList.remove("hidden");
      if (countEl) countEl.textContent = "";
      if (btnAll) btnAll.classList.add("hidden");
      updateQueueRowSelection();
      return;
    }
    if (empty) empty.classList.add("hidden");

    limited.forEach(function (row) {
      var card = document.createElement("div");
      card.setAttribute("role", "listitem");
      card.className = "vp-decision-row " + decisionRowToneClass(row);
      card.setAttribute("data-eid", String(row.employee_id));
      var eid = row.employee_id;
      var win = row.best_period_hint && String(row.best_period_hint).trim() ? String(row.best_period_hint) : "";
      var winChip = win
        ? "<span class=\"vp-card-meta-chip\" title=\"" +
          escapeHtml(win) +
          "\">Janela: " +
          escapeHtml(truncateChip(win, 36)) +
          "</span>"
        : "<span class=\"vp-card-meta-chip\">Janela: —</span>";
      var subChip =
        row.show_substitute_badge && (!row.substitute || row.substitute === "—")
          ? "<span class=\"vp-card-meta-chip vp-card-meta-chip--warn\">Sem substituto</span>"
          : "";
      var critChip = isCriticalityHigh(row)
        ? "<span class=\"vp-card-meta-chip vp-card-meta-chip--critical\">Crítico</span>"
        : "";
      var alertChip = rowAlertChipHtml(row);
      var lce = row.last_completed_vacation_end;
      var lav = row.last_approved_vacation;
      var lastChip = "";
      if (lce) {
        lastChip =
          "<span class=\"vp-card-meta-chip\" title=\"Maior data de fim entre todos os gozos aprovados já encerrados (retroativos somados)\">Gozo encerrado: até " +
          escapeHtml(formatDateBR(lce)) +
          "</span>";
      } else if (lav && lav.start && lav.end) {
        lastChip =
          "<span class=\"vp-card-meta-chip\" title=\"Último lançamento aprovado no planejamento (pode incluir período futuro)\">Último: " +
          escapeHtml(formatDateBR(lav.start)) +
          " – " +
          escapeHtml(formatDateBR(lav.end)) +
          "</span>";
      }
      card.innerHTML =
        "<div class=\"vp-decision-risk\" aria-hidden=\"true\"></div>" +
        "<div class=\"vp-decision-row__main\">" +
        "<div class=\"vp-decision-row__person\">" +
        "<div class=\"vp-decision-row__title\">" +
        "<strong class=\"vp-decision-row__name\">" +
        escapeHtml(row.name || "—") +
        "</strong>" +
        priorityMarkup(row) +
        "<span class=\"" +
        statusBadgeClass(row) +
        "\">" +
        escapeHtml(statusBadgeShort(row)) +
        "</span>" +
        "</div>" +
        "<div class=\"vp-decision-row__subtitle\">" +
        escapeHtml(row.role || "—") +
        " · " +
        escapeHtml(prazoLabelHuman(row)) +
        "</div>" +
        "<div class=\"vp-decision-row__meta\">" +
        winChip +
        subChip +
        critChip +
        alertChip +
        lastChip +
        "</div>" +
        "</div>" +
        "<div class=\"vp-decision-row__actions vp-row-actions--compact\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--primary vp-action-launch--compact vp-btn-launch\" data-eid=\"" +
        eid +
        "\">Lançar</button>" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary vp-action-sim--compact vp-btn-sim\" data-eid=\"" +
        eid +
        "\">Simular</button>" +
        "<button type=\"button\" class=\"vp-action-more vp-btn-det\" data-eid=\"" +
        eid +
        "\" aria-label=\"Detalhes\" title=\"Detalhes\">⋯</button>" +
        "</div>" +
        "</div>";
      rb.appendChild(card);
    });

    if (!queueRowClickBound) {
      queueRowClickBound = true;
      rb.addEventListener("click", function (ev) {
        var btn = ev.target && ev.target.closest("button");
        if (!btn || !rb.contains(btn)) return;
        var id = parseInt(btn.getAttribute("data-eid"), 10);
        if (btn.classList.contains("vp-btn-launch")) {
          if (id) {
            hideAlert();
            openLaunchModal(id, { clearDates: true, focusStart: true });
          }
        } else if (btn.classList.contains("vp-btn-sim")) {
          if (id) {
            hideAlert();
            openLaunchModal(id, { clearDates: true, focusStart: true });
          }
        } else if (btn.classList.contains("vp-btn-det")) {
          var found = cachedRows.find(function (r) {
            return r.employee_id === id;
          });
          if (found) openDetailModal(found);
        }
      });
    }

    if (countEl) {
      countEl.textContent =
        "Exibindo " +
        limited.length +
        " de " +
        filtered.length +
        (filtered.length !== rows.length ? " (após filtro na fila)" : "");
    }
    updateHeroChips();
    updateQueueRowSelection();
    if (btnAll) {
      if (filtered.length > INITIAL_TABLE_LIMIT && !showAllRows) {
        btnAll.classList.remove("hidden");
      } else {
        btnAll.classList.add("hidden");
      }
    }
  }

  function rebuildEmployeeSelects(filterText) {
    var f = (filterText || "").toLowerCase().trim();
    var sim = byId("vp-sim-employee");
    var prof = byId("vp-profile-employee");
    var prevSim = sim ? sim.value : "";
    var prevProf = prof ? prof.value : "";
    if (sim) sim.innerHTML = "<option value=\"\">Selecione…</option>";
    if (prof) prof.innerHTML = "<option value=\"\">Selecione…</option>";
    employeeOptionsFull.forEach(function (e) {
      var label = e.name + " — " + e.role + " (id " + e.id + ")";
      if (f && label.toLowerCase().indexOf(f) < 0 && String(e.id).indexOf(f) < 0) {
        return;
      }
      if (sim) {
        var o1 = document.createElement("option");
        o1.value = String(e.id);
        o1.textContent = label;
        sim.appendChild(o1);
      }
      if (prof) {
        var o2 = document.createElement("option");
        o2.value = String(e.id);
        o2.textContent = label;
        prof.appendChild(o2);
      }
    });
    if (sim && prevSim) sim.value = prevSim;
    if (prof && prevProf) prof.value = prevProf;
    updateQueueRowSelection();
  }

  function applyFilterChip(name) {
    activeFilter = name;
    showAllRows = false;
    root.querySelectorAll("[data-vp-filter]").forEach(function (c) {
      var on = c.getAttribute("data-vp-filter") === name;
      c.classList.toggle("filter-btn--active", on);
      c.setAttribute("aria-pressed", on ? "true" : "false");
    });
    renderQueueTable(cachedRows);
  }

  function setQueueLoading(on) {
    var el = byId("vp-queue-loading");
    var err = byId("vp-queue-error");
    var wrap = byId("vp-decision-list-shell") || byId("vp-decision-list");
    if (el) el.classList.toggle("hidden", !on);
    if (wrap) wrap.classList.toggle("opacity-50", !!on);
    if (on && err) {
      err.classList.add("hidden");
      err.textContent = "";
    }
  }

  function setQueueError(msg) {
    var err = byId("vp-queue-error");
    if (!err) return;
    if (msg) {
      err.textContent = msg;
      err.classList.remove("hidden");
    } else {
      err.classList.add("hidden");
      err.textContent = "";
    }
  }

  function loadOverview() {
    hideAlert();
    setQueueError("");
    setQueueLoading(true);
    var rb0 = byId("vp-decision-list");
    if (rb0) rb0.innerHTML = "";
    var q = qs();
    var url =
      "/api/vacation-planning/overview?year=" +
      encodeURIComponent(q.year) +
      "&cost_center=" +
      encodeURIComponent(q.cost_center) +
      "&month=" +
      encodeURIComponent(q.month);
    return fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("Falha ao carregar painel");
        return r.json();
      })
      .then(function (data) {
        setQueueLoading(false);
        var k = data.kpis || {};
        byId("vp-kpi-expired").textContent = String(k.expired ?? "0");
        byId("vp-kpi-d30").textContent = String(k.due_30 ?? "0");
        var d6090 =
          k.due_60_90 != null
            ? k.due_60_90
            : (parseInt(k.due_60, 10) || 0) + (parseInt(k.due_90, 10) || 0);
        byId("vp-kpi-d6090").textContent = String(d6090);
        byId("vp-kpi-sched").textContent = String(k.scheduled_in_month ?? "0");
        var ko = document.getElementById("vp-kpi-ontoday");
        if (ko) ko.textContent = String(k.on_vacation_today ?? "0");
        var kr = document.getElementById("vp-kpi-ret7");
        if (kr) kr.textContent = String(k.returning_within_7d ?? "0");

        renderMonthStrip(data);
        renderYearGrid(data);
        immediateActionIdSet = new Set(
          (data.immediate_actions || []).map(function (x) {
            return x.employee_id;
          }),
        );
        cachedRows = data.rows || [];
        renderImmediateBlocks(data);
        renderScheduledInMonth(data);
        renderDataQualityBlock(data);

        queueSearchDebounced = queueSearchRaw.trim();
        renderQueueTable(cachedRows);

        employeeOptionsFull = data.employees_options || [];
        rebuildEmployeeSelects(byId("vp-p-search") ? byId("vp-p-search").value : "");
        updateHeroChips();
        updateVacationLegalHint();
      })
      .catch(function (e) {
        setQueueLoading(false);
        var msg = e.message || "Erro";
        setQueueError(msg);
        showAlert(msg, "error");
      });
  }

  function loadCalibrationTable() {
    var y = parseInt(byId("vp-cal-year").value, 10) || currentYear();
    return fetch("/api/vacation-planning/month-demand?year=" + encodeURIComponent(y), {
      credentials: "same-origin",
    })
      .then(function (r) {
        if (r.status === 403) throw new Error("Sem permissão.");
        if (!r.ok) throw new Error("Falha ao carregar régua mensal");
        return r.json();
      })
      .then(function (data) {
        var tb = byId("vp-cal-body");
        tb.innerHTML = "";
        (data.months || []).forEach(function (m) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";

          var td0 = document.createElement("td");
          td0.className = "px-2 py-2 font-medium";
          td0.textContent = m.month_name;
          tr.appendChild(td0);

          var td1 = document.createElement("td");
          td1.className = "px-2 py-2";
          var badge = document.createElement("span");
          badge.className =
            m.source === "calibrated" ? "vp-badge vp-badge--ok" : "vp-badge vp-badge--muted";
          badge.textContent = m.source === "calibrated" ? "Calibrado" : "Padrão";
          td1.appendChild(badge);
          tr.appendChild(td1);

          var td2 = document.createElement("td");
          td2.className = "px-2 py-2";
          var dem = document.createElement("input");
          dem.type = "number";
          dem.min = "0";
          dem.max = "100";
          dem.className = "vp-cal-dem ops-toolbar-control w-20 px-2 text-xs";
          dem.setAttribute("data-m", String(m.month));
          dem.value = String(m.demand_index);
          td2.appendChild(dem);
          tr.appendChild(td2);

          var td3 = document.createElement("td");
          td3.className = "px-2 py-2";
          var note = document.createElement("input");
          note.type = "text";
          note.className = "vp-cal-note ops-toolbar-control w-full min-w-[140px] px-2 text-xs";
          note.setAttribute("data-m", String(m.month));
          note.value = m.risk_notes ? String(m.risk_notes) : "";
          td3.appendChild(note);
          tr.appendChild(td3);

          var td4 = document.createElement("td");
          td4.className = "px-2 py-2";
          var jn = document.createElement("input");
          jn.type = "text";
          jn.className = "vp-cal-json ops-toolbar-control w-full min-w-[160px] px-2 font-mono text-xs";
          jn.setAttribute("data-m", String(m.month));
          jn.placeholder = '{"MOTORISTA":1}';
          jn.value = m.function_limits_json ? JSON.stringify(m.function_limits_json) : "";
          td4.appendChild(jn);
          tr.appendChild(td4);

          var td5 = document.createElement("td");
          td5.className = "px-2 py-2";
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "sys-btn sys-btn--secondary vp-cal-save text-xs";
          btn.setAttribute("data-m", String(m.month));
          btn.textContent = "Salvar";
          btn.addEventListener("click", function () {
            saveCalibrationRow(parseInt(btn.getAttribute("data-m"), 10));
          });
          td5.appendChild(btn);
          tr.appendChild(td5);

          tb.appendChild(tr);
        });
      })
      .catch(function (e) {
        showAlert(e.message || "Erro na calibragem", "error");
      });
  }

  function saveCalibrationRow(month) {
    var y = parseInt(byId("vp-cal-year").value, 10) || currentYear();
    var tb = byId("vp-cal-body");
    var demInput = tb.querySelector('.vp-cal-dem[data-m="' + month + '"]');
    var noteInput = tb.querySelector('.vp-cal-note[data-m="' + month + '"]');
    var jsonInput = tb.querySelector('.vp-cal-json[data-m="' + month + '"]');
    var di = parseInt(demInput && demInput.value, 10);
    if (isNaN(di) || di < 0 || di > 100) {
      showAlert("Índice de demanda deve ser 0–100.", "error");
      return;
    }
    var rawJson = (jsonInput && jsonInput.value) || "";
    rawJson = rawJson.trim();
    var fj = null;
    if (rawJson) {
      try {
        fj = JSON.parse(rawJson);
      } catch (e) {
        showAlert("Limites por função: JSON inválido.", "error");
        return;
      }
    }
    var payload = {
      year: y,
      month: month,
      demand_index: di,
      risk_notes: ((noteInput && noteInput.value) || "").trim() || null,
      function_limits_json: fj,
    };
    fetch("/api/vacation-planning/month-demand", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, status: r.status, body: j };
        });
      })
      .then(function (res) {
        if (res.status === 403) throw new Error("Apenas líder/admin pode calibrar.");
        if (!res.ok) {
          var det = res.body.detail;
          if (Array.isArray(det))
            det = det
              .map(function (x) {
                return x.msg || x;
              })
              .join("; ");
          throw new Error(det || res.body.message || "Falha ao salvar");
        }
        showAlert("Mês " + month + " salvo.", "success");
        loadCalibrationTable();
        loadOverview();
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
      });
  }

  function loadProfileForEmployee(employeeId) {
    if (!employeeId) return;
    fetch("/api/vacation-planning/profile/" + encodeURIComponent(employeeId), {
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Perfil não encontrado");
        return r.json();
      })
      .then(function (data) {
        var vp = data.vacation_profile || {};
        byId("vp-p-sector").value = vp.department_sector || "";
        byId("vp-p-route").value = vp.route_team || "";
        byId("vp-p-criticality").value = vp.criticality || "media";
        byId("vp-p-sub-id").value =
          vp.substitute_employee_id != null ? String(vp.substitute_employee_id) : "";
        byId("vp-p-sub-trained").checked = !!vp.substitute_trained;
        byId("vp-p-aq-end").value = vp.acquisition_period_end || "";
        byId("vp-p-last-v").value = vp.last_vacation_end || "";
        byId("vp-p-days").value =
          vp.vacation_days_available != null ? String(vp.vacation_days_available) : "";
        var ex = document.getElementById("vp-p-exclude-op");
        if (ex) ex.checked = !!vp.exclude_from_operational_vacation;
      })
      .catch(function () {
        showAlert("Não foi possível carregar o perfil.", "error");
      });
  }

  function renderRecentLaunches(items) {
    var box = byId("vp-recent-launches-body");
    if (!box) return;
    var slice = (items || []).slice(0, 6);
    if (!slice.length) {
      box.innerHTML =
        "<p class=\"text-xs text-slate-500 dark:text-slate-400\">Nenhum lançamento ainda. Use «Lançar» na fila.</p>";
      return;
    }
    box.innerHTML = slice
      .map(function (h) {
        var sync = historyCadastroLabel(h);
        return (
          "<article class=\"vp-recent-item border-b border-slate-100 py-2.5 last:border-0 dark:border-slate-800\">" +
          "<p class=\"font-semibold text-slate-800 dark:text-slate-100\">" +
          escapeHtml(h.employee_name || "") +
          "</p>" +
          "<p class=\"text-xs mt-0.5\">" +
          escapeHtml(formatDateBR(h.start)) +
          " até " +
          escapeHtml(formatDateBR(h.end)) +
          "</p>" +
          "<p class=\"text-[11px] text-slate-500 mt-1\">" +
          escapeHtml(displayVacationStatusPt(h.status)) +
          " · " +
          escapeHtml(sync) +
          (h.approved_by ? " · por " + escapeHtml(h.approved_by) : "") +
          " · " +
          escapeHtml(formatDateTimeBR(h.created_at || "")) +
          "</p></article>"
        );
      })
      .join("");
  }

  function loadHistory() {
    fetch("/api/vacation-planning/history?limit=100", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (t) {
            try {
              var j = JSON.parse(t);
              var d = j.detail;
              if (Array.isArray(d)) d = d.map(function (x) { return x.msg || x; }).join("; ");
              throw new Error(d || j.message || "Falha ao carregar histórico (" + r.status + ")");
            } catch (parseErr) {
              if (parseErr instanceof SyntaxError) {
                throw new Error("Falha ao carregar histórico (" + r.status + ").");
              }
              throw parseErr;
            }
          });
        }
        return r.json();
      })
      .then(function (data) {
        var items = data.items || [];
        renderRecentLaunches(items);
        var hb = byId("vp-history-body");
        if (!hb) return;
        hb.innerHTML = "";
        items.forEach(function (h) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var syncShort = h.employee_vacation_synced ? "Sim" : "Não";
          var syncFull = historyCadastroLabel(h);
          tr.innerHTML =
            "<td class=\"px-3 py-2 text-xs whitespace-nowrap\">" +
            escapeHtml(formatDateTimeBR(h.created_at || "")) +
            "</td>" +
            "<td class=\"px-3 py-2\">" +
            escapeHtml(h.employee_name) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(formatDateBR(h.start)) +
            " até " +
            escapeHtml(formatDateBR(h.end)) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(displayVacationStatusPt(h.status)) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(displayVacationSourcePt(h.source)) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(h.approved_by || "—") +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\" title=\"" +
            escapeHtml(syncFull) +
            "\">" +
            escapeHtml(syncShort) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs max-w-xs truncate\" title=\"" +
            escapeHtml(h.decision_reason || "") +
            "\">" +
            escapeHtml(h.decision_reason || "—") +
            "</td>";
          hb.appendChild(tr);
        });
      })
      .catch(function (e) {
        var box = byId("vp-recent-launches-body");
        if (box) {
          box.innerHTML =
            "<p class=\"text-xs text-rose-600\">" + escapeHtml(e.message || "Erro ao carregar.") + "</p>";
        }
        var hb = byId("vp-history-body");
        if (hb) {
          hb.innerHTML =
            "<tr><td colspan=\"8\" class=\"px-3 py-3 text-xs text-rose-600\">" +
            escapeHtml(e.message || "Não foi possível carregar o histórico.") +
            "</td></tr>";
        }
        showAlert(e.message || "Não foi possível atualizar o histórico de férias.", "error");
      });
  }

  function runSuggest() {
    var q = qs();
    showAlert("Gerando sugestões…", "success");
    fetch(
      "/api/vacation-planning/suggest?year=" +
        encodeURIComponent(q.year) +
        "&cost_center=" +
        encodeURIComponent(q.cost_center),
      { method: "POST", credentials: "same-origin" }
    )
      .then(function (r) {
        if (r.status === 403) throw new Error("Sem permissão (apenas líder/admin).");
        if (!r.ok) throw new Error("Falha na sugestão");
        return r.json();
      })
      .then(function (data) {
        hideAlert();
        var sb = byId("vp-suggest-body");
        sb.innerHTML = "";
        (data.suggestions || []).forEach(function (s) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var reasons = (s.reasons || []).join("; ");
          tr.innerHTML =
            "<td class=\"px-3 py-2 tabular-nums\">" +
            s.priority_rank +
            "</td>" +
            "<td class=\"px-3 py-2\">" +
            escapeHtml(s.name) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(s.role) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs whitespace-nowrap\">" +
            escapeHtml(formatDateBR(s.suggested_start)) +
            " até " +
            escapeHtml(formatDateBR(s.suggested_end)) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(reasons) +
            "</td>" +
            "<td class=\"px-3 py-2 whitespace-nowrap\">" +
            "<button type=\"button\" class=\"sys-btn sys-btn--primary text-xs py-1 px-2 vp-suggest-launch\" " +
            "data-eid=\"" +
            String(s.employee_id) +
            "\" data-start=\"" +
            escapeHtml(String(s.suggested_start || "")) +
            "\" data-end=\"" +
            escapeHtml(String(s.suggested_end || "")) +
            "\" data-name=\"" +
            escapeHtml(String(s.name || "")) +
            "\" data-rank=\"" +
            String(s.priority_rank) +
            "\">Lançar</button></td>";
          sb.appendChild(tr);
        });
        switchSecondaryTab("suggest");
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
      });
  }

  function runSimulate() {
    hideAlert();
    var q = qs();
    var eid = byId("vp-sim-employee").value;
    var start = byId("vp-sim-start").value;
    var end = byId("vp-sim-end").value;
    var hi = byId("vp-sim-highlight");
    if (hi) hi.classList.add("hidden");
    if (!eid || !start || !end) {
      showAlert("Preencha colaborador e datas.", "error");
      return;
    }
    var dA = new Date(start + "T12:00:00");
    var dB = new Date(end + "T12:00:00");
    if (isNaN(dA.getTime()) || isNaN(dB.getTime()) || dB < dA) {
      showAlert("A data fim não pode ser anterior à data de início.", "error");
      return;
    }
    fetch("/api/vacation-planning/simulate", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        employee_id: parseInt(eid, 10),
        start: start,
        end: end,
        cost_center: q.cost_center,
      }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, status: r.status, body: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          var det = res.body.detail;
          if (Array.isArray(det))
            det = det
              .map(function (x) {
                return x.msg || x;
              })
              .join("; ");
          showAlert(det || res.body.message || "Não foi possível simular.", "error");
          return;
        }
        var data = res.body;
        var pre = byId("vp-sim-result");
        if (!data.ok) {
          if (hi) hi.classList.add("hidden");
          if (pre) {
            pre.classList.remove("hidden");
            pre.textContent = data.error || "Erro";
          }
          return;
        }
        var labelEl = byId("vp-sim-label");
        var explEl = byId("vp-sim-explanation");
        if (labelEl) labelEl.textContent = data.recommendation_label || "";
        if (explEl) explEl.textContent = data.recommendation_explanation || "";
        if (hi) hi.classList.remove("hidden");

        var lines = [];
        lines.push("Detalhes técnicos");
        lines.push("Impacto na equipe: " + data.impact_team);
        lines.push(
          "Substituto: " +
            (data.substitute_available ? "sim" : "não") +
            (data.substitute_trained ? " (treinado)" : "")
        );
        lines.push(
          "Demanda (índice min–max): " +
            data.demand_index_range.min +
            " – " +
            data.demand_index_range.max
        );
        lines.push(
          "Sobreposição mesma função: " +
            data.concurrent_same_role +
            " / limite " +
            data.role_limit
        );
        if (data.alerts && data.alerts.length) lines.push("Alertas:\n- " + data.alerts.join("\n- "));
        if (data.blocks && data.blocks.length) lines.push("Bloqueios:\n- " + data.blocks.join("\n- "));
        if (data.scores) {
          lines.push(
            "Notas: urgência " +
              data.scores.urgencia_trabalhista +
              " | criticidade " +
              data.scores.criticidade_operacional +
              " | oportunidade " +
              data.scores.oportunidade_periodo +
              " | cobertura " +
              data.scores.cobertura_equipe
          );
        }
        var ld = inclusiveCalendarDays(
          byId("vp-sim-start").value,
          byId("vp-sim-end").value
        );
        if (ld != null) {
          lines.push("");
          lines.push("— Referência CLT (gozo + 30 dias) —");
          lines.push("Dias corridos no período: " + ld);
          if (ld < 30) {
            lines.push("Faltam " + (30 - ld) + " dia(s) para os 30 dias legais.");
            if (30 - ld === 10) {
              lines.push(
                "Os 10 dias restantes costumam ser abono pecuniário (venda de 1/3); use a caixa no formulário ao lançar."
              );
            }
          } else if (ld > 30) {
            lines.push("Período maior que 30 dias corridos — validar com RH/DP.");
          }
        }
        if (pre) {
          pre.classList.remove("hidden");
          pre.textContent = lines.join("\n\n");
        }
      })
      .catch(function () {
        showAlert("Falha na simulação.", "error");
      });
  }

  function saveSchedule(overrides) {
    overrides = overrides || {};
    var q = qs();
    var eid =
      overrides.employee_id != null
        ? String(overrides.employee_id)
        : byId("vp-sim-employee").value;
    var start = overrides.start || byId("vp-sim-start").value;
    var end = overrides.end || byId("vp-sim-end").value;
    var reason =
      overrides.reason != null && overrides.reason !== ""
        ? String(overrides.reason)
        : buildScheduleReasonFromForm();
    var sync =
      overrides.sync != null ? !!overrides.sync : byId("vp-sync-employee").checked;
    var source = overrides.source || "manual";
    if (!eid || !start || !end) {
      showAlert("Preencha colaborador, início e fim.", "error");
      return;
    }
    var dsA = new Date(start + "T12:00:00");
    var dsB = new Date(end + "T12:00:00");
    if (isNaN(dsA.getTime()) || isNaN(dsB.getTime()) || dsB < dsA) {
      showAlert("A data fim não pode ser anterior à data de início.", "error");
      return;
    }
    fetch("/api/vacation-planning/schedule", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        employee_id: parseInt(eid, 10),
        start: start,
        end: end,
        status: "approved",
        source: source.length > 20 ? source.slice(0, 20) : source,
        decision_reason: reason,
        leadership_notes: null,
        cost_center: q.cost_center,
        sync_employee_vacation: sync,
      }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, status: r.status, body: j };
        });
      })
      .then(function (res) {
        if (res.status === 403) throw new Error("Apenas líder/admin registra histórico.");
        if (!res.ok) {
          var d = res.body.detail;
          if (Array.isArray(d))
            d = d.map(function (x) {
              return x.msg || x;
            }).join("; ");
          throw new Error(
            d ||
              res.body.message ||
              "Não foi possível registrar as férias. Tente novamente ou verifique as datas."
          );
        }
        var empName = "";
        var erow = (cachedRows || []).find(function (x) {
          return String(x.employee_id) === String(eid);
        });
        if (erow) empName = erow.name || "";
        if (!empName && employeeOptionsFull && employeeOptionsFull.length) {
          var eo = employeeOptionsFull.find(function (x) {
            return String(x.id) === String(eid);
          });
          if (eo) empName = eo.name || "";
        }
        closeLaunchModal();
        var msg =
          "Férias registradas" +
          (empName ? " para " + empName : "") +
          ": " +
          formatDateBR(start) +
          " até " +
          formatDateBR(end) +
          ".";
        if (res.body.employee_vacation_sync && res.body.employee_vacation_sync.message) {
          msg += " " + res.body.employee_vacation_sync.message;
        }
        showAlert(msg, "success");
        loadOverview();
        loadHistory();
        var recent = byId("vp-recent-launches");
        if (recent) {
          recent.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      })
      .catch(function (e) {
        showAlert(
          e.message ||
            "Não foi possível registrar as férias. Tente novamente ou verifique as datas.",
          "error"
        );
      });
  }

  var suggestPanel = byId("vp-panel-suggest");
  if (suggestPanel) {
    suggestPanel.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.classList.contains("vp-suggest-launch")) return;
      var eid = t.getAttribute("data-eid");
      var st = t.getAttribute("data-start");
      var en = t.getAttribute("data-end");
      var nm = t.getAttribute("data-name") || "";
      var rk = t.getAttribute("data-rank") || "";
      if (!eid || !st || !en) return;
      if (
        !window.confirm(
          "Lançar férias de " +
            nm +
            " de " +
            formatDateBR(st) +
            " até " +
            formatDateBR(en) +
            "? O registro vai para o histórico do planejamento."
        )
      ) {
        return;
      }
      var extraReason =
        (byId("vp-schedule-reason").value || "").trim() ||
        "Sugestão inteligente #" + rk + " (" + st + " a " + en + ")";
      saveSchedule({
        employee_id: parseInt(eid, 10),
        start: st,
        end: en,
        reason: extraReason,
        source: "suggestion",
        sync: byId("vp-sync-employee").checked,
      });
    });
  }

  function saveProfile() {
    var id = parseInt(byId("vp-profile-employee").value, 10);
    if (!id) {
      showAlert("Selecione um colaborador.", "error");
      return;
    }
    var body = {
      department_sector: byId("vp-p-sector").value || null,
      route_team: byId("vp-p-route").value || null,
      criticality: byId("vp-p-criticality").value,
      substitute_employee_id: byId("vp-p-sub-id").value
        ? parseInt(byId("vp-p-sub-id").value, 10)
        : null,
      substitute_trained: byId("vp-p-sub-trained").checked,
      acquisition_period_end: byId("vp-p-aq-end").value || null,
      last_vacation_end: byId("vp-p-last-v").value || null,
      vacation_days_available: byId("vp-p-days").value
        ? parseInt(byId("vp-p-days").value, 10)
        : null,
      exclude_from_operational_vacation: !!(function () {
        var ex = document.getElementById("vp-p-exclude-op");
        return ex && ex.checked;
      })(),
    };
    fetch("/api/vacation-planning/profile/" + id, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (r.status === 403) throw new Error("Apenas líder/admin edita perfil.");
        if (!r.ok) throw new Error("Falha ao salvar perfil");
        return r.json();
      })
      .then(function () {
        showAlert("Perfil atualizado.", "success");
        loadOverview();
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
      });
  }

  function switchSecondaryTab(tab) {
    var ph = byId("vp-tabs-placeholder");
    if (ph) ph.classList.add("hidden");
    root.querySelectorAll(".vp-tabs__btn").forEach(function (b) {
      var is = b.getAttribute("data-vp-tab") === tab;
      b.classList.toggle("vp-tabs__btn--active", is);
      b.setAttribute("aria-selected", is ? "true" : "false");
    });
    ["import", "cal", "profile", "suggest", "history"].forEach(function (id) {
      var p = byId("vp-panel-" + id);
      if (p) p.classList.toggle("hidden", id !== tab);
    });
  }

  byId("vp-year").value = String(currentYear());
  byId("vp-month").value = String(currentMonth());
  byId("vp-cal-year").value = String(currentYear());

  byId("vp-refresh").addEventListener("click", function () {
    loadOverview();
  });
  byId("vp-suggest").addEventListener("click", runSuggest);
  byId("vp-sim-run").addEventListener("click", runSimulate);
  byId("vp-schedule-save").addEventListener("click", saveSchedule);
  var simEmp = byId("vp-sim-employee");
  if (simEmp) {
    simEmp.addEventListener("change", function () {
      updateQueueRowSelection();
      var modal = byId("vp-launch-modal");
      if (modal && !modal.classList.contains("hidden")) {
        updateLaunchSummaryFromIds(simEmp.value);
      }
    });
  }

  var launchShell = byId("vp-launch-modal");
  if (launchShell) {
    launchShell.addEventListener("click", function (ev) {
      if (ev.target === launchShell) closeLaunchModal();
    });
  }
  var launchClose = byId("vp-launch-close");
  var launchCancel = byId("vp-launch-cancel");
  if (launchClose) launchClose.addEventListener("click", closeLaunchModal);
  if (launchCancel) launchCancel.addEventListener("click", closeLaunchModal);
  var recentRf = byId("vp-recent-refresh");
  if (recentRf) recentRf.addEventListener("click", loadHistory);

  root.querySelectorAll(".vp-dur-preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var n = parseInt(btn.getAttribute("data-vp-days"), 10);
      var startEl = byId("vp-sim-start");
      var endEl = byId("vp-sim-end");
      if (!startEl || !endEl) return;
      if (!startEl.value) {
        startEl.value = defaultVacationStartIsoFromOverview();
        try {
          startEl.dispatchEvent(new Event("input", { bubbles: true }));
          startEl.dispatchEvent(new Event("change", { bubbles: true }));
        } catch (e0) {}
      }
      if (!n || n < 1) return;
      var endIso = addCalendarDaysIso(startEl.value, n - 1);
      if (!endIso) {
        showAlert("Data de início inválida. Ajuste manualmente.", "error");
        return;
      }
      endEl.value = endIso;
      try {
        endEl.dispatchEvent(new Event("input", { bubbles: true }));
        endEl.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e1) {}
      updateVacationLegalHint();
      updateLaunchDaysLine();
    });
  });
  ["vp-sim-start", "vp-sim-end"].forEach(function (id) {
    var el = byId(id);
    if (!el) return;
    el.addEventListener("change", updateVacationLegalHint);
    el.addEventListener("input", updateVacationLegalHint);
  });
  var abono10 = byId("vp-abono-10");
  if (abono10) {
    abono10.addEventListener("change", function () {
      updateVacationLegalHint();
    });
  }
  byId("vp-history-refresh").addEventListener("click", loadHistory);
  byId("vp-profile-save").addEventListener("click", saveProfile);
  byId("vp-cal-load").addEventListener("click", function () {
    loadCalibrationTable();
  });

  byId("vp-p-search").addEventListener("input", function () {
    rebuildEmployeeSelects(byId("vp-p-search").value);
  });

  byId("vp-profile-employee").addEventListener("change", function () {
    var v = byId("vp-profile-employee").value;
    if (v) loadProfileForEmployee(v);
  });

  byId("vp-year").addEventListener("change", function () {
    byId("vp-cal-year").value = byId("vp-year").value;
    loadOverview();
  });

  byId("vp-cost-center").addEventListener("change", function () {
    loadOverview();
  });

  root.querySelectorAll("[data-vp-filter]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var name = chip.getAttribute("data-vp-filter");
      if (name) applyFilterChip(name);
    });
  });

  root.querySelectorAll(".vp-kpi-click").forEach(function (card) {
    card.addEventListener("click", function () {
      var name = card.getAttribute("data-vp-kpi-filter");
      if (name) applyFilterChip(name);
    });
    card.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      var name = card.getAttribute("data-vp-kpi-filter");
      if (name) applyFilterChip(name);
    });
  });

  var clearBtn = byId("vp-clear-filters");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      var si = byId("vp-queue-search");
      if (si) si.value = "";
      queueSearchRaw = "";
      queueSearchDebounced = "";
      if (queueSearchTimer) {
        clearTimeout(queueSearchTimer);
        queueSearchTimer = null;
      }
      applyFilterChip("critical");
    });
  }

  var searchEl = byId("vp-queue-search");
  if (searchEl) {
    searchEl.addEventListener("input", function () {
      queueSearchRaw = searchEl.value;
      scheduleQueueSearchRender();
    });
  }

  var showAllBtn = byId("vp-queue-show-all");
  if (showAllBtn) {
    showAllBtn.addEventListener("click", function () {
      showAllRows = true;
      renderQueueTable(cachedRows);
    });
  }

  byId("vp-detail-close").addEventListener("click", closeDetailModal);
  var detModal = byId("vp-detail-modal");
  if (detModal) {
    detModal.addEventListener("click", function (ev) {
      if (ev.target === detModal) closeDetailModal();
    });
  }
  var impModal = byId("vpImportModal");
  if (impModal) {
    impModal.addEventListener("click", function (ev) {
      if (ev.target === impModal) impModal.classList.add("hidden");
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      closeDetailModal();
      closeLaunchModal();
      var im = byId("vpImportModal");
      if (im && !im.classList.contains("hidden")) im.classList.add("hidden");
    }
  });

  root.querySelectorAll(".vp-tabs__btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tab = btn.getAttribute("data-vp-tab");
      if (tab) switchSecondaryTab(tab);
    });
  });
  switchSecondaryTab("import");

  byId("vp-month").addEventListener("change", function () {
    loadOverview();
  });

  var importForm = byId("vp-import-form");
  if (importForm) {
    importForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var fi = byId("vp-import-file");
      var pre = byId("vp-import-result");
      if (!fi || !fi.files || !fi.files[0]) {
        showAlert("Selecione um arquivo .xls ou .xlsx.", "error");
        return;
      }
      var interpretEl = root.querySelector('input[name="vp-import-interpret"]:checked');
      var interpretation = interpretEl ? interpretEl.value : "acquisition_end";
      var adm = byId("vp-import-admission");
      var fd = new FormData();
      fd.append("file", fi.files[0]);
      fd.append("interpretation", interpretation);
      fd.append("update_admission", adm && adm.checked ? "true" : "false");
      hideAlert();
      if (pre) {
        pre.classList.add("hidden");
        pre.textContent = "";
      }
      var btn = byId("vp-import-submit");
      if (btn) btn.disabled = true;
      fetch("/api/vacation-planning/import-workbook", {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, status: r.status, body: j };
          });
        })
        .then(function (res) {
          if (btn) btn.disabled = false;
          if (res.status === 403) {
            showAlert("Sem permissão (apenas líder/admin pode importar).", "error");
            return;
          }
          if (!res.ok) {
            var d = res.body.detail;
            if (Array.isArray(d))
              d = d
                .map(function (x) {
                  return x.msg || x;
                })
                .join("; ");
            showAlert(d || res.body.message || "Falha na importação", "error");
            return;
          }
          if (pre) {
            pre.textContent = JSON.stringify(res.body, null, 2);
            pre.classList.remove("hidden");
          }
          var kind = res.body.workbook_kind;
          var um = (res.body.unmatched_rows || []).length;
          var am = (res.body.ambiguous_name_rows || []).length;
          var re = (res.body.row_errors || []).length;
          var sk =
            kind === "programmed"
              ? (res.body.skipped_empty_period || 0) + (res.body.skipped_invalid_dates || 0)
              : res.body.skipped_no_period_dates || 0;
          var okMsg =
            kind === "programmed"
              ? "Importação concluída: " +
                (res.body.created_schedule_entries || 0) +
                " período(s) de férias gravado(s) no planejamento."
              : "Importação concluída: " +
                (res.body.updated_profiles || 0) +
                " perfil(is) atualizado(s).";
          if (um || am || re || sk) {
            okMsg +=
              " Atenção: " +
              [um ? um + " sem cadastro" : "", am ? am + " nome ambíguo" : "", re ? re + " com erro" : "", sk ? sk + " sem data/período" : ""]
                .filter(Boolean)
                .join(", ") +
              ". Veja o bloco de detalhe (JSON) na tela.";
          }
          var created =
            kind === "programmed"
              ? res.body.created_schedule_entries || 0
              : res.body.updated_profiles || 0;
          var level = !created && (um || am || re || sk) ? "error" : "success";
          showAlert(okMsg, level);
          var impModal = document.getElementById("vpImportModal");
          if (impModal && level === "success") impModal.classList.add("hidden");
          loadOverview();
        })
        .catch(function () {
          if (btn) btn.disabled = false;
          showAlert("Erro de rede na importação.", "error");
        });
    });
  }

  loadOverview();
  loadHistory();
})();
