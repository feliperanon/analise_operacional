// Inicialização do Smart Flow
document.addEventListener('DOMContentLoaded', () => {
    console.log('Smart Flow inicializado');

    // Inicializar variáveis globais com dados do servidor
    if (typeof INITIAL_DATA !== 'undefined') {
        ALL_EMPLOYEES = INITIAL_DATA.all_employees || [];

        if (INITIAL_DATA.config && INITIAL_DATA.config.sectors) {
            SECTORS = INITIAL_DATA.config.sectors;
        }

        if (INITIAL_DATA.employees) {
            employees.log = INITIAL_DATA.employees;
        }
    }

    // Inicializar drag & drop
    initDragDrop();

    // Carregar rotina do dia
    loadRoutine();

    // Renderizar interface inicial
    renderFlow();
    updateKPIs();

    console.log('✅ Smart Flow pronto');
});
