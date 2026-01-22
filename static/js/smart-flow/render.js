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

        // Calcular contagens detalhadas
        let countRealPresent = 0;
        let countAbsence = { vacation: 0, sick: 0, absent: 0, away: 0 };

        if (sector.subsectors) {
            sector.subsectors.forEach(sub => {
                Object.entries(state.allocations).forEach(([empId, subId]) => {
                    if (subId === sub.id) {
                        const emp = state.employees.find(e => e.id == empId);
                        const routine = state.routines[empId] || (emp ? emp.status : 'present');
                        const r = routine.toLowerCase();

                        if (['vacation', 'ferias'].includes(r)) countAbsence.vacation++;
                        else if (['sick', 'atestado'].includes(r)) countAbsence.sick++;
                        else if (['absent', 'falta'].includes(r)) countAbsence.absent++;
                        else if (['away', 'afastado'].includes(r)) countAbsence.away++;
                        else if (!['fired', 'demitido'].includes(r)) countRealPresent++;
                    }
                });
            });
        }

        // Percentual baseado em Presentes vs Alocados (Força de Trabalho Real)
        const realPercentage = sectorEmployeeCount > 0 ? Math.round((countRealPresent / sectorEmployeeCount) * 100) : 0;

        // Tornar card clicável para abrir modal de gestão
        card.onclick = (e) => {
            // Não abrir modal se clicou em botão de ação
            if (e.target.closest('button')) return;
            SectorManagement.open(sector.id);
        };

        card.innerHTML = `
            <!-- Header Compacto -->
            <div class="flex items-center justify-between mb-3 border-b border-slate-700/50 pb-2">
                <div class="flex-1 min-w-0">
                    <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider truncate mb-0.5">${sector.name}</h3>
                    <div class="flex items-center gap-2">
                         <span class="text-lg font-bold text-white leading-none">${countRealPresent} <span class="text-xs text-slate-500 font-normal">/ ${sectorEmployeeCount}</span></span>
                    </div>
                </div>
                <!-- Actions -->
                <div class="flex gap-1" onclick="event.stopPropagation()">
                    <button onclick="SectorsCRUD.openEditSector(${sector.id}, '${sector.name}', ${sector.max_employees}, '${sector.color}')" class="p-1.5 text-slate-500 hover:text-white rounded hover:bg-slate-700 transition"><svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg></button>
                    <button onclick="SectorsCRUD.deleteSector(${sector.id}, '${sector.name}')" class="p-1.5 text-slate-500 hover:text-red-400 rounded hover:bg-slate-700 transition"><svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
                </div>
            </div>

            <!-- Progress & Stats -->
            <div class="mb-3">
                <div class="flex justify-between items-end mb-1">
                    <span class="text-[9px] text-slate-500 font-bold uppercase">Presença</span>
                    <span class="text-[10px] font-bold ${realPercentage < 70 ? 'text-red-400' : 'text-emerald-400'}">${realPercentage}%</span>
                </div>
                <div class="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                    <div class="bg-${realPercentage < 70 ? 'red' : 'emerald'}-500 h-full transition-all" style="width: ${realPercentage}%"></div>
                </div>
            </div>

            <!-- Rupture Indicators (Badges) -->
            <div class="flex flex-wrap gap-2 min-h-[20px]">
                ${countAbsence.vacation > 0 ?
                `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-orange-500/10 border border-orange-500/20 text-[9px] font-bold text-orange-400" title="Férias">
                        <span>🏖️</span> ${countAbsence.vacation}
                    </span>` : ''}
                
                ${countAbsence.sick > 0 ?
                `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-[9px] font-bold text-amber-400" title="Atestado">
                        <span>🏥</span> ${countAbsence.sick}
                    </span>` : ''}

                ${countAbsence.absent > 0 ?
                `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-[9px] font-bold text-red-400" title="Falta">
                        <span>✗</span> ${countAbsence.absent}
                    </span>` : ''}
                
                ${countAbsence.away > 0 ?
                `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-[9px] font-bold text-indigo-400" title="Afastado">
                        <span>🚫</span> ${countAbsence.away}
                    </span>` : ''}
                
                ${(countAbsence.vacation + countAbsence.sick + countAbsence.absent + countAbsence.away) === 0 ?
                `<span class="text-[9px] text-slate-600 italic">Equipe completa</span>` : ''}
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
                // Bugfix: Considerar status do funcionário se não houver rotina diária
                const routine = state.routines[emp.id] || emp.status || 'present';
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
            <!-- Header Compacto -->
            <div class="flex items-center justify-between mb-4 border-b border-slate-700 pb-3">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center text-sm font-bold border border-slate-600">
                        ${employee.name.substring(0, 2).toUpperCase()}
                    </div>
                    <div>
                        <h3 class="text-base font-bold text-white leading-tight">${employee.name}</h3>
                        <p class="text-xs text-slate-400">${employee.role || 'Colaborador'}</p>
                    </div>
                </div>
                <div class="px-2.5 py-1 rounded-full bg-slate-700 border border-slate-600 flex items-center gap-2">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    <span class="text-[10px] text-slate-200 uppercase font-bold">${currentActivity}</span>
                </div>
            </div>

            <div class="space-y-4">
                <!-- Observação -->
                <div>
                    <div class="relative">
                        <input type="text" id="activity-observation" 
                            placeholder="Adicionar observação..." 
                            class="w-full bg-slate-900/50 border border-slate-600/50 rounded-lg px-3 py-2 text-white text-xs focus:ring-1 focus:ring-blue-500 transition-all outline-none">
                    </div>
                </div>

                <!-- Grids Compactos -->
                <div>
                    <p class="text-[10px] text-slate-500 font-bold uppercase mb-1.5 tracking-wide">Operação</p>
                    <div class="grid grid-cols-4 gap-2">
                        ${this.renderActivityButton(employee.id, 'Separacao', 'emerald', '📦', true)}
                        ${this.renderActivityButton(employee.id, 'Conferencia', 'emerald', '✅', true)}
                        ${this.renderActivityButton(employee.id, 'Carregamento', 'emerald', '🚛', true)}
                        ${this.renderActivityButton(employee.id, 'Limpeza', 'emerald', '🧹', true)}
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-2">
                    <div>
                        <p class="text-[10px] text-slate-500 font-bold uppercase mb-1.5 tracking-wide">Pausa</p>
                        <div class="grid grid-cols-2 gap-2">
                            ${this.renderActivityButton(employee.id, 'Pausa', 'amber', '☕', true)}
                            ${this.renderActivityButton(employee.id, 'Banheiro', 'amber', 'wc', true)}
                        </div>
                    </div>
                    <div>
                        <p class="text-[10px] text-slate-500 font-bold uppercase mb-1.5 tracking-wide">Problemas</p>
                        <div class="grid grid-cols-2 gap-2">
                            ${this.renderActivityButton(employee.id, 'Intercorrencia', 'rose', '⚠️', true)}
                            ${this.renderActivityButton(employee.id, 'Apoio', 'blue', '🤝', true)}
                        </div>
                    </div>
                </div>

                <!-- Administrativo (Com Input de Dias) -->
                <div class="pt-2 border-t border-slate-700/50">
                    <p class="text-[10px] text-slate-500 font-bold uppercase mb-1.5 tracking-wide">Administrativo / Ausência</p>
                    
                    <!-- Seletores Rápidos -->
                    <div class="grid grid-cols-4 gap-2 mb-3">
                        ${this.renderRoutineButton(employee.id, 'present', 'emerald', '🙌', 'Presente', true)}
                        ${this.renderRoutineButton(employee.id, 'absent', 'red', '✗', 'Falta', true)}
                        ${this.renderRoutineButton(employee.id, 'sick', 'amber', '🏥', 'Atestado', true)}
                        ${this.renderRoutineButton(employee.id, 'vacation', 'orange', '🏖️', 'Férias', true)}
                    </div>

                    <!-- Área de Detalhes (Inicialmente Oculta, ou integrada) -->
                    <!-- Aqui podemos adicionar lógica JS para expandir se clicar -->
                </div>
            </div>
            
            <button onclick="Render.closeBottomSheet()" class="mt-4 w-full py-3 bg-slate-900/80 text-slate-400 font-bold rounded-xl active:bg-slate-950 border border-slate-800 text-xs">
                Cancelar
            </button>
        `;
    },

    renderActivityButton(empId, activity, color, icon, compact = false) {
        const actKey = activity.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        const sizeClass = compact ? 'p-2.5 min-h-[60px]' : 'p-4';
        const iconClass = compact ? 'text-xl mb-0.5' : 'text-2xl mb-1';
        const textClass = compact ? 'text-[9px]' : 'text-xs';

        return `
            <button onclick="Events.setActivity(${empId}, '${actKey}')"
                class="flex flex-col items-center justify-center ${sizeClass} bg-slate-700/30 hover:bg-${color}-600/20 border border-slate-600/50 hover:border-${color}-500/50 rounded-xl transition-all active:scale-95 group">
                <span class="${iconClass} group-hover:scale-110 transition-transform">${icon}</span>
                <span class="${textClass} font-bold text-slate-300 group-hover:text-white uppercase tracking-tight">${activity}</span>
            </button>
        `;
    },

    renderRoutineButton(empId, routineKey, color, icon, label, compact = false) {
        const sizeClass = compact ? 'p-2.5 min-h-[60px]' : 'p-4';
        const iconClass = compact ? 'text-xl mb-0.5' : 'text-2xl mb-1';
        const textClass = compact ? 'text-[9px]' : 'text-xs';

        return `
            <button onclick="Render.openRoutineForm(${empId}, '${routineKey}', '${label}')"
                class="flex flex-col items-center justify-center ${sizeClass} bg-slate-700/30 hover:bg-${color}-600/20 border border-slate-600/50 hover:border-${color}-500/50 rounded-xl transition-all active:scale-95 group">
                <span class="${iconClass} group-hover:scale-110 transition-transform">${icon}</span>
                <span class="${textClass} font-bold text-slate-300 group-hover:text-white uppercase tracking-tight">${label}</span>
            </button>
        `;
    },

    openRoutineForm(empId, type, label) {
        const content = document.getElementById('sheet-content');
        if (!content) return;

        const today = Store.state.currentDate;
        const employee = Store.state.employees.find(e => e.id == empId);

        content.innerHTML = `
            <div class="animate-fade-in">
                <!-- Header com Voltar -->
                <div class="flex items-center gap-3 mb-6 border-b border-slate-700 pb-4">
                    <button onclick="Render.openBottomSheet(Store.state.employees.find(e => e.id == ${empId}))" 
                        class="w-8 h-8 flex items-center justify-center rounded-full bg-slate-700/50 hover:bg-slate-700 text-slate-400 hover:text-white transition">
                        <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>
                    </button>
                    <div>
                        <h3 class="text-base font-bold text-white leading-tight">Registrar ${label}</h3>
                        <p class="text-xs text-slate-400">Para: ${employee ? employee.name : 'Colaborador'}</p>
                    </div>
                </div>

                <div class="space-y-5">
                    <!-- Data Início -->
                    <div>
                        <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1.5 ml-1">Data Início</label>
                        <input type="date" id="routine-start-date" value="${today}"
                            class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium">
                    </div>

                    <!-- Duração -->
                    <div>
                        <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1.5 ml-1">Quantidade de Dias</label>
                        <div class="flex items-center gap-3">
                            <button onclick="document.getElementById('routine-days').stepDown()" 
                                class="w-12 h-12 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 font-bold text-xl hover:bg-slate-700 active:scale-95 transition flex items-center justify-center">–</button>
                            
                            <input type="number" id="routine-days" value="1" min="1" max="30" readonly
                                class="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white text-center text-xl font-bold outline-none focus:border-blue-500">
                            
                            <button onclick="document.getElementById('routine-days').stepUp()" 
                                class="w-12 h-12 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 font-bold text-xl hover:bg-slate-700 active:scale-95 transition flex items-center justify-center">+</button>
                        </div>
                    </div>
                </div>

                <!-- Botões de Ação -->
                <div class="mt-8 grid grid-cols-2 gap-3">
                     <button onclick="Render.openBottomSheet(Store.state.employees.find(e => e.id == ${empId}))" 
                        class="py-3.5 bg-slate-800/80 text-slate-400 font-bold rounded-xl border border-slate-700 text-sm hover:bg-slate-800 transition">
                        Voltar
                    </button>
                    <button onclick="Events.setExtendedRoutine(${empId}, '${type}')" 
                        class="py-3.5 bg-blue-600 text-white font-bold rounded-xl shadow-lg shadow-blue-900/20 text-sm hover:bg-blue-500 active:scale-95 transition flex items-center justify-center gap-2">
                        <span>Confirmar</span>
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                    </button>
                </div>
            </div>
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

