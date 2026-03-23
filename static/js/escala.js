/**
 * Módulo Escala Operacional - Quadro mobile-first
 * Integra com /separacao: alterações refletem nas rotas em tempo real
 */
(function() {
    'use strict';

    const init = window.__escalaInit || { date: new Date().toISOString().slice(0, 10), shift: "Manhã" };

    function escalaApp() {
        return {
            filters: { date: init.date, shift: init.shift },
            summary: { total: 0, completas: 0, pendentes: 0, em_ajuste: 0, peso_total: 0, valor_total: 0 },
            escalas: [],
            apiData: {},
            loading: true,
            columns: [
                { id: 'nao_escalado', label: 'Não escalados', headerClass: 'bg-slate-700/50' },
                { id: 'escalado', label: 'Escalados', headerClass: 'bg-emerald-900/30 border-emerald-500/30' },
                { id: 'em_ajuste', label: 'Em ajuste', headerClass: 'bg-violet-900/30 border-violet-500/30' },
                { id: 'pendencia', label: 'Pendências', headerClass: 'bg-amber-900/30 border-amber-500/30' }
            ],
            drawerOpen: false,
            quickChange: { open: false, campo: '', escala: null, ajudantesSelected: [] },
            toast: { show: false, ok: true, message: '' },
            dragTarget: null,

            get escalasByCol() {
                const by = { nao_escalado: [], escalado: [], em_ajuste: [], pendencia: [] };
                for (const e of this.escalas) {
                    const st = e.escala_status || 'escalado';
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
                    this.summary = data.summary || this.summary;
                    this.escalas = data.escalas || [];
                    this.renderRecursos();
                    if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 50);
                } catch (err) {
                    this.showToast('Erro ao carregar dados.', false);
                } finally {
                    this.loading = false;
                }
            },

            renderRecursos() {
                const mot = document.getElementById('recursos-motoristas');
                const ajd = document.getElementById('recursos-ajudantes');
                const cam = document.getElementById('recursos-caminhoes');
                if (!mot || !ajd || !cam) return;

                const fmt = (arr, cls) => (arr || []).map(x =>
                    `<span class="px-2 py-1 rounded text-[11px] ${cls}">${x.name || x.placa || '—'}</span>`
                ).join('');
                mot.innerHTML = fmt(this.apiData.motoristas_disponiveis || [], 'bg-slate-700/80 text-slate-300');
                ajd.innerHTML = fmt(this.apiData.ajudantes_disponiveis || [], 'bg-slate-700/80 text-slate-300');
                cam.innerHTML = (this.apiData.vehicles || []).map(v =>
                    `<span class="px-2 py-1 rounded text-[11px] bg-slate-700/80 text-slate-300">${v.placa || '—'}</span>`
                ).join('');
            },

            formatPesoValor() {
                const p = this.summary.peso_total || 0;
                const v = this.summary.valor_total || 0;
                return `${(p / 1000).toFixed(1)}t · R$ ${v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
            },

            formatKg(n) {
                if (n == null) return '—';
                return `${Number(n).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kg`;
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
