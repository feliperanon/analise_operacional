/**
 * Sectors CRUD Module - Smart Flow V3
 * Gerenciamento de Setores e Sub-setores
 */

const SectorsCRUD = {
    currentSectorId: null,
    currentSubSectorId: null,

    // Abrir modal de criação de setor
    openCreateSector() {
        document.getElementById('sector-modal-title').textContent = 'Novo Setor';
        document.getElementById('sector-id').value = '';
        document.getElementById('sector-name').value = '';
        document.getElementById('sector-max').value = '0';
        document.getElementById('sector-color').value = 'blue';
        document.getElementById('sector-crud-modal').classList.remove('hidden');
    },

    // Abrir modal de edição de setor
    openEditSector(sectorId, name, maxEmployees, color) {
        document.getElementById('sector-modal-title').textContent = 'Editar Setor';
        document.getElementById('sector-id').value = sectorId;
        document.getElementById('sector-name').value = name;
        document.getElementById('sector-max').value = maxEmployees;
        document.getElementById('sector-color').value = color;
        document.getElementById('sector-crud-modal').classList.remove('hidden');
    },

    // Salvar setor (criar ou editar)
    async saveSector() {
        const sectorId = document.getElementById('sector-id').value;
        const name = document.getElementById('sector-name').value;
        const maxEmployees = document.getElementById('sector-max').value;
        const color = document.getElementById('sector-color').value;
        const shift = Store.state.currentShift;

        if (!name.trim()) {
            alert('Nome do setor é obrigatório');
            return;
        }

        const formData = new FormData();
        formData.append('name', name);
        formData.append('max_employees', maxEmployees);
        formData.append('color', color);
        formData.append('shift', shift);

        try {
            let response;
            if (sectorId) {
                // Editar
                response = await fetch(`/api/smart-flow/sectors/${sectorId}`, {
                    method: 'PUT',
                    body: formData
                });
            } else {
                // Criar
                response = await fetch('/api/smart-flow/sectors', {
                    method: 'POST',
                    body: formData
                });
            }

            const result = await response.json();
            if (result.success) {
                this.closeModal('sector-crud-modal');
                await App.loadData(); // Recarregar dados
            } else {
                alert('Erro ao salvar setor');
            }
        } catch (error) {
            console.error('Error saving sector:', error);
            alert('Erro ao salvar setor');
        }
    },

    // Excluir setor
    async deleteSector(sectorId, sectorName) {
        if (!confirm(`Tem certeza que deseja excluir o setor "${sectorName}"? Todas as alocações serão removidas.`)) {
            return;
        }

        try {
            const response = await fetch(`/api/smart-flow/sectors/${sectorId}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            if (result.success) {
                await App.loadData(); // Recarregar dados
            } else {
                alert('Erro ao excluir setor');
            }
        } catch (error) {
            console.error('Error deleting sector:', error);
            alert('Erro ao excluir setor');
        }
    },

    // Abrir modal de criação de sub-setor
    openCreateSubSector(sectorId) {
        document.getElementById('subsector-modal-title').textContent = 'Novo Sub-setor';
        document.getElementById('subsector-id').value = '';
        document.getElementById('subsector-sector-id').value = sectorId;
        document.getElementById('subsector-name').value = '';
        document.getElementById('subsector-max').value = '0';
        document.getElementById('subsector-crud-modal').classList.remove('hidden');
    },

    // Abrir modal de edição de sub-setor
    openEditSubSector(subsectorId, sectorId, name, maxEmployees) {
        document.getElementById('subsector-modal-title').textContent = 'Editar Sub-setor';
        document.getElementById('subsector-id').value = subsectorId;
        document.getElementById('subsector-sector-id').value = sectorId;
        document.getElementById('subsector-name').value = name;
        document.getElementById('subsector-max').value = maxEmployees;
        document.getElementById('subsector-crud-modal').classList.remove('hidden');
    },

    // Salvar sub-setor
    async saveSubSector() {
        const subsectorId = document.getElementById('subsector-id').value;
        const sectorId = document.getElementById('subsector-sector-id').value;
        const name = document.getElementById('subsector-name').value;
        const maxEmployees = document.getElementById('subsector-max').value;

        if (!name.trim()) {
            alert('Nome do sub-setor é obrigatório');
            return;
        }

        const formData = new FormData();
        formData.append('sector_id', sectorId);
        formData.append('name', name);
        formData.append('max_employees', maxEmployees);

        try {
            let response;
            if (subsectorId) {
                // Editar
                response = await fetch(`/api/smart-flow/subsectors/${subsectorId}`, {
                    method: 'PUT',
                    body: formData
                });
            } else {
                // Criar
                response = await fetch('/api/smart-flow/subsectors', {
                    method: 'POST',
                    body: formData
                });
            }

            const result = await response.json();
            if (result.success) {
                this.closeModal('subsector-crud-modal');
                await App.loadData(); // Recarregar dados
            } else {
                alert('Erro ao salvar sub-setor');
            }
        } catch (error) {
            console.error('Error saving subsector:', error);
            alert('Erro ao salvar sub-setor');
        }
    },

    // Excluir sub-setor
    async deleteSubSector(subsectorId, subsectorName) {
        if (!confirm(`Tem certeza que deseja excluir o sub-setor "${subsectorName}"? Todas as alocações serão removidas.`)) {
            return;
        }

        try {
            const response = await fetch(`/api/smart-flow/subsectors/${subsectorId}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            if (result.success) {
                await App.loadData(); // Recarregar dados
            } else {
                alert('Erro ao excluir sub-setor');
            }
        } catch (error) {
            console.error('Error deleting subsector:', error);
            alert('Erro ao excluir sub-setor');
        }
    },

    closeModal(modalId) {
        document.getElementById(modalId).classList.add('hidden');
    }
};

// Expor globalmente
window.SectorsCRUD = SectorsCRUD;
window.createSector = () => SectorsCRUD.openCreateSector();
window.saveSector = () => SectorsCRUD.saveSector();
window.saveSubSector = () => SectorsCRUD.saveSubSector();
window.closeModal = (id) => SectorsCRUD.closeModal(id);
