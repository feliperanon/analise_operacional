/**
 * Store Module - Smart Flow V2
 * Gerenciamento Centralizado de Estado.
 * Single Source of Truth.
 */

const Store = {
    // --- Estado ---
    state: {
        currentDate: new Date().toISOString().split('T')[0],
        currentShift: 'Manhã',
        employees: [],      // Lista completa de colaboradores
        sectors: [],        // Setores hierárquicos com sub-setores
        allocations: {},    // Alocações: { empId: subsectorId }
        routines: {},       // Rotinas: { empId: 'present'|'absent'|'sick'|'vacation'|'away' }
        kpis: {},           // Indicadores calculados
        filters: {          // Filtros da sidebar
            search: '',
            status: 'all' // all, present, missing
        },
        tonnage: 0,
        isDirty: false      // Se houve alteração não salva
    },

    // --- Listeners ---
    listeners: [],

    subscribe(callback) {
        this.listeners.push(callback);
    },

    notify() {
        this.computeKPIs(); // Recalcula KPIs antes de notificar
        this.listeners.forEach(cb => cb(this.state));
    },

    // --- Actions (Mutations) ---

    // Inicialização
    init(initialData) {
        this.state.employees = initialData.employees || [];
        // Converte setores string em objetos se vierem simples, ou usa config
        this.state.sectors = initialData.sectors || [];
        console.log('Store initialized:', this.state.employees.length, 'employees');
    },

    // Carregar dados completos
    setData(data) {
        this.state.sectors = data.sectors || [];
        this.state.allocations = data.allocations || {};
        this.state.routines = data.routines || {};
        this.state.tonnage = data.tonnage || 0;
        this.state.isDirty = false;
        this.notify(); // Importante: notificar mudanças!
    },

    setShift(shift) {
        this.state.currentShift = shift;
        this.notify(); // UI deve recarregar dados
    },

    setDate(date) {
        this.state.currentDate = date;
        this.notify();
    },

    setFilter(type, value) {
        this.state.filters[type] = value;
        this.notify();
    },

    // Alocar colaborador em sub-setor
    allocateEmployee(employeeId, subsectorId) {
        this.state.allocations[employeeId] = subsectorId;
        this.state.isDirty = true;
        this.notify();
        this.autoSave(); // Reabilitado - erro 500 resolvido
    },

    // Remover alocação de colaborador
    removeAllocation(empId) {
        const wasAllocated = this.state.allocations.hasOwnProperty(empId);
        if (wasAllocated) {
            delete this.state.allocations[empId];
            delete this.state.routines[empId]; // Também remover rotina
            this.state.isDirty = true;
            this.notify();
            this.autoSave(); // Reabilitado - erro 500 resolvido
            console.log(`🗑️ Colaborador ${empId} removido (alocação e rotina)`);
        }
    },

    // Atualizar rotina do colaborador
    updateRoutine(empId, routine) {
        this.state.routines[empId] = routine;
        this.state.isDirty = true;
        this.notify();
        this.autoSave(); // Reabilitado - erro 500 resolvido
    },

    // Atualizar Tonelagem
    updateTonnage(val) {
        this.state.tonnage = val;
        this.state.isDirty = true;
        this.notify();
        this.autoSave(); // Reabilitado - erro 500 resolvido
    },

    // --- Computed Logic (KPIs) ---
    computeKPIs() {
        const { employees, sectors, allocations, routines, currentShift } = this.state;

        console.log('Computing KPIs:', {
            totalEmployees: employees.length,
            currentShift,
            sectors: sectors.length,
            allocations: Object.keys(allocations).length,
            routines: Object.keys(routines).length
        });

        // Filtrar funcionários do turno - usar comparação exata
        const shiftEmps = employees.filter(e => {
            const empShift = e.work_shift ?? e.shift ?? null;
            if (!empShift) {
                console.warn('Employee without shift:', e.id, e.name);
                return false;
            }
            // Comparação exata (case-insensitive) para evitar matches incorretos
            return empShift.toLowerCase() === currentShift.toLowerCase();
        });

        console.log('Shift employees:', shiftEmps.length, 'for shift:', currentShift);

        // Contadores de status
        let present = 0;
        let sick = 0;
        let vacation = 0;
        let away = 0;
        let missing = 0;

        // Contar status baseado em rotinas (prioridade) ou status do employee
        shiftEmps.forEach(emp => {
            // Priorizar rotina do dia, depois status do employee
            const routine = this.state.routines[emp.id];
            const status = routine || emp.status || 'active';
            const normalizedStatus = status.toLowerCase();

            // Apenas contar como presente se routine for 'present' ou não houver rotina e status for 'active'/'ativo'
            if (normalizedStatus === 'present' ||
                (!routine && (normalizedStatus === 'active' || normalizedStatus === 'ativo'))) {
                present++;
            } else if (normalizedStatus === 'sick' || normalizedStatus === 'atestado') {
                sick++;
            } else if (normalizedStatus === 'vacation' || normalizedStatus === 'férias' || normalizedStatus === 'ferias') {
                vacation++;
            } else if (normalizedStatus === 'away' || normalizedStatus === 'afastado') {
                away++;
            } else if (normalizedStatus === 'absent' || normalizedStatus === 'falta') {
                missing++;
            } else if (normalizedStatus === 'dayoff' || normalizedStatus === 'folga') {
                // Folga não conta como presente
                // Não incrementa nenhum contador específico
            } else if (normalizedStatus === 'fired' || normalizedStatus === 'demitido') {
                // Demitido - não conta como presente (usado para cálculo de vagas)
                // Não incrementa nenhum contador específico
            } else {
                // Default: se não for nenhuma rotina especial e não houver rotina definida, conta como presente
                if (!routine) {
                    console.warn('Unknown status for employee:', emp.name, '- status:', status);
                    present++;
                }
            }
        });

        console.log('Status breakdown:', { present, sick, vacation, away, missing });

        // Contar alocados (presentes operacionais)
        const operationalPresent = Object.keys(allocations).filter(empId => {
            const emp = employees.find(e => e.id == empId);
            if (!emp) return false;
            const empShift = emp.work_shift ?? emp.shift ?? null;
            return empShift && empShift.toLowerCase() === currentShift.toLowerCase();
        }).length;

        // Calcular target total (total de colaboradores ATIVOS do turno)
        const totalTarget = shiftEmps.length;

        // Calcular vagas REAIS (colaboradores demitidos do turno)
        // Buscar TODOS os colaboradores do turno (incluindo demitidos)
        const allShiftEmps = employees.filter(e => {
            const empShift = e.work_shift ?? e.shift ?? null;
            if (!empShift) return false;
            return empShift.toLowerCase() === currentShift.toLowerCase();
        });

        // Contar demitidos
        const fired = allShiftEmps.filter(e => {
            const status = (e.status || 'active').toLowerCase();
            return status === 'fired' || status === 'demitido';
        }).length;

        // Produtividade
        const prod = present > 0 ? Math.round(this.state.tonnage / present) : 0;

        this.state.kpis = {
            headcount: shiftEmps.length,
            present: present,
            target: totalTarget,
            gap: fired, // Vagas = demitidos
            sick,
            vacation,
            away,
            missing,
            tonnage: this.state.tonnage,
            productivity: prod,
            percent: totalTarget > 0 ? Math.round((present / totalTarget) * 100) : 0
        };

        console.log('KPIs computed:', this.state.kpis);
    },

    // Debounce Save
    saveTimeout: null,
    autoSave() {
        if (this.saveTimeout) clearTimeout(this.saveTimeout);
        this.saveTimeout = setTimeout(async () => { // Adicionado async aqui
            const payload = {
                date: this.state.currentDate,
                shift: this.state.currentShift,
                allocations: this.state.allocations,
                routines: this.state.routines
            };

            console.log('💾 Salvando alocações:');
            console.log('📅 Date:', payload.date);
            console.log('🕐 Shift:', payload.shift);
            console.log('📊 Allocations:', payload.allocations);
            console.log('📋 Routines:', payload.routines);
            console.log('📦 Payload completo:', JSON.stringify(payload, null, 2));

            const result = await API.saveAllocations(payload);

            if (result.success) {
                console.log('✅ Alocações salvas com sucesso');
            } else {
                console.error('❌ Erro ao salvar alocações:', result);
                alert('Erro ao salvar alocações. Verifique o console para mais detalhes.');
            }
        }, 2000);
    }
};

window.Store = Store; // Expor globalmente
