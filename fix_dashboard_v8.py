import os

# Dashboard Mobile 5.3 (Syntax Repair)
# Fixing {{ c.id }} spacing and chart variable line breaks
content = r'''{% extends "mobile/layout.html" %}

{% block content %}
<!-- Dashboard Mobile 5.3 (Syntax Fix) -->
<div x-data="dashboardController()" class="dashboard-grid animate-fade-in relative z-10 w-full h-full pb-24">

    <!-- HEADER Area -->
    <div class="grid-header flex justify-between items-center mb-2">
        <div>
            <h2 class="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
                Olá, {{ (employee.name or 'Colaborador').split()[0] }}
            </h2>
            <p class="text-xs font-medium text-blue-400 tracking-wide mt-1">
                MATRÍCULA: {{ employee.registration_id }}
            </p>
        </div>
        <div class="glass-panel px-4 py-2 flex items-center gap-3 border-yellow-500/20 shadow-[0_4px_12px_rgba(234,179,8,0.1)]">
            <div class="p-1.5 rounded-full bg-yellow-500/10 text-yellow-400">
                <i data-lucide="trophy" width="16" height="16"></i>
            </div>
            <span class="font-bold text-lg text-yellow-400 font-mono tracking-tight">
                {{ "{:,.0f}".format(employee.total_xp or 0).replace(",", ".") }}
            </span>
        </div>
    </div>

    <!-- INSIGHT Area -->
    {% if ai_message %}
    <div class="grid-insight glass-panel p-5 border-l-4 border-l-blue-500 relative overflow-hidden group">
        <div class="absolute inset-0 bg-blue-500/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex gap-4 items-start relative z-10">
            <div class="p-2 rounded-lg bg-blue-500/20 text-blue-400 shrink-0 mt-0.5">
                <i data-lucide="bot" width="20" height="20"></i>
            </div>
            <div>
                <p class="text-sm text-slate-200 leading-relaxed font-medium">"{{ ai_message }}"</p>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- ACTIVE ROUTES LIST (Dynamic) -->
    <div class="grid-modules glass-panel p-5 flex flex-col h-full overflow-hidden">
        <div class="flex justify-between items-center mb-4">
             <h3 class="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Atividades em Andamento</h3>
             <span class="text-xs font-bold text-blue-400" x-text="activeRoutes.length + ' Ativas'"></span>
        </div>

        <!-- Empty State -->
        <div x-show="activeRoutes.length === 0" class="flex-1 flex flex-col items-center justify-center text-slate-500 opacity-60">
            <i data-lucide="check-circle" width="32" height="32" class="mb-2"></i>
            <p class="text-xs">Nenhuma rota ativa.</p>
        </div>

        <!-- Scrollable List -->
        <div class="flex-1 overflow-y-auto space-y-3 pr-1">
            <template x-for="(route, index) in activeRoutes" :key="route.id">
                <div class="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 shadow-sm relative group">
                    <div class="flex justify-between items-start mb-2">
                        <div class="pr-8">
                             <h4 class="text-sm font-bold text-white leading-tight" x-text="route.client_name"></h4>
                             <div class="flex items-center gap-3 mt-2">
                                 <div class="flex items-center text-[10px] text-slate-400 bg-slate-900/50 px-2 py-1 rounded">
                                     <i data-lucide="clock" width="10" class="mr-1"></i> <span x-text="route.start_time"></span>
                                 </div>
                                 <div class="flex items-center text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded">
                                     <i data-lucide="weight" width="10" class="mr-1"></i> <span x-text="route.tonnage + ' kg'"></span>
                                 </div>
                             </div>
                        </div>
                        <button @click="finishRoute(route.id, index)" 
                            :disabled="finishLoading === route.id"
                            class="absolute top-3 right-3 p-2 bg-slate-900 hover:bg-emerald-500 text-slate-400 hover:text-white rounded-lg border border-slate-700 hover:border-emerald-500 transition-all shadow-lg active:scale-95">
                            <span x-show="finishLoading !== route.id"><i data-lucide="check" width="18"></i></span>
                            <span x-show="finishLoading === route.id" class="animate-spin"><i data-lucide="loader-2" width="18"></i></span>
                        </button>
                    </div>
                </div>
            </template>
        </div>
    </div>

    <!-- ACTIONS Area -->
    <div class="grid-actions grid grid-cols-2 gap-4">
        <!-- Start Routine -->
        <button @click="openStartModal()" class="glass-panel action-card w-full group hover:border-green-500/40 transform hover:-translate-y-1 transition-all duration-300">
            <div class="p-4 rounded-2xl bg-gradient-to-br from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/30 group-hover:shadow-green-500/50 transition-shadow">
                <i data-lucide="plus" fill="currentColor" class="w-7 h-7"></i>
            </div>
            <span class="font-bold text-lg text-green-400 group-hover:text-green-300">Nova Carga</span>
        </button>

        <!-- Stop Routine -->
        <button @click="openStopModal()" class="glass-panel action-card w-full group hover:border-red-500/40 transform hover:-translate-y-1 transition-all duration-300">
            <div class="p-4 rounded-2xl bg-gradient-to-br from-red-500 to-rose-600 text-white shadow-lg shadow-red-500/30 group-hover:shadow-red-500/50 transition-shadow">
                <i data-lucide="power" fill="currentColor" class="w-7 h-7"></i>
            </div>
            <span class="font-bold text-lg text-red-500 group-hover:text-red-400">Encerrar Dia</span>
        </button>
    </div>

    <!-- STATS Area -->
    <div class="grid-stats glass-panel p-6 relative overflow-hidden min-h-[220px]">
         <div class="flex justify-between items-end mb-4 relative z-10">
            <div>
                 <h3 class="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Performance Semanal</h3>
                 <p class="text-xs text-slate-400 mt-1">Produtividade vs Meta</p>
            </div>
        </div>
        <div class="relative z-10 h-48 w-full">
            <canvas id="productivityChart"></canvas>
        </div>
    </div>

    <!-- MODALS (Start / Stop) -->
    <!-- STOP ROUTINE MODAL -->
    <div x-show="showStopModal" 
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0 scale-95"
         class="fixed inset-0 z-50 flex items-center justify-center p-4" x-cloak>
        <div @click="showStopModal = false" class="absolute inset-0 bg-black/80 backdrop-blur-sm"></div>
        <div class="relative w-full max-w-sm bg-slate-900 border border-slate-700 rounded-3xl overflow-hidden shadow-2xl p-6">
            <div class="text-center">
                <div class="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4 ring-4 ring-red-500/5">
                    <i data-lucide="alert-triangle" width="32" class="text-red-500"></i>
                </div>
                <h3 class="text-xl font-bold text-white mb-2">Encerrar Expediente?</h3>
                <p class="text-sm text-slate-400 mb-6">Isso finalizará todas as rotas pendentes e fechará seu dia.</p>
                <div class="grid grid-cols-2 gap-3">
                    <button @click="showStopModal = false" class="py-3 bg-slate-800 rounded-xl text-slate-300">Voltar</button>
                    <form action="/mobile/routine/stop" method="POST" class="w-full">
                        <button type="submit" class="w-full py-3 bg-red-600 text-white rounded-xl font-bold">Confirmar</button>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- START ROUTINE MODAL -->
    <div x-show="showStartModal" 
         x-transition:enter="transition ease-out duration-300"
         x-transition:enter-start="translate-y-full"
         x-transition:enter-end="translate-y-0"
         class="fixed inset-0 z-50 flex items-end sm:items-center justify-center pointer-events-none" x-cloak>
        <div @click="showStartModal = false" x-show="showStartModal" class="absolute inset-0 bg-black/80 backdrop-blur-sm pointer-events-auto"></div>
        <div class="bg-slate-900 w-full max-w-md rounded-t-3xl sm:rounded-3xl border-t sm:border border-slate-700 shadow-2xl pointer-events-auto h-[85vh] flex flex-col overflow-hidden">
            <div class="p-6 border-b border-slate-800 flex justify-between items-center bg-slate-900 z-10">
                <div>
                    <h3 class="text-xl font-bold text-white">Nova Carga</h3>
                    <p class="text-xs text-slate-400">Adicionar clientes à rotina</p>
                </div>
                <button @click="showStartModal = false" class="p-2 bg-slate-800 rounded-full text-slate-400"><i data-lucide="x" width="18"></i></button>
            </div>
            <div class="flex-1 overflow-y-auto p-6 space-y-4">
                <template x-for="(alloc, index) in allocations" :key="index">
                    <div class="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 animate-slide-up">
                        <div class="flex justify-between mb-2">
                             <label class="text-xs font-bold text-blue-400 uppercase">Cliente</label>
                             <button @click="removeAlloc(index)" class="text-xs text-red-500" x-show="allocations.length > 1">Remover</button>
                        </div>
                        <select x-model="alloc.client_id" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-white text-sm focus:border-blue-500 focus:outline-none mb-3">
                            <option value="">Selecione o Cliente...</option>
                            <template x-for="c in clientsList" :key="c.id">
                                <option :value="c.id" x-text="c.name"></option>
                            </template>
                        </select>
                        <label class="text-xs font-bold text-emerald-400 uppercase">Peso (Kg)</label>
                        <input type="number" x-model="alloc.weight" placeholder="0" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-white text-lg font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                </template>
                <button @click="addAlloc()" class="w-full py-3 border-2 border-dashed border-slate-700 rounded-xl text-slate-400 text-sm font-semibold hover:border-slate-500 hover:text-white transition-colors">
                    + Adicionar Cliente
                </button>
            </div>
            <div class="p-6 border-t border-slate-800 bg-slate-900 z-10">
                <button @click="submitStart()" :disabled="isLoading" class="w-full py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-lg shadow-lg shadow-blue-900/40 disabled:opacity-50 flex items-center justify-center gap-2">
                    <span x-show="!isLoading">Confirmar Início</span>
                    <span x-show="isLoading" class="animate-spin"><i data-lucide="loader-2"></i></span>
                </button>
                <div x-show="errorMessage" x-text="errorMessage" class="text-red-400 text-xs text-center mt-2"></div>
            </div>
        </div>
    </div>

</div>

{% endblock %}

{% block scripts %}
<script src="/static/js/chart.js"></script>
<script>
    function dashboardController() {
        return {
            showStopModal: false,
            showStartModal: false,
            isLoading: false,
            finishLoading: null,
            errorMessage: '',
            clientsList: [],
            activeRoutes: [],
            allocations: [{ client_id: '', weight: '' }],

            init() {
                // Initialize Data from Jinja
                this.clientsList = [
                    {% for c in clients %}
                        { id: {{ c.id }}, name: "{{ c.name }}" },
                    {% endfor %}
                ];
                
                this.activeRoutes = {{ active_routes | safe }};
                
                this.initChart();
            },

            activeRoutesCount() { return this.activeRoutes.length; },

            openStartModal() {
                this.allocations = [{ client_id: '', weight: '' }];
                this.showStartModal = true;
            },

            openStopModal() {
                this.showStopModal = true;
            },

            addAlloc() {
                this.allocations.push({ client_id: '', weight: '' });
            },

            removeAlloc(index) {
                this.allocations.splice(index, 1);
            },

            async submitStart() {
                const valid = this.allocations.filter(a => a.client_id && a.weight > 0);
                if (valid.length === 0) {
                    this.errorMessage = "Preencha os dados corretamente.";
                    return;
                }
                
                this.isLoading = true;
                try {
                    const res = await fetch('/mobile/routine/start_with_allocation', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ allocations: valid })
                    });
                    
                    if (res.ok) {
                        window.location.reload();
                    } else {
                        const data = await res.json();
                        this.errorMessage = data.error || "Erro.";
                    }
                } catch {
                    this.errorMessage = "Erro de conexão.";
                } finally {
                    this.isLoading = false;
                }
            },
            
            async finishRoute(id, index) {
                if (!confirm("Confirmar conclusão desta carga?")) return;
                
                this.finishLoading = id;
                try {
                     const res = await fetch(`/mobile/route/${id}/finish`, { method: 'POST' });
                     if (res.ok) {
                         this.activeRoutes.splice(index, 1);
                     }
                } catch (e) {
                    alert("Erro ao finalizar.");
                } finally {
                    this.finishLoading = null;
                }
            },

            initChart() {
                const ctx = document.getElementById('productivityChart');
                if (!ctx) return;
                
                const labels = {{ chart_labels | safe }};
                const dailyKg = {{ chart_daily_kg | safe }};
                const dailyKgh = {{ chart_daily_kgh | safe }};
                const cumulativeKg = {{ chart_cumulative_kg | safe }};
                const bgColors = {{ chart_bg_colors | safe }};

                new Chart(ctx.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                type: 'line',
                                label: 'Kg/h',
                                data: dailyKgh,
                                borderColor: '#fbbf24',
                                borderWidth: 2,
                                borderDash: [5, 5],
                                pointBackgroundColor: '#fbbf24',
                                yAxisID: 'y1',
                                tension: 0.4
                            },
                            {
                                type: 'bar',
                                label: 'Peso (Kg)',
                                data: dailyKg,
                                backgroundColor: bgColors,
                                borderRadius: 4,
                                yAxisID: 'y'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            y: { display: false, beginAtZero: true, grid: { display: false } },
                            y1: { display: false, beginAtZero: true, position: 'right', grid: { display: false } },
                            x: { display: true, grid: { display: false }, ticks: { color: '#64748b', font: { size: 10 } } }
                        }
                    }
                });
            }
        }
    }
</script>
{% endblock %}
'''

with open(r'c:\Projeto\analise_operacional\templates\mobile\dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Dashboard 5.3 (Syntax Repair V8) written successfully.")
