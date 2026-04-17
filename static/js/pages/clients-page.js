(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
  }

  window.openNovoClienteModal = function () {
    var modal = byId("novoClienteModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    setBodyLock(true);
  };

  window.closeNovoClienteModal = function () {
    var modal = byId("novoClienteModal");
    if (!modal) return;
    modal.classList.add("hidden");
    setBodyLock(false);
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
    if (event.key === "Escape") window.closeNovoClienteModal();
  });

  document.addEventListener("DOMContentLoaded", function () {
    bindWhatsappPhoneInputs(document);
    updateBulkCount();
  });
})();
