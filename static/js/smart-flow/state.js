// Estado global do Smart Flow

// Variáveis de contexto
let currentShift = 'Manhã';
let currentDate = new Date().toISOString().split('T')[0];
let shiftTargetHr = 0;

// Configuração de setores
let SECTORS = [];

// Dados de colaboradores
let employees = {
    log: {}  // { empId: { sector, subsector, status } }
};

let ALL_EMPLOYEES = [];

// Variáveis de tonelagem
let manualTonnage = 0;
let calculatedTonnage = 0;

// Event Logger
class EventLog {
    constructor() {
        this.events = [];
    }

    add(type, payload) {
        this.events.push({
            timestamp: new Date().toISOString(),
            type: type,
            payload: payload,
            context: { shift: currentShift, date: currentDate }
        });
        console.log(`[EventLog] ${type}`, payload);
    }

    getEvents() {
        return this.events;
    }

    clear() {
        this.events = [];
    }
}

const eventLogger = new EventLog();

function logEvent(type, payload) {
    eventLogger.add(type, payload);
    markDirty();
}

// Estado de dirty flag
let isDirtyFlag = false;

// Getters e setters
function getCurrentShift() { return currentShift; }
function setCurrentShift(shift) { currentShift = shift; }
function getCurrentDate() { return currentDate; }
function setCurrentDate(date) { currentDate = date; }
function markDirty() { isDirtyFlag = true; }
function clearDirty() { isDirtyFlag = false; }
function isDirty() { return isDirtyFlag; }

// Funções de mudança de turno e data
function changeShift(shift) {
    currentShift = shift;

    // Atualizar UI
    document.querySelectorAll('.shift-btn').forEach(btn => {
        if (btn.textContent.includes(shift)) {
            btn.classList.add('bg-blue-600', 'text-white');
            btn.classList.remove('bg-slate-700', 'text-slate-300');
        } else {
            btn.classList.remove('bg-blue-600', 'text-white');
            btn.classList.add('bg-slate-700', 'text-slate-300');
        }
    });

    // Recarregar dados
    loadRoutine();
    renderFlow();
    updateKPIs();
}

function changeDate(date) {
    currentDate = date;
    loadRoutine();
    renderFlow();
    updateKPIs();
}
