// Drag & Drop Module - Gerenciamento de arrastar e soltar colaboradores

// Inicializar drag & drop
function initDragDrop() {
    // Implementação será adicionada conforme necessário
    console.log('Drag & Drop inicializado');
}

// Manipular início do arrasto
function handleDragStart(event, empId) {
    event.dataTransfer.setData('empId', empId);
    event.dataTransfer.effectAllowed = 'move';
}

// Manipular soltar
function handleDrop(event, sectorKey) {
    event.preventDefault();

    const empId = event.dataTransfer.getData('empId');
    if (!empId) return;

    // Atualizar log do colaborador
    if (!employees.log[empId]) {
        employees.log[empId] = {};
    }

    employees.log[empId].sector = sectorKey;
    employees.log[empId].status = 'present';

    // Atualizar UI
    renderFlow();
    updateKPIs();
    markDirty();

    logEvent('employee_moved', { empId, sector: sectorKey });
}

// Permitir soltar
function handleDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
}
