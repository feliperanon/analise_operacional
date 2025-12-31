/**
 * Render Module - Smart Flow V3
 * Responsável por desenhar a interface hierárquica baseada no Estado.
 */

const Render = {
    init() {
        // Inicializa elementos DOM cacheados
        this.els = {
            flowGrid: document.getElementById('flow-grid'),
            kpiContainer: document.getElementById('kpi-strip')
        };
    },

    // Função Principal de Renderização
    update(state) {
        this.renderKPIs(state.kpis);
        this.renderSectors(state);
        this.updateHeader(state);
    },

    updateHeader(state) {
        // Atualizar Botões de Turno
        const buttons = document.querySelectorAll('#shift-controls button');
        buttons.forEach(btn => {
            const shift = btn.dataset.shift;
            if (shift === state.currentShift) {
                btn.className = "px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all bg-blue-600 text-white shadow-md";
            } else {
                btn.className = "px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all text-slate-500 hover:text-slate-300 hover:bg-slate-700/50";
            }
        });

        // Atualizar Link do Relatório
        const link = document.getElementById('report-link');
        if (link) {
            link.href = `/routine/report?date=${state.currentDate}&shift=${state.currentShift}`;
        }

        // Atualizar Date Picker
        const datePicker = document.getElementById('date-picker');
        if (datePicker) {
            datePicker.value = state.currentDate;
        }
    },

    renderKPIs(kpis) {
        if (!kpis) return;

        const setText = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.innerText = val;
        };

        setText('total-present', kpis.present || 0);
        setText('total-target-kpi', kpis.target || 0);
        setText('present-percent', `${kpis.percent || 0}%`);
        setText('total-gap', kpis.gap || 0);
        setText('total-sick', kpis.sick || 0);
        setText('total-missing', kpis.missing || 0);
        setText('total-vacation', kpis.vacation || 0);
        setText('total-away', kpis.away || 0);
        setText('total-tonnage', (kpis.tonnage || 0).toLocaleString('pt-BR') + ' kg');
        setText('prod-per-person', (kpis.productivity || 0).toLocaleString('pt-BR'));
    },

    renderSectors(state) {
        const container = document.getElementById('flow-grid');
        if (!container) return;

        container.innerHTML = '';

        if (!state.sectors || state.sectors.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center text-slate-500 mt-10">
                    <p class="mb-4">Nenhum setor configurado para este turno.</p>
                    <button onclick="createSector()" 
                        class="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg font-bold">
                        Criar Primeiro Setor
                    </button>
                </div>
            `;
            return;
        }

        state.sectors.forEach(sector => {
            const sectorCard = this.createSectorCard(sector, state);
            container.appendChild(sectorCard);
        });
    },

    createSectorCard(sector, state) {
        const card = document.createElement('div');
        card.className = 'bg-slate-800 rounded-2xl border border-slate-700 p-4 hover:border-slate-600 transition';

        // Calcular total de colaboradores alocados neste setor
        const sectorEmployeeCount = this.countSectorEmployees(sector, state.allocations);

        // Header do Setor
        const header = document.createElement('div');
        header.className = 'flex items-center justify-between mb-4';
        header.innerHTML = `
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-${sector.color}-600/20 flex items-center justify-center">
                    <span class="text-${sector.color}-400 text-xl">📦</span>
                </div>
                <div>
                    <h3 class="text-lg font-bold text-white">${sector.name}</h3>
                    <p class="text-xs text-slate-400">
                        <span id="sector-${sector.id}-count">${sectorEmployeeCount}</span> / ${sector.max_employees} colaboradores
                    </p>
                </div>
            </div>
            <div class="flex gap-2">
                <button onclick="SectorsCRUD.openEditSector(${sector.id}, '${sector.name}', ${sector.max_employees}, '${sector.color}')"
                    class="text-slate-400 hover:text-white p-2" title="Editar Setor">
                    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button onclick="SectorsCRUD.deleteSector(${sector.id}, '${sector.name}')"
                    class="text-red-400 hover:text-red-300 p-2" title="Excluir Setor">
                    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
                <button onclick="SectorsCRUD.openCreateSubSector(${sector.id})"
                    class="text-blue-400 hover:text-blue-300 p-2" title="Adicionar Sub-setor">
                    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <line x1="12" y1="5" x2="12" y2="19"></line>
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                </button>
            </div>
        `;
        card.appendChild(header);

        // Sub-setores
        const subsectorsContainer = document.createElement('div');
        subsectorsContainer.className = 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3';

        if (sector.subsectors && sector.subsectors.length > 0) {
            sector.subsectors.forEach(subsector => {
                const subsectorCard = this.createSubSectorCard(sector, subsector, state);
                subsectorsContainer.appendChild(subsectorCard);
            });
        } else {
            subsectorsContainer.innerHTML = `
                <div class="col-span-full text-center text-slate-500 py-4 text-sm">
                    Nenhum sub-setor criado. Clique no + acima para adicionar.
                </div>
            `;
        }

        card.appendChild(subsectorsContainer);
        return card;
    },

    createSubSectorCard(sector, subsector, state) {
        const card = document.createElement('div');
        card.className = 'bg-slate-900 rounded-xl border border-slate-700 p-3 min-h-[200px] flex flex-col';
        card.dataset.subsectorId = subsector.id;
        card.dataset.maxEmployees = subsector.max_employees;

        // Filtrar colaboradores alocados neste sub-setor
        const allocatedEmployees = this.getSubsectorEmployees(subsector.id, state);
        const currentCount = allocatedEmployees.length;

        // Header do Sub-setor
        const header = document.createElement('div');
        header.className = 'flex items-center justify-between mb-3 pb-2 border-b border-slate-700';
        header.innerHTML = `
            <div>
                <h4 class="text-sm font-bold text-white">${subsector.name}</h4>
                <p class="text-xs text-slate-500">
                    <span class="subsector-count">${currentCount}</span> / ${subsector.max_employees}
                </p>
            </div>
            <div class="flex gap-1">
                <button onclick="SectorsCRUD.openEditSubSector(${subsector.id}, ${sector.id}, '${subsector.name}', ${subsector.max_employees})"
                    class="text-slate-500 hover:text-white p-1" title="Editar">
                    <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button onclick="SectorsCRUD.deleteSubSector(${subsector.id}, '${subsector.name}')"
                    class="text-red-500 hover:text-red-300 p-1" title="Excluir">
                    <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `;
        card.appendChild(header);

        // Lista de colaboradores alocados
        const employeesList = document.createElement('div');
        employeesList.className = 'space-y-2 employees-list flex-1 overflow-y-auto';

        if (allocatedEmployees.length === 0) {
            employeesList.innerHTML = `
                <div class="text-xs text-slate-600 text-center py-4">
                    Arraste colaboradores aqui
                </div>
            `;
        } else {
            allocatedEmployees.forEach(emp => {
                const routine = state.routines[emp.id] || 'present';
                const empCard = this.createEmployeeCard(emp, routine);
                employeesList.appendChild(empCard);
            });
        }

        card.appendChild(employeesList);

        // Tornar drop zone
        this.makeDropZone(card, subsector.id);

        return card;
    },

    createEmployeeCard(employee, routine) {
        const card = document.createElement('div');
        card.className = 'bg-slate-800 rounded-lg p-2 border border-slate-700 hover:border-slate-600 transition cursor-move';
        card.draggable = true;
        card.dataset.employeeId = employee.id;

        const statusColors = {
            present: 'emerald',
            absent: 'red',
            sick: 'amber',
            vacation: 'orange',
            away: 'indigo'
        };

        const statusLabels = {
            present: 'Presente',
            absent: 'Falta',
            sick: 'Atestado',
            vacation: 'Férias',
            away: 'Afastado'
        };

        const color = statusColors[routine] || 'slate';

        card.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-white truncate">${employee.name}</p>
                    <p class="text-xs text-slate-400 truncate">${employee.role || 'Colaborador'}</p>
                </div>
                <div class="flex-shrink-0">
                    <select onchange="updateRoutine(${employee.id}, this.value)" 
                        class="text-xs bg-${color}-600/20 text-${color}-400 border border-${color}-600/30 rounded px-2 py-1 cursor-pointer">
                        <option value="present" ${routine === 'present' ? 'selected' : ''}>✓ Presente</option>
                        <option value="absent" ${routine === 'absent' ? 'selected' : ''}>✗ Falta</option>
                        <option value="sick" ${routine === 'sick' ? 'selected' : ''}>🏥 Atestado</option>
                        <option value="vacation" ${routine === 'vacation' ? 'selected' : ''}>🏖️ Férias</option>
                        <option value="away" ${routine === 'away' ? 'selected' : ''}>🚫 Afastado</option>
                    </select>
                </div>
            </div>
        `;

        // Drag events
        card.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('employeeId', employee.id);
            card.classList.add('opacity-50');
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('opacity-50');
        });

        return card;
    },

    makeDropZone(element, subsectorId) {
        element.addEventListener('dragover', (e) => {
            e.preventDefault();
            element.classList.add('ring-2', 'ring-blue-500');
        });

        element.addEventListener('dragleave', () => {
            element.classList.remove('ring-2', 'ring-blue-500');
        });

        element.addEventListener('drop', (e) => {
            e.preventDefault();
            element.classList.remove('ring-2', 'ring-blue-500');

            const employeeId = e.dataTransfer.getData('employeeId');
            const maxEmployees = parseInt(element.dataset.maxEmployees);
            const currentCount = element.querySelectorAll('.employees-list > div').length;

            if (currentCount >= maxEmployees) {
                alert('Limite de vagas atingido para este sub-setor');
                return;
            }

            // Atualizar Store
            Store.allocateEmployee(employeeId, subsectorId);
        });
    },

    // Helpers
    countSectorEmployees(sector, allocations) {
        if (!sector.subsectors) return 0;

        let count = 0;
        sector.subsectors.forEach(subsector => {
            Object.values(allocations).forEach(subsectorId => {
                if (subsectorId === subsector.id) count++;
            });
        });
        return count;
    },

    getSubsectorEmployees(subsectorId, state) {
        const employees = [];
        Object.entries(state.allocations).forEach(([empId, allocSubId]) => {
            if (allocSubId === subsectorId) {
                const emp = state.employees.find(e => e.id == empId);
                if (emp) employees.push(emp);
            }
        });
        return employees;
    }
};

// Expor globalmente
window.Render = Render;

// Função global para atualizar rotina
window.updateRoutine = (empId, routine) => {
    Store.updateRoutine(empId, routine);
};
