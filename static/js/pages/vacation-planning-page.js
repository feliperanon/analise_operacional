(function () {
  "use strict";

  var root = document.querySelector('[data-page="vacation-planning"]');
  if (!root) return;

  var employeeOptionsFull = [];

  function byId(id) { return document.getElementById(id); }

  function showAlert(msg, level) {
    var el = byId("vp-alert");
    if (!el) return;
    el.className = "sys-alert flex items-center gap-3 " + (level === "error" ? "sys-alert--danger" : "sys-alert--success");
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

  function rebuildEmployeeSelects(filterText) {
    var f = (filterText || "").toLowerCase().trim();
    var sim = byId("vp-sim-employee");
    var prof = byId("vp-profile-employee");
    var prevSim = sim ? sim.value : "";
    var prevProf = prof ? prof.value : "";
    if (sim) {
      sim.innerHTML = "<option value=\"\">Selecione…</option>";
    }
    if (prof) {
      prof.innerHTML = "<option value=\"\">Selecione…</option>";
    }
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

  function loadOverview() {
    hideAlert();
    var q = qs();
    var url = "/api/vacation-planning/overview?year=" + encodeURIComponent(q.year) +
      "&cost_center=" + encodeURIComponent(q.cost_center) +
      "&month=" + encodeURIComponent(q.month);
    return fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("Falha ao carregar painel");
        return r.json();
      })
      .then(function (data) {
        var k = data.kpis || {};
        byId("vp-kpi-expired").textContent = String(k.expired ?? "0");
        byId("vp-kpi-d30").textContent = String(k.due_30 ?? "0");
        byId("vp-kpi-d60").textContent = String(k.due_60 ?? "0");
        byId("vp-kpi-d90").textContent = String(k.due_90 ?? "0");
        byId("vp-kpi-sched").textContent = String(k.scheduled_in_month ?? "0");
        byId("vp-kpi-risk").textContent = String(k.operational_risk_month ?? "—");

        var mb = byId("vp-monthly-body");
        mb.innerHTML = "";
        (data.monthly || []).forEach(function (row) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var st = row.status_color || "yellow";
          tr.innerHTML =
            "<td class=\"px-3 py-2 font-medium\">" + row.month_name + "</td>" +
            "<td class=\"px-3 py-2\">" + row.demand_label + " (" + row.demand_index + ")</td>" +
            "<td class=\"px-3 py-2 tabular-nums\">" + row.capacity_hint + "</td>" +
            "<td class=\"px-3 py-2 tabular-nums\">" + row.scheduled_count + "</td>" +
            "<td class=\"px-3 py-2\"><span class=\"" + statusClass(st) + "\">" + st + "</span></td>" +
            "<td class=\"px-3 py-2 tabular-nums\">" + (row.risk_score != null ? row.risk_score : "—") + "</td>";
          mb.appendChild(tr);
        });

        var rb = byId("vp-rows-body");
        rb.innerHTML = "";
        (data.rows || []).forEach(function (row) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var d = row.days_until_deadline;
          var dlabel = d == null ? "—" : String(d);
          var wc = row.window_color || "yellow";
          tr.innerHTML =
            "<td class=\"px-3 py-2\">" + row.name + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + row.role + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + row.vacation_status_label + "</td>" +
            "<td class=\"px-3 py-2 tabular-nums\">" + dlabel + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + row.criticality + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + row.substitute + (row.substitute_trained ? " ✓" : "") + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + row.best_period_hint + "</td>" +
            "<td class=\"px-3 py-2 tabular-nums\">" + row.priority_index + "</td>" +
            "<td class=\"px-3 py-2\"><span class=\"" + statusClass(wc) + "\">" + wc + "</span></td>";
          rb.appendChild(tr);
        });

        employeeOptionsFull = data.employees_options || [];
        rebuildEmployeeSelects(byId("vp-p-search") ? byId("vp-p-search").value : "");
      })
      .catch(function (e) {
        showAlert(e.message || "Erro", "error");
      });
  }

  function loadCalibrationTable() {
    var y = parseInt(byId("vp-cal-year").value, 10) || currentYear();
    return fetch("/api/vacation-planning/month-demand?year=" + encodeURIComponent(y), { credentials: "same-origin" })
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
          badge.className = m.source === "calibrated" ? "vp-badge vp-badge--ok" : "vp-badge vp-badge--muted";
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
    var demInput = tb.querySelector(".vp-cal-dem[data-m=\"" + month + "\"]");
    var noteInput = tb.querySelector(".vp-cal-note[data-m=\"" + month + "\"]");
    var jsonInput = tb.querySelector(".vp-cal-json[data-m=\"" + month + "\"]");
    var di = parseInt(demInput && demInput.value, 10);
    if (isNaN(di) || di < 0 || di > 100) {
      showAlert("Índice de demanda deve ser 0–100.", "error");
      return;
    }
    var rawJson = (jsonInput && jsonInput.value || "").trim();
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
      risk_notes: (noteInput && noteInput.value || "").trim() || null,
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
          if (Array.isArray(det)) det = det.map(function (x) { return x.msg || x; }).join("; ");
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
    fetch("/api/vacation-planning/profile/" + encodeURIComponent(employeeId), { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("Perfil não encontrado");
        return r.json();
      })
      .then(function (data) {
        var vp = data.vacation_profile || {};
        byId("vp-p-sector").value = vp.department_sector || "";
        byId("vp-p-route").value = vp.route_team || "";
        byId("vp-p-criticality").value = vp.criticality || "media";
        byId("vp-p-sub-id").value = vp.substitute_employee_id != null ? String(vp.substitute_employee_id) : "";
        byId("vp-p-sub-trained").checked = !!vp.substitute_trained;
        byId("vp-p-aq-end").value = vp.acquisition_period_end || "";
        byId("vp-p-last-v").value = vp.last_vacation_end || "";
        byId("vp-p-days").value = vp.vacation_days_available != null ? String(vp.vacation_days_available) : "";
      })
      .catch(function () {
        showAlert("Não foi possível carregar o perfil.", "error");
      });
  }

  function loadHistory() {
    fetch("/api/vacation-planning/history?limit=80", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var hb = byId("vp-history-body");
        hb.innerHTML = "";
        (data.items || []).forEach(function (h) {
          var tr = document.createElement("tr");
          tr.className = "border-b border-slate-100 dark:border-slate-800";
          var sync = h.employee_vacation_synced ? "Sim" : "Não";
          tr.innerHTML =
            "<td class=\"px-3 py-2 text-xs whitespace-nowrap\">" + (h.created_at || "").replace("T", " ").slice(0, 19) + "</td>" +
            "<td class=\"px-3 py-2\">" + h.employee_name + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + h.start + " → " + h.end + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + h.status + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + h.source + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + (h.approved_by || "—") + "</td>" +
            "<td class=\"px-3 py-2 text-xs\" title=\"" + (h.employee_vacation_sync_detail && h.employee_vacation_sync_detail.message ? h.employee_vacation_sync_detail.message : "") + "\">" + sync + "</td>" +
            "<td class=\"px-3 py-2 text-xs max-w-xs truncate\" title=\"" + (h.decision_reason || "") + "\">" + (h.decision_reason || "—") + "</td>";
          hb.appendChild(tr);
        });
      });
  }

  function runSuggest() {
    var q = qs();
    showAlert("Gerando sugestões…", "success");
    fetch("/api/vacation-planning/suggest?year=" + encodeURIComponent(q.year) +
      "&cost_center=" + encodeURIComponent(q.cost_center),
      { method: "POST", credentials: "same-origin" })
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
            "<td class=\"px-3 py-2 tabular-nums\">" + s.priority_rank + "</td>" +
            "<td class=\"px-3 py-2\">" + s.name + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + s.role + "</td>" +
            "<td class=\"px-3 py-2 text-xs whitespace-nowrap\">" + s.suggested_start + " → " + s.suggested_end + "</td>" +
            "<td class=\"px-3 py-2 text-xs\">" + reasons + "</td>";
          sb.appendChild(tr);
        });
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
      .then(function (r) { return r.json(); })
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
        lines.push("Substituto: " + (data.substitute_available ? "sim" : "não") +
          (data.substitute_trained ? " (treinado)" : ""));
        lines.push("Demanda (índice min–max): " + data.demand_index_range.min + " – " + data.demand_index_range.max);
        lines.push("Sobreposição mesma função: " + data.concurrent_same_role + " / limite " + data.role_limit);
        if (data.alerts && data.alerts.length) lines.push("Alertas:\n- " + data.alerts.join("\n- "));
        if (data.blocks && data.blocks.length) lines.push("Bloqueios:\n- " + data.blocks.join("\n- "));
        if (data.scores) {
          lines.push("Notas: urgência " + data.scores.urgencia_trabalhista +
            " | criticidade " + data.scores.criticidade_operacional +
            " | oportunidade " + data.scores.oportunidade_periodo +
            " | cobertura " + data.scores.cobertura_equipe);
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
          if (Array.isArray(d)) d = d.map(function (x) { return x.msg || x; }).join("; ");
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
      substitute_employee_id: byId("vp-p-sub-id").value ? parseInt(byId("vp-p-sub-id").value, 10) : null,
      substitute_trained: byId("vp-p-sub-trained").checked,
      acquisition_period_end: byId("vp-p-aq-end").value || null,
      last_vacation_end: byId("vp-p-last-v").value || null,
      vacation_days_available: byId("vp-p-days").value ? parseInt(byId("vp-p-days").value, 10) : null,
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

  byId("vp-year").value = String(currentYear());
  byId("vp-month").value = String(currentMonth());
  byId("vp-cal-year").value = String(currentYear());

  byId("vp-refresh").addEventListener("click", function () { loadOverview(); });
  byId("vp-suggest").addEventListener("click", runSuggest);
  byId("vp-sim-run").addEventListener("click", runSimulate);
  byId("vp-schedule-save").addEventListener("click", saveSchedule);
  byId("vp-history-refresh").addEventListener("click", loadHistory);
  byId("vp-profile-save").addEventListener("click", saveProfile);
  byId("vp-cal-load").addEventListener("click", function () { loadCalibrationTable(); });

  byId("vp-p-search").addEventListener("input", function () {
    rebuildEmployeeSelects(byId("vp-p-search").value);
  });

  byId("vp-profile-employee").addEventListener("change", function () {
    var v = byId("vp-profile-employee").value;
    if (v) loadProfileForEmployee(v);
  });

  byId("vp-year").addEventListener("change", function () {
    byId("vp-cal-year").value = byId("vp-year").value;
  });

  loadOverview();
  loadHistory();
})();
