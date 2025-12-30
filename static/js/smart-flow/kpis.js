// KPIs Module - Cálculos e atualização de indicadores

// Função principal de atualização de KPIs
function updateKPIs() {
    // Calculate stats
    let totalPresent = 0;

    // Count Present (Anyone present in log is counted)
    Object.values(employees.log).forEach(e => {
        if (e.status === 'present') totalPresent++;
    });

    // Absences/Status Logic (Strict Shift Filtering + Effective Status)
    const listAbsent = getShiftEmployeesByStatus('absent');
    const listSick = getShiftEmployeesByStatus('sick');
    const listVacation = getShiftEmployeesByStatus('vacation');
    const listAway = getShiftEmployeesByStatus('away');

    const dailyAbsences = listAbsent.length;
    const totalSick = listSick.length;
    const vacationCount = listVacation.length;
    const awayCount = listAway.length;

    // Substitution Calculation
    const substitutedCount = [...listAway, ...listVacation].filter(emp => emp.is_substituted).length;

    // Gap Calculation & Total Target
    let totalGap = 0;
    let totalTarget = 0;

    SECTORS.forEach(sec => {
        const demand = sec.target || 0;
        totalTarget += demand;

        // Operational Gap: Count only PRESENT people
        const allocated = Object.values(employees.log).filter(e => e.sector === sec.key && e.status === 'present').length;
        const gap = Math.max(0, demand - allocated);
        totalGap += gap;
    });

    // Presence Percent Logic
    const presencePercent = totalTarget > 0 ? Math.round((totalPresent / totalTarget) * 100) : 0;

    // Production / Person
    let tonnage = 0;

    // Use raw variables instead of DOM scraping
    if (manualTonnage > 0) {
        tonnage = manualTonnage;
    } else {
        tonnage = calculatedTonnage;
    }

    const prodPerPerson = totalPresent > 0 ? Math.round(tonnage / totalPresent) : 0;

    // Update DOM
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val;
    };

    setVal('total-present', totalPresent);
    setVal('total-target-kpi', `${totalPresent} / ${totalTarget}`);
    setVal('present-percent', `${presencePercent}%`);
    setVal('total-gap', totalGap);
    setVal('total-sick', totalSick + dailyAbsences);
    setVal('total-away', awayCount);
    setVal('total-vacation', vacationCount);
    setVal('production-per-person', `${prodPerPerson.toLocaleString('pt-BR')} kg/p`);
}

// Função auxiliar para pegar colaboradores por status
function getShiftEmployeesByStatus(status) {
    return ALL_EMPLOYEES.filter(emp => {
        // Shift filter
        if (emp.shift !== currentShift) return false;

        // Status logic
        const dailyStatus = employees.log[emp.id]?.status;
        const effectiveStatus = dailyStatus || emp.status_master;

        return effectiveStatus === status;
    });
}

// Calcular estatísticas de setor
function getSectorStats(sectorKey) {
    const sectorConfig = SECTORS.find(s => s.key === sectorKey);
    const target = sectorConfig ? (sectorConfig.target || 0) : 0;

    const people = Object.entries(employees.log)
        .filter(([_, entry]) => entry.sector === sectorKey && entry.status === 'present')
        .map(([id, entry]) => ({ ...entry, id }));

    return {
        count: people.length,
        people: people,
        target: target,
        deficit: Math.max(0, target - people.length)
    };
}

// Calcular dados detalhados de todos os setores
function calculateSectorData() {
    const context = {
        shift: currentShift,
        date: currentDate
    };

    // Build people list with daily status
    const peopleList = ALL_EMPLOYEES.map(emp => {
        const daily = employees.log[emp.id] || {};
        return {
            id: emp.id,
            name: emp.name,
            role: emp.role,
            shift: emp.shift,
            cost_center: emp.cost_center,
            status_master: emp.status,
            birthday: emp.birthday,
            admission: emp.admission_date,
            status_daily: daily.status || null,
            sector_daily: daily.sector || null,
            subsector_daily: daily.subsector || null
        };
    });

    // Calculate sector stats
    let totalTarget = 0;
    let totalPresent = 0;

    const sectorsDetailed = SECTORS.map(sec => {
        const target = sec.target || 0;
        totalTarget += target;

        const allocatedPeople = peopleList.filter(p => employees.log[p.id]?.sector === sec.key);
        const presentPeople = allocatedPeople.filter(p => employees.log[p.id]?.status === 'present');

        totalPresent += presentPeople.length;

        return {
            key: sec.key,
            label: sec.label,
            target: target,
            present: presentPeople.length,
            allocated: allocatedPeople.length,
            gap: Math.max(0, target - presentPeople.length),
            people: allocatedPeople.map(p => ({ id: p.id, name: p.name, status: p.status_daily, subsector: p.subsector_daily }))
        };
    });

    // KPIs
    const totalGap = sectorsDetailed.reduce((sum, s) => sum + s.gap, 0);
    const presencePercent = totalTarget > 0 ? Math.round((totalPresent / totalTarget) * 100) : 0;

    // Tonnage & Prod
    let tonnage = 0;
    const tonnageEl = document.getElementById('total-tonnage');
    if (tonnageEl) tonnage = parseInt(tonnageEl.innerText.replace(/\D/g, '')) || 0;
    const prodPerPerson = totalPresent > 0 ? Math.round(tonnage / totalPresent) : 0;

    return {
        context: context,
        sectors: sectorsDetailed,
        kpis: {
            total_target: totalTarget,
            total_present: totalPresent,
            total_gap: totalGap,
            presence_percent: presencePercent,
            tonnage: tonnage,
            prod_per_person: prodPerPerson
        },
        people: peopleList
    };
}
