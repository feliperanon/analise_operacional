/**
 * Chamados de equipamento — UX alinhada à página de colaboradores.
 * Busca com debounce (submete o filtro GET), seleção em lote, modais leves.
 */
(function () {
  'use strict';

  var _searchDebounceTimer = null;

  function debounce(fn, ms) {
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(_searchDebounceTimer);
      _searchDebounceTimer = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  function getForm() {
    return document.getElementById('ticketsFilterForm');
  }

  function submitFilterForm() {
    var form = getForm();
    if (!form) return;
    var applyBtn = document.getElementById('ticketsApplyBtn');
    if (applyBtn) {
      applyBtn.disabled = true;
      applyBtn.textContent = 'Carregando...';
    }
    var pageInput = form.querySelector('input[name="page"]');
    if (pageInput) pageInput.value = '1';
    form.submit();
  }

  var debouncedSubmit = debounce(submitFilterForm, 320);

  function initSearchDebounce() {
    var input = document.getElementById('ticketsSearchInput');
    if (!input) return;
    input.addEventListener('input', function () {
      debouncedSubmit();
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        clearTimeout(_searchDebounceTimer);
        submitFilterForm();
      }
    });

    var form = getForm();
    if (form) {
      ['status', 'severity', 'shift', 'days', 'equipment', 'sort'].forEach(function (name) {
        var el = form.querySelector('[name="' + name + '"]');
        if (el && el.tagName === 'SELECT') {
          el.addEventListener('change', submitFilterForm, { passive: true });
        }
      });
    }
  }

  function setModalOpen(id, open) {
    var el = document.getElementById(id);
    if (!el) return;
    if (open) el.classList.remove('hidden');
    else el.classList.add('hidden');
  }

  window.eqTicketsOpenModal = function (id) {
    setModalOpen(id, true);
  };
  window.eqTicketsCloseModal = function (id) {
    setModalOpen(id, false);
  };

  function parseEditPayload(payload) {
    if (!payload) return {};
    if (typeof payload === 'object') return payload;
    if (typeof payload !== 'string') return {};

    var raw = payload.trim();
    if (!raw) return {};

    try {
      return JSON.parse(raw);
    } catch (_) {
      // Fallback para payload legado vindo como repr Python ({'k': 'v'}).
      try {
        var normalized = raw
          .replace(/([{,]\s*)'([^']+)'\s*:/g, '$1"$2":')
          .replace(/:\s*'([^']*)'/g, function (m, value) {
            return ': "' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
          });
        return JSON.parse(normalized);
      } catch (e2) {
        console.error('eqTickets parseEditPayload', e2, raw);
        return {};
      }
    }
  }

  window.eqTicketsOpenEditModal = function (payload) {
    var d = parseEditPayload(payload);
    var fid = document.getElementById('editTicketId');
    var fd = document.getElementById('editDescription');
    var fs = document.getElementById('editSeverity');
    var fsh = document.getElementById('editShift');
    if (fid) fid.value = d.id || '';
    if (fd) fd.value = d.description || '';
    if (fs) fs.value = d.severity === 'high' ? 'high' : 'low';
    if (fsh) fsh.value = d.shift || '';
    setModalOpen('editTicketModal', true);
  };

  function selectedTicketIds() {
    var boxes = document.querySelectorAll('.ticket-row-select:checked');
    var ids = [];
    for (var i = 0; i < boxes.length; i++) {
      var v = boxes[i].value;
      if (v) ids.push(v);
    }
    return ids;
  }

  window.eqTicketsUpdateBulkBar = function () {
    var ids = selectedTicketIds();
    var bar = document.getElementById('ticketsBulkBar');
    var countEl = document.getElementById('ticketsBulkCount');
    var hidden = document.getElementById('bulkTicketIds');
    if (countEl) countEl.textContent = String(ids.length);
    if (hidden) hidden.value = ids.join(',');
    if (bar) {
      if (ids.length > 0) bar.classList.remove('hidden');
      else bar.classList.add('hidden');
    }
  };

  window.eqTicketsToggleAll = function (master) {
    var checked = master && master.checked;
    document.querySelectorAll('.ticket-row-select').forEach(function (cb) {
      cb.checked = checked;
    });
    window.eqTicketsUpdateBulkBar();
  };

  window.eqTicketsOpenBulkCloseModal = function () {
    var ids = selectedTicketIds();
    if (!ids.length) return;
    var hidden = document.getElementById('bulkTicketIds');
    if (hidden) hidden.value = ids.join(',');
    setModalOpen('bulkCloseTicketModal', true);
  };

  document.addEventListener('DOMContentLoaded', function () {
    initSearchDebounce();
    document.querySelectorAll('.ticket-row-select').forEach(function (cb) {
      cb.addEventListener('change', window.eqTicketsUpdateBulkBar);
    });
    var master = document.getElementById('ticketSelectAll');
    if (master) {
      master.addEventListener('change', function () {
        window.eqTicketsToggleAll(master);
      });
    }
    window.eqTicketsUpdateBulkBar();

    document.querySelectorAll('[data-eq-modal-close]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-eq-modal-close');
        if (id) setModalOpen(id, false);
      });
    });

    document.querySelectorAll('.emp-modal-shell').forEach(function (shell) {
      shell.addEventListener('click', function (e) {
        if (e.target === shell) shell.classList.add('hidden');
      });
    });
  });
})();
