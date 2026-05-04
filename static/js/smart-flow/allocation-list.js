/**
 * Lista do turno: tabela (desktop) + cards (mobile), debounce na busca, paginação incremental.
 */
const AllocationList = {
    PAGE_SIZE: 45,
    _debounceTimer: null,
    _search: '',
    _view: 'all',
    _displayLimit: 45,

    _esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    init() {
        const search = document.getElementById('sf-list-search');
        if (search) {
            search.addEventListener('input', () => {
                clearTimeout(this._debounceTimer);
                this._debounceTimer = setTimeout(() => {
                    this._search = (search.value || '').trim().toLowerCase();
                    this._displayLimit = this.PAGE_SIZE;
                    this._renderFromStore();
                }, 280);
            });
        }

        document.querySelectorAll('[data-sf-view]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this._view = btn.getAttribute('data-sf-view') || 'all';
                document.querySelectorAll('[data-sf-view]').forEach((b) => {
                    b.classList.toggle('filter-btn--active', b.getAttribute('data-sf-view') === this._view);
                });
                this._displayLimit = this.PAGE_SIZE;
                this._renderFromStore();
            });
        });

        const clearBtn = document.getElementById('sf-view-clear');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                this._view = 'all';
                this._search = '';
                if (search) search.value = '';
                document.querySelectorAll('[data-sf-view]').forEach((b) => {
                    b.classList.toggle('filter-btn--active', b.getAttribute('data-sf-view') === 'all');
                });
                this._displayLimit = this.PAGE_SIZE;
                this._renderFromStore();
            });
        }

        const loadMore = document.getElementById('sf-load-more');
        if (loadMore) {
            loadMore.addEventListener('click', () => {
                this._displayLimit += this.PAGE_SIZE;
                this._renderFromStore();
            });
        }

        const tabMural = document.getElementById('sf-tab-mural');
        const tabList = document.getElementById('sf-tab-list');
        const panelMural = document.getElementById('sf-panel-mural');
        const panelList = document.getElementById('sf-panel-list');

        const styleTabActive = (btn) => {
            if (!btn) return;
            btn.classList.add('sf-tab--active', 'opacity-100');
            btn.classList.remove('opacity-70');
        };
        const styleTabIdle = (btn) => {
            if (!btn) return;
            btn.classList.remove('sf-tab--active');
            btn.classList.add('opacity-70');
        };

        const activateMural = () => {
            panelMural?.classList.remove('hidden');
            panelList?.classList.add('hidden');
            styleTabActive(tabMural);
            styleTabIdle(tabList);
            try {
                window.__safeSession.setItem('sf-tab', 'mural');
            } catch (_) {
                /* ignore */
            }
        };

        const activateList = () => {
            panelList?.classList.remove('hidden');
            panelMural?.classList.add('hidden');
            styleTabActive(tabList);
            styleTabIdle(tabMural);
            try {
                window.__safeSession.setItem('sf-tab', 'list');
            } catch (_) {
                /* ignore */
            }
            this._renderFromStore();
        };

        tabMural?.addEventListener('click', activateMural);
        tabList?.addEventListener('click', activateList);

        try {
            if (window.__safeSession.getItem('sf-tab') === 'list') activateList();
        } catch (_) {
            /* ignore */
        }
    },

    onStoreUpdate(state) {
        const panelList = document.getElementById('sf-panel-list');
        if (!panelList || panelList.classList.contains('hidden')) return;
        this._renderFromStore(state);
    },

    _shiftEmployees(state) {
        const cs = state.currentShift;
        return (state.employees || []).filter((e) => {
            const empShift = e.work_shift ?? e.shift ?? null;
            if (!empShift) return false;
            return String(empShift).toLowerCase() === String(cs).toLowerCase();
        });
    },

    _locationForEmp(empId, state) {
        const raw = state.allocations[String(empId)] ?? state.allocations[empId];
        if (raw == null) return { sector: '—', sub: '—' };
        const subId = raw;
        for (const sec of state.sectors || []) {
            const subs = sec.subsectors || [];
            const found = subs.find((s) => String(s.id) === String(subId) || s.id === subId);
            if (found) return { sector: sec.name || '—', sub: found.name || '—' };
        }
        return { sector: '—', sub: '—' };
    },

    _routineLabel(emp, routines) {
        const r = routines[emp.id] || emp.status || 'present';
        const x = String(r).toLowerCase();
        const map = {
            present: 'Presente',
            ativo: 'Presente',
            active: 'Presente',
            dayoff: 'Folga',
            folga: 'Folga',
            absent: 'Falta',
            falta: 'Falta',
            sick: 'Atestado',
            atestado: 'Atestado',
            vacation: 'Férias',
            ferias: 'Férias',
            férias: 'Férias',
            away: 'Afastado',
            afastado: 'Afastado'
        };
        return map[x] || (typeof r === 'string' ? r : 'Presente');
    },

    _isUnavailable(emp, routines) {
        const st = (emp.status || 'active').toLowerCase();
        const routine = routines[emp.id];
        const normalized = routine ? String(routine).toLowerCase() : null;
        if (
            normalized === 'dayoff' ||
            normalized === 'folga' ||
            normalized === 'absent' ||
            normalized === 'falta' ||
            normalized === 'sick' ||
            normalized === 'atestado' ||
            normalized === 'vacation' ||
            normalized === 'ferias' ||
            normalized === 'férias' ||
            normalized === 'away' ||
            normalized === 'afastado'
        ) {
            return true;
        }
        if (st === 'vacation' || st === 'férias' || st === 'ferias' || st === 'away' || st === 'afastado' || st === 'sick' || st === 'atestado') {
            return true;
        }
        return false;
    },

    _countInSector(sector, allocations) {
        if (!sector || !sector.subsectors || !allocations) return 0;
        const subIds = new Set(sector.subsectors.map((s) => String(s.id)));
        let n = 0;
        for (const sid of Object.values(allocations)) {
            if (subIds.has(String(sid))) n += 1;
        }
        return n;
    },

    _sectorCriticalForEmp(empId, state) {
        const subRef = state.allocations[String(empId)] ?? state.allocations[empId];
        if (subRef == null) return false;
        for (const sec of state.sectors || []) {
            const inThis = (sec.subsectors || []).some((s) => String(s.id) === String(subRef) || s.id === subRef);
            if (!inThis) continue;
            const max = sec.max_employees || 0;
            if (max <= 0) return false;
            const n = this._countInSector(sec, state.allocations);
            const pct = Math.round((n / max) * 100);
            return pct < 80;
        }
        return false;
    },

    _hasAllocation(empId, allocations) {
        if (!allocations) return false;
        return allocations[String(empId)] != null || allocations[empId] != null;
    },

    _rowsForState(state) {
        const employees = this._shiftEmployees(state);
        const rows = [];
        for (const emp of employees) {
            const st = (emp.status || 'active').toLowerCase();
            if (st === 'fired' || st === 'demitido') continue;
            const loc = this._locationForEmp(emp.id, state);
            const hasAlloc = this._hasAllocation(emp.id, state.allocations);
            const unavailable = this._isUnavailable(emp, state.routines);
            rows.push({
                emp,
                loc,
                statusLabel: this._routineLabel(emp, state.routines),
                unavailable,
                unallocated: !hasAlloc,
                critical: hasAlloc && !unavailable && this._sectorCriticalForEmp(emp.id, state)
            });
        }
        return rows;
    },

    _applyFilters(rows) {
        let out = rows;
        const q = this._search;
        if (q) {
            out = out.filter((r) => {
                const name = (r.emp.name || '').toLowerCase();
                const id = String(r.emp.id || '');
                const role = (r.emp.role || '').toLowerCase();
                return name.includes(q) || id.includes(q) || role.includes(q);
            });
        }
        if (this._view === 'present') {
            out = out.filter((r) => !r.unavailable);
        } else if (this._view === 'unallocated') {
            out = out.filter((r) => r.unallocated && !r.unavailable);
        } else if (this._view === 'absent') {
            out = out.filter((r) => r.unavailable);
        } else if (this._view === 'critical') {
            out = out.filter((r) => r.critical);
        }
        return out;
    },

    _renderFromStore(state) {
        state = state || (typeof Store !== 'undefined' ? Store.state : null);
        if (!state) return;

        const loading = document.getElementById('sf-list-loading');
        const err = document.getElementById('sf-list-error');
        const empty = document.getElementById('sf-list-empty');
        const tbody = document.getElementById('sf-allocation-tbody');
        const cards = document.getElementById('sf-allocation-cards');
        const tableWrap = tbody ? tbody.closest('.sys-table-wrap') : null;
        const pageInfo = document.getElementById('sf-page-info');
        const loadMore = document.getElementById('sf-load-more');

        if (!tbody) return;

        if (loading) loading.classList.add('hidden');
        if (err) err.classList.add('hidden');

        const allRows = this._rowsForState(state);
        const filtered = this._applyFilters(allRows);
        const total = filtered.length;
        const slice = filtered.slice(0, this._displayLimit);

        if (total === 0) {
            empty?.classList.remove('hidden');
            tableWrap?.classList.add('hidden');
            if (cards) {
                cards.classList.add('hidden');
                cards.innerHTML = '';
            }
            tbody.innerHTML = '';
            if (pageInfo) pageInfo.textContent = '0';
            loadMore?.classList.add('hidden');
            return;
        }

        empty?.classList.add('hidden');
        tableWrap?.classList.remove('hidden');
        if (cards) cards.classList.remove('hidden');

        tbody.innerHTML = slice
            .map((r) => {
                const e = r.emp;
                const sit = r.unallocated ? 'Sem alocação' : r.critical ? 'Abaixo da ocupação' : 'Ok';
                return `<tr class="employees-data-table__row transition-colors">
                <td class="employees-data-table__td px-3 py-2 pl-5 align-middle font-medium text-slate-800 dark:text-slate-100">${this._esc(e.name)}</td>
                <td class="employees-data-table__cell px-2 py-2 align-middle tabular-nums text-sm">${this._esc(e.id)}</td>
                <td class="employees-data-table__cell px-2 py-2 align-middle text-sm">${this._esc(e.role || '—')}</td>
                <td class="employees-data-table__cell px-2 py-2 align-middle"><span class="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">${this._esc(r.statusLabel)}</span></td>
                <td class="employees-data-table__cell px-2 py-2 align-middle text-sm">${this._esc(r.loc.sector)}</td>
                <td class="employees-data-table__cell px-2 py-2 align-middle text-sm">${this._esc(r.loc.sub)}</td>
                <td class="employees-data-table__cell px-2 py-2 pr-5 align-middle text-sm">${this._esc(sit)}</td>
            </tr>`;
            })
            .join('');

        if (cards) {
            cards.innerHTML = slice
                .map((r) => {
                    const e = r.emp;
                    return `<article class="sys-card sys-card--surface rounded-xl border border-slate-200/80 p-4 shadow-sm dark:border-slate-700">
                    <div class="flex justify-between gap-2">
                        <div class="min-w-0">
                            <p class="truncate font-semibold text-slate-900 dark:text-white">${this._esc(e.name)}</p>
                            <p class="text-xs text-slate-500">Mat. ${this._esc(e.id)} · ${this._esc(e.role || '—')}</p>
                        </div>
                        <span class="inline-flex shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">${this._esc(r.statusLabel)}</span>
                    </div>
                    <div class="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600 dark:text-slate-300">
                        <div><span class="text-slate-400">Setor</span><br><span class="font-medium">${this._esc(r.loc.sector)}</span></div>
                        <div><span class="text-slate-400">Subsetor</span><br><span class="font-medium">${this._esc(r.loc.sub)}</span></div>
                    </div>
                </article>`;
                })
                .join('');
        }

        if (pageInfo) pageInfo.textContent = `${slice.length} de ${total}`;
        if (loadMore) {
            if (this._displayLimit < total) loadMore.classList.remove('hidden');
            else loadMore.classList.add('hidden');
        }
    }
};

window.AllocationList = AllocationList;
