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
        activities: {},     // Atividades reais: { empId: { activity: 'Separation', started_at: '...' } }
        logs: [],           // Histórico de transições de atividades
        kpis: {},           // Indicadores calculados
        filters: {          // Filtros da sidebar
            search: '',
            status: 'all' // all, present, missing
        },
        tonnage: 0,
        targets: {},        // Metas de Headcount por turno
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
        this.state.targets = initialData.targets || {};
        console.log('Store initialized:', this.state.employees.length, 'employees, Targets:', this.state.targets);
    },

    // Carregar dados completos
    setData(data) {
        this.state.sectors = data.sectors || [];
        this.state.allocations = data.allocations || {};
        this.state.routines = data.routines || {};
        this.state.activities = data.activities || {}; // Recuperar atividades atuais
        this.state.logs = data.logs || []; // Recuperar histórico
        this.state.tonnage = data.tonnage || 0;
        if (data.targets) this.state.targets = data.targets; // Update targets if provided
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
        // Validação: Não permitir alocar se estiver faltando ou de atestado/férias
        const emp = this.state.employees.find(e => e.id == employeeId);
        const currentRoutine = this.state.routines[employeeId] || (emp ? emp.status : null);

        if (currentRoutine && ['absent', 'sick', 'vacation', 'away', 'falta', 'atestado', 'ferias', 'afastado', 'dayoff', 'folga'].includes(currentRoutine.toLowerCase())) {
            const routineMap = {
                'absent': 'Falta', 'falta': 'Falta',
                'sick': 'Atestado', 'atestado': 'Atestado',
                'vacation': 'Férias', 'ferias': 'Férias',
                'away': 'Afastado', 'afastado': 'Afastado',
                'dayoff': 'Folga', 'folga': 'Folga'
            };
            const statusName = routineMap[currentRoutine.toLowerCase()] || currentRoutine;
            alert(`Colaborador com status de ${statusName}. Remova a ausência primeiro se deseja alocá-lo.`);
            return;
        }

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

    // Atualizar Atividade (Smart Activity)
    updateActivity(empId, activityName, observation = null) {
        // 1. Snapshot do estado anterior
        const currentActivity = this.state.activities[empId];
        const now = new Date().toISOString();
        const nowBR = new Date().toLocaleString('pt-BR');

        // Se já estava numa atividade, encerrar e logar
        if (currentActivity) {
            this.state.logs.push({
                employee_id: empId,
                activity: currentActivity.activity,
                started_at: currentActivity.started_at,
                ended_at: now,
                duration_minutes: this.diffMinutes(currentActivity.started_at, now),
                observation: currentActivity.observation || null // Persistir observação da atividade anterior
            });
        }

        // 2. Definir nova atividade
        this.state.activities[empId] = {
            activity: activityName,
            started_at: now,
            status: 'active',
            observation: observation // Salvar nova observação
        };

        // 3. Atualizar Rotina Global para 'present' (corrige bug de dupla contagem se estava como falta)
        // Se o colaborador inicia atividade, ele está presente.
        this.updateRoutine(empId, 'present');

        this.state.isDirty = true;
        this.notify();
        this.autoSave();
    },

    // Helper de tempo
    diffMinutes(start, end) {
        const s = new Date(start);
        const e = new Date(end);
        return Math.round((e - s) / 60000);
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

        // Filtrar funcionários do turno - usar comparação exata
        const shiftEmps = employees.filter(e => {
            const empShift = e.work_shift ?? e.shift ?? null;
            if (!empShift) return false;
            // Comparação exata (case-insensitive) para evitar matches incorretos
            return empShift.toLowerCase() === currentShift.toLowerCase();
        });

        // Contadores de status
        let present = 0;
        let sick = 0;
        let vacation = 0;
        let away = 0;
        let missing = 0;
        let dayoff = 0;

        // Contar status baseado em rotinas (prioridade) ou status do employee
        // APENAS para colaboradores ALOCADOS (consistência com Relatório)
        const allocatedEmpIds = Object.keys(allocations);

        allocatedEmpIds.forEach(empId => {
            const emp = employees.find(e => e.id == empId);
            if (!emp) return;

            // Se está alocado neste turno, conta (não filtra por turno do cadastro)
            // A alocação já foi feita para este turno específico

            // Priorizar rotina do dia, depois status do employee
            const routine = this.state.routines[empId];
            let status;
            if (routine) {
                status = routine;
            } else if (emp.status && ['vacation', 'away', 'sick'].includes(emp.status.toLowerCase())) {
                status = emp.status;
            } else {
                status = 'present';
            }
            const normalizedStatus = status.toLowerCase();

            // Classificar por status
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
                dayoff++;
            } else if (normalizedStatus === 'fired' || normalizedStatus === 'demitido') {
                // Demitido - não conta
            } else {
                // Default: presente se não tiver rotina especial
                if (!routine) {
                    present++;
                }
            }
        });

        // Total de alocados (para referência)

        // Calcular target total (total de colaboradores ATIVOS/AFASTADOS do turno, excluindo demitidos)
        // Antes era shiftEmps.length (incluía demitidos)
        // Agora: Total - Demitidos
        const firedCount = shiftEmps.filter(e => {
            const s = (e.status || 'active').toLowerCase();
            return s === 'fired' || s === 'demitido';
        }).length;

        // Use defined target for the current shift, fallback to calculated if not set (legacy behavior)
        // Normalized shift name for key lookup
        let shiftKey = currentShift;
        if (currentShift.toLowerCase() === 'manhã') shiftKey = 'Manhã';
        if (currentShift.toLowerCase() === 'tarde') shiftKey = 'Tarde';
        if (currentShift.toLowerCase() === 'noite') shiftKey = 'Noite';

        const definedTarget = this.state.targets[shiftKey];
        const totalTarget = definedTarget !== undefined ? definedTarget : (shiftEmps.length - firedCount);

        console.group('KPI Debug');
        console.log('Shift:', currentShift);
        console.log('Total in Shift (incl. fired):', shiftEmps.length);
        console.log('Fired Count:', firedCount);
        console.log('Active Workforce (Target):', totalTarget);
        console.log('Present:', present);
        console.groupEnd();

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

        // Log reduzido - apenas em caso de mudanças significativas
        // console.log('KPIs computed:', this.state.kpis);
    },

    // Debounce Save - Otimizado para evitar salvamentos excessivos
    saveTimeout: null,
    isSaving: false,
    autoSave() {
        // Evitar múltiplos salvamentos simultâneos
        if (this.isSaving) {
            console.log('⏳ Salvamento já em andamento, aguardando...');
            return;
        }

        if (this.saveTimeout) clearTimeout(this.saveTimeout);

        // Debounce de 5 segundos (aumentado de 2s para reduzir requests)
        this.saveTimeout = setTimeout(async () => {
            this.isSaving = true;

            const payload = {
                date: this.state.currentDate,
                shift: this.state.currentShift,
                allocations: this.state.allocations,
                routines: this.state.routines,
                tonnage: this.state.tonnage,
                // Mapear logs e activities para serem salvos
                logs: this.state.logs,
                // Nota: O backend pode não esperar 'activities' soltos no root do payload se for um modelo estrito.
                // Vou injetar 'activities' dentro de 'attendance_log' ou similar se necessário.
                // Por hora, vou assumir que 'attendance_log' pode guardar o snapshot atual.
                attendance_log: {
                    activities: this.state.activities
                }
            };

            console.log('💾 Salvando alocações:', {
                date: payload.date,
                shift: payload.shift,
                allocations: Object.keys(payload.allocations).length,
                routines: Object.keys(payload.routines).length
            });

            try {
                const result = await API.saveAllocations(payload);

                if (result.success) {
                    console.log('✅ Alocações salvas com sucesso');
                    this.state.isDirty = false;
                } else {
                    console.error('❌ Erro ao salvar alocações:', result);
                    alert('Erro ao salvar alocações. Verifique o console para mais detalhes.');
                }
            } catch (error) {
                console.error('❌ Exceção ao salvar:', error);
                alert('Erro de conexão ao salvar. Tente novamente.');
            } finally {
                this.isSaving = false;
            }
        }, 5000); // Aumentado de 2000ms para 5000ms
    }
};

window.Store = Store; // Expor globalmente
