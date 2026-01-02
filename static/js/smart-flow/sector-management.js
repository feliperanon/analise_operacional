/**
 * Sector Management Modal - Smart Flow
 * Modal completo para gerenciar colaboradores e sub-setores de um setor
 */

const SectorManagement = {
    currentSectorId: null,
    searchTerm: '',

    open(sectorId) {
        this.currentSectorId = sectorId;
        this.searchTerm = '';

        const sector = Store.state.sectors.find(s => s.id === sectorId);
        if (!sector) {
            console.error('Sector not found:', sectorId);
            return;
        }

        console.log('Opening sector management for:', sector.name);

        // Criar e mostrar modal
        this.render(sector);

        const modal = document.getElementById('sector-management-modal');
        if (modal) {
            modal.classList.remove('hidden');
        }
    },

    close() {
        const modal = document.getElementById('sector-management-modal');
        if (modal) {
            modal.classList.add('hidden');
        }
        this.currentSectorId = null;
        this.searchTerm = '';
    },

    render(sector) {
        const state = Store.state;

        // Obter colaboradores alocados neste setor
        const allocatedEmployees = this.getAllocatedEmployees(sector, state);

        // Obter colaboradores disponíveis (não alocados, do turno correto)
        const availableEmployees = this.getAvailableEmployees(state);

        const modalHTML = `
            <div id="sector-management-modal" class="fixed inset-0 z-50 hidden">
                <div class="absolute inset-0 bg-slate-900/90 backdrop-blur-sm" onclick="SectorManagement.close()"></div>
                <div class="relative z-10 flex min-h-full items-center justify-center p-4">
                    <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
                        
                        <!-- Header -->
                        <div class="flex items-center justify-between p-6 border-b border-slate-700 bg-slate-900/50">
                            <div class="flex items-center gap-4">
                                <div class="w-12 h-12 rounded-xl bg-${sector.color}-600/20 flex items-center justify-center">
                                    <span class="text-${sector.color}-400 text-2xl">📦</span>
                                </div>
                                <div>
                                    <h2 class="text-2xl font-bold text-white">${sector.name}</h2>
                                    <p class="text-sm text-slate-400">Gestão de Colaboradores e Sub-setores</p>
                                </div>
                            </div>
                            <button onclick="SectorManagement.close()" class="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-700 transition">
                                <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path d="M6 18L18 6M6 6l12 12"></path>
                                </svg>
                            </button>
                        </div>

                        <!-- Content -->
                        <div class="flex-1 overflow-y-auto p-6">
                            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                
                                <!-- Left: Sub-setores e Alocados -->
                                <div class="space-y-6">
                                    <!-- Sub-setores Header -->
                                    <div class="flex items-center justify-between">
                                        <h3 class="text-lg font-bold text-white">Sub-setores</h3>
                                        <button onclick="SectorManagement.addSubsectorInline(${sector.id})"
                                            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold flex items-center gap-1.5">
                                            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                                <path d="M12 4v16m8-8H4"></path>
                                            </svg>
                                            Novo Sub-setor
                                        </button>
                                    </div>

                                    <!-- Sub-setores List -->
                                    <div class="space-y-3" id="subsectors-list">
                                        ${this.renderSubsectors(sector, state)}
                                    </div>
                                </div>

                                <!-- Right: Colaboradores Disponíveis -->
                                <div class="space-y-6">
                                    <!-- Search -->
                                    <div>
                                        <h3 class="text-lg font-bold text-white mb-3">Colaboradores Disponíveis</h3>
                                        <div class="relative">
                                            <input type="text" 
                                                id="employee-search" 
                                                placeholder="Buscar colaborador..." 
                                                oninput="SectorManagement.handleSearch(this.value)"
                                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 pl-10 text-white focus:ring-2 focus:ring-blue-500 text-sm">
                                            <svg class="absolute left-3 top-2.5 w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                                            </svg>
                                        </div>
                                    </div>

                                    <!-- Available Employees List -->
                                    <div class="space-y-2 max-h-[500px] overflow-y-auto" id="available-employees-list">
                                        ${this.renderAvailableEmployees(availableEmployees)}
                                    </div>
                                </div>

                            </div>
                        </div>

                        <!-- Footer -->
                        <div class="p-4 border-t border-slate-700 bg-slate-900/50 flex justify-end gap-2">
                            <button onclick="SectorManagement.close()" 
                                class="px-4 py-2 text-sm text-slate-300 hover:text-white rounded-lg hover:bg-slate-700 transition">
                                Fechar
                            </button>
                        </div>

                    </div>
                </div>
            </div>
        `;

        // Remover modal antigo se existir
        const oldModal = document.getElementById('sector-management-modal');
        if (oldModal) {
            oldModal.remove();
        }

        // Adicionar novo modal ao body
        document.body.insertAdjacentHTML('beforeend', modalHTML);
    },

    renderSubsectors(sector, state) {
        if (!sector.subsectors || sector.subsectors.length === 0) {
            return `
                <div class="text-center text-slate-500 py-8 bg-slate-900/50 rounded-xl border border-slate-700">
                    <p class="text-sm">Nenhum sub-setor criado.</p>
                    <p class="text-xs mt-1">Clique em "Novo Sub-setor" para começar.</p>
                </div>
            `;
        }

        return sector.subsectors.map(subsector => {
            const allocatedEmployees = Render.getSubsectorEmployees(subsector.id, state);
            const percentage = subsector.max_employees > 0 ? Math.round((allocatedEmployees.length / subsector.max_employees) * 100) : 0;

            return `
                <div class="bg-slate-900 rounded-xl border border-slate-700 p-4" data-subsector-id="${subsector.id}">
                    <!-- Subsector Header -->
                    <div class="flex items-center justify-between mb-3">
                        <div class="flex-1">
                            <h4 class="text-sm font-bold text-white">${subsector.name}</h4>
                            <p class="text-xs text-slate-500">
                                ${allocatedEmployees.length} / ${subsector.max_employees} colaboradores
                            </p>
                        </div>
                        <div class="flex gap-1">
                            <button onclick="SectorManagement.editSubsectorInline(${subsector.id}, ${sector.id}, '${subsector.name}', ${subsector.max_employees})"
                                class="text-slate-500 hover:text-white p-1.5 rounded hover:bg-slate-700 transition" title="Editar">
                                <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                                </svg>
                            </button>
                            <button onclick="SectorsCRUD.deleteSubSector(${subsector.id}, '${subsector.name}')"
                                class="text-slate-500 hover:text-red-400 p-1.5 rounded hover:bg-slate-700 transition" title="Excluir">
                                <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden mb-3">
                        <div class="bg-${percentage >= 80 ? 'emerald' : percentage >= 50 ? 'amber' : 'red'}-500 h-full transition-all" style="width: ${percentage}%"></div>
                    </div>

                    <!-- Allocated Employees -->
                    <div class="space-y-1.5">
                        ${allocatedEmployees.length === 0 ?
                    '<p class="text-xs text-slate-600 text-center py-2">Nenhum colaborador alocado</p>' :
                    allocatedEmployees.map(emp => {
                        const routine = state.routines[emp.id] || 'present';
                        return this.renderAllocatedEmployee(emp, routine, subsector.id);
                    }).join('')
                }
                    </div>
                </div>
            `;
        }).join('');
    },

    renderAllocatedEmployee(emp, routine, subsectorId) {
        const statusColors = {
            present: 'emerald',
            absent: 'red',
            sick: 'amber',
            vacation: 'orange',
            away: 'indigo',
            dayoff: 'blue'
        };

        const statusLabels = {
            present: '✓',
            absent: '✗',
            sick: '🏥',
            vacation: '🏖️',
            away: '🚫',
            dayoff: '📅'
        };

        const color = statusColors[routine] || 'slate';

        return `
            <div class="bg-slate-800 rounded-lg p-2 border border-slate-700 flex items-center justify-between gap-2 group">
                <div class="flex-1 min-w-0">
                    <p class="text-xs font-medium text-white truncate">${emp.name}</p>
                    <p class="text-[10px] text-slate-500 truncate">${emp.role || 'Colaborador'}</p>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="text-xs px-2 py-0.5 rounded bg-${color}-600/20 text-${color}-400 border border-${color}-600/30">
                        ${statusLabels[routine]}
                    </span>
                    
                    <!-- Dropdown Rotinas -->
                    <div class="relative">
                        <button onclick="SectorManagement.toggleRoutineMenu(${emp.id})" 
                            class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-white p-1 rounded hover:bg-slate-700 transition" title="Alterar rotina">
                            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                <circle cx="12" cy="12" r="1"></circle>
                                <circle cx="12" cy="5" r="1"></circle>
                                <circle cx="12" cy="19" r="1"></circle>
                            </svg>
                        </button>
                        <div id="routine-menu-${emp.id}" class="hidden absolute right-0 mt-1 w-48 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50">
                            <div class="py-1">
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'present')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span class="text-emerald-400">✓</span> Presente
                                </button>
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'vacation')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span>🏖️</span> Férias
                                </button>
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'sick')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span>🏥</span> Atestado
                                </button>
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'away')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span>🚫</span> Afastado
                                </button>
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'absent')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span class="text-red-400">✗</span> Falta
                                </button>
                                <button onclick="SectorManagement.setRoutine(${emp.id}, 'dayoff')" class="w-full text-left px-3 py-2 text-xs text-white hover:bg-slate-700 flex items-center gap-2">
                                    <span>📅</span> Folga
                                </button>
                            </div>
                        </div>
                    </div>
                    
                    <button onclick="SectorManagement.removeEmployee(${emp.id})" 
                        class="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 p-1 transition" title="Remover">
                        <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `;
    },

    renderAvailableEmployees(employees) {
        if (!employees || employees.length === 0) {
            return `
                <div class="text-center text-slate-500 py-8 bg-slate-900/50 rounded-xl border border-slate-700">
                    <p class="text-sm">Nenhum colaborador disponível</p>
                    <p class="text-xs mt-1">Todos os colaboradores do turno já estão alocados.</p>
                </div>
            `;
        }

        // Cores por turno
        const shiftColors = {
            'Manhã': 'blue',
            'Tarde': 'orange',
            'Noite': 'purple'
        };

        // Cores por status/rotina
        const statusColors = {
            present: 'emerald',
            active: 'emerald',
            ativo: 'emerald',
            absent: 'red',
            falta: 'red',
            sick: 'amber',
            atestado: 'amber',
            vacation: 'orange',
            férias: 'orange',
            ferias: 'orange',
            away: 'indigo',
            afastado: 'indigo',
            dayoff: 'blue',
            folga: 'blue'
        };

        const statusLabels = {
            present: '✓',
            active: '✓',
            ativo: '✓',
            absent: '✗',
            falta: '✗',
            sick: '🏥',
            atestado: '🏥',
            vacation: '🏖️',
            férias: '🏖️',
            ferias: '🏖️',
            away: '🚫',
            afastado: '🚫',
            dayoff: '📅',
            folga: '📅'
        };

        return employees.map(emp => {
            // Filtrar demitidos
            const status = (emp.status || 'active').toLowerCase();
            if (status === 'fired' || status === 'demitido') {
                return ''; // Não renderizar demitidos
            }

            const routine = (Store.state.routines[emp.id] || emp.status || 'present').toLowerCase();
            const color = statusColors[routine] || 'emerald';
            const label = statusLabels[routine] || '✓';

            // Cor do turno
            const shift = emp.work_shift || emp.shift || 'Manhã';
            const shiftColor = shiftColors[shift] || 'slate';

            // Opacidade reduzida para férias e afastado
            const isUnavailable = routine === 'vacation' || routine === 'férias' || routine === 'ferias' ||
                routine === 'away' || routine === 'afastado';
            const opacity = isUnavailable ? 'opacity-50' : '';

            return `
                <div class="bg-slate-900 rounded-lg p-3 border border-slate-700 hover:border-${shiftColor}-500 transition cursor-pointer group ${opacity}"
                    onclick="SectorManagement.showSubsectorSelector(${emp.id})">
                    <div class="flex items-center justify-between">
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2 mb-1">
                                <p class="text-sm font-medium text-white truncate">${emp.name}</p>
                                <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-${shiftColor}-600/30 text-${shiftColor}-300 border border-${shiftColor}-600/50 font-bold">
                                    ${shift}
                                </span>
                            </div>
                            <div class="flex items-center gap-2">
                                <p class="text-xs text-slate-400 truncate">${emp.role || 'Colaborador'}</p>
                                <span class="text-xs px-2 py-0.5 rounded bg-${color}-600/20 text-${color}-400 border border-${color}-600/30">
                                    ${label}
                                </span>
                            </div>
                        </div>
                        <svg class="w-5 h-5 text-slate-600 group-hover:text-${shiftColor}-400 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                        </svg>
                    </div>
                </div>
            `;
        }).filter(html => html !== '').join(''); // Remover strings vazias (demitidos)
    },

    getAllocatedEmployees(sector, state) {
        const allocated = [];
        if (!sector.subsectors) return allocated;

        sector.subsectors.forEach(subsector => {
            const subsectorEmps = Render.getSubsectorEmployees(subsector.id, state);
            allocated.push(...subsectorEmps);
        });

        return allocated;
    },

    getAvailableEmployees(state) {
        const { employees, allocations, currentShift } = state;

        return employees.filter(emp => {
            // Deve ser do turno correto
            const empShift = emp.work_shift ?? emp.shift ?? null;
            if (!empShift || empShift.toLowerCase() !== currentShift.toLowerCase()) {
                return false;
            }

            // Não deve estar alocado
            return !allocations[emp.id];
        });
    },

    handleSearch(term) {
        this.searchTerm = term.toLowerCase();

        const state = Store.state;
        const availableEmployees = this.getAvailableEmployees(state);

        const filtered = availableEmployees.filter(emp =>
            emp.name.toLowerCase().includes(this.searchTerm) ||
            (emp.role && emp.role.toLowerCase().includes(this.searchTerm))
        );

        const container = document.getElementById('available-employees-list');
        if (container) {
            container.innerHTML = this.renderAvailableEmployees(filtered);
        }
    },

    showSubsectorSelector(empId) {
        const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
        if (!sector || !sector.subsectors || sector.subsectors.length === 0) {
            alert('Crie pelo menos um sub-setor antes de alocar colaboradores.');
            return;
        }

        const subsectorOptions = sector.subsectors.map(sub =>
            `<option value="${sub.id}">${sub.name} (${Render.getSubsectorEmployees(sub.id, Store.state).length}/${sub.max_employees})</option>`
        ).join('');

        const html = `
            <div id="subsector-selector-modal" class="fixed inset-0 z-[60] flex items-center justify-center">
                <div class="absolute inset-0 bg-black/50" onclick="document.getElementById('subsector-selector-modal').remove()"></div>
                <div class="relative bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-md">
                    <h3 class="text-lg font-bold text-white mb-4">Selecione o Sub-setor</h3>
                    <select id="subsector-select" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white mb-4">
                        ${subsectorOptions}
                    </select>
                    <div class="flex gap-2 justify-end">
                        <button onclick="document.getElementById('subsector-selector-modal').remove()" 
                            class="px-4 py-2 text-sm text-slate-300 hover:text-white">Cancelar</button>
                        <button onclick="SectorManagement.allocateEmployee(${empId}, document.getElementById('subsector-select').value)" 
                            class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold">Alocar</button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
    },

    allocateEmployee(empId, subsectorId) {
        // Remover modal de seleção
        const modal = document.getElementById('subsector-selector-modal');
        if (modal) modal.remove();

        // Alocar via Store
        Store.allocateEmployee(empId, parseInt(subsectorId));

        // Reabrir modal de gestão atualizado
        setTimeout(() => {
            const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
            if (sector) {
                this.render(sector);
                document.getElementById('sector-management-modal').classList.remove('hidden');
            }
        }, 100);
    },

    removeEmployee(empId) {
        if (!confirm('Remover este colaborador da alocação?')) return;

        Store.removeAllocation(empId);

        // Reabrir modal de gestão atualizado
        setTimeout(() => {
            const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
            if (sector) {
                this.render(sector);
                document.getElementById('sector-management-modal').classList.remove('hidden');
            }
        }, 100);
    },

    toggleRoutineMenu(empId) {
        // Fechar todos os menus abertos
        document.querySelectorAll('[id^="routine-menu-"]').forEach(menu => {
            if (menu.id !== `routine-menu-${empId}`) {
                menu.classList.add('hidden');
            }
        });

        // Toggle do menu atual
        const menu = document.getElementById(`routine-menu-${empId}`);
        if (menu) {
            menu.classList.toggle('hidden');
        }
    },

    setRoutine(empId, routine) {
        // Fechar menu
        const menu = document.getElementById(`routine-menu-${empId}`);
        if (menu) menu.classList.add('hidden');

        // Se for férias, abrir modal
        if (routine === 'vacation') {
            this.openVacationModal(empId);
            return;
        }

        // Atualizar rotina localmente
        Store.updateRoutine(empId, routine);

        // Salvar rotina permanentemente no backend
        API.setEmployeeRoutine(empId, routine)
            .then(result => {
                if (result.success) {
                    console.log(`✅ Rotina salva no backend: ${routine}`);
                } else {
                    console.error('❌ Erro ao salvar rotina no backend:', result.error);
                }
            });

        // Reabrir modal atualizado
        setTimeout(() => {
            const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
            if (sector) {
                this.render(sector);
                document.getElementById('sector-management-modal').classList.remove('hidden');
            }
        }, 100);
    },

    openVacationModal(empId) {
        const employee = Store.state.employees.find(e => e.id === empId);
        if (!employee) return;

        const html = `
            <div id="vacation-modal" class="fixed inset-0 z-[70] flex items-center justify-center">
                <div class="absolute inset-0 bg-black/50" onclick="document.getElementById('vacation-modal').remove()"></div>
                <div class="relative bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-md">
                    <h3 class="text-lg font-bold text-white mb-4">🏖️ Definir Férias</h3>
                    <p class="text-sm text-slate-300 mb-4">${employee.name}</p>
                    
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-slate-300 mb-2">Data Início</label>
                            <input type="date" id="vacation-start" 
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-300 mb-2">Data Fim</label>
                            <input type="date" id="vacation-end" 
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white">
                        </div>
                    </div>
                    
                    <div class="flex gap-2 justify-end mt-6">
                        <button onclick="document.getElementById('vacation-modal').remove()" 
                            class="px-4 py-2 text-sm text-slate-300 hover:text-white">Cancelar</button>
                        <button onclick="SectorManagement.confirmVacation(${empId})" 
                            class="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-lg text-sm font-bold">Confirmar</button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
    },

    confirmVacation(empId) {
        const startDate = document.getElementById('vacation-start').value;
        const endDate = document.getElementById('vacation-end').value;

        if (!startDate || !endDate) {
            alert('Por favor, preencha as datas de início e fim.');
            return;
        }

        if (new Date(startDate) > new Date(endDate)) {
            alert('Data de início não pode ser maior que data de fim.');
            return;
        }

        // Atualizar rotina localmente
        Store.updateRoutine(empId, 'vacation');

        // Salvar férias permanentemente no backend
        API.setEmployeeVacation(empId, startDate, endDate)
            .then(result => {
                if (result.success) {
                    console.log(`✅ Férias salvas no backend: ${startDate} até ${endDate}`);
                } else {
                    console.error('❌ Erro ao salvar férias no backend:', result.error);
                    alert('Erro ao salvar férias. Tente novamente.');
                }
            });

        // Fechar modal
        document.getElementById('vacation-modal').remove();

        // Reabrir modal de gestão atualizado
        setTimeout(() => {
            const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
            if (sector) {
                this.render(sector);
                document.getElementById('sector-management-modal').classList.remove('hidden');
            }
        }, 100);
    },

    editSubsectorInline(subsectorId, sectorId, currentName, currentMax) {
        // Encontrar o elemento do subsector
        const targetCard = document.querySelector(`[data-subsector-id="${subsectorId}"]`);

        if (!targetCard) {
            alert('Erro ao localizar sub-setor');
            return;
        }

        // Salvar conteúdo original no próprio card
        if (!targetCard.dataset.originalContent) {
            targetCard.dataset.originalContent = targetCard.innerHTML;
        }

        // Criar formulário inline
        targetCard.innerHTML = `
            <div class="p-4">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="text-sm font-bold text-white">Editando Sub-setor</h4>
                    <button onclick="SectorManagement.cancelEditInline(${subsectorId})"
                        class="text-slate-400 hover:text-white">
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="space-y-3">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">Nome</label>
                        <input type="text" id="edit-subsector-name-${subsectorId}" value="${currentName}"
                            class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500">
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">Limite de Vagas</label>
                        <input type="number" id="edit-subsector-max-${subsectorId}" value="${currentMax}" min="0"
                            class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500">
                    </div>

                    <div class="flex gap-2 justify-end pt-2">
                        <button onclick="SectorManagement.cancelEditInline(${subsectorId})"
                            class="px-3 py-1.5 text-xs text-slate-300 hover:text-white">
                            Cancelar
                        </button>
                        <button onclick="SectorManagement.saveEditInline(${subsectorId}, ${sectorId})"
                            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold">
                            Salvar
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Focar no campo de nome
        setTimeout(() => {
            document.getElementById(`edit-subsector-name-${subsectorId}`)?.focus();
        }, 100);
    },

    cancelEditInline(subsectorId) {
        const targetCard = document.querySelector(`[data-subsector-id="${subsectorId}"]`);
        if (targetCard && targetCard.dataset.originalContent) {
            targetCard.innerHTML = targetCard.dataset.originalContent;
            delete targetCard.dataset.originalContent;
        }
    },

    async saveEditInline(subsectorId, sectorId) {
        const name = document.getElementById(`edit-subsector-name-${subsectorId}`)?.value;
        const maxEmployees = document.getElementById(`edit-subsector-max-${subsectorId}`)?.value;

        if (!name || !maxEmployees) {
            alert('Preencha todos os campos');
            return;
        }

        try {
            const formData = new FormData();
            formData.append('sector_id', sectorId);
            formData.append('name', name);
            formData.append('max_employees', maxEmployees);

            const response = await fetch(`/api/smart-flow/subsectors/${subsectorId}`, {
                method: 'PUT',
                body: formData
            });

            const result = await response.json();
            if (result.success) {
                // Recarregar dados
                await App.loadData();

                // Reabrir modal atualizado
                setTimeout(() => {
                    const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
                    if (sector) {
                        this.render(sector);
                        document.getElementById('sector-management-modal').classList.remove('hidden');
                    }
                }, 100);
            } else {
                alert('Erro ao salvar sub-setor');
            }
        } catch (error) {
            console.error('Error saving subsector:', error);
            alert('Erro ao salvar sub-setor');
        }
    },

    addSubsectorInline(sectorId) {
        // Verificar se já existe um formulário de criação aberto
        if (document.getElementById('new-subsector-form')) {
            alert('Já existe um formulário de criação aberto');
            return;
        }

        // Encontrar container de sub-setores
        const subsectorsContainer = document.getElementById('subsectors-list');
        if (!subsectorsContainer) return;

        // Criar card de formulário
        const formCard = document.createElement('div');
        formCard.id = 'new-subsector-form';
        formCard.className = 'bg-slate-900 rounded-xl border-2 border-blue-500 p-4';
        formCard.innerHTML = `
            <div class="mb-3">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-bold text-blue-400">Novo Sub-setor</h4>
                    <button onclick="SectorManagement.cancelNewSubsectorInline()"
                        class="text-slate-400 hover:text-white">
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="space-y-3">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">Nome</label>
                        <input type="text" id="new-subsector-name" placeholder="Ex: Doca 1"
                            class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500">
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">Limite de Vagas</label>
                        <input type="number" id="new-subsector-max" value="4" min="0"
                            class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500">
                    </div>

                    <div class="flex gap-2 justify-end pt-2">
                        <button onclick="SectorManagement.cancelNewSubsectorInline()"
                            class="px-3 py-1.5 text-xs text-slate-300 hover:text-white">
                            Cancelar
                        </button>
                        <button onclick="SectorManagement.saveNewSubsectorInline(${sectorId})"
                            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold">
                            Criar
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Adicionar no início da lista
        subsectorsContainer.insertBefore(formCard, subsectorsContainer.firstChild);

        // Focar no campo de nome
        setTimeout(() => {
            document.getElementById('new-subsector-name')?.focus();
        }, 100);
    },

    cancelNewSubsectorInline() {
        const form = document.getElementById('new-subsector-form');
        if (form) form.remove();
    },

    async saveNewSubsectorInline(sectorId) {
        const name = document.getElementById('new-subsector-name')?.value;
        const maxEmployees = document.getElementById('new-subsector-max')?.value;

        if (!name || !maxEmployees) {
            alert('Preencha todos os campos');
            return;
        }

        try {
            const formData = new FormData();
            formData.append('sector_id', sectorId);
            formData.append('name', name);
            formData.append('max_employees', maxEmployees);

            const response = await fetch('/api/smart-flow/subsectors', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            if (result.success) {
                // Remover formulário
                this.cancelNewSubsectorInline();

                // Recarregar dados
                await App.loadData();

                // Reabrir modal atualizado
                setTimeout(() => {
                    const sector = Store.state.sectors.find(s => s.id === this.currentSectorId);
                    if (sector) {
                        this.render(sector);
                        document.getElementById('sector-management-modal').classList.remove('hidden');
                    }
                }, 100);
            } else {
                alert('Erro ao criar sub-setor');
            }
        } catch (error) {
            console.error('Error creating subsector:', error);
            alert('Erro ao criar sub-setor');
        }
    }
};

// Expor globalmente
window.SectorManagement = SectorManagement;
