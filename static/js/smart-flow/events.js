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

        window.changeShift = (newShift) => {
            Store.setShift(newShift);
            App.loadData();
            // Update layout active state on shift change
            document.querySelectorAll('[data-shift]').forEach(el => {
                if (el.dataset.shift === newShift) {
                    el.classList.add('active');
                } else {
                    el.classList.remove('active');
                }
            });
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
        const days = parseInt(document.getElementById('routine-days').value);

        console.log(`Extended Routine: ${empId}, ${routine}, Start: ${startDate}, Days: ${days}`);

        // Validação simples
        if (days > 1) {
            // TODO: Implementar lógica de backend para range dates
            alert(`ℹ️ Registro de ${days} dias: O sistema salvou o status para HOJE (${startDate}).\n\nO suporte a agendamento futuro automático será ativado na próxima atualização do Backend.`);
        }

        // Aplica para o dia atual (lógica padrão)
        // Se a data selecionada for diferente de hoje, avisar?
        if (startDate !== Store.state.currentDate) {
            alert('Atenção: Você selecionou uma data diferente da visualizada no painel. O registro será aplicado na data visualizada.');
        }

        Store.updateRoutine(empId, routine);
        Render.closeBottomSheet();
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
