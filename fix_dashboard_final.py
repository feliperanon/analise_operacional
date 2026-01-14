import os

file_path = "c:\\Projeto\\analise_operacional\\templates\\mobile\\dashboard.html"

new_content = """{% extends "mobile/layout.html" %}

{% block content %}
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

    <!-- ACTIVE ROUTES LIST (Rich Detail + Timer) -->
    <div class="grid-modules flex flex-col gap-4 overflow-visible">
        
        <!-- Section Title -->
        <div class="flex justify-between items-center px-1">
             <h3 class="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Em Andamento</h3>
             <span class="text-xs font-bold text-blue-400" x-text="activeRoutes.length + ' Ativas'"></span>
        </div>

        <!-- Empty State -->
        <div x-show="activeRoutes.length === 0" class="glass-panel p-8 flex flex-col items-center justify-center text-slate-500 opacity-60">
            <i data-lucide="coffee" width="32" height="32" class="mb-2"></i>
            <p class="text-xs">Nenhuma atividade agora.</p>
        </div>

        <!-- Rich Active Cards -->
        <div class="space-y-4">
            <template x-for="(route, index) in activeRoutes" :key="route.id">
                <div class="relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 border border-blue-500/30 shadow-[0_8px_30px_rgb(59,130,246,0.15)] group transition-all hover:scale-[1.01]">
                    
                    <!-- Pulsing Glow Effect -->
                    <div class="absolute top-0 right-0 p-3">
                        <span class="relative flex h-3 w-3">
                          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                          <span class="relative inline-flex rounded-full h-3 w-3 bg-blue-500"></span>
                        </span>
                    </div>

                    <div class="p-5 relative z-10">
                        <!-- Client Name -->
                        <div class="pr-8 mb-4">
                            <h4 class="text-lg font-bold text-white leading-tight" x-text="route.client_name"></h4>
                            <p class="text-xs text-blue-400 mt-1 font-medium">Iniciado às <span x-text="route.start_time"></span></p>
                        </div>

                        <!-- Main Stats Grid -->
                        <div class="grid grid-cols-2 gap-3 mb-4">
                            <!-- Timer Card -->
                            <div class="bg-slate-950/50 rounded-xl p-3 border border-slate-800 flex flex-col items-center justify-center">
                                <span class="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Tempo</span>
                                <div class="text-2xl font-mono font-bold text-white tracking-widest mt-1">
                                    <span x-text="getElapsed(route.start_time)">00:00:00</span>
                                </div>
                            </div>

                            <!-- Weight Card -->
                            <div class="bg-slate-950/50 rounded-xl p-3 border border-slate-800 flex flex-col items-center justify-center">
                                <span class="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Peso</span>
                                <div class="text-xl font-mono font-bold text-emerald-400 mt-1 flex items-baseline gap-1">
                                    <span x-text="route.tonnage"></span> <span class="text-xs text-emerald-600">kg</span>
                                </div>
                            </div>
                        </div>

                        <!-- Action Button (Full Width) -->
                        <button @click="finishRoute(route.id, index)" 
                            :disabled="finishLoading === route.id"
                            class="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold flex items-center justify-center gap-2 shadow-lg shadow-blue-900/30 transition-all active:scale-[0.98]">
                            <span x-show="finishLoading !== route.id">
                                <i data-lucide="check-circle-2" width="18"></i> Concluir Atividade
                            </span>
                            <span x-show="finishLoading === route.id" class="animate-spin">
                                <i data-lucide="loader-2" width="18"></i> Processando...
                            </span>
                        </button>
                    </div>
                </div>
            </template>
        </div>

        <!-- HISTORY / COMPLETED ROUTES -->
        <div x-show="completedRoutes.length > 0" class="mt-6">
            <div class="flex justify-between items-center px-1 mb-3">
                 <h3 class="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Histórico Hoje</h3>
                 <span class="text-xs font-medium text-slate-600" x-text="completedRoutes.length + ' Concluídas'"></span>
            </div>
            
            <div class="glass-panel overflow-hidden">
                <div class="divide-y divide-slate-800/50">
                    <template x-for="route in completedRoutes" :key="route.id">
                        <div class="p-4 hover:bg-slate-800/30 transition-colors">
                            <div class="flex justify-between items-start">
                                <div>
                                    <h5 class="text-sm font-semibold text-slate-300" x-text="route.client_name"></h5>
                                    <div class="flex items-center gap-3 mt-1.5">
                                        <div class="flex items-center gap-1 text-[10px] text-slate-500">
                                            <i data-lucide="clock" width="10"></i>
                                            <span x-text="route.start_time + ' - ' + route.end_time"></span>
                                        </div>
                                        <div class="flex items-center gap-1 text-[10px] text-slate-400">
                                            <i data-lucide="timer" width="10"></i>
                                            <span x-text="route.duration"></span>
                                        </div>
                                    </div>
                                </div>
                                <div class="text-right">
                                    <div class="text-sm font-mono font-bold text-emerald-500" x-text="route.tonnage + ' kg'"></div>
                                    <div class="text-[10px] font-mono text-slate-500 mt-1" x-text="route.performance"></div>
                                </div>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </div>

    </div>

    <!-- ACTIONS Area -->
    <div class="grid-actions grid grid-cols-2 gap-4 mt-6">
        <!-- Start Routine -->
        <button @click="openStartModal()" class="glass-panel action-card w-full group hover:border-green-500/40 transform hover:-translate-y-1 transition-all duration-300 py-3">
            <div class="p-3 mb-2 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/30 group-hover:shadow-green-500/50 transition-shadow w-fit mx-auto">
                <i data-lucide="plus" fill="currentColor" class="w-6 h-6"></i>
            </div>
            <span class="font-bold text-sm text-green-400 group-hover:text-green-300 block text-center">Nova Carga</span>
        </button>

        <!-- Stop Routine -->
        <button @click="openStopModal()" class="glass-panel action-card w-full group hover:border-red-500/40 transform hover:-translate-y-1 transition-all duration-300 py-3">
            <div class="p-3 mb-2 rounded-xl bg-gradient-to-br from-red-500 to-rose-600 text-white shadow-lg shadow-red-500/30 group-hover:shadow-red-500/50 transition-shadow w-fit mx-auto">
                <i data-lucide="power" fill="currentColor" class="w-6 h-6"></i>
            </div>
            <span class="font-bold text-sm text-red-500 group-hover:text-red-400 block text-center">Encerrar Dia</span>
        </button>
    </div>

    <!-- STATS Area -->
    <div class="grid-stats glass-panel p-6 relative overflow-hidden min-h-[220px] mt-4">
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
            completedRoutes: [],
            allocations: [{ client_id: '', weight: '' }],
            now: new Date().getTime(),
            timer: null,

            init() {
                // Initialize Data
                this.clientsList = [
                    {% for c in clients %}
                        { id: {{ c.id }}, name: "{{ c.name }}" },
                    {% endfor %}
                ];
                
                this.activeRoutes = {{ active_routes | safe }};
                this.completedRoutes = {{ completed_routes | safe }};
                
                this.initChart();
                
                // Start Timer Interval
                this.timer = setInterval(() => {
                    this.now = new Date().getTime();
                }, 1000);
            },
            
            getElapsed(startTimeStr) {
                if (!startTimeStr) return "00:00:00";
                
                // Parse HH:MM to Today Date
                const now = new Date();
                const [hours, minutes] = startTimeStr.split(':').map(Number);
                const startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hours, minutes, 0);
                
                // Diff in ms
                // Use this.now to trigger reactivity
                let diff = this.now - startDate.getTime();
                if (diff < 0) diff = 0; // protection if clock mismatch
                
                const totalSeconds = Math.floor(diff / 1000);
                const h = Math.floor(totalSeconds / 3600);
                const m = Math.floor((totalSeconds % 3600) / 60);
                const s = totalSeconds % 60;
                
                // Format 00:00:00
                const pad = (n) => n.toString().padStart(2, '0');
                if (h > 0) {
                    return `${pad(h)}:${pad(m)}:${pad(s)}`;
                } else {
                    return `${pad(m)}:${pad(s)}`;
                }
            },

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
                         // Instead of just removing, we might want to reload to see it in history
                         // But for smooth UX, removed from active. History updates on reload.
                         // Or we can move it to completedRoutes?
                         // Let's reload to ensure data consistency
                         window.location.reload();
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
                                label: 'min/Ton',
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
"""

with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("SUCCESS: Dashboard file corrected overwritten.")
