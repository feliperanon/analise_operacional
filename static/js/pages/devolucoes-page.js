(function () {
  "use strict";

  var pageRoot = document.querySelector('[data-page="devolucoes"]');
  if (!pageRoot) return;

  var state = {
    openModalId: null,
    confirmHandler: null,
    importPreview: null,
    debounceTimer: 0,
    filterChangeTimer: 0,
    clientSearchTimer: 0,
    clientSearchController: null,
    bulkCountRaf: 0,
    manualElementsCache: null,
    modalsTeleported: false,
  };

  var SEARCH_DEBOUNCE_MS = 380;
  var FILTER_CHANGE_DEBOUNCE_MS = 220;

  var currencyFormatter = new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function byId(id) {
    return document.getElementById(id);
  }

  function teleportModalsToBody() {
    ["importModal", "manualDevolucaoModal", "batchOperationsModal", "confirmActionModal"].forEach(function (id) {
      var modal = byId(id);
      if (!modal || modal.parentElement === document.body) return;
      document.body.appendChild(modal);
    });
  }

  function ensureModalsTeleported() {
    if (state.modalsTeleported) return;
    state.modalsTeleported = true;
    teleportModalsToBody();
  }

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
  }

  function openModal(id) {
    ensureModalsTeleported();
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (openShell) {
      if (openShell.id && openShell.id !== id) {
        openShell.classList.add("hidden");
        openShell.classList.remove("flex");
      }
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    modal.scrollTop = 0;
    var modalCard = modal.querySelector(".devolucoes-modal-card");
    if (modalCard) modalCard.scrollTop = 0;
    state.openModalId = id;
    setBodyLock(true);
    window.requestAnimationFrame(function () {
      var target = modal.querySelector("[data-autofocus], input:not([type='hidden']), select, textarea, button");
      if (!target) return;
      try {
        target.focus({ preventScroll: true });
      } catch (_error) {
        target.focus();
      }
    });
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (state.openModalId === id) state.openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) {
      setBodyLock(false);
    }
  }

  function closeActiveModal() {
    if (state.openModalId) closeModal(state.openModalId);
  }

  function buildAlert(message, level) {
    var alert = byId("page-alert");
    if (!alert) return null;
    alert.className =
      "sys-alert flex items-center gap-3 " +
      (level === "error"
        ? "sys-alert--danger"
        : level === "success"
          ? "sys-alert--success"
          : "sys-alert--info");
    alert.setAttribute("role", "alert");
    alert.innerHTML = "";

    var iconWrap = document.createElement("span");
    iconWrap.className = "flex h-5 w-5 shrink-0 items-center justify-center";
    iconWrap.setAttribute("aria-hidden", "true");
    iconWrap.innerHTML =
      level === "success"
        ? '<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
        : '<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
    alert.appendChild(iconWrap);

    var content = document.createElement("span");
    content.className = "min-w-0 flex-1";
    content.textContent = message || "Ocorreu uma atualização.";
    alert.appendChild(content);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "emp-modal-close shrink-0";
    button.setAttribute("data-dismiss-alert", "true");
    button.setAttribute("aria-label", "Fechar");
    button.textContent = "x";
    alert.appendChild(button);

    return alert;
  }

  function showPageAlert(message, level) {
    var alert = buildAlert(message, level);
    if (!alert) return;
    alert.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function hidePageAlert() {
    var alert = byId("page-alert");
    if (!alert) return;
    alert.classList.add("hidden");
    alert.innerHTML = "";
  }

  function setButtonBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent;
      button.disabled = true;
      button.classList.add("opacity-70");
      button.textContent = label || "Processando...";
      return;
    }
    button.disabled = false;
    button.classList.remove("opacity-70");
    if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
  }

  function parseJsonSafe(value) {
    if (!value) return null;
    try {
      return JSON.parse(value);
    } catch (_error) {
      return null;
    }
  }

  function formatMoneyValue(value) {
    var amount = Number(value || 0);
    if (!isFinite(amount)) amount = 0;
    return currencyFormatter.format(amount);
  }

  function parseMoneyValue(rawValue) {
    var value = String(rawValue || "").trim();
    if (!value) return 0;
    value = value.replace(/\s+/g, "").replace(/[R$]/gi, "");
    if (value.indexOf(",") >= 0 && value.indexOf(".") >= 0) {
      if (value.lastIndexOf(",") > value.lastIndexOf(".")) {
        value = value.replace(/\./g, "").replace(",", ".");
      } else {
        value = value.replace(/,/g, "");
      }
    } else if (value.indexOf(",") >= 0) {
      value = value.replace(/\./g, "").replace(",", ".");
    } else {
      var dotMatches = value.match(/\./g);
      if (dotMatches && dotMatches.length > 1) {
        value = value.replace(/\./g, "");
      }
    }
    var parsed = Number(value.replace(/[^\d.-]/g, ""));
    return isFinite(parsed) ? parsed : 0;
  }

  async function fetchJson(url, options) {
    var response = await fetch(url, Object.assign({ credentials: "same-origin" }, options || {}));
    var payload = null;
    var text = "";
    try {
      text = await response.text();
      payload = text ? JSON.parse(text) : null;
    } catch (_jsonError) {
      payload = null;
    }
    if (!response.ok) {
      var message = (payload && (payload.error || payload.message)) || text || "Não foi possível concluir a solicitação.";
      throw new Error(message);
    }
    return payload;
  }

  function redirectWithFlash(message, level) {
    var url = new URL(window.location.href);
    url.searchParams.set("message", message || "Atualização concluída.");
    url.searchParams.set("level", level || "success");
    window.location.assign(url.toString());
  }

  function getBulkCheckboxes() {
    return Array.prototype.slice.call(document.querySelectorAll(".devolucao-bulk-cb"));
  }

  function updateBulkCount() {
    if (state.bulkCountRaf) {
      window.cancelAnimationFrame(state.bulkCountRaf);
      state.bulkCountRaf = 0;
    }
    state.bulkCountRaf = window.requestAnimationFrame(function () {
      state.bulkCountRaf = 0;
      var boxes = getBulkCheckboxes();
      var checked = boxes.filter(function (box) {
        return !!box.checked;
      });
      var count = checked.length;
      var master = byId("devolucao-bulk-select-all");
      var countEl = byId("bulk-selected-count");
      var modalCountEl = byId("batch-modal-selected-count");

      boxes.forEach(function (box) {
        var row = box.closest(".employee-row");
        if (row) row.classList.toggle("devolucao-row--selected", !!box.checked);
      });

      if (countEl) countEl.textContent = String(count);
      if (modalCountEl) modalCountEl.textContent = String(count);
      if (master) {
        master.checked = boxes.length > 0 && count === boxes.length;
        master.indeterminate = count > 0 && count < boxes.length;
      }
    });
  }

  function getSelectedIds(approvableOnly) {
    return getBulkCheckboxes()
      .filter(function (box) {
        if (!box.checked) return false;
        if (!approvableOnly) return true;
        return box.dataset.canApprove === "true";
      })
      .map(function (box) {
        return Number(box.value);
      })
      .filter(function (id) {
        return isFinite(id) && id > 0;
      });
  }

  function updateConfirmButtonTone(tone, label) {
    var button = byId("confirm-action-submit");
    if (!button) return;
    button.classList.remove("sys-btn--danger");
    button.classList.remove("sys-btn--primary");
    button.classList.add(tone === "danger" ? "sys-btn--danger" : "sys-btn--primary");
    button.textContent = label || "Confirmar";
    button.dataset.originalLabel = label || "Confirmar";
  }

  function openConfirmModal(config) {
    var title = byId("confirm-action-title");
    var text = byId("confirm-action-text");
    if (title) title.textContent = config.title || "Confirmar ação";
    if (text) text.textContent = config.text || "Deseja continuar?";
    updateConfirmButtonTone(config.tone, config.confirmLabel);
    state.confirmHandler = config.onConfirm || null;
    openModal("confirmActionModal");
  }

  async function runConfirmAction() {
    if (typeof state.confirmHandler !== "function") {
      closeModal("confirmActionModal");
      return;
    }
    var button = byId("confirm-action-submit");
    try {
      setButtonBusy(button, true, "Processando...");
      await state.confirmHandler();
    } catch (error) {
      showPageAlert(error.message || "Não foi possível concluir a ação.", "error");
    } finally {
      setButtonBusy(button, false);
      closeModal("confirmActionModal");
      state.confirmHandler = null;
    }
  }

  function getDefaultDateValue() {
    return pageRoot.dataset.reconnectEnd || new Date().toISOString().slice(0, 10);
  }

  function getManualElements() {
    if (state.manualElementsCache) return state.manualElementsCache;
    state.manualElementsCache = {
      form: byId("manual-devolucao-form"),
      id: byId("manual-devolucao-id"),
      title: byId("manual-devolucao-title"),
      submit: byId("manual-devolucao-submit"),
      dataRomaneio: byId("manual-data-romaneio"),
      dataEntrega: byId("manual-data-entrega"),
      clientId: byId("manual-client-id"),
      clientSearch: byId("manual-client-search"),
      clientSuggestions: byId("manual-client-suggestions"),
      clientSelected: byId("manual-client-selected"),
      clientSelectedName: byId("manual-client-selected-name"),
      clientSelectedDetail: byId("manual-client-selected-detail"),
      vendedor: byId("manual-vendedor"),
      motorista: byId("manual-motorista"),
      ajudante: byId("manual-ajudante"),
      valor: byId("manual-valor"),
      motivo: byId("manual-motivo"),
      observacao: byId("manual-observacao"),
      responsabilidade: byId("manual-responsabilidade"),
    };
    return state.manualElementsCache;
  }

  function clearClientSuggestions() {
    var elements = getManualElements();
    if (!elements.clientSuggestions) return;
    elements.clientSuggestions.classList.add("hidden");
    elements.clientSuggestions.innerHTML = "";
  }

  function setSelectedClient(client) {
    var elements = getManualElements();
    if (!elements.clientId || !elements.clientSelected || !elements.clientSearch) return;
    var nb = client.nb ? "NB " + client.nb : "";
    var detailParts = [nb, client.nome_fantasia || client.client_fantasia || "", client.endereco || ""].filter(Boolean);
    elements.clientId.value = client.id || "";
    elements.clientSelected.classList.remove("hidden");
    elements.clientSelectedName.textContent = client.name || client.client_name || "Cliente selecionado";
    elements.clientSelectedDetail.textContent = detailParts.join(" | ");
    elements.clientSearch.value = client.display || client.name || client.client_name || "";
    elements.clientSearch.readOnly = true;
    clearClientSuggestions();
  }

  function clearSelectedClient(focusInput) {
    var elements = getManualElements();
    if (!elements.clientId || !elements.clientSelected || !elements.clientSearch) return;
    elements.clientId.value = "";
    elements.clientSelected.classList.add("hidden");
    elements.clientSelectedName.textContent = "";
    elements.clientSelectedDetail.textContent = "";
    elements.clientSearch.readOnly = false;
    elements.clientSearch.value = "";
    clearClientSuggestions();
    if (focusInput) elements.clientSearch.focus();
  }

  function resetManualForm() {
    var elements = getManualElements();
    if (!elements.form) return;
    elements.form.reset();
    if (elements.id) elements.id.value = "";
    clearSelectedClient(false);
    if (elements.title) elements.title.textContent = "Nova Devolução";
    if (elements.submit) {
      elements.submit.textContent = "Salvar devolução";
      elements.submit.dataset.originalLabel = "Salvar devolução";
    }
    var defaultDate = getDefaultDateValue();
    if (elements.dataRomaneio) elements.dataRomaneio.value = defaultDate;
    if (elements.dataEntrega) elements.dataEntrega.value = defaultDate;
  }

  function fillManualForm(row) {
    var elements = getManualElements();
    if (!elements.form) return;
    resetManualForm();
    if (elements.id) elements.id.value = row.id || "";
    if (elements.title) elements.title.textContent = "Editar Devolução";
    if (elements.submit) {
      elements.submit.textContent = "Salvar alterações";
      elements.submit.dataset.originalLabel = "Salvar alterações";
    }
    if (elements.dataRomaneio) elements.dataRomaneio.value = row.data_romaneio || getDefaultDateValue();
    if (elements.dataEntrega) elements.dataEntrega.value = row.data_entrega || row.data_efetiva || getDefaultDateValue();
    if (elements.vendedor) elements.vendedor.value = row.vendedor_id || "";
    if (elements.motorista) elements.motorista.value = row.motorista_id || "";
    if (elements.ajudante) elements.ajudante.value = row.ajudante_id || "";
    if (elements.valor) elements.valor.value = formatMoneyValue(row.valor || 0);
    if (elements.motivo) elements.motivo.value = row.motivo_id || "";
    if (elements.observacao) elements.observacao.value = row.observacao || "";
    if (elements.responsabilidade) elements.responsabilidade.value = row.responsabilidade_id || "";
    setSelectedClient({
      id: row.client_id,
      name: row.client_name || row.client_razao_social || "",
      nb: row.client_code || "",
      nome_fantasia: row.client_fantasia || "",
      display: row.client_name || row.client_razao_social || "",
    });
  }

  function openCreateModal() {
    resetManualForm();
    openModal("manualDevolucaoModal");
  }

  function openEditModal(button) {
    var row = parseJsonSafe(button && button.dataset.row);
    if (!row) {
      showPageAlert("Não foi possível carregar os dados da devolução.", "error");
      return;
    }
    fillManualForm(row);
    openModal("manualDevolucaoModal");
  }

  function renderClientSuggestions(items) {
    var elements = getManualElements();
    if (!elements.clientSuggestions) return;
    elements.clientSuggestions.innerHTML = "";
    if (!items || !items.length) {
      elements.clientSuggestions.classList.remove("hidden");
      var empty = document.createElement("div");
      empty.className = "px-3 py-3 text-sm text-slate-500 dark:text-slate-400";
      empty.textContent = "Nenhum cliente encontrado.";
      elements.clientSuggestions.appendChild(empty);
      return;
    }
    var fragment = document.createDocumentFragment();
    items.forEach(function (item) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "manual-client-suggestion";
      button.dataset.client = JSON.stringify(item);

      var title = document.createElement("span");
      title.className = "manual-client-suggestion__title";
      title.textContent = item.name || "-";
      button.appendChild(title);

      var detailParts = [];
      if (item.nb) detailParts.push("NB " + item.nb);
      if (item.nome_fantasia) detailParts.push(item.nome_fantasia);
      if (item.endereco) detailParts.push(item.endereco);
      var detail = document.createElement("span");
      detail.className = "manual-client-suggestion__meta";
      detail.textContent = detailParts.join(" | ");
      button.appendChild(detail);
      fragment.appendChild(button);
    });
    elements.clientSuggestions.appendChild(fragment);
    elements.clientSuggestions.classList.remove("hidden");
  }

  function scheduleClientSearch(term) {
    window.clearTimeout(state.clientSearchTimer);
    if (state.clientSearchController && typeof state.clientSearchController.abort === "function") {
      state.clientSearchController.abort();
    }
    if (!term || term.length < 2) {
      clearClientSuggestions();
      return;
    }
    var elements = getManualElements();
    state.clientSearchTimer = window.setTimeout(async function () {
      if (!elements.clientSuggestions) return;
      elements.clientSuggestions.classList.remove("hidden");
      elements.clientSuggestions.innerHTML =
        '<div class="px-3 py-3 text-sm text-slate-500 dark:text-slate-400">Buscando clientes...</div>';
      try {
        state.clientSearchController = typeof AbortController !== "undefined" ? new AbortController() : null;
        var response = await fetch(
          "/api/delivery/clients/search?q=" + encodeURIComponent(term) + "&limit=12",
          {
            credentials: "same-origin",
            signal: state.clientSearchController ? state.clientSearchController.signal : undefined,
          }
        );
        var items = await response.json();
        renderClientSuggestions(Array.isArray(items) ? items : []);
      } catch (error) {
        if (error && error.name === "AbortError") return;
        clearClientSuggestions();
      }
    }, 260);
  }

  function syncResponsabilidadeFromMotivo() {
    var elements = getManualElements();
    if (!elements.motivo || !elements.responsabilidade) return;
    var option = elements.motivo.options[elements.motivo.selectedIndex];
    if (!option) return;
    var responsabilidadeId = option.dataset.responsabilidade;
    if (responsabilidadeId) elements.responsabilidade.value = responsabilidadeId;
  }

  async function submitManualForm(event) {
    event.preventDefault();
    var elements = getManualElements();
    if (!elements.form) return;
    hidePageAlert();
    if (!elements.clientId.value) {
      showPageAlert("Selecione um cliente antes de salvar a devolução.", "error");
      return;
    }
    if (!elements.form.reportValidity()) return;

    var payload = {
      data_romaneio: elements.dataRomaneio.value,
      data_entrega: elements.dataEntrega.value,
      client_id: Number(elements.clientId.value),
      vendedor_id: Number(elements.vendedor.value),
      motorista_id: Number(elements.motorista.value),
      ajudante_id: elements.ajudante.value ? Number(elements.ajudante.value) : null,
      valor: parseMoneyValue(elements.valor.value),
      motivo_id: Number(elements.motivo.value),
      observacao: elements.observacao.value || null,
      responsabilidade_id: Number(elements.responsabilidade.value),
    };

    if (!payload.valor || payload.valor <= 0) {
      showPageAlert("Informe um valor maior que zero para a devolução.", "error");
      return;
    }

    var isEdit = !!(elements.id && elements.id.value);
    try {
      setButtonBusy(elements.submit, true, isEdit ? "Salvando..." : "Criando...");
      await fetchJson(
        isEdit ? "/api/devolucoes/" + encodeURIComponent(elements.id.value) : "/api/devolucoes",
        {
          method: isEdit ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      redirectWithFlash(
        isEdit ? "Devolução atualizada com sucesso." : "Devolução criada com sucesso.",
        "success"
      );
    } catch (error) {
      showPageAlert(error.message || "Não foi possível salvar a devolução.", "error");
    } finally {
      setButtonBusy(elements.submit, false);
    }
  }

  function clearImportPreview() {
    var previewBox = byId("devolucoes-import-preview");
    var validCount = byId("import-valid-count");
    var invalidCount = byId("import-invalid-count");
    var preCadastroText = byId("import-precadastro-text");
    var errorsBox = byId("import-errors");
    var commitButton = byId("devolucoes-import-commit-btn");
    var commitHint = byId("devolucoes-import-commit-hint");

    state.importPreview = null;
    if (previewBox) previewBox.classList.add("hidden");
    if (validCount) validCount.textContent = "0";
    if (invalidCount) invalidCount.textContent = "0";
    if (preCadastroText) {
      preCadastroText.classList.add("hidden");
      preCadastroText.textContent = "";
    }
    if (errorsBox) {
      errorsBox.innerHTML = "";
      errorsBox.scrollTop = 0;
    }
    if (commitButton) commitButton.disabled = true;
    if (commitButton) commitButton.title = "Gere a prévia para habilitar.";
    if (commitHint) {
      commitHint.textContent = "Gere a prévia para habilitar a gravação.";
      commitHint.classList.remove("text-rose-500", "dark:text-rose-300");
    }
  }

  function renderImportPreview(payload) {
    var previewBox = byId("devolucoes-import-preview");
    var validCount = byId("import-valid-count");
    var invalidCount = byId("import-invalid-count");
    var preCadastroText = byId("import-precadastro-text");
    var errorsBox = byId("import-errors");
    var commitButton = byId("devolucoes-import-commit-btn");
    var commitHint = byId("devolucoes-import-commit-hint");

    if (previewBox) previewBox.classList.remove("hidden");
    if (validCount) validCount.textContent = String(payload.valid_count || 0);
    if (invalidCount) invalidCount.textContent = String(payload.invalid_count || 0);
    var hasPreview = true;
    var hasValidRows = !!(payload.valid_rows && payload.valid_rows.length);
    if (commitButton) {
      commitButton.disabled = !hasPreview;
      commitButton.title = hasValidRows
        ? "Clique para gravar as linhas válidas."
        : "Confirmar agora separa as inválidas para revisão.";
    }
    if (commitHint) {
      if (hasValidRows) {
        commitHint.textContent =
          "Pronto para gravar " + String(payload.valid_count || 0) + " linha(s) válida(s).";
        commitHint.classList.remove("text-rose-500", "dark:text-rose-300");
      } else {
        commitHint.textContent =
          "Nenhuma linha válida na prévia. Você ainda pode confirmar para separar as inválidas e revisar depois.";
        commitHint.classList.add("text-rose-500", "dark:text-rose-300");
      }
    }

    if (preCadastroText) {
      if (payload.precadastrados && payload.precadastrados.length) {
        preCadastroText.textContent =
          "Pre-cadastros gerados: " + payload.precadastrados.join(", ") + ".";
        preCadastroText.classList.remove("hidden");
      } else {
        preCadastroText.classList.add("hidden");
        preCadastroText.textContent = "";
      }
    }

    if (!errorsBox) return;
    errorsBox.innerHTML = "";
    errorsBox.scrollTop = 0;
    if (!payload.invalid_details || !payload.invalid_details.length) {
      var okMessage = document.createElement("p");
      okMessage.className = "text-sm font-medium text-emerald-600 dark:text-emerald-300";
      okMessage.textContent = "Prévia pronta. Nenhum erro de validação encontrado.";
      errorsBox.appendChild(okMessage);
      return;
    }

    var list = document.createElement("ul");
    list.className = "space-y-2";
    errorsBox.appendChild(list);
    var details = payload.invalid_details.slice(0, 30);
    var index = 0;
    function appendChunk() {
      var fragment = document.createDocumentFragment();
      var limit = Math.min(index + 10, details.length);
      for (; index < limit; index += 1) {
        var item = details[index];
        var row = document.createElement("li");
        row.className = "rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/50";
        var title = document.createElement("p");
        title.className = "font-semibold text-slate-800 dark:text-slate-100";
        title.textContent = "Linha " + (item.row_index || "-");
        row.appendChild(title);
        var errors = document.createElement("div");
        errors.className = "mt-1 space-y-1";
        (item.errors || []).slice(0, 3).forEach(function (err) {
          var msg = document.createElement("p");
          msg.className = "text-xs text-slate-600 dark:text-slate-300";
          msg.textContent =
            (err.column ? err.column + ": " : "") +
            (err.reason || "Erro de validação.");
          errors.appendChild(msg);
        });
        row.appendChild(errors);
        fragment.appendChild(row);
      }
      list.appendChild(fragment);
      if (index < details.length) {
        window.requestAnimationFrame(appendChunk);
        return;
      }
      if (payload.invalid_count > 30) {
        var extra = document.createElement("p");
        extra.className = "mt-3 text-xs font-medium text-amber-600 dark:text-amber-300";
        extra.textContent =
          "Mostrando os 30 primeiros erros. Baixe a planilha de erros para revisar tudo.";
        errorsBox.appendChild(extra);
      }
      if (payload.batch_id) {
        var download = document.createElement("a");
        download.href = "/api/devolucoes/import/" + encodeURIComponent(payload.batch_id) + "/errors.xlsx";
        download.className =
          "mt-3 inline-flex text-xs font-semibold text-sky-600 underline underline-offset-2 hover:text-sky-500 dark:text-sky-300 dark:hover:text-sky-200";
        download.textContent = "Baixar planilha de erros";
        errorsBox.appendChild(download);
      }
    }
    window.requestAnimationFrame(appendChunk);
  }

  async function handleImportPreview() {
    hidePageAlert();
    var fileInput = byId("devolucoes-import-file");
    var previewButton = byId("devolucoes-import-preview-btn");
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      showPageAlert("Selecione um arquivo Excel para gerar a prévia.", "error");
      return;
    }
    try {
      setButtonBusy(previewButton, true, "Validando...");
      clearImportPreview();
      var formData = new FormData();
      formData.append("file", fileInput.files[0]);
      var payload = await fetchJson("/api/devolucoes/import", {
        method: "POST",
        body: formData,
      });
      payload.filename = fileInput.files[0].name;
      state.importPreview = payload;
      renderImportPreview(payload);
    } catch (error) {
      showPageAlert(error.message || "Não foi possível gerar a prévia da planilha.", "error");
    } finally {
      setButtonBusy(previewButton, false);
    }
  }

  async function handleImportCommit() {
    hidePageAlert();
    var commitButton = byId("devolucoes-import-commit-btn");
    if (!state.importPreview) {
      showPageAlert("Gere uma prévia válida antes de confirmar a importação.", "error");
      return;
    }
    try {
      setButtonBusy(commitButton, true, "Gravando...");
      var payload = await fetchJson("/api/devolucoes/import/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          batch_id: state.importPreview.batch_id,
          filename: state.importPreview.filename || "import.xlsx",
          valid_rows: state.importPreview.valid_rows,
        }),
      });
      redirectWithFlash(
        payload.message ||
          ("Importação concluída: " +
            (payload.created || 0) +
            " gravadas, " +
            (payload.skipped || 0) +
            " ignoradas."),
        "success"
      );
    } catch (error) {
      showPageAlert(error.message || "Não foi possível confirmar a importação.", "error");
    } finally {
      setButtonBusy(commitButton, false);
    }
  }

  async function deleteSingle(id) {
    await fetchJson("/api/devolucoes/" + encodeURIComponent(id), { method: "DELETE" });
    redirectWithFlash("Devolução excluída com sucesso.", "success");
  }

  async function approveSingle(id) {
    await fetchJson("/api/devolucoes/" + encodeURIComponent(id) + "/approve", { method: "POST" });
    redirectWithFlash("Devolução aprovada com sucesso.", "success");
  }

  async function bulkApprove() {
    var ids = getSelectedIds(true);
    if (!ids.length) throw new Error("Selecione ao menos uma devolução em aguardando para aprovar.");
    var payload = await fetchJson("/api/devolucoes/bulk-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids }),
    });
    var approvedCount = (payload.approved || []).length;
    var skippedCount = (payload.skipped || []).length;
    redirectWithFlash(
      "Aprovação em lote concluída: " +
        approvedCount +
        " aprovadas" +
        (skippedCount ? ", " + skippedCount + " ignoradas." : "."),
      approvedCount ? "success" : "error"
    );
  }

  async function bulkDelete() {
    var ids = getSelectedIds(false);
    if (!ids.length) throw new Error("Selecione ao menos uma devolução para excluir.");
    var payload = await fetchJson("/api/devolucoes/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids }),
    });
    var deletedCount = (payload.deleted || []).length;
    var skippedCount = (payload.skipped || []).length;
    redirectWithFlash(
      "Exclusão em lote concluída: " +
        deletedCount +
        " excluídas" +
        (skippedCount ? ", " + skippedCount + " ignoradas." : "."),
      deletedCount ? "success" : "error"
    );
  }

  async function reconnectOrphans() {
    var startDate = pageRoot.dataset.reconnectStart;
    var endDate = pageRoot.dataset.reconnectEnd;
    if (!startDate || !endDate) {
      throw new Error("Período atual não disponível para reconectar devoluções sem rota.");
    }
    var payload = await fetchJson("/api/devolucoes/reconnect-orphans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_date: startDate,
        end_date: endDate,
      }),
    });
    redirectWithFlash(
      "Reconexão concluída: " +
        (payload.reconnected || 0) +
        " vinculadas, " +
        (payload.duplicates_linked || 0) +
        " duplicatas consolidadas.",
      "success"
    );
  }

  function submitFilterForm(resetPage) {
    var form = byId("devolucoesFilterForm");
    if (!form) return;
    if (resetPage) {
      var pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
    }
    form.requestSubmit();
  }

  function queueFilterSubmit() {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = window.setTimeout(function () {
      submitFilterForm(true);
    }, SEARCH_DEBOUNCE_MS);
  }

  function queueFilterSubmitDebounced() {
    window.clearTimeout(state.filterChangeTimer);
    state.filterChangeTimer = window.setTimeout(function () {
      state.filterChangeTimer = 0;
      submitFilterForm(true);
    }, FILTER_CHANGE_DEBOUNCE_MS);
  }

  document.addEventListener("click", function (event) {
    var dismissButton = event.target.closest("[data-dismiss-alert]");
    if (dismissButton) {
      hidePageAlert();
      return;
    }

    var closeButton = event.target.closest("[data-close-modal]");
    if (closeButton) {
      closeModal(closeButton.getAttribute("data-close-modal"));
      return;
    }

    if (event.target.classList.contains("emp-modal-shell")) {
      closeModal(event.target.id);
      return;
    }

    var openButton = event.target.closest("[data-open-modal]");
    if (openButton) {
      var modalId = openButton.getAttribute("data-open-modal");
      if (modalId === "manualDevolucaoModal" && openButton.dataset.modalMode === "create") {
        openCreateModal();
      } else if (modalId === "batchOperationsModal") {
        updateBulkCount();
        openModal(modalId);
      } else {
        openModal(modalId);
      }
      return;
    }

    var clearClientButton = event.target.closest("#manual-client-clear");
    if (clearClientButton) {
      clearSelectedClient(true);
      return;
    }

    var suggestion = event.target.closest(".manual-client-suggestion");
    if (suggestion) {
      var client = parseJsonSafe(suggestion.dataset.client);
      if (client) setSelectedClient(client);
      return;
    }

    if (!event.target.closest("#manual-client-suggestions") && !event.target.closest("#manual-client-search")) {
      clearClientSuggestions();
    }

    var actionButton = event.target.closest("[data-action]");
    if (actionButton) {
      var action = actionButton.getAttribute("data-action");
      var id = actionButton.getAttribute("data-id");
      var label = actionButton.getAttribute("data-label") || "este registro";
      if (action === "edit") {
        openEditModal(actionButton);
        return;
      }
      if (action === "approve") {
        openConfirmModal({
          title: "Aprovar devolução",
          text: "Deseja aprovar a devolução de " + label + "?",
          confirmLabel: "Aprovar",
          tone: "primary",
          onConfirm: function () {
            return approveSingle(id);
          },
        });
        return;
      }
      if (action === "delete") {
        openConfirmModal({
          title: "Excluir devolução",
          text: "Deseja excluir a devolução de " + label + "? Esta ação não pode ser desfeita.",
          confirmLabel: "Excluir",
          tone: "danger",
          onConfirm: function () {
            return deleteSingle(id);
          },
        });
      }
      return;
    }

    var batchButton = event.target.closest("[data-batch-action]");
    if (batchButton) {
      var batchAction = batchButton.getAttribute("data-batch-action");
      if (batchAction === "approve") {
        openConfirmModal({
          title: "Aprovar selecionados",
          text: "Os itens em aguardando serão consolidados e sairão da fila de revisão.",
          confirmLabel: "Aprovar lote",
          tone: "primary",
          onConfirm: bulkApprove,
        });
      } else if (batchAction === "delete") {
        openConfirmModal({
          title: "Excluir selecionados",
          text: "As devoluções selecionadas serão removidas da base. Confirme apenas se já revisou a seleção.",
          confirmLabel: "Excluir lote",
          tone: "danger",
          onConfirm: bulkDelete,
        });
      } else if (batchAction === "reconnect") {
        openConfirmModal({
          title: "Reconectar devoluções sem rota",
          text: "O sistema tentará vincular as devoluções órfãs do período atual às rotas correspondentes.",
          confirmLabel: "Reconectar",
          tone: "primary",
          onConfirm: reconnectOrphans,
        });
      }
      return;
    }

    var confirmButton = event.target.closest("[data-confirm-action]");
    if (confirmButton && confirmButton.getAttribute("data-confirm-action") === "reconnect") {
      openConfirmModal({
        title: "Reconectar devoluções sem rota",
        text: "Deseja executar a reconciliação de devoluções órfãs para o período filtrado?",
        confirmLabel: "Reconectar",
        tone: "primary",
        onConfirm: reconnectOrphans,
      });
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (state.openModalId) {
        closeActiveModal();
        return;
      }
      clearClientSuggestions();
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.id === "devolucao-bulk-select-all") {
      var checked = !!event.target.checked;
      getBulkCheckboxes().forEach(function (box) {
        box.checked = checked;
      });
      updateBulkCount();
      return;
    }
    if (event.target.classList.contains("devolucao-bulk-cb")) {
      updateBulkCount();
      return;
    }
    if (event.target.id === "manual-motivo") {
      syncResponsabilidadeFromMotivo();
      return;
    }
    if (event.target.id === "devolucoes-import-file") {
      var fileName = byId("devolucoes-import-file-name");
      if (fileName) {
        fileName.textContent =
          event.target.files && event.target.files[0] ? event.target.files[0].name : "";
      }
      clearImportPreview();
      return;
    }
    var filterForm = byId("devolucoesFilterForm");
    if (filterForm && filterForm.contains(event.target)) {
      if (event.target.matches("[data-debounce-submit='true']")) {
        return;
      }
      window.clearTimeout(state.debounceTimer);
      window.clearTimeout(state.filterChangeTimer);
      queueFilterSubmitDebounced();
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-debounce-submit='true']")) {
      queueFilterSubmit();
      return;
    }
    if (event.target.id === "manual-client-search") {
      if (event.target.readOnly) return;
      scheduleClientSearch((event.target.value || "").trim());
    }
  });

  document.addEventListener("focusout", function (event) {
    if (event.target.id === "manual-valor") {
      var parsed = parseMoneyValue(event.target.value);
      if (parsed > 0) event.target.value = formatMoneyValue(parsed);
    }
  });

  var filterForm = byId("devolucoesFilterForm");
  if (filterForm) {
    filterForm.addEventListener("submit", function () {
      var pageField = filterForm.querySelector('[name="page"]');
      if (pageField && !pageField.value) pageField.value = "1";
      pageRoot.classList.add("devolucoes-page--navigating");
    });
  }

  var manualForm = byId("manual-devolucao-form");
  if (manualForm) manualForm.addEventListener("submit", submitManualForm);

  var confirmSubmit = byId("confirm-action-submit");
  if (confirmSubmit) confirmSubmit.addEventListener("click", runConfirmAction);

  var importPreviewButton = byId("devolucoes-import-preview-btn");
  if (importPreviewButton) importPreviewButton.addEventListener("click", handleImportPreview);

  var importCommitButton = byId("devolucoes-import-commit-btn");
  if (importCommitButton) importCommitButton.addEventListener("click", handleImportCommit);

  window.addEventListener("pageshow", function () {
    pageRoot.classList.remove("devolucoes-page--navigating");
  });

  updateBulkCount();
})();
