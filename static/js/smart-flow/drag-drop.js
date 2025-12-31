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

// Renderizar pool de colaboradores (Sidebar)
function renderPool(filter = 'all') {
    const container = document.getElementById('pool-list');
    const countEl = document.getElementById('pool-count');
    const searchVal = normalizeStr(document.getElementById('files-search').value);

    if (!container) return;

    container.innerHTML = '';

    // Normalizar turno atual
    const curShiftNorm = normalizeStr(currentShift);

    const filtered = ALL_EMPLOYEES.filter(emp => {
        // 1. Filtro de Turno (Deve pertencer ao turno atual)
        // Se o turno do colaborador for diferente do atual, ele não aparece no pool inicial
        const empShiftNorm = normalizeStr(emp.shift || "");
        if (!empShiftNorm.includes(curShiftNorm)) return false;

        // 2. Filtro de Alocação
        // Se já estiver alocado em algum setor, não aparece no pool (drag source)
        if (employees.log[emp.id] && employees.log[emp.id].sector) return false;

        // 3. Filtro de Busca
        if (searchVal && !normalizeStr(emp.name).includes(searchVal)) return false;

        // 4. Filtro de Status Rápido
        const status = employees.log[emp.id] ? employees.log[emp.id].status : emp.status;

        if (filter === 'present') {
            return status === 'active' || status === 'present';
        } else if (filter === 'missing') {
            return status === 'absent' || status === 'sick' || status === 'vacation';
        }

        return true;
    });

    if (countEl) countEl.innerText = filtered.length;

    if (filtered.length === 0) {
        container.innerHTML = `<div class="p-4 text-center text-slate-500 text-xs">Nenhum colaborador encontrado para o turno ${currentShift}.</div>`;
        return;
    }

    filtered.forEach(emp => {
        const div = document.createElement('div');
        div.className = 'bg-slate-800 p-2 rounded border border-slate-700 hover:border-blue-500/50 cursor-grab active:cursor-grabbing flex items-center justify-between group transition-all';
        div.draggable = true;
        div.ondragstart = (e) => handleDragStart(e, emp.id);

        // Determinar status para badge
        let statusBadge = '';
        const status = employees.log[emp.id] ? employees.log[emp.id].status : emp.status;

        if (status === 'sick') statusBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">Atestado</span>';
        else if (status === 'vacation') statusBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20">Férias</span>';
        else if (status === 'absent') statusBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">Falta</span>';

        div.innerHTML = `
            <div class="flex items-center gap-2 overflow-hidden">
                <div class="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-[10px] font-bold text-slate-300 border border-slate-600 shrink-0">
                    ${emp.name.charAt(0)}
                </div>
                <div class="overflow-hidden">
                    <p class="text-xs font-medium text-slate-200 truncate leading-tight" title="${emp.name}">${emp.name}</p>
                    <p class="text-[9px] text-slate-500 truncate">${emp.role || 'Operador'}</p>
                </div>
            </div>
            ${statusBadge}
        `;

        // Menu de contexto rápido (opcional)
        // div.oncontextmenu = ...

        container.appendChild(div);
    });
}

let activeFilter = 'all';

function filterPool(type) {
    if (type) activeFilter = type;
    renderPool(activeFilter);
}



// Helpers
function normalizeStr(str) {
    if (!str) return "";
    return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

// Expor funções globalmente para acesso via HTML (onclick)
window.renderPool = renderPool;
window.filterPool = filterPool;
window.initDragDrop = initDragDrop;
window.handleDragStart = handleDragStart;
window.handleDrop = handleDrop;
window.handleDragOver = handleDragOver;

// Expor funções globalmente para acesso via HTML (onclick)
window.renderPool = renderPool;
window.filterPool = filterPool;
window.initDragDrop = initDragDrop;
window.handleDragStart = handleDragStart;
window.handleDrop = handleDrop;
window.handleDragOver = handleDragOver;
