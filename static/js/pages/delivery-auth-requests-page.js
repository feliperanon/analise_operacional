/**
 * Admin: autorizações de entrega fora do raio (/admin/delivery-auth-requests).
 * Lista via API, filtros com debounce, paginação client-side, ações em lote com delegação de eventos.
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 280;
  var PAGE_SIZE = 25;
  var POLL_MS = 60000;

  var state = {
    rows: [],
    filtered: [],
    page: 1,
    quick: 'all',
    search: '',
    searchDebounced: '',
    selected: new Set(),
    denyIds: [],
    bulkApproveIds: [],
    loading: false,
    initialLoadDone: false,
    pollTimer: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    if (s == null || s === '') return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }

  function fmtDist(m) {
    if (m == null || m === '') return '—';
    var n = Number(m);
    if (!isFinite(n)) return '—';
    if (n >= 1000) return (n / 1000).toFixed(1).replace('.', ',') + ' km';
    return Math.round(n) + ' m';
  }

  function fmtDt(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  }

  function dateKeySaoPaulo(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
  }

  function isTodaySaoPaulo(iso) {
    var today = dateKeySaoPaulo(new Date().toISOString());
    return dateKeySaoPaulo(iso) === today;
  }

  function readInitialStats() {
    var el = $('dac-initial-stats');
    if (!el || !el.textContent) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  function applyKpis(stats) {
    if (!stats) return;
    var map = [
      ['dac-kpi-pending', stats.pending_count],
      ['dac-kpi-critical', stats.critical_pending_count],
      ['dac-kpi-approved-today', stats.approved_today],
      ['dac-kpi-denied-today', stats.denied_today],
    ];
    for (var i = 0; i < map.length; i++) {
      var n = $(map[i][0]);
      if (n) n.textContent = String(map[i][1] != null ? map[i][1] : '0');
    }
    var chip = $('dac-hero-pending-chip');
    if (chip) {
      var p = stats.pending_count != null ? stats.pending_count : 0;
      chip.textContent = p + ' pendente(s)';
    }
  }

  function showAlert(type, message) {
    var slot = $('dac-alert-slot');
    if (!slot || !message) return;
    var cls = type === 'success' ? 'sys-alert--success' : type === 'danger' ? 'sys-alert--danger' : 'sys-alert--info';
    var icon =
      type === 'success'
        ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>'
        : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>';
    var html =
      '<div class="sys-alert ' +
      cls +
      ' flex items-start gap-3" role="alert">' +
      '<svg class="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
      icon +
      '</svg>' +
      '<span class="min-w-0 flex-1">' +
      esc(message) +
      '</span>' +
      '<button type="button" class="dac-alert-dismiss shrink-0 rounded-md p-1.5 text-slate-500 transition hover:bg-black/5 dark:text-slate-400 dark:hover:bg-white/10" aria-label="Fechar">' +
      '<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' +
      '</button></div>';
    slot.innerHTML = html;
    var btn = slot.querySelector('.dac-alert-dismiss');
    if (btn) {
      btn.addEventListener('click', function () {
        slot.innerHTML = '';
      });
    }
  }

  function setLoading(on) {
    state.loading = on;
    var ld = $('dac-loading');
    var tw = $('dac-table-wrap');
    if (ld) ld.classList.toggle('hidden', !on);
    if (tw && on) tw.classList.add('hidden');
  }

  function showError(msg) {
    var wrap = $('dac-error-wrap');
    var ld = $('dac-loading');
    var tw = $('dac-table-wrap');
    var em = $('dac-empty-wrap');
    if (ld) ld.classList.add('hidden');
    if (tw) tw.classList.add('hidden');
    if (em) em.classList.add('hidden');
    if (wrap) {
      wrap.classList.remove('hidden');
      wrap.innerHTML =
        '<div class="sys-alert sys-alert--danger flex items-center gap-3" role="alert">' +
        '<svg class="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>' +
        '<span>' +
        esc(msg) +
        '</span></div>';
    }
  }

  function hideError() {
    var wrap = $('dac-error-wrap');
    if (wrap) {
      wrap.classList.add('hidden');
      wrap.innerHTML = '';
    }
  }

  function badgeHtml(st) {
    var s = (st || '').toLowerCase();
    if (s === 'pending') {
      return '<span class="sys-badge sys-badge--alert">Pendente</span>';
    }
    if (s === 'approved') {
      return '<span class="sys-badge sys-badge--ok">Aprovado</span>';
    }
    if (s === 'denied') {
      return '<span class="sys-badge sys-badge--critical">Negado</span>';
    }
    return '<span class="employees-pill employees-pill--status employees-pill--pending">' + esc(st) + '</span>';
  }

  function mergeRows(data) {
    var pending = data.pending || [];
    var recent = data.recent || [];
    var out = pending.slice().concat(recent.slice());
    return out;
  }

  function rowMatchesQuick(row) {
    var st = (row.status || '').toLowerCase();
    var q = state.quick;
    if (q === 'all') return true;
    if (q === 'pending') return st === 'pending';
    if (q === 'approved') return st === 'approved';
    if (q === 'denied') return st === 'denied';
    if (q === 'critical') {
      if (st !== 'pending') return false;
      var d = row.distancia_metros;
      return d != null && Number(d) >= 500;
    }
    if (q === 'today') {
      if (st === 'pending') return row.requested_at && isTodaySaoPaulo(row.requested_at);
      return row.resolved_at && isTodaySaoPaulo(row.resolved_at);
    }
    return true;
  }

  function rowMatchesSearch(row) {
    var t = (state.searchDebounced || '').trim().toLowerCase();
    if (!t) return true;
    var parts = [
      String(row.id || ''),
      row.driver_name || '',
      row.client_name || '',
      row.motivo || '',
      String(row.route_id || ''),
    ];
    var blob = parts.join(' ').toLowerCase();
    return blob.indexOf(t) !== -1;
  }

  function applyFilters() {
    state.filtered = state.rows.filter(function (r) {
      return rowMatchesQuick(r) && rowMatchesSearch(r);
    });
    var maxPage = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    if (state.page > maxPage) state.page = maxPage;
    if (state.page < 1) state.page = 1;
  }

  function currentPageSlice() {
    var start = (state.page - 1) * PAGE_SIZE;
    return state.filtered.slice(start, start + PAGE_SIZE);
  }

  function updateBulkBar() {
    var bar = $('dac-bulk-bar');
    var cnt = $('dac-bulk-count');
    if (!bar || !cnt) return;
    var n = 0;
    state.selected.forEach(function (id) {
      var row = state.rows.find(function (r) {
        return String(r.id) === String(id);
      });
      if (row && (row.status || '').toLowerCase() === 'pending') n++;
    });
    cnt.textContent = String(n);
    bar.classList.toggle('hidden', n === 0);
  }

  function renderTable() {
    var body = $('dacTableBody');
    var tw = $('dac-table-wrap');
    var ld = $('dac-loading');
    var em = $('dac-empty-wrap');
    var rc = $('dac-result-count');
    var pag = $('dac-pagination');
    if (!body) return;

    hideError();
    if (ld) ld.classList.add('hidden');

    if (state.filtered.length === 0) {
      if (tw) tw.classList.add('hidden');
      if (pag) pag.classList.add('hidden');
      if (em) {
        em.classList.remove('hidden');
        if (state.rows.length === 0) {
          em.innerHTML =
            '<div class="sys-empty-state text-center">' +
            '<p class="employees-text-strong text-base">Nenhuma solicitação cadastrada</p>' +
            '<p class="mt-2 text-sm employees-text-muted">Quando um motorista pedir liberação no app, ela aparece aqui.</p></div>';
        } else {
          em.innerHTML =
            '<div class="sys-empty-state text-center">' +
            '<p class="employees-text-strong text-base">Nenhum resultado</p>' +
            '<p class="mt-2 text-sm employees-text-muted">Ajuste a busca ou os filtros rápidos.</p></div>';
        }
      }
      if (rc) rc.textContent = '0 itens';
      body.innerHTML = '';
      return;
    }

    if (em) em.classList.add('hidden');
    if (tw) tw.classList.remove('hidden');

    var slice = currentPageSlice();
    if (rc) {
      rc.textContent =
        state.filtered.length +
        (state.filtered.length === 1 ? ' item' : ' itens') +
        (state.filtered.length > PAGE_SIZE ? ' · página ' + state.page + ' de ' + Math.ceil(state.filtered.length / PAGE_SIZE) : '');
    }

    var html = '';
    for (var i = 0; i < slice.length; i++) {
      var row = slice[i];
      var st = (row.status || '').toLowerCase();
      var isPen = st === 'pending';
      var checked = state.selected.has(String(row.id));
      var cb =
        '<input type="checkbox" class="dac-row-check dac-checkbox h-4 w-4 rounded border-slate-300" data-id="' +
        row.id +
        '" ' +
        (checked ? 'checked' : '') +
        (isPen ? '' : ' disabled') +
        ' aria-label="Selecionar solicitação ' +
        row.id +
        '">';
      var actions = '';
      if (isPen) {
        actions =
          '<div class="employee-actions employees-action-strip flex flex-wrap items-center gap-1">' +
          '<button type="button" class="sys-btn sys-btn--success px-2 py-1.5 text-xs dac-action-approve" data-id="' +
          row.id +
          '">Aprovar</button>' +
          '<button type="button" class="sys-btn sys-btn--ghost-danger px-2 py-1.5 text-xs dac-action-deny" data-id="' +
          row.id +
          '">Negar</button>' +
          '</div>';
      } else {
        actions =
          '<button type="button" class="sys-btn sys-btn--secondary px-2 py-1.5 text-xs dac-action-detail" data-row=\'' +
          encodeURIComponent(JSON.stringify(row)) +
          "'>Detalhes</button>";
      }
      html +=
        '<tr class="employees-data-table__row transition-colors" data-id="' +
        row.id +
        '">' +
        '<td class="employees-data-table__td dac-auth-td-check px-2 py-2 pl-4 align-middle" data-label="Selecionar">' +
        cb +
        '</td>' +
        '<td class="employees-data-table__cell px-2 py-2 align-middle tabular-nums employees-text-body" data-label="ID">#' +
        row.id +
        '</td>' +
        '<td class="employees-data-table__cell px-2 py-2 align-middle employees-text-body" data-label="Motorista"><span class="employees-text-strong">' +
        esc(row.driver_name) +
        '</span></td>' +
        '<td class="employees-data-table__cell px-2 py-2 align-middle employees-text-body" data-label="Cliente">' +
        esc(row.client_name || '—') +
        '</td>' +
        '<td class="employees-data-table__cell px-2 py-2 align-middle whitespace-nowrap" data-label="Distância">' +
        fmtDist(row.distancia_metros) +
        '</td>' +
        '<td class="employees-data-table__cell employees-data-table__cell--muted px-2 py-2 align-middle whitespace-nowrap" data-label="Solicitado">' +
        fmtDt(row.requested_at) +
        '</td>' +
        '<td class="employees-data-table__td--col-status px-2 py-2 align-middle" data-label="Status">' +
        badgeHtml(row.status) +
        '</td>' +
        '<td class="employees-data-table__cell px-2 py-2 align-middle tabular-nums employees-text-muted" data-label="Rota">#' +
        (row.route_id != null ? row.route_id : '—') +
        '</td>' +
        '<td class="employee-actions-cell employees-data-table__td--col-actions px-2 py-2 pr-4 align-middle" data-label="Ações">' +
        actions +
        '</td>' +
        '</tr>';
    }
    body.innerHTML = html;

    if (pag) {
      var pages = Math.ceil(state.filtered.length / PAGE_SIZE);
      pag.classList.toggle('hidden', pages <= 1);
      var pi = $('dac-page-info');
      if (pi) {
        pi.textContent = 'Página ' + state.page + ' de ' + pages;
      }
      var prev = $('dac-page-prev');
      var next = $('dac-page-next');
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= pages;
    }

    syncSelectPageCheckbox();
    updateBulkBar();
  }

  function syncSelectPageCheckbox() {
    var master = $('dac-select-page');
    if (!master) return;
    var slice = currentPageSlice();
    var pendingOnPage = slice.filter(function (r) {
      return (r.status || '').toLowerCase() === 'pending';
    });
    if (pendingOnPage.length === 0) {
      master.checked = false;
      master.indeterminate = false;
      master.disabled = true;
      return;
    }
    master.disabled = false;
    var allSel = pendingOnPage.every(function (r) {
      return state.selected.has(String(r.id));
    });
    var someSel = pendingOnPage.some(function (r) {
      return state.selected.has(String(r.id));
    });
    master.checked = allSel;
    master.indeterminate = someSel && !allSel;
  }

  async function fetchList() {
    var isInitial = !state.initialLoadDone;
    if (isInitial) setLoading(true);
    try {
      var r = await fetch('/api/admin/delivery-auth-requests', { credentials: 'same-origin' });
      var data = await r.json().catch(function () {
        return {};
      });
      if (!r.ok) {
        showError(data.error || 'Não foi possível carregar as solicitações.');
        return;
      }
      state.initialLoadDone = true;
      applyKpis(data.stats);
      state.rows = mergeRows(data);
      state.selected.forEach(function (id) {
        var row = state.rows.find(function (x) {
          return String(x.id) === String(id);
        });
        if (!row || (row.status || '').toLowerCase() !== 'pending') state.selected.delete(id);
      });
      applyFilters();
      renderTable();
    } catch (e) {
      showError('Erro de rede. Verifique a conexão e tente de novo.');
    } finally {
      if (isInitial) setLoading(false);
    }
  }

  async function patchResolve(id, status, obs) {
    var r = await fetch('/api/admin/delivery-auth-requests/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ status: status, obs: obs || null }),
    });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok) throw new Error(j.error || 'Erro ao salvar');
    return j;
  }

  function openModal(id) {
    var m = $(id);
    if (m) m.classList.remove('hidden');
  }

  function closeModal(id) {
    var m = $(id);
    if (m) m.classList.add('hidden');
    if (id === 'dac-approve-bulk-modal') state.bulkApproveIds = [];
  }

  function closeAllModals() {
    ['dac-detail-modal', 'dac-deny-modal', 'dac-approve-bulk-modal'].forEach(closeModal);
  }

  function openDetail(row) {
    var sub = $('dac-detail-sub');
    var body = $('dac-detail-body');
    if (sub) sub.textContent = '#' + row.id + ' · ' + (row.driver_name || '');
    if (body) {
      var dl =
        '<div class="grid grid-cols-1 gap-2">' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Cliente</dt><dd>' +
        esc(row.client_name || '—') +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Distância</dt><dd>' +
        fmtDist(row.distancia_metros) +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Motivo</dt><dd>' +
        esc(row.motivo || '—') +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Solicitado</dt><dd>' +
        fmtDt(row.requested_at) +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Resolvido</dt><dd>' +
        fmtDt(row.resolved_at) +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Observação</dt><dd>' +
        esc(row.obs || '—') +
        '</dd></div>' +
        '<div><dt class="text-xs font-semibold uppercase tracking-wide employees-text-muted">Rota</dt><dd>#' +
        (row.route_id != null ? row.route_id : '—') +
        '</dd></div></div>';
      body.innerHTML = dl;
    }
    openModal('dac-detail-modal');
  }

  function openDenyModal(ids) {
    state.denyIds = ids.slice();
    var title = $('dac-deny-title');
    var lead = $('dac-deny-lead');
    var err = $('dac-deny-error');
    var ta = $('dac-deny-obs');
    if (err) {
      err.classList.add('hidden');
      err.textContent = '';
    }
    if (ta) ta.value = '';
    if (ids.length === 1) {
      if (title) title.textContent = 'Negar solicitação';
      if (lead) lead.textContent = 'Solicitação #' + ids[0] + '.';
    } else {
      if (title) title.textContent = 'Negar em lote';
      if (lead) lead.textContent = ids.length + ' solicitações serão negadas.';
    }
    openModal('dac-deny-modal');
  }

  function openApproveBulkModal(n) {
    var lead = $('dac-approve-bulk-lead');
    if (lead) lead.textContent = 'Confirma aprovar ' + n + ' solicitação(ões) pendente(s)? Cada uma libera uma tentativa de iniciar no app.';
    openModal('dac-approve-bulk-modal');
  }

  var debounceTimer = null;
  function scheduleDebouncedSearch() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      state.searchDebounced = state.search;
      state.page = 1;
      applyFilters();
      renderTable();
    }, DEBOUNCE_MS);
  }

  function setQuickFilter(key) {
    state.quick = key;
    state.page = 1;
    document.querySelectorAll('[data-dac-quick]').forEach(function (btn) {
      var k = btn.getAttribute('data-dac-quick');
      var on = k === key;
      btn.classList.toggle('filter-btn--active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    applyFilters();
    renderTable();
  }

  function bind() {
    applyKpis(readInitialStats());

    $('dac-btn-refresh') &&
      $('dac-btn-refresh').addEventListener('click', function () {
        fetchList();
      });

    var search = $('dac-search');
    if (search) {
      search.addEventListener('input', function () {
        state.search = search.value;
        scheduleDebouncedSearch();
      });
    }

    document.querySelectorAll('[data-dac-quick]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setQuickFilter(btn.getAttribute('data-dac-quick') || 'all');
      });
    });

    $('dac-clear-filters') &&
      $('dac-clear-filters').addEventListener('click', function () {
        if (search) search.value = '';
        state.search = '';
        state.searchDebounced = '';
        setQuickFilter('all');
      });

    $('dac-page-prev') &&
      $('dac-page-prev').addEventListener('click', function () {
        if (state.page > 1) {
          state.page--;
          renderTable();
        }
      });
    $('dac-page-next') &&
      $('dac-page-next').addEventListener('click', function () {
        var pages = Math.ceil(state.filtered.length / PAGE_SIZE);
        if (state.page < pages) {
          state.page++;
          renderTable();
        }
      });

    var master = $('dac-select-page');
    if (master) {
      master.addEventListener('change', function () {
        var slice = currentPageSlice();
        var pendingOnPage = slice.filter(function (r) {
          return (r.status || '').toLowerCase() === 'pending';
        });
        if (master.checked) {
          pendingOnPage.forEach(function (r) {
            state.selected.add(String(r.id));
          });
        } else {
          pendingOnPage.forEach(function (r) {
            state.selected.delete(String(r.id));
          });
        }
        renderTable();
      });
    }

    var tbody = $('dacTableBody');
    if (tbody) {
      tbody.addEventListener('change', function (e) {
        var t = e.target;
        if (!t || !t.classList || !t.classList.contains('dac-row-check')) return;
        var id = t.getAttribute('data-id');
        if (t.checked) state.selected.add(String(id));
        else state.selected.delete(String(id));
        syncSelectPageCheckbox();
        updateBulkBar();
      });
      tbody.addEventListener('click', function (e) {
        var btn = e.target.closest('.dac-action-approve');
        if (btn) {
          var id = btn.getAttribute('data-id');
          btn.disabled = true;
          patchResolve(id, 'approved', null)
            .then(function () {
              showAlert('success', 'Solicitação #' + id + ' aprovada.');
              return fetchList();
            })
            .catch(function (err) {
              showAlert('danger', err.message || 'Falha ao aprovar.');
            })
            .finally(function () {
              btn.disabled = false;
            });
          return;
        }
        btn = e.target.closest('.dac-action-deny');
        if (btn) {
          openDenyModal([btn.getAttribute('data-id')]);
          return;
        }
        btn = e.target.closest('.dac-action-detail');
        if (btn) {
          try {
            var raw = decodeURIComponent(btn.getAttribute('data-row') || '{}');
            openDetail(JSON.parse(raw));
          } catch (err) {}
        }
      });
    }

    document.querySelectorAll('[data-close-modal]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        closeModal(btn.getAttribute('data-close-modal'));
      });
    });

    ['dac-detail-modal', 'dac-deny-modal', 'dac-approve-bulk-modal'].forEach(function (mid) {
      var el = $(mid);
      if (!el) return;
      el.addEventListener('click', function (e) {
        if (e.target === el) closeModal(mid);
      });
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeAllModals();
    });

    $('dac-bulk-clear') &&
      $('dac-bulk-clear').addEventListener('click', function () {
        state.selected.clear();
        renderTable();
      });

    $('dac-bulk-approve') &&
      $('dac-bulk-approve').addEventListener('click', function () {
        var ids = [];
        state.selected.forEach(function (id) {
          var row = state.rows.find(function (r) {
            return String(r.id) === String(id);
          });
          if (row && (row.status || '').toLowerCase() === 'pending') ids.push(id);
        });
        if (!ids.length) return;
        state.bulkApproveIds = ids;
        openApproveBulkModal(ids.length);
      });

    $('dac-approve-bulk-confirm') &&
      $('dac-approve-bulk-confirm').addEventListener('click', async function () {
        var ids = (state.bulkApproveIds || []).slice();
        closeModal('dac-approve-bulk-modal');
        state.bulkApproveIds = [];
        var ok = 0;
        var fail = 0;
        for (var i = 0; i < ids.length; i++) {
          try {
            await patchResolve(ids[i], 'approved', null);
            ok++;
          } catch (e) {
            fail++;
          }
        }
        state.selected.clear();
        await fetchList();
        if (fail === 0) showAlert('success', ok + ' solicitação(ões) aprovada(s).');
        else showAlert('danger', ok + ' ok, ' + fail + ' falha(s). Recarregue e tente de novo nas pendentes.');
      });

    $('dac-bulk-deny') &&
      $('dac-bulk-deny').addEventListener('click', function () {
        var ids = [];
        state.selected.forEach(function (id) {
          var row = state.rows.find(function (r) {
            return String(r.id) === String(id);
          });
          if (row && (row.status || '').toLowerCase() === 'pending') ids.push(id);
        });
        if (!ids.length) return;
        openDenyModal(ids);
      });

    $('dac-deny-confirm') &&
      $('dac-deny-confirm').addEventListener('click', async function () {
        var errEl = $('dac-deny-error');
        var ta = $('dac-deny-obs');
        var obs = ta ? ta.value.trim().slice(0, 1000) : '';
        var ids = state.denyIds.slice();
        if (errEl) {
          errEl.classList.add('hidden');
          errEl.textContent = '';
        }
        var btn = $('dac-deny-confirm');
        if (btn) btn.disabled = true;
        var ok = 0;
        var fail = 0;
        try {
          for (var i = 0; i < ids.length; i++) {
            try {
              await patchResolve(ids[i], 'denied', obs || null);
              ok++;
            } catch (e) {
              fail++;
            }
          }
          closeModal('dac-deny-modal');
          state.selected.clear();
          await fetchList();
          if (fail === 0) showAlert('success', ok + ' solicitação(ões) negada(s).');
          else showAlert('danger', ok + ' ok, ' + fail + ' falha(s).');
        } catch (e) {
          if (errEl) {
            errEl.textContent = e.message || 'Erro';
            errEl.classList.remove('hidden');
          }
        } finally {
          if (btn) btn.disabled = false;
        }
      });

    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(fetchList, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      bind();
      fetchList();
    });
  } else {
    bind();
    fetchList();
  }
})();
