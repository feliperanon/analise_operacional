(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  var novoClienteTrigger = null;

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
    document.documentElement.classList.toggle("clients-modal-open", !!locked);
  }

  function isNovoClienteModalOpen() {
    var modal = byId("novoClienteModal");
    return modal && !modal.classList.contains("hidden");
  }

  function blurIfInside(modal) {
    var active = document.activeElement;
    if (active && modal && modal.contains(active) && typeof active.blur === "function") {
      active.blur();
    }
  }

  window.openNovoClienteModal = function () {
    var modal = byId("novoClienteModal");
    if (!modal) return;
    var trigger = document.activeElement;
    if (trigger && trigger.id !== "novoClienteModal") {
      novoClienteTrigger = trigger;
    }
    modal.classList.remove("hidden");
    modal.removeAttribute("aria-hidden");
    setBodyLock(true);
    var nameInput = byId("new-client-name");
    var focusName = function () {
      if (nameInput && typeof nameInput.focus === "function") {
        nameInput.focus({ preventScroll: true });
      }
    };
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(focusName);
    } else {
      focusName();
    }
  };

  window.closeNovoClienteModal = function () {
    var modal = byId("novoClienteModal");
    if (!modal || modal.classList.contains("hidden")) return;
    blurIfInside(modal);
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    setBodyLock(false);
    var trigger = novoClienteTrigger || byId("btn-novo-cliente");
    if (trigger && typeof trigger.focus === "function") {
      trigger.focus({ preventScroll: true });
    }
    novoClienteTrigger = null;
  };

  function normalizeWhatsappPhoneDigits(value) {
    var raw = String(value || "").trim();
    var digits = raw.replace(/\D/g, "");
    digits = digits.replace(/^0+/, "");
    if (raw.indexOf("+55") === 0 && digits.indexOf("55") === 0) digits = digits.slice(2);
    if (digits.indexOf("55") === 0 && digits.length > 11) digits = digits.slice(2);
    if (digits.length > 11) digits = digits.slice(-11);
    return digits;
  }

  function formatWhatsappPhoneValue(value) {
    var digits = normalizeWhatsappPhoneDigits(value);
    return digits ? "+55" + digits : "";
  }

  var ENTREGA_LABELS = ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA"];

  function visitaWeekdayIndex(visita) {
    if (!visita || !String(visita).trim()) return null;
    var n = String(visita)
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
    var aliases = {
      seg: 0,
      segunda: 0,
      "segunda-feira": 0,
      ter: 1,
      terca: 1,
      "terca-feira": 1,
      qua: 2,
      quarta: 2,
      "quarta-feira": 2,
      qui: 3,
      quinta: 3,
      "quinta-feira": 3,
      sex: 4,
      sexta: 4,
      "sexta-feira": 4,
      sab: 5,
      sabado: 5,
      dom: 6,
      domingo: 6,
    };
    if (Object.prototype.hasOwnProperty.call(aliases, n)) return aliases[n];
    var first = n.split("-")[0].split(" ")[0];
    if (Object.prototype.hasOwnProperty.call(aliases, first)) return aliases[first];
    return null;
  }

  function computeEntregaFromVisita(visita) {
    var idx = visitaWeekdayIndex(visita);
    if (idx === null) return "";
    if (idx >= 4) return ENTREGA_LABELS[0];
    return ENTREGA_LABELS[idx + 1];
  }

  function bindVisitaEntrega(root) {
    (root || document).querySelectorAll('[data-visita-entrega="true"]').forEach(function (visitaInput) {
      if (visitaInput.dataset.entregaBound === "1") return;
      visitaInput.dataset.entregaBound = "1";
      var entregaInput =
        byId("new-client-entrega") ||
        (visitaInput.id === "edit-client-visita" ? byId("edit-client-entrega") : null);
      if (!entregaInput) return;
      var sync = function () {
        entregaInput.value = computeEntregaFromVisita(visitaInput.value);
      };
      visitaInput.addEventListener("input", sync);
      visitaInput.addEventListener("change", sync);
      sync();
    });
  }

  function bindWhatsappPhoneInputs(root) {
    (root || document).querySelectorAll('[data-whatsapp-phone="true"]').forEach(function (input) {
      if (input.dataset.phoneBound === "1") return;
      input.dataset.phoneBound = "1";
      var sync = function () {
        if (!input.value) return;
        input.value = formatWhatsappPhoneValue(input.value);
      };
      input.addEventListener("input", sync);
      input.addEventListener("blur", sync);
      if (input.value) sync();
    });
  }

  function syncRowHighlight(cb) {
    var row = cb && cb.closest("tr");
    if (row) row.classList.toggle("clients-data-table__row--selected", !!cb.checked);
  }

  function updateBulkCount() {
    var boxes = Array.from(document.querySelectorAll(".client-bulk-cb"));
    var checked = boxes.filter(function (cb) {
      return cb.checked;
    }).length;
    var total = boxes.length;
    var countEl = byId("bulk-selected-count");
    var master = byId("bulk-select-all");
    if (countEl) countEl.textContent = String(checked);
    if (master) {
      master.checked = total > 0 && checked === total;
      master.indeterminate = checked > 0 && checked < total;
    }
  }

  var bulkSelectAll = byId("bulk-select-all");
  if (bulkSelectAll) {
    bulkSelectAll.addEventListener("change", function () {
      document.querySelectorAll(".client-bulk-cb").forEach(function (cb) {
        cb.checked = !!bulkSelectAll.checked;
        syncRowHighlight(cb);
      });
      updateBulkCount();
    });
  }

  document.querySelectorAll(".client-bulk-cb").forEach(function (cb) {
    cb.addEventListener("change", function () {
      syncRowHighlight(this);
      updateBulkCount();
    });
  });

  var bulkForm = byId("bulk-group-form");
  if (bulkForm) {
    bulkForm.addEventListener("submit", function (event) {
      var count = document.querySelectorAll(".client-bulk-cb:checked").length;
      var groupField = this.querySelector('[name="group_id"]');
      var newGroupField = this.querySelector('[name="new_group_name"]');
      var groupId = groupField ? groupField.value : "";
      var newGroup = ((newGroupField ? newGroupField.value : "") || "").trim();
      if (!count) {
        event.preventDefault();
        alert("Selecione ao menos um cliente na tabela.");
        return;
      }
      if (!groupId && !newGroup) {
        event.preventDefault();
        alert("Escolha um grupo existente ou digite o nome de um novo grupo.");
      }
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !isNovoClienteModalOpen()) return;
    event.preventDefault();
    window.closeNovoClienteModal();
  });

  document.addEventListener("DOMContentLoaded", function () {
    bindWhatsappPhoneInputs(document);
    bindVisitaEntrega(document);
    updateBulkCount();
    var modal = byId("novoClienteModal");
    if (modal) {
      bindWhatsappPhoneInputs(modal);
      bindVisitaEntrega(modal);
    }
  });
})();
