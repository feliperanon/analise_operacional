// Modals Module - Gerenciamento de modais

// Abrir modal de setor
function openModal(sectorKey) {
    const modal = document.getElementById('sector-modal');
    if (!modal) return;

    // Implementação será adicionada conforme necessário
    modal.classList.remove('hidden');

    // Carregar dados do setor
    const sectorData = getSectorStats(sectorKey);

    // Atualizar título do modal
    const titleEl = modal.querySelector('.modal-title');
    if (titleEl) {
        const sector = SECTORS.find(s => s.key === sectorKey);
        titleEl.innerText = sector ? sector.label : sectorKey;
    }

    // Renderizar lista de pessoas
    renderSectorPeople(sectorKey, sectorData.people);
}

// Fechar modal
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Renderizar pessoas do setor no modal
function renderSectorPeople(sectorKey, people) {
    const container = document.getElementById('sector-people-list');
    if (!container) return;

    container.innerHTML = people.map(p => `
        <div class="flex items-center justify-between p-2 bg-slate-700 rounded">
            <span>${p.name}</span>
            <button onclick="removePerson('${sectorKey}', '${p.id}')" class="text-red-400 hover:text-red-300">
                Remover
            </button>
        </div>
    `).join('');
}

// Remover pessoa do setor
function removePerson(sectorKey, empId) {
    if (employees.log[empId]) {
        delete employees.log[empId];

        renderFlow();
        updateKPIs();
        markDirty();

        // Atualizar modal
        const sectorData = getSectorStats(sectorKey);
        renderSectorPeople(sectorKey, sectorData.people);
    }
}

// Abrir modal de férias
function openVacationModal(empId) {
    const modal = document.getElementById('vacation-modal');
    if (!modal) return;

    modal.classList.remove('hidden');

    // Armazenar ID do colaborador
    modal.dataset.empId = empId;
}

// Salvar agendamento de férias
async function saveVacationSchedule() {
    const modal = document.getElementById('vacation-modal');
    const empId = modal.dataset.empId;

    const startDate = document.getElementById('vacation-start').value;
    const endDate = document.getElementById('vacation-end').value;

    if (!startDate || !endDate) {
        alert('Preencha as datas');
        return;
    }

    const success = await scheduleVacation(empId, startDate, endDate);

    if (success) {
        closeModal('vacation-modal');
        loadRoutine(); // Recarregar para atualizar status
    }
}

// Editar tonelagem
function editTonnage() {
    const current = manualTonnage || 0;
    const newVal = prompt('Tonelagem (kg):', current);

    if (newVal !== null && !isNaN(newVal)) {
        manualTonnage = parseFloat(newVal);

        const el = document.getElementById('total-tonnage');
        if (el) {
            if (typeof formatBR === 'function') {
                el.innerText = formatBR(manualTonnage) + ' kg';
            } else {
                el.innerText = manualTonnage.toLocaleString('pt-BR') + ' kg';
            }
        }

        updateKPIs();
        markDirty();
    }
}

// Abrir detalhes do dashboard
function openDashboardDetail(type) {
    console.log('Abrindo dashboard:', type);
    // Implementação futura
    alert('Dashboard de ' + type + ' em desenvolvimento');
}
