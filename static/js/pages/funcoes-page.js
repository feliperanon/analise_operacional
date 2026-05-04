(function () {
  "use strict";

  var root = document.querySelector('[data-page="funcoes"]');
  if (!root) return;

  var state = {
    openModalId: null,
    debounceTimer: 0,
    modalsTeleported: false,
  };

  var SEARCH_DEBOUNCE_MS = 360;

  function byId(id) {
    return document.getElementById(id);
  }

  function teleportModals() {
    ["addFuncaoModal", "editFuncaoModal", "importFuncaoModal", "confirmFuncaoModal"].forEach(function (id) {
      var el = byId(id);
      if (el && el.parentElement !== document.body) document.body.appendChild(el);
    });
    state.modalsTeleported = true;
  }

  function setBodyLock(on) {
    document.body.classList.toggle("overflow-hidden", !!on);
  }

  function openModal(id) {
    if (!state.modalsTeleported) teleportModals();
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (o) {
      if (o.id && o.id !== id) {
        o.classList.add("hidden");
        o.classList.remove("flex");
      }
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    modal.scrollTop = 0;
    state.openModalId = id;
    setBodyLock(true);
    window.requestAnimationFrame(function () {
      var t = modal.querySelector("[data-autofocus], input:not([type='hidden']), select, textarea, button");
      if (!t) return;
      try {
        t.focus({ preventScroll: true });
      } catch (_e) {
        t.focus();
      }
    });
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (state.openModalId === id) state.openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) setBodyLock(false);
  }

  function closeAny() {
    if (state.openModalId) closeModal(state.openModalId);
  }

  function parseJsonSafe(s) {
    if (!s) return null;
    try {
      return JSON.parse(s);
    } catch (_e) {
      return null;
    }
  }

  function openEdit(row) {
    var f = byId("editFuncaoForm");
    if (!f || !row) return;
    f.action = "/funcoes/" + encodeURIComponent(row.id) + "/update";
    byId("edit-nome").value = row.nome || "";
    byId("edit-salario").value = row.salario_base != null && row.salario_base !== "" ? row.salario_base : "";
    byId("edit-desc").value = row.descricao || "";
    var st = (row.status || "ATIVO").toUpperCase();
    byId("edit-status").value = st === "INATIVO" ? "INATIVO" : "ATIVO";
    openModal("editFuncaoModal");
  }

  function openDeleteConfirm(id, label) {
    var form = byId("deleteFuncaoForm");
    if (!form) return;
    form.action = "/funcoes/" + encodeURIComponent(id) + "/delete";
    var t = byId("confirm-funcao-text");
    if (t) t.textContent = 'Excluir "' + (label || "esta função") + '"? Colaboradores existentes mantêm o texto de cargo já lançado.';
    openModal("confirmFuncaoModal");
  }

  function submitFilter(resetPage) {
    var form = byId("funcoesFilterForm");
    if (!form) return;
    root.classList.add("funcoes-page--navigating");
    form.submit();
  }

  function queueFilterSubmit() {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = window.setTimeout(function () {
      submitFilter(true);
    }, SEARCH_DEBOUNCE_MS);
  }

  document.addEventListener("click", function (ev) {
    var closeBtn = ev.target.closest("[data-close-modal]");
    if (closeBtn) {
      closeModal(closeBtn.getAttribute("data-close-modal"));
      return;
    }
    if (ev.target.classList.contains("emp-modal-shell")) {
      closeModal(ev.target.id);
      return;
    }
    var openBtn = ev.target.closest("[data-open-modal]");
    if (openBtn) {
      openModal(openBtn.getAttribute("data-open-modal"));
      return;
    }
    var act = ev.target.closest("[data-action]");
    if (act) {
      var action = act.getAttribute("data-action");
      if (action === "edit") {
        openEdit(parseJsonSafe(act.getAttribute("data-row")));
        return;
      }
      if (action === "delete") {
        openDeleteConfirm(act.getAttribute("data-id"), act.getAttribute("data-label"));
      }
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeAny();
  });

  document.addEventListener("input", function (ev) {
    if (ev.target.matches("[data-debounce-submit='true']")) queueFilterSubmit();
  });

  var impFile = byId("import-funcao-file");
  var impName = byId("import-funcao-file-name");
  if (impFile && impName) {
    impFile.addEventListener("change", function () {
      impName.textContent = impFile.files && impFile.files[0] ? impFile.files[0].name : "";
    });
  }

  var filterForm = byId("funcoesFilterForm");
  if (filterForm) {
    filterForm.addEventListener("submit", function () {
      root.classList.add("funcoes-page--navigating");
    });
  }

  window.addEventListener("pageshow", function () {
    root.classList.remove("funcoes-page--navigating");
  });
})();
