(function () {
  "use strict";

  var root = document.querySelector('[data-page="vacation-planning"]');
  if (!root) return;

  var INITIAL_TABLE_LIMIT = 25;
  var employeeOptionsFull = [];
  var cachedRows = [];
  var activeFilter = "critical";
  var showAllRows = false;

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
    byId("vp-strip-decision").textContent = sit.decision_label || "—";
    byId("vp-strip-risk").textContent =
      sit.operational_risk != null ? String(sit.operational_risk) : "—";
    byId("vp-strip-cap").textContent =
      sit.capacity_hint != null ? String(sit.capacity_hint) : "—";
    byId("vp-strip-sched").textContent =
      sit.scheduled_count != null ? String(sit.scheduled_count) : "—";
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
    return {
      status_color: situation,
      decision_label: labels[decision_key] || decision_key,
      operational_risk: k.operational_risk_month,
      capacity_hint: cap,
      scheduled_count: sched,
      guidance_text: g,
    };
  }

  function renderYearGrid(data) {
    var grid = byId("vp-year-grid");
    if (!grid) return;
    var sel = qs().month;
    grid.innerHTML = "";
    (data.monthly || []).forEach(function (row) {
      var m = row.month;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "vp-month-card";
      if (m === sel) btn.classList.add("vp-month-card--selected");
      var st = row.status_color || "yellow";
      var stLabel = st === "green" ? "Verde" : st === "red" ? "Vermelho" : "Amarelo";
      btn.innerHTML =
        '<span class="vp-month-card__name">' +
        escapeHtml(row.month_name) +
        "</span>" +
        '<p class="vp-month-card__demand">' +
        escapeHtml(row.demand_label || "") +
        " demanda</p>" +
        '<p class="vp-month-card__nums tabular-nums">' +
        (row.scheduled_count != null ? row.scheduled_count : "—") +
        "/" +
        (row.capacity_hint != null ? row.capacity_hint : "—") +
        " programadas</p>" +
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

  function rowNeedsAttention(row) {
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
    if (filter === "critical") return rowNeedsAttention(row);
    if (filter === "expired") return row.vacation_status === "expired";
    if (filter === "d30") return d != null && d >= 0 && d <= 30;
    if (filter === "d6090") return d != null && d > 30 && d <= 90;
    if (filter === "no_sub") return subEmpty && c !== "baixa";
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

  function prazoLabel(row) {
    var d = row.days_until_deadline;
    if (d == null) return "—";
    if (d < 0) return "Vencida (" + Math.abs(d) + "d)";
    return String(d) + " dias";
  }

  function prioridadeLabel(row) {
    var p = row.priority_index != null ? row.priority_index : "—";
    var c = (row.criticality || "").toLowerCase();
    var tag =
      c === "muito_alta" || c === "alta"
        ? ' <span class="text-rose-600 dark:text-rose-300 font-semibold text-xs">Alta</span>'
        : "";
    return '<span class="tabular-nums">' + escapeHtml(String(p)) + "</span>" + tag;
  }

  function rowHighlightClass(row) {
    if (row.vacation_status === "expired" || row.window_color === "red") return "vp-queue-row--hot";
    var d = row.days_until_deadline;
    if (d != null && d >= 0 && d <= 30) return "vp-queue-row--hot";
    if (row.window_color === "yellow") return "vp-queue-row--warn";
    if (d != null && d <= 60) return "vp-queue-row--warn";
    return "";
  }

  function openDetailModal(row) {
    var modal = byId("vp-detail-modal");
    var back = byId("vp-detail-backdrop");
    var body = byId("vp-detail-body");
    var title = byId("vp-detail-title");
    if (!modal || !body || !title) return;
    title.textContent = row.name || "Colaborador";
    var hint = row.window_hint || "";
    var wc = row.window_color || "";
    body.innerHTML =
      "<dl>" +
      "<dt>Função</dt><dd>" +
      escapeHtml(row.role || "—") +
      "</dd>" +
      "<dt>Status trabalhista</dt><dd>" +
      escapeHtml(row.vacation_status_label || "—") +
      "</dd>" +
      "<dt>Criticidade</dt><dd>" +
      escapeHtml(row.criticality || "—") +
      "</dd>" +
      "<dt>Substituto</dt><dd>" +
      escapeHtml(row.substitute || "—") +
      (row.substitute_trained ? " (treinado)" : "") +
      "</dd>" +
      "<dt>Janela no mês focado</dt><dd><span class=\"" +
      statusClass(wc) +
      "\">" +
      escapeHtml(wc || "—") +
      "</span>" +
      (hint ? " — " + escapeHtml(hint) : "") +
      "</dd>" +
      "<dt>Índice de prioridade</dt><dd class=\"tabular-nums\">" +
      escapeHtml(row.priority_index != null ? String(row.priority_index) : "—") +
      "</dd>" +
      "<dt>Setor / rota</dt><dd>" +
      escapeHtml((row.sector || "") + (row.route_team ? " · " + row.route_team : "") || "—") +
      "</dd>" +
      "</dl>";
    modal.classList.remove("hidden");
    back.classList.remove("hidden");
  }

  function closeDetailModal() {
    var modal = byId("vp-detail-modal");
    var back = byId("vp-detail-backdrop");
    if (modal) modal.classList.add("hidden");
    if (back) back.classList.add("hidden");
  }

  function setSimulatorEmployee(employeeId) {
    var sim = byId("vp-sim-employee");
    if (!sim) return;
    rebuildEmployeeSelects(byId("vp-p-search") ? byId("vp-p-search").value : "");
    sim.value = String(employeeId);
    sim.dispatchEvent(new Event("change", { bubbles: true }));
    try {
      sim.focus();
    } catch (e) {}
    var aside = byId("vp-sim-aside");
    if (aside && window.matchMedia && window.matchMedia("(max-width: 1023px)").matches) {
      aside.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function renderQueueTable(rows) {
    var rb = byId("vp-rows-body");
    var empty = byId("vp-queue-empty");
    var countEl = byId("vp-queue-count");
    var btnAll = byId("vp-queue-show-all");
    if (!rb) return;

    var filtered = filterRows(
      rows,
      activeFilter,
      byId("vp-queue-search") ? byId("vp-queue-search").value : ""
    );
    var limited = showAllRows ? filtered : filtered.slice(0, INITIAL_TABLE_LIMIT);

    rb.innerHTML = "";
    if (filtered.length === 0) {
      if (empty) empty.classList.remove("hidden");
      if (countEl) countEl.textContent = "";
      if (btnAll) btnAll.classList.add("hidden");
      return;
    }
    if (empty) empty.classList.add("hidden");

    limited.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.className = rowHighlightClass(row);
      var eid = row.employee_id;
      tr.innerHTML =
        "<td>" +
        escapeHtml(row.name) +
        "</td>" +
        "<td class=\"text-xs text-slate-600 dark:text-slate-400\">" +
        escapeHtml(row.role) +
        "</td>" +
        "<td class=\"text-xs\">" +
        escapeHtml(row.vacation_status_label) +
        "</td>" +
        "<td class=\"tabular-nums text-xs\">" +
        escapeHtml(prazoLabel(row)) +
        "</td>" +
        "<td class=\"text-xs\">" +
        prioridadeLabel(row) +
        "</td>" +
        "<td class=\"text-xs\">" +
        escapeHtml(row.best_period_hint || "—") +
        "</td>" +
        "<td class=\"vp-queue-table__actions\">" +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary text-xs py-1 px-2 vp-btn-sim\" data-eid=\"" +
        eid +
        "\">Simular</button> " +
        "<button type=\"button\" class=\"sys-btn sys-btn--secondary text-xs py-1 px-2 vp-btn-det\" data-eid=\"" +
        eid +
        "\">Ver detalhes</button>" +
        "</td>";
      rb.appendChild(tr);
    });

    rb.querySelectorAll(".vp-btn-sim").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = parseInt(b.getAttribute("data-eid"), 10);
        if (id) setSimulatorEmployee(id);
      });
    });
    rb.querySelectorAll(".vp-btn-det").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = parseInt(b.getAttribute("data-eid"), 10);
        var found = rows.find(function (r) { return r.employee_id === id; });
        if (found) openDetailModal(found);
      });
    });

    if (countEl) {
      countEl.textContent =
        "Exibindo " +
        limited.length +
        " de " +
        filtered.length +
        (filtered.length !== rows.length ? " (filtrado)" : "");
    }
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
  }

  function applyFilterChip(name) {
    activeFilter = name;
    showAllRows = false;
    root.querySelectorAll(".vp-chip").forEach(function (c) {
      c.classList.toggle("vp-chip--active", c.getAttribute("data-vp-filter") === name);
    });
    renderQueueTable(cachedRows);
  }

  function loadOverview() {
    hideAlert();
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
        var k = data.kpis || {};
        byId("vp-kpi-expired").textContent = String(k.expired ?? "0");
        byId("vp-kpi-d30").textContent = String(k.due_30 ?? "0");
        var d6090 =
          k.due_60_90 != null
            ? k.due_60_90
            : (parseInt(k.due_60, 10) || 0) + (parseInt(k.due_90, 10) || 0);
        byId("vp-kpi-d6090").textContent = String(d6090);
        byId("vp-kpi-sched").textContent = String(k.scheduled_in_month ?? "0");

        renderMonthStrip(data);
        renderYearGrid(data);

        cachedRows = data.rows || [];
        renderQueueTable(cachedRows);

        employeeOptionsFull = data.employees_options || [];
        rebuildEmployeeSelects(byId("vp-p-search") ? byId("vp-p-search").value : "");
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
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
      })
      .catch(function () {
        showAlert("Não foi possível carregar o perfil.", "error");
      });
  }

  function loadHistory() {
    fetch("/api/vacation-planning/history?limit=80", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var hb = byId("vp-history-body");
        hb.innerHTML = "";
        (data.items || []).forEach(function (h) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var sync = h.employee_vacation_synced ? "Sim" : "Não";
          tr.innerHTML =
            "<td class=\"px-3 py-2 text-xs whitespace-nowrap\">" +
            (h.created_at || "").replace("T", " ").slice(0, 19) +
            "</td>" +
            "<td class=\"px-3 py-2\">" +
            escapeHtml(h.employee_name) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(h.start) +
            " → " +
            escapeHtml(h.end) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(h.status) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(h.source) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(h.approved_by || "—") +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\" title=\"" +
            escapeHtml(
              h.employee_vacation_sync_detail && h.employee_vacation_sync_detail.message
                ? h.employee_vacation_sync_detail.message
                : ""
            ) +
            "\">" +
            sync +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs max-w-xs truncate\" title=\"" +
            escapeHtml(h.decision_reason || "") +
            "\">" +
            escapeHtml(h.decision_reason || "—") +
            "</td>";
          hb.appendChild(tr);
        });
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
            escapeHtml(s.suggested_start) +
            " → " +
            escapeHtml(s.suggested_end) +
            "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" +
            escapeHtml(reasons) +
            "</td>";
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
        return r.json();
      })
      .then(function (data) {
        var pre = byId("vp-sim-result");
        if (!data.ok) {
          if (hi) hi.classList.add("hidden");
          pre.classList.remove("hidden");
          pre.textContent = data.error || "Erro";
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
        pre.classList.remove("hidden");
        pre.textContent = lines.join("\n\n");
      })
      .catch(function () {
        showAlert("Falha na simulação.", "error");
      });
  }

  function saveSchedule() {
    var q = qs();
    var eid = byId("vp-sim-employee").value;
    var start = byId("vp-sim-start").value;
    var end = byId("vp-sim-end").value;
    var reason = (byId("vp-schedule-reason").value || "").trim();
    var sync = byId("vp-sync-employee").checked;
    if (!eid || !start || !end) {
      showAlert("Preencha colaborador e datas (use o simulador).", "error");
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
        source: "manual",
        decision_reason: reason || null,
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
          throw new Error(d || "Falha ao salvar");
        }
        var msg = "Registro salvo.";
        if (res.body.employee_vacation_sync && res.body.employee_vacation_sync.message) {
          msg += " " + res.body.employee_vacation_sync.message;
        }
        showAlert(msg, "success");
        loadOverview();
        loadHistory();
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
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

  root.querySelectorAll(".vp-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var name = chip.getAttribute("data-vp-filter");
      if (name) applyFilterChip(name);
    });
  });

  var searchEl = byId("vp-queue-search");
  if (searchEl) {
    searchEl.addEventListener("input", function () {
      showAllRows = false;
      renderQueueTable(cachedRows);
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
  byId("vp-detail-backdrop").addEventListener("click", closeDetailModal);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeDetailModal();
  });

  root.querySelectorAll(".vp-tabs__btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tab = btn.getAttribute("data-vp-tab");
      if (tab) switchSecondaryTab(tab);
    });
  });

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
          showAlert(
            "Importação concluída: " +
              (res.body.updated_profiles || 0) +
              " perfil(is) atualizado(s).",
            "success"
          );
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
