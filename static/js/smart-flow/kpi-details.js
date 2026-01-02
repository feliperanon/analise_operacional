/**
 * KPI Details Module - Smart Flow
 * Modal para mostrar detalhes de KPIs (colaboradores por status)
 */

const KPIDetails = {
    show(type) {
        const { employees, currentShift, currentDate, routines } = Store.state;

        // Filtrar colaboradores do turno atual
        const shiftEmps = employees.filter(e => {
            const empShift = e.work_shift ?? e.shift ?? null;
            if (!empShift) return false;
            return empShift.toLowerCase() === currentShift.toLowerCase();
        });

        // Se for 'present', mostrar TODAS as rotinas agrupadas
        if (type === 'present') {
            this.renderAllRoutinesModal(shiftEmps, currentShift, currentDate, routines);
            return;
        }

        // Filtrar por tipo de status específico
        let filtered = [];
        let title = '';
        let color = 'blue';

        if (type === 'vacation') {
            filtered = shiftEmps.filter(e => {
                const routine = routines[e.id];
                const status = routine || e.status || 'active';
                return status.toLowerCase() === 'vacation' || status.toLowerCase() === 'férias' || status.toLowerCase() === 'ferias';
            });
            title = 'Colaboradores em Férias';
            color = 'orange';
        } else if (type === 'away') {
            filtered = shiftEmps.filter(e => {
                const routine = routines[e.id];
                const status = routine || e.status || 'active';
                return status.toLowerCase() === 'away' || status.toLowerCase() === 'afastado';
            });
            title = 'Colaboradores Afastados';
            color = 'indigo';
        } else if (type === 'sick') {
            filtered = shiftEmps.filter(e => {
                const routine = routines[e.id];
                const status = routine || e.status || 'active';
                return status.toLowerCase() === 'sick' || status.toLowerCase() === 'atestado';
            });
            title = 'Colaboradores com Atestado';
            color = 'amber';
        } else if (type === 'missing') {
            filtered = shiftEmps.filter(e => {
                const routine = routines[e.id];
                const status = routine || e.status || 'active';
                return status.toLowerCase() === 'absent' || status.toLowerCase() === 'falta';
            });
            title = 'Colaboradores em Falta';
            color = 'rose';
        } else if (type === 'gap') {
            // Buscar TODOS os colaboradores do turno (incluindo demitidos)
            const allShiftEmps = Store.state.employees.filter(e => {
                const empShift = e.work_shift ?? e.shift ?? null;
                if (!empShift) return false;
                return empShift.toLowerCase() === currentShift.toLowerCase();
            });

            filtered = allShiftEmps.filter(e => {
                const status = (e.status || 'active').toLowerCase();
                return status === 'fired' || status === 'demitido';
            });
            title = 'Vagas em Aberto (Demitidos)';
            color = 'red';
        }

        this.renderModal(title, filtered, color, currentShift, currentDate);
    },

    renderModal(title, employees, color, shift, date) {
        // Remover modal existente se houver
        const existing = document.getElementById('kpi-details-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'kpi-details-modal';
        modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';

        modal.innerHTML = `
            <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col m-4">
                
                <!-- Header -->
                <div class="flex items-center justify-between p-6 border-b border-slate-700 bg-slate-900/50">
                    <div>
                        <h2 class="text-2xl font-bold text-white">${title}</h2>
                        <p class="text-sm text-slate-400">${shift} • ${date} • ${employees.length} colaborador${employees.length !== 1 ? 'es' : ''}</p>
                    </div>
                    <button onclick="KPIDetails.close()" class="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-700 transition">
                        <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-6">
                    ${employees.length === 0 ? `
                        <div class="text-center py-12">
                            <p class="text-slate-500">Nenhum colaborador encontrado</p>
                        </div>
                    ` : `
                        <div class="space-y-2">
                            ${employees.map(emp => {
            // Traduzir status
            const statusMap = {
                'active': 'Ativo',
                'ativo': 'Ativo',
                'present': 'Presente',
                'presente': 'Presente',
                'vacation': 'Férias',
                'férias': 'Férias',
                'ferias': 'Férias',
                'away': 'Afastado',
                'afastado': 'Afastado',
                'sick': 'Atestado',
                'atestado': 'Atestado',
                'absent': 'Falta',
                'falta': 'Falta'
            };
            const statusLower = (emp.status || 'active').toLowerCase();
            const statusText = statusMap[statusLower] || emp.status || 'Ativo';

            return `
                                <div class="bg-slate-900 rounded-lg p-4 border border-slate-700 hover:border-${color}-500 transition">
                                    <div class="flex items-center justify-between">
                                        <div class="flex-1">
                                            <p class="text-sm font-bold text-white">${emp.name}</p>
                                            <p class="text-xs text-slate-400">${emp.role || 'Sem cargo'} • ID: ${emp.id}</p>
                                        </div>
                                        <div class="text-right">
                                            <span class="px-2 py-1 rounded-full text-xs font-bold bg-${color}-600/20 text-${color}-400">
                                                ${statusText}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            `}).join('')}
                        </div>
                    `}
                </div>

                <!-- Footer -->
                <div class="p-4 border-t border-slate-700 bg-slate-900/50 flex justify-end">
                    <button onclick="KPIDetails.close()" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition text-sm font-bold">
                        Fechar
                    </button>
                </div>

            </div>
        `;

        document.body.appendChild(modal);

        // Fechar ao clicar fora
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.close();
            }
        });
    },

    renderAllRoutinesModal(employees, shift, date, routines) {
        // Agrupar colaboradores por rotina
        const groups = {
            present: [],
            vacation: [],
            sick: [],
            away: [],
            absent: [],
            dayoff: []
        };

        employees.forEach(emp => {
            const routine = routines[emp.id];
            const status = routine || emp.status || 'active';
            const normalized = status.toLowerCase();

            if (normalized === 'present' || (!routine && (normalized === 'active' || normalized === 'ativo'))) {
                groups.present.push(emp);
            } else if (normalized === 'vacation' || normalized === 'férias' || normalized === 'ferias') {
                groups.vacation.push(emp);
            } else if (normalized === 'sick' || normalized === 'atestado') {
                groups.sick.push(emp);
            } else if (normalized === 'away' || normalized === 'afastado') {
                groups.away.push(emp);
            } else if (normalized === 'absent' || normalized === 'falta') {
                groups.absent.push(emp);
            } else if (normalized === 'dayoff' || normalized === 'folga') {
                groups.dayoff.push(emp);
            }
        });

        const total = employees.length;
        const present = groups.present.length;
        const percent = total > 0 ? Math.round((present / total) * 100) : 0;

        // Remover modal existente
        const existing = document.getElementById('kpi-details-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'kpi-details-modal';
        modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';

        modal.innerHTML = `
            <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col m-4">
                
                <!-- Header -->
                <div class="flex items-center justify-between p-6 border-b border-slate-700 bg-slate-900/50">
                    <div>
                        <h2 class="text-2xl font-bold text-white">Detalhamento de Presença</h2>
                        <p class="text-sm text-slate-400">${shift} • ${date} • ${total} colaboradores</p>
                        <p class="text-xs text-emerald-400 font-bold mt-1">${present} presentes (${percent}%) • ${total - present} ausentes</p>
                    </div>
                    <button onclick="KPIDetails.close()" class="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-700 transition">
                        <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-6 space-y-4">
                    ${this.renderRoutineGroup('✓ Presentes', groups.present, 'emerald', true)}
                    ${this.renderRoutineGroup('🏖️ Férias', groups.vacation, 'orange', false)}
                    ${this.renderRoutineGroup('🏥 Atestado', groups.sick, 'amber', false)}
                    ${this.renderRoutineGroup('🚫 Afastado', groups.away, 'indigo', false)}
                    ${this.renderRoutineGroup('📅 Folga', groups.dayoff, 'blue', false)}
                    ${this.renderRoutineGroup('✗ Falta', groups.absent, 'rose', false)}
                </div>

                <!-- Footer -->
                <div class="p-4 border-t border-slate-700 bg-slate-900/50 flex justify-between items-center">
                    <p class="text-xs text-slate-400">
                        <span class="text-emerald-400 font-bold">Presentes</span> contam para presença • 
                        <span class="text-orange-400">Férias</span>, 
                        <span class="text-amber-400">Atestado</span>, 
                        <span class="text-indigo-400">Afastado</span>, 
                        <span class="text-blue-400">Folga</span> e 
                        <span class="text-rose-400">Falta</span> não contam
                    </p>
                    <button onclick="KPIDetails.close()" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition text-sm font-bold">
                        Fechar
                    </button>
                </div>

            </div>
        `;

        document.body.appendChild(modal);

        // Fechar ao clicar fora
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.close();
            }
        });
    },

    renderRoutineGroup(title, employees, color, isPresent) {
        if (employees.length === 0) return '';

        return `
            <div class="bg-slate-900/50 rounded-xl border border-slate-700 p-4">
                <div class="flex items-center justify-between mb-3">
                    <h3 class="text-sm font-bold text-${color}-400">${title}</h3>
                    <span class="text-xs px-2 py-1 rounded-full bg-${color}-600/20 text-${color}-400 font-bold">
                        ${employees.length} ${employees.length === 1 ? 'colaborador' : 'colaboradores'}
                    </span>
                </div>
                <div class="space-y-2">
                    ${employees.map(emp => `
                        <div class="bg-slate-800 rounded-lg p-3 border border-slate-700 hover:border-${color}-500 transition">
                            <div class="flex items-center justify-between">
                                <div class="flex-1">
                                    <p class="text-xs font-bold text-white">${emp.name}</p>
                                    <p class="text-[10px] text-slate-400">${emp.role || 'Sem cargo'} • ID: ${emp.id}</p>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    },

    close() {
        const modal = document.getElementById('kpi-details-modal');
        if (modal) modal.remove();
    }
};

window.KPIDetails = KPIDetails;
