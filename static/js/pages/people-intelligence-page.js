(function () {
  "use strict";

  var root = document.querySelector('[data-page="people-intelligence"]');
  if (!root) return;

  var state = { openModalId: null, debounceTimer: 0, confirmHandler: null };
  var SEARCH_DEBOUNCE_MS = 350;

  function byId(id) { return document.getElementById(id); }
  function setBodyLock(locked) { document.body.classList.toggle("overflow-hidden", !!locked); }

  function openModal(id) {
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (node) {
      if (node.id !== id) {
        node.classList.add("hidden");
        node.classList.remove("flex");
      }
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    state.openModalId = id;
    setBodyLock(true);
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (state.openModalId === id) state.openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) setBodyLock(false);
  }

  function hideAlert() {
    var alert = byId("page-alert");
    if (!alert) return;
    alert.classList.add("hidden");
    alert.innerHTML = "";
  }

  function showAlert(message, level) {
    var alert = byId("page-alert");
    if (!alert) return;
    alert.className = "sys-alert flex items-center gap-3 " + (level === "error" ? "sys-alert--danger" : "sys-alert--success");
    alert.innerHTML = '<span class="min-w-0 flex-1">' + message + '</span><button type="button" class="emp-modal-close shrink-0" data-dismiss-alert aria-label="Fechar">x</button>';
    alert.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateBulkCount() {
    var boxes = Array.prototype.slice.call(document.querySelectorAll(".pi-bulk-cb"));
    var checked = boxes.filter(function (b) { return !!b.checked; });
    var count = checked.length;
    var countEl = byId("bulk-selected-count");
    var modalCountEl = byId("batch-modal-selected-count");
    var master = byId("bulk-select-all");
    if (countEl) countEl.textContent = String(count);
    if (modalCountEl) modalCountEl.textContent = String(count);
    if (master) {
      master.checked = boxes.length > 0 && count === boxes.length;
      master.indeterminate = count > 0 && count < boxes.length;
    }
    boxes.forEach(function (box) {
      var row = box.closest(".employee-row");
      if (row) row.classList.toggle("employee-row--selected", !!box.checked);
    });
  }

  function submitFilters() {
    var form = byId("peopleFiltersForm");
    if (!form) return;
    var pageField = form.querySelector('[name="page"]');
    if (pageField) pageField.value = "1";
    form.requestSubmit();
  }

  function openConfirmModal(config) {
    byId("confirm-action-title").textContent = config.title || "Confirmar ação";
    byId("confirm-action-text").textContent = config.text || "Deseja continuar?";
    state.confirmHandler = config.onConfirm || null;
    openModal("confirmActionModal");
  }

  function validateImportPreview() {
    var input = byId("people-import-file");
    var preview = byId("people-import-preview");
    var errors = byId("people-import-errors");
    var confirmBtn = byId("people-import-confirm-btn");
    if (!input || !input.files || !input.files[0]) {
      showAlert("Selecione um arquivo para validar.", "error");
      return;
    }
    var filename = (input.files[0].name || "").toLowerCase();
    var msgs = [];
    if (!(/\.(xlsx|xls|csv)$/).test(filename)) msgs.push("Formato inválido. Use .xlsx, .xls ou .csv.");
    preview.classList.remove("hidden");
    if (msgs.length) {
      errors.innerHTML = '<p class="text-rose-600 dark:text-rose-300">' + msgs.join("<br>") + "</p>";
      confirmBtn.disabled = true;
      return;
    }
    errors.innerHTML = '<p class="text-emerald-600 dark:text-emerald-300">Arquivo válido para importação. Colunas serão conferidas no processamento.</p>';
    confirmBtn.disabled = false;
  }

  document.addEventListener("click", function (event) {
    var dismiss = event.target.closest("[data-dismiss-alert]");
    if (dismiss) { hideAlert(); return; }

    var open = event.target.closest("[data-open-modal]");
    if (open) { openModal(open.getAttribute("data-open-modal")); return; }

    var close = event.target.closest("[data-close-modal]");
    if (close) { closeModal(close.getAttribute("data-close-modal")); return; }

    if (event.target.classList.contains("emp-modal-shell")) {
      closeModal(event.target.id);
      return;
    }

    var action = event.target.closest("[data-action]");
    if (action) {
      var type = action.getAttribute("data-action");
      if (type === "edit") {
        var row = {};
        try { row = JSON.parse(action.dataset.row || "{}"); } catch (_e) { row = {}; }
        byId("action-employee").value = row.name || "";
        byId("action-sector").value = row.sector || "";
        if (row.status_key) byId("action-priority").value = row.status_key;
        openModal("createActionModal");
      } else if (type === "details") {
        window.location.href = "/employees/" + encodeURIComponent(action.dataset.id || "");
      }
      return;
    }

    var batch = event.target.closest("[data-batch-action]");
    if (batch) {
      var mode = batch.getAttribute("data-batch-action");
      if (mode === "clear-selection") {
        document.querySelectorAll(".pi-bulk-cb:checked").forEach(function (box) { box.checked = false; });
        updateBulkCount();
        closeModal("batchOperationsModal");
        return;
      }
      openConfirmModal({
        title: "Confirmar operação em lote",
        text: "Deseja aplicar esta ação aos itens selecionados?",
        onConfirm: function () {
          closeModal("confirmActionModal");
          closeModal("batchOperationsModal");
          showAlert("Ação em lote executada com sucesso.", "success");
        },
      });
      return;
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.id === "bulk-select-all") {
      var checked = !!event.target.checked;
      document.querySelectorAll(".pi-bulk-cb").forEach(function (box) { box.checked = checked; });
      updateBulkCount();
      return;
    }
    if (event.target.classList.contains("pi-bulk-cb")) {
      updateBulkCount();
      return;
    }
    if (event.target.id === "people-import-file") {
      var nameEl = byId("people-import-file-name");
      if (nameEl) nameEl.textContent = event.target.files && event.target.files[0] ? event.target.files[0].name : "";
      byId("people-import-preview").classList.add("hidden");
      byId("people-import-confirm-btn").disabled = true;
      return;
    }
    var form = byId("peopleFiltersForm");
    if (form && form.contains(event.target) && !event.target.matches("[data-debounce-submit='true']")) {
      submitFilters();
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-debounce-submit='true']")) {
      window.clearTimeout(state.debounceTimer);
      state.debounceTimer = window.setTimeout(submitFilters, SEARCH_DEBOUNCE_MS);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.openModalId) closeModal(state.openModalId);
  });

  var importValidateBtn = byId("people-import-validate-btn");
  if (importValidateBtn) importValidateBtn.addEventListener("click", validateImportPreview);

  var importConfirmBtn = byId("people-import-confirm-btn");
  if (importConfirmBtn) {
    importConfirmBtn.addEventListener("click", function () {
      closeModal("importModal");
      showAlert("Importação confirmada. Processamento iniciado.", "success");
    });
  }

  var createForm = byId("create-action-form");
  if (createForm) {
    createForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!createForm.reportValidity()) return;
      closeModal("createActionModal");
      showAlert("Plano de ação salvo com sucesso.", "success");
    });
  }

  var confirmSubmit = byId("confirm-action-submit");
  if (confirmSubmit) {
    confirmSubmit.addEventListener("click", function () {
      if (typeof state.confirmHandler === "function") state.confirmHandler();
      state.confirmHandler = null;
    });
  }

  updateBulkCount();
})();
