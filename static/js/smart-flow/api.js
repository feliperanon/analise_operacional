/**
 * API Module - Smart Flow V2
 * Responsável por toda comunicação com o Backend.
 */

const API = {
    /**
     * Carrega a rotina do dia/turno
     */
    async loadRoutine(date, shift) {
        try {
            const response = await fetch(`/api/smart-flow/routine?date=${date}&shift=${shift}`);
            if (!response.ok) throw new Error('Erro ao carregar rotina');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            // Retorna estrutura vazia em caso de erro para não quebrar a UI
            return { log: {}, tonnage: 0, sectors_config: [] };
        }
    },

    /**
     * Salva o estado atual (log de alocações)
     */
    async saveRoutine(payload) {
        try {
            const response = await fetch('/api/smart-flow/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) throw new Error('Erro ao salvar');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { success: false };
        }
    },

    /**
     * Adiciona um novo colaborador
     */
    async addEmployee(data) {
        // Implementar se necessário endpoint via AJAX, 
        // ou manter o form submit tradicional do HTML se preferir.
    },

    /**
     * Reseta a rotina do dia
     */
    async resetRoutine(date, shift) {
        try {
            const response = await fetch('/api/smart-flow/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date, shift })
            });
            return await response.json();
        } catch (error) {
            console.error('API Reset Error:', error);
            return { success: false };
        }
    },

    /**
     * Carrega setores e sub-setores do turno
     */
    async loadSectors(shift) {
        try {
            const response = await fetch(`/api/smart-flow/sectors?shift=${shift}`);
            if (!response.ok) throw new Error('Erro ao carregar setores');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { sectors: [] };
        }
    },

    /**
     * Carrega alocações e rotinas do dia/turno
     */
    async loadAllocations(date, shift) {
        try {
            const response = await fetch(`/api/smart-flow/allocations?date=${date}&shift=${shift}`);
            if (!response.ok) throw new Error('Erro ao carregar alocações');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { allocations: {}, routines: {} };
        }
    },

    /**
     * Salva alocações e rotinas
     */
    async saveAllocations(payload) {
        try {
            const response = await fetch('/api/smart-flow/allocations/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) throw new Error('Erro ao salvar alocações');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { success: false };
        }
    },

    /**
     * Define férias de um colaborador
     */
    async setEmployeeVacation(employeeId, vacationStart, vacationEnd) {
        try {
            const response = await fetch('/api/employees/vacation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    employee_id: employeeId,
                    vacation_start: vacationStart,
                    vacation_end: vacationEnd
                })
            });
            if (!response.ok) throw new Error('Erro ao definir férias');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Define rotina de um colaborador
     */
    async setEmployeeRoutine(employeeId, routine) {
        try {
            const response = await fetch('/api/employees/routine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    employee_id: employeeId,
                    routine: routine
                })
            });
            if (!response.ok) throw new Error('Erro ao definir rotina');
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            return { success: false, error: error.message };
        }
    }
};

window.API = API; // Expor globalmente
