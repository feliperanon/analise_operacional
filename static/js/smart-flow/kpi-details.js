/**
 * KPI Details Module - Smart Flow
 * Modal para mostrar detalhes de KPIs (colaboradores por status)
 */

const KPIDetails = {
    show(type) {
        const { employees, currentShift, currentDate, routines, allocations } = Store.state;

        // IMPORTANTE: Usar apenas colaboradores ALOCADOS (consistência com KPI strip)
        // Antes: contava todos do turno. Agora: apenas alocados.
        const allocatedEmpIds = Object.keys(allocations);

        const shiftEmps = employees.filter(e => {
            // Verificar se está alocado
            if (!allocatedEmpIds.includes(String(e.id))) return false;

            // Excluir demitidos
            const status = (e.status || 'active').toLowerCase();
            return status !== 'fired' && status !== 'demitido';
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
        } else if (type === 'unavailable') {
            const allShift = employees.filter(e => {
                const empShift = e.work_shift ?? e.shift ?? null;
                if (!empShift) return false;
                return empShift.toLowerCase() === currentShift.toLowerCase();
            });
            filtered = allShift.filter(e => {
                const st = (e.status || 'active').toLowerCase();
                if (st === 'fired' || st === 'demitido') return false;
                const routine = routines[e.id];
                const normalized = routine ? String(routine).toLowerCase() : null;
                if (normalized === 'dayoff' || normalized === 'folga') return true;
                if (normalized === 'absent' || normalized === 'falta') return true;
                if (normalized === 'sick' || normalized === 'atestado') return true;
                if (normalized === 'vacation' || normalized === 'férias' || normalized === 'ferias') return true;
                if (normalized === 'away' || normalized === 'afastado') return true;
                if (st === 'vacation' || st === 'férias' || st === 'ferias') return true;
                if (st === 'away' || st === 'afastado') return true;
                if (st === 'sick' || st === 'atestado') return true;
                return false;
            });
            title = 'Indisponíveis no turno';
            color = 'amber';
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
            <div class="sys-card sys-card--surface m-4 flex w-full max-w-2xl max-h-[80vh] flex-col overflow-hidden shadow-xl border border-slate-200/80 dark:border-slate-700">
                
                <!-- Header -->
                <div class="flex items-center justify-between border-b border-slate-200/80 bg-slate-50/80 p-5 dark:border-slate-700 dark:bg-slate-800/50">
                    <div>
                        <h2 class="text-xl font-bold text-slate-900 dark:text-white">${title}</h2>
                        <p class="text-sm text-slate-500 dark:text-slate-400">${shift} • ${date} • ${employees.length} colaborador${employees.length !== 1 ? 'es' : ''}</p>
                    </div>
                    <button type="button" onclick="KPIDetails.close()" class="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-700 dark:hover:text-white">
                        <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-5">
                    ${employees.length === 0 ? `
                        <div class="sys-empty-state py-10 text-center">
                            <p class="text-sm text-slate-600 dark:text-slate-300">Nenhum colaborador encontrado</p>
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
                                <div class="rounded-lg border border-slate-200/80 bg-white p-3 transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800/40">
                                    <div class="flex items-center justify-between gap-2">
                                        <div class="min-w-0 flex-1">
                                            <p class="truncate text-sm font-semibold text-slate-900 dark:text-white">${(emp.name || '').toUpperCase()}</p>
                                            <p class="text-xs text-slate-500">${emp.role || 'Sem cargo'} • Mat.: ${emp.id}</p>
                                        </div>
                                        <div class="shrink-0 text-right">
                                            <span class="sys-badge inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200">
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
                <div class="flex justify-end border-t border-slate-200/80 bg-slate-50/50 p-3 dark:border-slate-700 dark:bg-slate-800/30">
                    <button type="button" onclick="KPIDetails.close()" class="sys-btn sys-btn--secondary text-sm">
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
                                    <p class="text-xs font-bold text-white">${(emp.name || '').toUpperCase()}</p>
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
