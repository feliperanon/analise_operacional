// Sectors Module - Renderização e gerenciamento de setores

// Renderizar grid de setores
function renderFlow() {
    const container = document.getElementById('flow-grid');
    if (!container) return;

    container.innerHTML = '';

    SECTORS.forEach((sec, idx) => {
        const sectorData = getSectorStats(sec.key);
        const isDeficit = sectorData.deficit > 0;

        const card = document.createElement('div');
        card.innerHTML = `
            <div class="bg-slate-800 border-slate-700 border rounded-xl p-3 flex flex-col justify-between h-32 relative group hover:border-blue-500 hover:shadow-lg transition-all shadow-md cursor-pointer ${isDeficit ? 'border-l-4 border-l-red-500' : 'border-l-4 border-l-emerald-500'}" onclick="openModal('${sec.key}')">
                <!-- Delete Btn -->
                <button onclick="event.stopPropagation(); deleteSector(${idx})" class="absolute -top-2 -right-2 w-5 h-5 bg-red-500 rounded-full text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition shadow-sm z-10 hover:bg-red-600" title="Excluir">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>

                <!-- Header -->
                <div class="flex justify-between items-start">
                    <div class="overflow-hidden">
                        <h3 class="font-bold text-slate-200 text-sm leading-tight truncate" title="${sec.label}">${sec.label}</h3>
                        <span class="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Meta: ${sec.target || 0}</span>
                    </div>
                    <button onclick="event.stopPropagation(); editMeta(${idx})" class="text-[10px] bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded border border-slate-600 hover:bg-slate-600 hover:text-white transition shrink-0 ml-1">${sectorData.count}/${sec.target || 0}</button>
                </div>

                <!-- Progress -->
                <div class="mt-1">
                    <div class="flex justify-between items-end mb-1">
                        ${isDeficit
                ? `<span class="text-[10px] font-bold text-red-400 flex items-center gap-1"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg> -${sectorData.deficit}</span>`
                : `<span class="text-[10px] font-bold text-emerald-400 flex items-center gap-1"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg> OK</span>`
            }
                    </div>
                    <div class="w-full bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
                        <div class="bg-blue-500 h-1.5 rounded-full transition-all duration-500" style="width: ${Math.min(100, (sectorData.count / (sec.target || 1)) * 100)}%"></div>
                    </div>
                </div>

                <!-- People Preview (limit 5) -->
                <div class="flex -space-x-1.5 overflow-hidden pt-1">
                        ${sectorData.people.slice(0, 5).map(p => `
                        <div class="w-5 h-5 rounded-full bg-slate-700 border border-slate-800 flex items-center justify-center text-[9px] font-bold text-slate-300 shrink-0 select-none shadow-sm" title="${p.name}">
                            ${p.name.charAt(0)}
                        </div>
                        `).join('')}
                        ${sectorData.people.length > 5 ? `<div class="w-5 h-5 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-[9px] text-slate-500 shrink-0 shadow-sm">+${sectorData.people.length - 5}</div>` : ''}
                </div>
            </div>
        `;
        container.appendChild(card.firstElementChild);
    });
}

// Deletar setor
function deleteSector(idx) {
    if (!confirm('Excluir este setor?')) return;

    SECTORS.splice(idx, 1);
    renderFlow();
    updateKPIs();
    markDirty();
}

// Editar meta do setor
function editMeta(idx) {
    const sector = SECTORS[idx];
    const newTarget = prompt(`Meta para ${sector.label}:`, sector.target || 0);

    if (newTarget === null) return;

    const target = parseInt(newTarget);
    if (isNaN(target) || target < 0) {
        alert('Meta inválida');
        return;
    }

    sector.target = target;
    renderFlow();
    updateKPIs();
    markDirty();
}

// Adicionar novo setor
function addSector() {
    const label = prompt('Nome do setor:');
    if (!label) return;

    const target = parseInt(prompt('Meta de pessoas:', '0'));
    if (isNaN(target)) return;

    const key = label.toLowerCase().replace(/\s+/g, '_');

    SECTORS.push({
        key: key,
        label: label,
        target: target,
        subsectors: []
    });

    renderFlow();
    updateKPIs();
    markDirty();
}
