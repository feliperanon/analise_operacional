/**
 * Módulo Escala Operacional - Caminhões como base, motoristas e ajudantes filtrados por permissão
 * Formato BR: kg, R$, data/hora
 */
(function() {
    'use strict';

    const init = window.__escalaInit || { date: new Date().toISOString().slice(0, 10), shift: "Manhã" };

    function escalaApp() {
        return {
            filters: { date: init.date, shift: init.shift },
            summary: {
                total: 0,
                completas: 0,
                pendentes: 0,
                motoristas: 0,
                ajudantes: 0,
                escalados: 0,
                sem_escala: 0,
            },
            escalas: [],
            apiData: {},
            loading: true,
            columns: [
                {
                    id: 'escalado',
                    label: 'Escalados',
                    headerClass:
                        'border-emerald-200/90 bg-emerald-50 text-emerald-900 dark:border-emerald-800/50 dark:bg-emerald-950/50 dark:text-emerald-100',
                },
                {
                    id: 'nao_escalado',
                    label: 'Não escalados',
                    headerClass:
                        'border-amber-200/90 bg-amber-50 text-amber-950 dark:border-amber-800/50 dark:bg-amber-950/40 dark:text-amber-100',
                },
            ],
            quickChange: { open: false, campo: '', escala: null, ajudantesSelected: [] },
            toast: { show: false, ok: true, message: '' },
            dragTarget: null,

            get escalasByCol() {
                const by = { nao_escalado: [], escalado: [] };
                for (const e of this.escalas) {
                    let st = e.escala_status || 'escalado';
                    if (st === 'em_ajuste') st = 'escalado';
                    if (st === 'pendencia') st = 'nao_escalado';
                    if (by[st]) by[st].push(e);
                    else by.escalado.push(e);
                }
                return by;
            },

            normalizePersonName(name) {
                return String(name || '')
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .trim()
                    .toLowerCase();
            },

            getFilteredAjudantesDisponiveis() {
                const motoristas = this.apiData.motoristas_disponiveis || [];
                const ajudantes = this.apiData.ajudantes_disponiveis || [];
                return this.filterHelpersAgainstDrivers(ajudantes, motoristas);
            },

            filterHelpersAgainstDrivers(helpers, drivers) {
                const motoristas = Array.isArray(drivers) ? drivers : [];
                const ajudantes = Array.isArray(helpers) ? helpers : [];
                const motoristaIds = new Set(
                    motoristas
                        .map((m) => Number(m && m.id))
                        .filter((id) => Number.isFinite(id))
                );
                const motoristaNames = new Set(
                    motoristas
                        .map((m) => this.normalizePersonName(m && m.name))
                        .filter(Boolean)
                );

                return ajudantes.filter((a) => {
                    const helperId = Number(a && a.id);
                    const helperName = this.normalizePersonName(a && a.name);
                    if (Number.isFinite(helperId) && motoristaIds.has(helperId)) return false;
                    if (helperName && motoristaNames.has(helperName)) return false;
                    return true;
                });
            },

            getFilteredHelperNames(esc) {
                const helperNames = Array.isArray(esc && esc.helper_names) ? esc.helper_names : [];
                const driverName = this.normalizePersonName(esc && esc.driver_name);
                if (!driverName) return helperNames;
                return helperNames.filter((name) => this.normalizePersonName(name) !== driverName);
            },

            abbreviatePersonName(name) {
                const parts = String(name || '')
                    .trim()
                    .split(/\s+/)
                    .filter(Boolean);
                if (!parts.length) return '—';
                if (parts.length === 1) return parts[0];
                const first = parts[0];
                const lastInitial = parts[parts.length - 1].charAt(0).toUpperCase();
                return `${first} ${lastInitial}.`;
            },

            formatHelperNamesShort(esc) {
                const helperNames = this.getFilteredHelperNames(esc);
                if (!helperNames.length) return '—';
                return helperNames.map((name) => this.abbreviatePersonName(name)).join(', ');
            },

            normalizeId(value) {
                const n = Number(value);
                return Number.isFinite(n) ? n : null;
            },

            splitInTwo(list) {
                const items = Array.isArray(list) ? list : [];
                if (!items.length) return [[], []];
                const middle = Math.ceil(items.length / 2);
                return [items.slice(0, middle), items.slice(middle)];
            },

            get selectedHelperConflicts() {
                if (this.quickChange.campo !== 'ajudante' || !this.quickChange.escala) return [];
                const selectedIds = (this.quickChange.ajudantesSelected || [])
                    .map((id) => this.normalizeId(id))
                    .filter((id) => id != null);
                if (!selectedIds.length) return [];

                const currentEscalaId = this.normalizeId(this.quickChange.escala.id);
                const selectedSet = new Set(selectedIds);
                const conflictsByHelperId = new Map();

                for (const esc of this.escalas || []) {
                    const escId = this.normalizeId(esc && esc.id);
                    if (currentEscalaId != null && escId === currentEscalaId) continue;
                    if ((esc && esc.escala_status) === 'nao_escalado') continue;

                    const helperIds = Array.isArray(esc && esc.helper_ids) ? esc.helper_ids : [];
                    for (const rawId of helperIds) {
                        const helperId = this.normalizeId(rawId);
                        if (helperId == null || !selectedSet.has(helperId) || conflictsByHelperId.has(helperId)) continue;
                        conflictsByHelperId.set(helperId, {
                            helperId,
                            vehiclePlate: esc && esc.vehicle_plate ? esc.vehicle_plate : 'Sem caminhão'
                        });
                    }
                }

                if (!conflictsByHelperId.size) return [];
                const helperList = Array.isArray(this.apiData && this.apiData.ajudantes_todos) ? this.apiData.ajudantes_todos : [];
                const helperById = new Map(
                    helperList
                        .map((h) => [this.normalizeId(h && h.id), h && h.name])
                        .filter(([id]) => id != null)
                );

                return Array.from(conflictsByHelperId.values()).map((c) => ({
                    ...c,
                    name: helperById.get(c.helperId) || `ID ${c.helperId}`
                }));
            },

            get hasSelectedHelperConflicts() {
                return this.selectedHelperConflicts.length > 0;
            },

            isHelperQuickChange() {
                return String(this.quickChange && this.quickChange.campo ? this.quickChange.campo : '')
                    .trim()
                    .toLowerCase()
                    .startsWith('ajud');
            },

            init() {
                this.loadData();
            },

            async loadData() {
                this.loading = true;
                const params = new URLSearchParams({ date: this.filters.date, shift: this.filters.shift });
                try {
                    const r = await fetch(`/escala/api/data?${params}`);
                    const data = await r.json();
                    this.apiData = data;
                    const s = data.summary || {};
                    const motoristasTodos = data.motoristas_todos || [];
                    const ajudantesTodosRaw = data.ajudantes_todos || [];
                    const ajudantesTodos = this.filterHelpersAgainstDrivers(ajudantesTodosRaw, motoristasTodos);
                    const motoristasDisponiveis = data.motoristas_disponiveis || [];
                    const ajudantesDisponiveisRaw = data.ajudantes_disponiveis || [];
                    const ajudantesDisponiveis = this.filterHelpersAgainstDrivers(ajudantesDisponiveisRaw, motoristasDisponiveis);
                    this.summary = {
                        total: s.total ?? 0,
                        completas: s.completas ?? 0,
                        pendentes: s.pendentes ?? 0,
                        motoristas: s.motoristas ?? motoristasTodos.length,
                        ajudantes: ajudantesTodos.length,
                        escalados: s.escalados ?? s.completas ?? 0,
                        sem_escala: motoristasDisponiveis.length + ajudantesDisponiveis.length
                    };
                    this.escalas = data.escalas || [];
                } catch (err) {
                    this.showToast('Erro ao carregar dados.', false);
                } finally {
                    this.loading = false;
                    if (typeof lucide !== 'undefined') {
                        setTimeout(() => lucide.createIcons(), 50);
                    }
                }
            },

            formatKg(n) {
                if (n == null) return '—';
                const v = Number(n);
                if (v >= 1000) {
                    return `${(v / 1000).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 2 })} t`;
                }
                return `${v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kg`;
            },

            formatMoeda(n) {
                if (n == null) return '—';
                return `R$ ${Number(n).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            },

            showToast(msg, ok = true) {
                this.toast = { show: true, ok, message: msg };
                setTimeout(() => { this.toast.show = false; }, 3000);
            },

            dragStart(ev, esc) {
                this.dragTarget = esc;
                ev.dataTransfer.effectAllowed = 'move';
                ev.dataTransfer.setData('text/plain', esc.id);
                const el = ev.currentTarget || ev.target;
                const card = el && el.closest ? el.closest('.escala-card') : el;
                if (card && card.classList) card.classList.add('opacity-50');
            },

            dragEnd(ev) {
                const el = ev.currentTarget || ev.target;
                const card = el && el.closest ? el.closest('.escala-card') : el;
                if (card && card.classList) card.classList.remove('opacity-50');
                this.dragTarget = null;
            },

            dragOver(ev, colId) {
                ev.preventDefault();
                ev.dataTransfer.dropEffect = 'move';
            },

            drop(ev, colId) {
                ev.preventDefault();
                const esc = this.dragTarget;
                if (!esc || esc.escala_status === colId) return;
                this.applyStatusChange(esc, colId);
                this.dragTarget = null;
            },

            async applyStatusChange(esc, novoStatus) {
                try {
                    const r = await fetch('/escala/api/atualizar', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            date: this.filters.date,
                            shift: this.filters.shift,
                            escala_id: esc.id,
                            novo_status: novoStatus
                        })
                    });
                    const data = await r.json();
                    if (data.ok) {
                        esc.escala_status = novoStatus;
                        this.loadData();
                        this.showToast('Status atualizado.');
                    } else {
                        this.showToast(data.error || 'Erro ao atualizar.', false);
                    }
                } catch (err) {
                    this.showToast('Erro de conexão.', false);
                }
            },

            openQuickChange(esc, campo) {
                const campoNormalizado = campo === 'ajudantes' ? 'ajudante' : campo;
                this.quickChange = { open: true, campo: campoNormalizado, escala: esc, ajudantesSelected: [...(esc.helper_ids || [])] };
                if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 50);
            },

            async applyQuickChange(novoMotoristaId, novoCaminhaoPlaca, novosAjudantesIds) {
                const esc = this.quickChange.escala;
                if (!esc) return;
                if (novosAjudantesIds != null && this.hasSelectedHelperConflicts) {
                    this.showToast('Há ajudante já em outra rota. Ajuste a seleção antes de aplicar.', false);
                    return;
                }

                const payload = {
                    date: this.filters.date,
                    shift: this.filters.shift,
                    escala_id: esc.id
                };
                if (novoMotoristaId != null) payload.novo_motorista_id = novoMotoristaId;
                if (novoCaminhaoPlaca != null) payload.novo_caminhao_placa = novoCaminhaoPlaca;
                if (novosAjudantesIds != null) {
                    const normalizedIds = (Array.isArray(novosAjudantesIds) ? novosAjudantesIds : [novosAjudantesIds])
                        .map((id) => this.normalizeId(id))
                        .filter((id) => id != null);
                    payload.novos_ajudantes_ids = normalizedIds;
                }

                try {
                    const r = await fetch('/escala/api/atualizar', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await r.json();
                    if (data.ok) {
                        this.quickChange.open = false;
                        this.loadData();
                        this.showToast('Alteração salva. Atualize /separacao para ver.');
                    } else {
                        this.showToast(data.error || 'Erro ao salvar.', false);
                    }
                } catch (err) {
                    this.showToast('Erro de conexão.', false);
                }
            }
        };
    }

    window.escalaApp = escalaApp;
})();
