(function () {
  "use strict";

  var root = document.querySelector('[data-page="relatorio-avaliacao-motorista"]');
  if (!root) return;

  var debounceTimer = 0;
  var openModalId = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
  }

  function teleportModals() {
    ["gerarRelatorioModal", "batchModal", "detailModal"].forEach(function (id) {
      var el = byId(id);
      if (el && el.parentElement !== document.body) {
        document.body.appendChild(el);
      }
    });
  }

  function openModal(id) {
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (current) {
      if (current.id && current.id !== id) {
        current.classList.add("hidden");
        current.classList.remove("flex");
      }
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    openModalId = id;
    setBodyLock(true);
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (openModalId === id) openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) {
      setBodyLock(false);
    }
  }

  function hidePageAlert() {
    var el = byId("page-alert");
    if (!el) return;
    el.classList.add("hidden");
    el.innerHTML = "";
  }

  function queueFilterSubmit() {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(function () {
      var form = byId("relatorioFilterForm");
      if (!form) return;
      var pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
      root.classList.add("relatorio-driver-page--navigating");
      form.requestSubmit();
    }, 360);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function badgeHtml(label, badge) {
    var cls = "sys-badge sys-badge--neutral";
    if (badge === "ok") cls = "sys-badge sys-badge--ok";
    else if (badge === "critical") cls = "sys-badge sys-badge--critical";
    else if (badge === "alert") cls = "sys-badge sys-badge--alert";
    return '<span class="' + cls + '">' + escapeHtml(label) + "</span>";
  }

  function renderDetailTable(headers, rows, emptyMessage) {
    if (!rows || !rows.length) {
      return '<p class="relatorio-driver-detail-empty">' + escapeHtml(emptyMessage) + "</p>";
    }
    var headHtml = headers
      .map(function (header) {
        return "<th>" + escapeHtml(header) + "</th>";
      })
      .join("");
    var bodyHtml = rows
      .map(function (cells) {
        return (
          "<tr>" +
          cells
            .map(function (cell) {
              return "<td>" + cell + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    return (
      '<div class="overflow-x-auto"><table class="relatorio-driver-detail-table">' +
      "<thead><tr>" +
      headHtml +
      "</tr></thead><tbody>" +
      bodyHtml +
      "</tbody></table></div>"
    );
  }

  function setDetailLoading() {
    var title = byId("detail-modal-title");
    var subtitle = document.querySelector("[data-detail-subtitle]");
    var body = document.querySelector("[data-detail-body]");
    var printLink = document.querySelector("[data-detail-print]");
    if (title) title.textContent = "Carregando detalhes...";
    if (subtitle) subtitle.textContent = "Buscando resumo do motorista selecionado.";
    if (printLink) {
      printLink.classList.add("hidden");
      printLink.setAttribute("href", "#");
    }
    if (body) {
      body.innerHTML =
        '<div class="sys-empty-state"><p class="font-medium text-slate-800 dark:text-slate-100">Carregando...</p><p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Montando resumo, top clientes e paradas.</p></div>';
    }
  }

  function setDetailError(message) {
    var title = byId("detail-modal-title");
    var subtitle = document.querySelector("[data-detail-subtitle]");
    var body = document.querySelector("[data-detail-body]");
    var printLink = document.querySelector("[data-detail-print]");
    if (title) title.textContent = "Nao foi possivel abrir o detalhe";
    if (subtitle) subtitle.textContent = "Tente novamente em instantes.";
    if (printLink) {
      printLink.classList.add("hidden");
      printLink.setAttribute("href", "#");
    }
    if (body) {
      body.innerHTML =
        '<div class="sys-empty-state"><p class="font-medium text-slate-800 dark:text-slate-100">Falha ao carregar.</p><p class="mt-1 text-sm text-slate-500 dark:text-slate-400">' +
        escapeHtml(message || "Erro inesperado.") +
        "</p></div>";
    }
  }

  function renderDetail(data) {
    var title = byId("detail-modal-title");
    var subtitle = document.querySelector("[data-detail-subtitle]");
    var body = document.querySelector("[data-detail-body]");
    var printLink = document.querySelector("[data-detail-print]");

    if (title) title.textContent = data.motorista || "Detalhes do motorista";
    if (subtitle) {
      subtitle.textContent =
        (data.date_fmt || "") +
        " · " +
        (data.turnos_label || "-") +
        " · " +
        String(data.total_paradas || 0) +
        " parada(s)";
    }
    if (printLink && data.print_href) {
      printLink.classList.remove("hidden");
      printLink.setAttribute("href", data.print_href);
    }
    if (!body) return;

    var reasonsHtml = (data.status_reasons || [])
      .map(function (reason) {
        return "<span>" + escapeHtml(reason) + "</span>";
      })
      .join("");

    var summaryCards = [
      { label: "Veiculo", value: escapeHtml((data.placa || "-") + " · " + (data.modelo || "-")) },
      { label: "Ajudantes", value: escapeHtml((data.ajudantes || []).join(", ") || "Sem ajudantes") },
      { label: "Operacao", value: escapeHtml((data.hora_inicio || "--:--") + " → " + (data.hora_fim || "--:--")) },
      { label: "Tempo", value: escapeHtml(data.tempo_operando || "—") },
      { label: "KM", value: escapeHtml(data.km_total || "—") },
      { label: "Expedido", value: escapeHtml(data.saiu_valor || "—") },
      { label: "Entregue", value: escapeHtml(data.entregue_valor || "—") },
      { label: "Devolucao", value: escapeHtml((data.devolucao_valor || "—") + " · " + (data.devolucao_pct || "0,00%")) },
    ]
      .map(function (item) {
        return (
          '<div class="relatorio-driver-detail-stat">' +
          '<span class="relatorio-driver-detail-stat__label">' +
          item.label +
          "</span>" +
          '<span class="relatorio-driver-detail-stat__value">' +
          item.value +
          "</span>" +
          "</div>"
        );
      })
      .join("");

    var topTimeRows = (data.top_time || []).map(function (row) {
      return [
        escapeHtml(row.cliente || "-"),
        escapeHtml(row.tipo || "-"),
        escapeHtml(row.duracao || "—"),
      ];
    });

    var clientRows = (data.clients || []).map(function (row) {
      return [
        escapeHtml(row.cliente || "-"),
        escapeHtml(row.tipos || "-"),
        escapeHtml(row.paradas || 0),
        escapeHtml(row.duracao || "—"),
        escapeHtml(row.janela || "—"),
        escapeHtml(row.valor || "—"),
      ];
    });

    var stopRows = (data.stops || []).map(function (row) {
      return [
        escapeHtml(row.cliente || "-"),
        escapeHtml(row.tipo || "-"),
        escapeHtml(row.inicio || "--:--"),
        escapeHtml(row.fim || "--:--"),
        escapeHtml(row.duracao || "—"),
        escapeHtml(row.kg || "—"),
        escapeHtml(row.valor || "—"),
      ];
    });

    body.innerHTML =
      '<section class="relatorio-driver-detail-section">' +
      '<div class="flex flex-wrap items-center gap-2">' +
      badgeHtml(data.status_label || "Status", data.status_badge) +
      badgeHtml(data.checklist_label || "Checklist", data.checklist_badge) +
      '<span class="employees-pill employees-pill--neutral">' +
      escapeHtml(String(data.total_clientes || 0) + " clientes") +
      "</span>" +
      '<span class="employees-pill employees-pill--neutral">' +
      escapeHtml(String(data.total_paradas || 0) + " paradas") +
      "</span>" +
      "</div>" +
      '<div class="relatorio-driver-detail-reasons">' +
      reasonsHtml +
      "</div>" +
      "</section>" +
      '<div class="relatorio-driver-detail-grid">' +
      summaryCards +
      "</div>" +
      '<section class="relatorio-driver-detail-section">' +
      '<h4 class="relatorio-driver-detail-section__title">Top tempo de parada</h4>' +
      '<p class="relatorio-driver-detail-section__subtitle">Clientes que mais consumiram tempo no dia.</p>' +
      renderDetailTable(["Cliente", "Tipo", "Tempo"], topTimeRows, "Nenhum destaque de tempo neste recorte.") +
      "</section>" +
      '<section class="relatorio-driver-detail-section">' +
      '<h4 class="relatorio-driver-detail-section__title">Resumo por cliente</h4>' +
      '<p class="relatorio-driver-detail-section__subtitle">Consolidado por cliente com janela e valor movimentado.</p>' +
      renderDetailTable(["Cliente", "Tipos", "Paradas", "Tempo", "Janela", "Valor"], clientRows, "Nenhum cliente consolidado para este motorista.") +
      "</section>" +
      '<section class="relatorio-driver-detail-section">' +
      '<h4 class="relatorio-driver-detail-section__title">Paradas do dia</h4>' +
      '<p class="relatorio-driver-detail-section__subtitle">Detalhe cronologico das entregas e devolucoes registradas.</p>' +
      renderDetailTable(["Cliente", "Tipo", "Inicio", "Fim", "Tempo", "Kg", "Valor"], stopRows, "Nenhuma parada encontrada.") +
      "</section>";
  }

  function openDetail(driverId) {
    if (!driverId) return;
    openModal("detailModal");
    setDetailLoading();

    var endpoint = root.getAttribute("data-detail-endpoint") || "";
    if (!endpoint) {
      setDetailError("Endpoint de detalhe nao configurado.");
      return;
    }

    var url = new URL(endpoint, window.location.origin);
    url.searchParams.set("date", root.getAttribute("data-current-date") || "");
    url.searchParams.set("driver_id", String(driverId));

    fetch(url.pathname + url.search, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response.json().catch(function () {
          return {};
        }).then(function (data) {
          if (!response.ok) {
            throw new Error(data.error || "Falha ao carregar detalhe.");
          }
          return data;
        });
      })
      .then(renderDetail)
      .catch(function (error) {
        setDetailError(error && error.message ? error.message : "Erro ao carregar detalhe.");
      });
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-dismiss-alert]")) {
      hidePageAlert();
      return;
    }

    var closeBtn = event.target.closest("[data-close-modal]");
    if (closeBtn) {
      closeModal(closeBtn.getAttribute("data-close-modal"));
      return;
    }

    if (event.target.classList.contains("emp-modal-shell")) {
      closeModal(event.target.id);
      return;
    }

    var detailTrigger = event.target.closest("[data-open-detail]");
    if (detailTrigger) {
      openDetail(detailTrigger.getAttribute("data-driver-id"));
      return;
    }

    var openBtn = event.target.closest("[data-open-modal]");
    if (openBtn) {
      openModal(openBtn.getAttribute("data-open-modal"));
      return;
    }

    if (event.target.closest("[data-clear-driver-picker]")) {
      document
        .querySelectorAll('#gerarRelatorioModal input[type="checkbox"][name="driver_id"]')
        .forEach(function (input) {
          input.checked = false;
        });
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && openModalId) {
      closeModal(openModalId);
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-debounce-submit='true']")) {
      queueFilterSubmit();
      return;
    }

    if (event.target.matches("[data-driver-picker-search]")) {
      var query = String(event.target.value || "").trim().toLowerCase();
      document.querySelectorAll("[data-driver-picker-option]").forEach(function (option) {
        var label = option.getAttribute("data-driver-label") || "";
        option.classList.toggle("hidden", !!query && label.indexOf(query) === -1);
      });
    }
  });

  var filterForm = byId("relatorioFilterForm");
  if (filterForm) {
    filterForm.addEventListener("submit", function () {
      root.classList.add("relatorio-driver-page--navigating");
    });
  }

  window.addEventListener("pageshow", function () {
    root.classList.remove("relatorio-driver-page--navigating");
  });

  teleportModals();
})();
