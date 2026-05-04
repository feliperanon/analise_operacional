(function () {
  "use strict";

  var root = document.querySelector('[data-page="documentos-novo"]');
  if (!root) return;

  var state = {
    openModalId: null,
    searchDebounceTimer: 0,
    modalsTeleported: false,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
  }

  function teleportModalsToBody() {
    ["importCsvModal"].forEach(function (id) {
      var el = byId(id);
      if (el && el.parentElement !== document.body) document.body.appendChild(el);
    });
  }

  function ensureModalsTeleported() {
    if (state.modalsTeleported) return;
    state.modalsTeleported = true;
    teleportModalsToBody();
  }

  function openModal(id) {
    ensureModalsTeleported();
    var modal = byId(id);
    if (!modal) return;
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

  function queueFilterSubmit() {
    window.clearTimeout(state.searchDebounceTimer);
    state.searchDebounceTimer = window.setTimeout(function () {
      var form = byId("documentosNovoFilterForm");
      if (!form) return;
      var pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
      root.classList.add("documentos-page--navigating");
      form.requestSubmit();
    }, 360);
  }

  async function handleImportCsv() {
    var fileInput = byId("doc-import-file");
    var submitBtn = byId("doc-import-submit");
    var result = byId("doc-import-result");
    if (!fileInput || !submitBtn || !result) return;

    if (!fileInput.files || !fileInput.files[0]) {
      result.className =
        "rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200";
      result.textContent = "Selecione um arquivo CSV.";
      result.classList.remove("hidden");
      return;
    }

    var prevLabel = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = "Enviando...";
    try {
      var fd = new FormData();
      fd.append("file", fileInput.files[0]);
      var res = await fetch("/api/documentos/import", {
        method: "POST",
        body: fd,
        credentials: "same-origin",
      });
      var payload = await res.json();
      result.classList.remove("hidden");
      if (!res.ok || !payload.ok) {
        result.className =
          "rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200";
        result.textContent = payload.error || "Falha na importação.";
        return;
      }
      var msg = payload.message || "Importação concluída.";
      if (payload.error_count) msg += " " + String(payload.error_count) + " linha(s) com erro.";
      result.className =
        "rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-100";
      result.textContent = msg;
      if (payload.created) {
        window.setTimeout(function () {
          window.location.assign("/documentos/novo");
        }, 900);
      }
    } catch (_error) {
      result.className =
        "rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200";
      result.textContent = "Erro de rede ao importar.";
      result.classList.remove("hidden");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = prevLabel;
    }
  }

  document.addEventListener("click", function (event) {
    var openBtn = event.target.closest("[data-open-modal]");
    if (openBtn) {
      openModal(openBtn.getAttribute("data-open-modal"));
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
    if (event.target.id === "doc-import-submit") {
      handleImportCsv();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.openModalId) {
      closeModal(state.openModalId);
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-debounce-submit='true']")) {
      queueFilterSubmit();
    }
  });

  document.addEventListener("change", function (event) {
    var form = byId("documentosNovoFilterForm");
    if (!form) return;
    if (form.contains(event.target)) {
      var pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
      root.classList.add("documentos-page--navigating");
      form.requestSubmit();
    }
  });

  var createForm = byId("novo-documento-form");
  if (createForm) {
    createForm.addEventListener("submit", function () {
      var submitBtn = byId("novo-documento-submit");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Criando...";
      }
    });
  }

  window.addEventListener("pageshow", function () {
    root.classList.remove("documentos-page--navigating");
  });
})();
