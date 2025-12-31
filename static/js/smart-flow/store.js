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
    allocateEmployee(empId, subsectorId) {
        if (!empId || !subsectorId) return;

        this.state.allocations[empId] = subsectorId;

        // Inicializar rotina como presente se não existir
        if (!this.state.routines[empId]) {
            this.state.routines[empId] = 'present';
        }

        this.state.isDirty = true;
        this.notify();
        this.autoSave();
    },

    // Remover alocação de colaborador
    removeAllocation(empId) {
        if (this.state.allocations[empId]) {
            delete this.state.allocations[empId];
            this.state.isDirty = true;
            this.notify();
            this.autoSave();
        }
    },

    // Atualizar rotina do colaborador
    updateRoutine(empId, routine) {
        this.state.routines[empId] = routine;
        this.state.isDirty = true;
        this.notify();
        this.autoSave();
    },

    // Atualizar Tonelagem
    updateTonnage(val) {
        this.state.tonnage = val;
        this.state.isDirty = true;
        this.notify();
        this.autoSave();
    },

    // --- Computed Logic (KPIs) ---
    computeKPIs() {
        const { employees, sectors, allocations, routines, currentShift } = this.state;

        console.log('Computing KPIs:', {
            totalEmployees: employees.length,
            currentShift,
            sectors: sectors.length,
            allocations: Object.keys(allocations).length
        });

        // Filtrar funcionários do turno (campo correto é work_shift, não shift)
        const shiftEmps = employees.filter(e => {
            if (!e.shift && !e.work_shift) return false;
            const empShift = e.shift || e.work_shift;
            return empShift && empShift.toLowerCase().includes(currentShift.toLowerCase());
        });

        console.log('Shift employees:', shiftEmps.length);

        // Contadores de rotinas
        let present = 0;
        let sick = 0;
        let vacation = 0;
        let away = 0;
        let missing = 0;

        // Contar por rotina
        Object.entries(routines).forEach(([empId, routine]) => {
            const emp = employees.find(e => e.id == empId);
            if (!emp) return;

            const empShift = emp.shift || emp.work_shift;
            if (!empShift || empShift !== currentShift) return;

            if (routine === 'present') present++;
            else if (routine === 'sick') sick++;
            else if (routine === 'vacation') vacation++;
            else if (routine === 'away') away++;
            else if (routine === 'absent') missing++;
        });

        // Contar alocados (presentes operacionais)
        const operationalPresent = Object.keys(allocations).filter(empId => {
            const emp = employees.find(e => e.id == empId);
            if (!emp) return false;
            const empShift = emp.shift || emp.work_shift;
            return empShift && empShift === currentShift;
        }).length;

        // Calcular target total
        let totalTarget = 0;
        sectors.forEach(sector => {
            totalTarget += sector.max_employees || 0;
        });

        const totalGap = Math.max(0, totalTarget - operationalPresent);

        // Produtividade
        const prod = operationalPresent > 0 ? Math.round(this.state.tonnage / operationalPresent) : 0;

        this.state.kpis = {
            headcount: shiftEmps.length,
            present: operationalPresent,
            target: totalTarget,
            gap: totalGap,
            sick,
            vacation,
            away,
            missing,
            tonnage: this.state.tonnage,
            productivity: prod,
            percent: totalTarget > 0 ? Math.round((operationalPresent / totalTarget) * 100) : 0
        };

        console.log('KPIs computed:', this.state.kpis);
    },

    // Debounce Save
    saveTimeout: null,
    autoSave() {
        if (this.saveTimeout) clearTimeout(this.saveTimeout);
        this.saveTimeout = setTimeout(() => {
            console.log('Auto-saving...');
            API.saveAllocations({
                date: this.state.currentDate,
                shift: this.state.currentShift,
                allocations: this.state.allocations,
                routines: this.state.routines,
                tonnage: this.state.tonnage
            });
        }, 2000);
    }
};

window.Store = Store; // Expor globalmente
