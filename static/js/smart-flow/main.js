/**
 * Main App Module - Smart Flow V2
 * Ponto de entrada.
 */

const App = {
    async init() {
        console.log('🚀 Smart Flow V2 Starting...');

        // 1. Inicializar Store com dados injetados
        if (typeof INITIAL_DATA !== 'undefined') {
            Store.init(INITIAL_DATA);
        } else {
            console.error('CRITICAL: INITIAL_DATA not found.');
        }

        // 2. Inicializar Renderizador
        Render.init();

        // 3. Inicializar Eventos
        Events.init();

        // 4. Subscrever Renderizador ao Store
        Store.subscribe((state) => {
            Render.update(state);
        });

        // 5. Carregar dados da API
        await this.loadData();

        console.log('✅ Smart Flow V2 Ready.');
    },

    async loadData() {
        const { currentDate, currentShift } = Store.state;

        // Carregar setores
        const sectorsData = await API.loadSectors(currentShift);

        // Carregar alocações e rotinas
        const allocData = await API.loadAllocations(currentDate, currentShift);

        // Atualizar Store
        Store.setData({
            sectors: sectorsData.sectors || [],
            allocations: allocData.allocations || {},
            routines: allocData.routines || {}
        });
    }
};

// Start
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
