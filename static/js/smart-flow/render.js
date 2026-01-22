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
        card.className = 'bg-slate-800 rounded-lg border border-slate-700 p-3 hover:border-blue-500 transition cursor-pointer group';

        // Calcular total de colaboradores alocados neste setor
        const sectorEmployeeCount = this.countSectorEmployees(sector, state.allocations);
        const percentage = sector.max_employees > 0 ? Math.round((sectorEmployeeCount / sector.max_employees) * 100) : 0;

        // Tornar card clicável para abrir modal de gestão
        card.onclick = (e) => {
            // Não abrir modal se clicou em botão de ação
            if (e.target.closest('button')) return;
            SectorManagement.open(sector.id);
        };

        card.innerHTML = `
            <!-- Header -->
            <div class="flex items-center justify-between mb-3 pb-2 border-b border-slate-700/50">
                <div class="flex-1 min-w-0">
                    <h3 class="text-sm font-bold text-white group-hover:text-blue-400 transition truncate">${sector.name}</h3>
                    <p class="text-[9px] text-slate-500">${sector.subsectors?.length || 0} sub-setores</p>
                </div>
                <div class="flex gap-1 flex-shrink-0" onclick="event.stopPropagation()">
                    <button onclick="SectorsCRUD.openEditSector(${sector.id}, '${sector.name}', ${sector.max_employees}, '${sector.color}')"
                        class="text-slate-500 hover:text-blue-400 p-1 rounded transition" title="Editar">
                        <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <button onclick="SectorsCRUD.deleteSector(${sector.id}, '${sector.name}')"
                        class="text-slate-500 hover:text-red-400 p-1 rounded transition" title="Excluir">
                        <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>

            <!-- Stats -->
            <div class="space-y-2">
                <div class="flex items-baseline justify-between">
                    <span class="text-[9px] text-slate-500 uppercase font-bold">Alocados</span>
                    <div class="text-right">
                        <span class="text-xl font-bold text-${percentage >= 80 ? 'emerald' : percentage >= 50 ? 'amber' : 'red'}-400">${sectorEmployeeCount}</span>
                        <span class="text-slate-600 text-sm"> / ${sector.max_employees}</span>
                    </div>
                </div>
                
                <!-- Progress Bar -->
                <div class="w-full bg-slate-900 rounded-full h-1 overflow-hidden">
                    <div class="bg-${percentage >= 80 ? 'emerald' : percentage >= 50 ? 'amber' : 'red'}-500 h-full transition-all" style="width: ${percentage}%"></div>
                </div>
                
                <div class="text-right">
                    <span class="text-[9px] text-slate-500">Ocupação: </span>
                    <span class="text-xs font-bold text-${percentage >= 80 ? 'emerald' : percentage >= 50 ? 'amber' : 'red'}-400">${percentage}%</span>
                </div>
            </div>
        `;

        return card;
    },

    createSubSectorCard(sector, subsector, state) {
        const card = document.createElement('div');
        card.className = 'bg-slate-900 rounded-xl border border-slate-700 overflow-hidden flex flex-col transition-all duration-300'; // Alterado para suportar collapse
        card.dataset.subsectorId = subsector.id;
        card.dataset.maxEmployees = subsector.max_employees;

        // Filtrar colaboradores alocados neste sub-setor
        const allocatedEmployees = this.getSubsectorEmployees(subsector.id, state);
        const currentCount = allocatedEmployees.length;

        // --- HEADER DO SUB-SETOR (Clicável para Accordion) ---
        const header = document.createElement('div');
        header.className = 'flex items-center justify-between p-3 border-b border-slate-700 cursor-pointer bg-slate-800 hover:bg-slate-750 transition select-none';

        // Estado inicial: Aberto se tiver gente, fechado se vazio (ou lógica customizada)
        const isOpen = true; // Default open for now

        header.innerHTML = `
            <div class="flex items-center gap-2">
                <!-- Chevron Icon -->
                <svg class="chevron-icon w-4 h-4 text-slate-400 transition-transform duration-300 transform rotate-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
                <div>
                    <h4 class="text-sm font-bold text-white leading-tight">${subsector.name}</h4>
                    <p class="text-[10px] text-slate-500">
                        <span class="subsector-count font-bold text-slate-300">${currentCount}</span> / ${subsector.max_employees}
                    </p>
                </div>
            </div>
            
            <!-- Ações (Editar/Excluir) - Stop Propagation para não triggar o accordion -->
            <div class="flex gap-1" onclick="event.stopPropagation()">
                <button onclick="SectorsCRUD.openEditSubSector(${subsector.id}, ${sector.id}, '${subsector.name}', ${subsector.max_employees})"
                    class="text-slate-500 hover:text-white p-1.5 rounded active:bg-slate-700" title="Editar">
                    <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button onclick="SectorsCRUD.deleteSubSector(${subsector.id}, '${subsector.name}')"
                    class="text-slate-500 hover:text-red-400 p-1.5 rounded active:bg-slate-700" title="Excluir">
                    <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `;
        card.appendChild(header);

        // --- LISTA DE COLABORADORES ---
        const listContainer = document.createElement('div');
        listContainer.className = 'accordion-content transition-all duration-300 ease-in-out';
        // Altura automática handling é chato no CSS transition, vamos usar max-height trick ou só toggle class

        const employeesList = document.createElement('div');
        employeesList.className = 'space-y-2 p-3 employees-list min-h-[60px]'; // Padding movido para cá

        if (allocatedEmployees.length === 0) {
            employeesList.innerHTML = `
                <div class="text-xs text-slate-600 text-center py-4 border-2 border-dashed border-slate-700 rounded-lg">
                    Arraste aqui
                </div>
            `;
        } else {
            allocatedEmployees.forEach(emp => {
                const routine = state.routines[emp.id] || 'present';
                const empCard = this.createEmployeeCard(emp, routine);
                employeesList.appendChild(empCard);
            });
        }

        listContainer.appendChild(employeesList);
        card.appendChild(listContainer);

        // --- ACCORDION LOGIC ---
        const chevron = header.querySelector('.chevron-icon');

        header.onclick = () => {
            const isHidden = listContainer.classList.contains('hidden');
            if (isHidden) {
                listContainer.classList.remove('hidden');
                chevron.style.transform = 'rotate(0deg)';
            } else {
                listContainer.classList.add('hidden');
                chevron.style.transform = 'rotate(-90deg)';
            }
        };

        // Estado inicial (Opcional: fechar se tiver muitos sub-setores?) 
        // Por enquanto deixa aberto.

        // Tornar drop zone (funciona mesmo fechado? Sim, events fire on container)
        this.makeDropZone(card, subsector.id);

        return card;
    },

    createEmployeeCard(employee, routine) {
        const card = document.createElement('div');
        // Card base stylings - touch friendly
        card.className = 'bg-slate-800 rounded-xl p-3 border-l-4 shadow-sm hover:shadow-md transition-all cursor-pointer relative group active:scale-95 duration-100 touch-manipulation select-none';

        card.draggable = true;
        card.dataset.employeeId = employee.id;

        // Recuperar Atividade Atual do Store (se existir)
        const activityData = Store.state.activities ? Store.state.activities[employee.id] : null;
        const currentActivity = activityData ? activityData.activity : null;

        // Definição de Cores baseada na Atividade ou Rotina
        let statusColor = 'slate';
        let statusText = 'Disponível';

        // Mapeamento de Status Visual
        if (currentActivity) {
            const act = currentActivity.toLowerCase();
            if (['separacao', 'conferencia', 'carregamento', 'limpeza'].includes(act)) {
                statusColor = 'emerald';
            } else if (['aguardando', 'pausa', 'banheiro'].includes(act)) {
                statusColor = 'amber';
            } else if (['intercorrencia', 'apoio'].includes(act)) {
                statusColor = 'rose';
            } else {
                statusColor = 'blue';
            }
            statusText = currentActivity.charAt(0).toUpperCase() + currentActivity.slice(1);
        } else if (routine && routine !== 'present') {
            // Fallback para rotinas legadas (Falta, Atestado, etc)
            const routineMap = {
                'absent': { color: 'red', text: 'Falta' },
                'sick': { color: 'amber', text: 'Atestado' },
                'vacation': { color: 'orange', text: 'Férias' },
                'away': { color: 'indigo', text: 'Afastado' }
            };
            const r = routineMap[routine];
            if (r) {
                statusColor = r.color;
                statusText = r.text;
            }
        } else {
            // Default Present
            statusColor = 'emerald';
        }

        card.classList.add(`border-${statusColor}-500`);

        // Conteúdo do Card
        card.innerHTML = `
            <div class="flex items-center justify-between gap-3">
                <!-- Avatar / Initials -->
                <div class="h-10 w-10 rounded-full bg-slate-700 flex items-center justify-center shrink-0 border border-slate-600">
                    ${employee.photo_url ?
                `<img src="${employee.photo_url}" class="h-full w-full rounded-full object-cover">` :
                `<span class="text-xs font-bold text-slate-400">${employee.name.substring(0, 2).toUpperCase()}</span>`
            }
                </div>

                <!-- Info -->
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-bold text-white truncate leading-tight">${employee.name}</p>
                    <p class="text-[11px] text-${statusColor}-400 font-medium truncate mt-0.5 flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-${statusColor}-500 animate-pulse"></span>
                        ${statusText}
                    </p>
                </div>

                <!-- Timer (Opcional, futuro) -->
                ${activityData ? `
                <div class="text-[10px] text-slate-500 font-mono">
                    ${this.formatTime(activityData.started_at)}
                </div>` : ''}
            </div>
        `;

        // Click Event -> Open Bottom Sheet
        card.onclick = (e) => {
            // Evita abrir se estiver arrastando (embora click não dispare no dragend, bom garantir)
            this.openBottomSheet(employee);
        };

        // Drag Events
        card.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('employeeId', employee.id);
            card.classList.add('opacity-50', 'scale-95');
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('opacity-50', 'scale-95');
        });

        return card;
    },

    // --- Bottom Sheet Logic ---

    openBottomSheet(employee) {
        const sheet = document.getElementById('employee-bottom-sheet');
        const backdrop = document.getElementById('sheet-backdrop');
        const content = document.getElementById('sheet-content');

        if (!sheet || !content) return;

        // Popular Conteúdo
        content.innerHTML = this.buildSheetContent(employee);

        // Mostrar
        sheet.classList.remove('translate-y-full');
        backdrop.classList.remove('opacity-0', '-z-10');
        backdrop.classList.add('z-40');
    },

    closeBottomSheet() {
        const sheet = document.getElementById('employee-bottom-sheet');
        const backdrop = document.getElementById('sheet-backdrop');

        if (!sheet) return;

        sheet.classList.add('translate-y-full');
        backdrop.classList.add('opacity-0', '-z-10');
        backdrop.classList.remove('z-40');
    },

    buildSheetContent(employee) {
        const currentActivity = Store.state.activities[employee.id]?.activity || 'Nenhuma';

        return `
            <!-- Header do Sheet -->
            <div class="text-center mb-4">
                <h3 class="text-xl font-bold text-white">${employee.name}</h3>
                <p class="text-slate-400 text-sm">${employee.role || 'Colaborador'}</p>
                <div class="mt-2 inline-flex items-center px-3 py-1 rounded-full bg-slate-700 border border-slate-600">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 mr-2"></span>
                    <span class="text-xs text-slate-200 uppercase tracking-wide font-bold">${currentActivity}</span>
                </div>
            </div>

            <!-- Campo de Observação (Opcional) -->
            <div class="mb-5">
                <label class="block text-[10px] font-bold text-slate-500 uppercase mb-1.5 ml-1">Observação / Obs. Curta</label>
                <div class="relative">
                    <input type="text" id="activity-observation" 
                        placeholder="Ex: Falta de caixa, prioridade, etc..." 
                        class="w-full bg-slate-900 border border-slate-600 rounded-xl px-4 py-3 text-white text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all shadow-inner placeholder-slate-600">
                    <div class="absolute right-3 top-3 text-slate-600 pointer-events-none">
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                    </div>
                </div>
            </div>

            <!-- Ações Rápidas (Grid) -->
            <p class="text-xs text-slate-500 font-bold uppercase mb-2 pl-1">Atividades Principais</p>
            <div class="grid grid-cols-2 gap-3 mb-5">
                ${this.renderActivityButton(employee.id, 'Separacao', 'emerald', '📦')}
                ${this.renderActivityButton(employee.id, 'Conferencia', 'emerald', '✅')}
                ${this.renderActivityButton(employee.id, 'Carregamento', 'emerald', '🚛')}
                ${this.renderActivityButton(employee.id, 'Limpeza', 'emerald', '🧹')}
            </div>

            <p class="text-xs text-slate-500 font-bold uppercase mb-2 pl-1">Pausa / Outros</p>
            <div class="grid grid-cols-3 gap-3 mb-5">
                ${this.renderActivityButton(employee.id, 'Aguardando', 'amber', '⏳')}
                ${this.renderActivityButton(employee.id, 'Pausa', 'amber', '☕')}
                ${this.renderActivityButton(employee.id, 'Banheiro', 'amber', 'wc')}
            </div>

            <p class="text-xs text-slate-500 font-bold uppercase mb-2 pl-1">Problemas</p>
            <div class="grid grid-cols-2 gap-3">
                ${this.renderActivityButton(employee.id, 'Intercorrencia', 'rose', '⚠️')}
                ${this.renderActivityButton(employee.id, 'Apoio', 'blue', '🤝')}
            </div>
            
            <!-- Botão Fechar -->
            <button onclick="Render.closeBottomSheet()" class="mt-8 w-full py-4 bg-slate-900 text-slate-400 font-bold rounded-xl active:bg-slate-950 border border-slate-800">
                Cancelar / Fechar
            </button>
        `;
    },

    renderActivityButton(empId, activity, color, icon) {
        // Normalizar strings para evitar erros
        const actKey = activity.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

        return `
            <button onclick="Events.setActivity(${empId}, '${actKey}')"
                class="flex flex-col items-center justify-center p-4 bg-slate-700/50 hover:bg-${color}-600/20 border border-slate-600 hover:border-${color}-500/50 rounded-2xl transition-all active:scale-95 group">
                <span class="text-2xl mb-1 group-hover:scale-110 transition-transform">${icon}</span>
                <span class="text-xs font-bold text-slate-300 group-hover:text-white">${activity}</span>
            </button>
        `;
    },

    formatTime(isoString) {
        if (!isoString) return '';
        const date = new Date(isoString);
        return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
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
    },

    openBottomSheet(employee) {
        const sheet = document.getElementById('employee-bottom-sheet');
        const backdrop = document.getElementById('sheet-backdrop');
        const content = document.getElementById('sheet-content');

        if (!sheet || !backdrop || !content) {
            console.error('Bottom Sheet elements not found');
            return;
        }

        // Renderizar conteúdo do funcionário
        content.innerHTML = this.buildSheetContent(employee);

        // Mostrar Backdrop
        backdrop.classList.remove('opacity-0', 'pointer-events-none');

        // Deslizar Sheet para cima
        sheet.classList.remove('translate-y-full');
    },

    closeBottomSheet() {
        const sheet = document.getElementById('employee-bottom-sheet');
        const backdrop = document.getElementById('sheet-backdrop');

        if (sheet) sheet.classList.add('translate-y-full');
        if (backdrop) backdrop.classList.add('opacity-0', 'pointer-events-none');
    }
};

// Expor globalmente e helper para fechar sheet
window.Render = Render;
window.closeEmployeeSheet = Render.closeBottomSheet; // Atalho para o onclick do backdrop

// Função global para atualizar rotina (mantida para compatibilidade, mas UI mudou)
window.updateRoutine = (empId, routine) => {
    Store.updateRoutine(empId, routine);
};

