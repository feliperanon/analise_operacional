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

        window.saveRoutine = () => {
            API.saveRoutine({
                date: Store.state.currentDate,
                shift: Store.state.currentShift,
                log: Store.state.log,
                tonnage: Store.state.tonnage
            }).then(() => {
                alert('Rotina salva com sucesso!');
            });
        };

        window.closeOperation = () => {
            if (confirm("Tem certeza que deseja encerrar a operação deste turno?")) {
                // Implementar lógica de encerramento se houver endpoint específico,
                // ou apenas redirecionar para relatórios.
                window.location.href = `/daily_operations?date=${Store.state.currentDate}`;
            }
        };

        window.createSector = () => {
            alert("Funcionalidade de criar setor visualmente será implementada em breve.");
        };

        // --- KPI & Details ---

        window.openDashboardDetail = (type) => {
            console.log('Open detail:', type);
            // Implementar lógica de detalhe se necessário
        };

        window.editTonnage = () => {
            const newVal = prompt("Nova Tonelagem:", Store.state.tonnage);
            if (newVal && !isNaN(parseInt(newVal))) {
                Store.updateTonnage(parseInt(newVal));
            }
        };
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
