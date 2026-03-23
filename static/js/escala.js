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
            summary: { total: 0, completas: 0, pendentes: 0 },
            escalas: [],
            apiData: {},
            loading: true,
            columns: [
                { id: 'escalado', label: 'Escalados', headerClass: 'bg-emerald-900/30 border-emerald-500/30' },
                { id: 'nao_escalado', label: 'Não escalados', headerClass: 'bg-slate-700/50' }
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
                    this.summary = {
                        total: data.summary?.total ?? 0,
                        completas: data.summary?.completas ?? 0,
                        pendentes: data.summary?.pendentes ?? 0
                    };
                    this.escalas = data.escalas || [];
                    if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 50);
                } catch (err) {
                    this.showToast('Erro ao carregar dados.', false);
                } finally {
                    this.loading = false;
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
                if (el && el.classList) el.classList.add('opacity-50');
            },

            dragEnd(ev) {
                const el = ev.currentTarget || ev.target;
                if (el && el.classList) el.classList.remove('opacity-50');
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
                this.quickChange = { open: true, campo, escala: esc, ajudantesSelected: [...(esc.helper_ids || [])] };
                if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 50);
            },

            async applyQuickChange(novoMotoristaId, novoCaminhaoPlaca, novosAjudantesIds) {
                const esc = this.quickChange.escala;
                if (!esc) return;

                const payload = {
                    date: this.filters.date,
                    shift: this.filters.shift,
                    escala_id: esc.id
                };
                if (novoMotoristaId != null) payload.novo_motorista_id = novoMotoristaId;
                if (novoCaminhaoPlaca != null) payload.novo_caminhao_placa = novoCaminhaoPlaca;
                if (novosAjudantesIds != null) payload.novos_ajudantes_ids = Array.isArray(novosAjudantesIds) ? novosAjudantesIds : [novosAjudantesIds];

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
