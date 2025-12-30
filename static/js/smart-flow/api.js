// API Module - Chamadas ao backend

// Salvar rotina do dia
async function saveRoutine() {
    if (!isDirty()) {
        alert('Nenhuma alteração para salvar');
        return;
    }

    const data = {
        date: currentDate,
        shift: currentShift,
        employees_log: employees.log,
        sector_config: SECTORS,
        events: eventLogger.getEvents()
    };

    try {
        const response = await fetch('/smart-flow/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            clearDirty();
            eventLogger.clear();
            alert('Rotina salva com sucesso!');
        } else {
            alert('Erro ao salvar rotina');
        }
    } catch (error) {
        console.error('Erro:', error);
        alert('Erro de conexão');
    }
}

// Carregar rotina do dia
async function loadRoutine() {
    try {
        const response = await fetch(`/smart-flow/load?date=${currentDate}&shift=${currentShift}`);

        if (response.ok) {
            const data = await response.json();

            if (data.employees_log) {
                employees.log = data.employees_log;
            }

            if (data.sector_config) {
                SECTORS.length = 0;
                SECTORS.push(...data.sector_config);
            }

            renderFlow();
            updateKPIs();
        }
    } catch (error) {
        console.error('Erro ao carregar rotina:', error);
    }
}

// Atualizar status de colaborador
async function updateEmployeeStatus(empId, status) {
    try {
        const response = await fetch(`/employees/${empId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status })
        });

        return response.ok;
    } catch (error) {
        console.error('Erro ao atualizar status:', error);
        return false;
    }
}

// Agendar férias
async function scheduleVacation(empId, startDate, endDate) {
    try {
        const response = await fetch(`/employees/${empId}/vacation`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_date: startDate,
                end_date: endDate
            })
        });

        if (response.ok) {
            return true;
        } else {
            const error = await response.json();
            alert(error.error || 'Erro ao agendar férias');
            return false;
        }
    } catch (error) {
        console.error('Erro:', error);
        alert('Erro de conexão');
        return false;
    }
}
