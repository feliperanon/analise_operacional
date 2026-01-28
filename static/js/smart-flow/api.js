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
    },

    /**
     * Define rotina estendida de um colaborador (múltiplos dias)
     * @param {number} employeeId - ID do colaborador
     * @param {string} routine - Tipo de rotina (absent, sick, etc)
     * @param {string} startDate - Data inicial (YYYY-MM-DD)
     * @param {number} days - Número de dias
     * @param {boolean} updateExisting - Se true, atualiza registros existentes
     */
    async setEmployeeRoutineExtended(employeeId, routine, startDate, days, updateExisting = false) {
        try {
            const response = await fetch('/api/employees/routine/extended', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    employee_id: employeeId,
                    routine: routine,
                    start_date: startDate,
                    days: days,
                    update_existing: updateExisting
                }),
                signal: AbortSignal.timeout(30000) // Timeout de 30 segundos
            });
            
            // Verificar se a resposta é JSON válida
            let result;
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                result = await response.json();
            } else {
                const text = await response.text();
                throw new Error(`Resposta inválida do servidor: ${text.substring(0, 100)}`);
            }
            
            if (!response.ok) {
                // Se houver conflito (409), retornar resultado com can_update para o chamador decidir
                if (response.status === 409 && result.can_update) {
                    return { 
                        success: false, 
                        canUpdate: true,
                        conflicts: result.conflicts,
                        error: result.error 
                    };
                }
                throw new Error(result.error || `Erro ${response.status}: Erro ao definir rotina estendida`);
            }
            
            return result;
        } catch (error) {
            console.error('API Error:', error);
            // Tratar diferentes tipos de erro
            if (error.name === 'AbortError' || error.message.includes('timeout')) {
                return { success: false, error: 'Tempo de espera esgotado. Tente novamente.' };
            }
            if (error.message.includes('Failed to fetch') || error.message.includes('ERR_CONNECTION_RESET')) {
                return { success: false, error: 'Erro de conexão com o servidor. Verifique sua internet e tente novamente.' };
            }
            return { success: false, error: error.message || 'Erro desconhecido ao definir rotina estendida' };
        }
    }
};

window.API = API; // Expor globalmente
