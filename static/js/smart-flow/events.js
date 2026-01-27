/**
 * Events Module - Smart Flow V2
 * Gerenciamento de Interações (Drag & Drop, Cliques Globais).
 */

const Events = {
    init() {
        this.setupDragDrop();
        this.setupGlobalClicks();
        this.setupInputs();
    },

    setupDragDrop() {
        const grid = document.getElementById('flow-grid');

        // Como os cards são gerados dinamicamente, delegamos no grid
        document.addEventListener('dragstart', (e) => {
            // Se arrastar da Sidebar ou de um Card (se implementarmos drag reverso)
            // Assumimos que o elemento arrastável tem dataset.empId
            if (e.target.dataset.empId) {
                e.dataTransfer.setData('empId', e.target.dataset.empId);
                e.dataTransfer.effectAllowed = 'move';
                e.target.classList.add('opacity-50');
            }
        });

        document.addEventListener('dragend', (e) => {
            if (e.target.dataset.empId) {
                e.target.classList.remove('opacity-50');
            }
        });

        // Drop Zone: Setores
        grid.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessário para permitir o drop
            const card = e.target.closest('[data-sector]');
            if (card) {
                card.classList.add('border-blue-500', 'bg-slate-800/80');
                e.dataTransfer.dropEffect = 'move';
            }
        });

        grid.addEventListener('dragleave', (e) => {
            const card = e.target.closest('[data-sector]');
            if (card) {
                card.classList.remove('border-blue-500', 'bg-slate-800/80');
            }
        });

        grid.addEventListener('drop', (e) => {
            e.preventDefault();
            const card = e.target.closest('[data-sector]');
            if (card) {
                card.classList.remove('border-blue-500', 'bg-slate-800/80');
                const empId = e.dataTransfer.getData('empId');
                const sectorKey = card.dataset.sector;

                if (empId && sectorKey) {
                    Store.moveEmployee(empId, sectorKey);
                }
            }
        });
    },

    setupGlobalClicks() {
        // Fechar modais ao clicar no overlay
        window.closeModal = (id) => {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        };

        // --- Header Actions ---

        window.changeDate = (newDate) => {
            Store.setDate(newDate);
            App.loadData();
        };

        window.changeShift = async (newShift) => {
            // Limpar state imediatamente para evitar valores misturados durante o carregamento
            Store.state.allocations = {};
            Store.state.routines = {};
            Store.state.kpis = { present: 0, target: 0, percent: 0 };

            Store.setShift(newShift);

            // Update layout active state on shift change
            document.querySelectorAll('[data-shift]').forEach(el => {
                if (el.dataset.shift === newShift) {
                    el.classList.add('active');
                } else {
                    el.classList.remove('active');
                }
            });

            // Carregar novos dados (aguardar para evitar race condition)
            await App.loadData();
        };

        window.saveAll = async () => {
            const payload = {
                date: Store.state.currentDate,
                shift: Store.state.currentShift,
                allocations: Store.state.allocations,
                routines: Store.state.routines,
                tonnage: Store.state.tonnage
            };

            console.log('💾 SALVANDO MANUALMENTE:');
            console.log('📅 Date:', payload.date);
            console.log('🕐 Shift:', payload.shift);
            console.log('📊 Allocations:', payload.allocations);
            console.log('📋 Routines:', payload.routines);
            console.log('📦 Payload JSON:', JSON.stringify(payload, null, 2));

            try {
                const result = await API.saveAllocations(payload);
                if (result.success) {
                    alert('✅ Alocações salvas com sucesso!');
                    Store.state.isDirty = false;
                } else {
                    console.error('❌ Resultado do servidor:', result);
                    alert('❌ Erro ao salvar. Verifique o console.');
                }
            } catch (err) {
                console.error('❌ Erro na requisição:', err);
                alert('❌ Erro ao salvar. Verifique o console.');
            }
        };

        window.closeShift = () => {
            if (!confirm("Tem certeza que deseja encerrar este turno?")) return;

            // Salvar antes de encerrar
            API.saveAllocations({
                date: Store.state.currentDate,
                shift: Store.state.currentShift,
                allocations: Store.state.allocations,
                routines: Store.state.routines,
                tonnage: Store.state.tonnage
            }).then(() => {
                alert('✅ Turno encerrado e salvo!');
                // Redirecionar para daily operations
                window.location.href = `/daily_operations?date=${Store.state.currentDate}`;
            }).catch(err => {
                console.error('Error closing shift:', err);
                alert('❌ Erro ao encerrar turno. Verifique o console.');
            });
        };

        window.createSector = () => {
            // Abrir modal de criação de setor
            SectorsCRUD.openCreateSector();
        };

        // --- KPI & Details ---

        window.openDashboardDetail = (type) => {
            console.log('Open detail:', type);
            // Implementar lógica de detalhe se necessário
        };

        window.editTonnage = () => {
            alert('A produção é calculada automaticamente a partir da Separação (Rotas).');
        };
    },

    setActivity(empId, activity) {
        console.log(`Setting activity for ${empId}: ${activity}`);

        // Validação de Ausência (Incluindo Status Permanente)
        const emp = Store.state.employees.find(e => e.id == empId);
        const currentRoutine = Store.state.routines[empId] || (emp ? emp.status : null);

        if (currentRoutine && ['absent', 'sick', 'vacation', 'away', 'falta', 'atestado', 'ferias', 'afastado', 'dayoff', 'folga'].includes(currentRoutine.toLowerCase())) {
            const routineMap = {
                'absent': 'Falta', 'falta': 'Falta',
                'sick': 'Atestado', 'atestado': 'Atestado',
                'vacation': 'Férias', 'ferias': 'Férias',
                'away': 'Afastado', 'afastado': 'Afastado',
                'dayoff': 'Folga', 'folga': 'Folga'
            };
            const statusName = routineMap[currentRoutine.toLowerCase()] || currentRoutine;

            if (!confirm(`O colaborador está marcado com ${statusName}. Deseja remover a ausência e iniciar esta atividade?`)) {
                return;
            }
            // Se confirmou, a rotina será atualizada para 'present' automaticamente pelo Store.updateActivity
        }

        const obsInput = document.getElementById('activity-observation');
        const observation = obsInput ? obsInput.value.trim() : null;

        Store.updateActivity(empId, activity, observation);
        Render.closeBottomSheet();
    },

    setRoutine(empId, routine) {
        console.log(`Setting routine for ${empId}: ${routine}`);
        const obsInput = document.getElementById('activity-observation');
        const observation = obsInput ? obsInput.value.trim() : null;

        // Limpar atividade atual
        if (Store.state.activities[empId]) {
            Store.updateActivity(empId, null, observation);
        }

        Store.updateRoutine(empId, routine);
        Render.closeBottomSheet();
    },

    async setExtendedRoutine(empId, routine) {
        const startDate = document.getElementById('routine-start-date').value;
        // Para 'away', days pode estar oculto/vazio. Assumir 1 ou backend deve lidar.
        const daysInput = document.getElementById('routine-days');
        const days = daysInput ? parseInt(daysInput.value) : 1;

        console.log(`Extended Routine: ${empId}, ${routine}, Start: ${startDate}, Days: ${days}`);

        // Validação básica
        if (!startDate) {
            alert('Por favor, selecione uma data de início.');
            return;
        }

        if (days < 1 || days > 365) {
            alert('A quantidade de dias deve estar entre 1 e 365.');
            return;
        }

        // Chamar API para criar rotina estendida
        try {
            const result = await API.setEmployeeRoutineExtended(empId, routine, startDate, days);
            
            if (result.success) {
                // Atualizar Store localmente para refletir mudanças
                Store.updateRoutine(empId, routine);
                
                // Mostrar mensagem de sucesso
                const routineLabels = {
                    'present': 'Presente',
                    'vacation': 'Férias',
                    'sick': 'Atestado',
                    'away': 'Afastado',
                    'absent': 'Falta',
                    'dayoff': 'Folga'
                };
                const label = routineLabels[routine] || routine;
                
                alert(`✅ ${result.message || `Rotina de ${label} criada com sucesso para ${days} dias`}`);
                
                // Fechar bottom sheet
                Render.closeBottomSheet();
                
                // Recarregar página se estiver na página de detalhes do colaborador
                if (window.location.pathname.includes('/employees/')) {
                    setTimeout(() => {
                        window.location.reload();
                    }, 500);
                }
            } else {
                // Mostrar erro (pode ser conflito)
                if (result.error) {
                    alert(`❌ Erro: ${result.error}`);
                } else {
                    alert('❌ Erro ao criar rotina estendida.');
                }
            }
        } catch (error) {
            console.error('Error setting extended routine:', error);
            alert(`❌ Erro: ${error.message || 'Erro ao criar rotina estendida'}`);
        }
    },

    setupInputs() {
        // Date & Shift pickers
        const dateInput = document.getElementById('date-filter');
        const shiftInput = document.getElementById('shift-filter');

        if (dateInput) {
            dateInput.onchange = (e) => {
                Store.setDate(e.target.value);
                App.loadData();
            };
        }

        if (shiftInput) {
            shiftInput.onchange = (e) => {
                Store.setShift(e.target.value);
                App.loadData();
            };
        }
    }
};

window.Events = Events;
