import re

with open("templates/base.html", "r", encoding="utf-8") as f:
    html = f.read()

# We want to replace everything from {% if user_role == "admin" %} down to {% endif %} after <!-- ========== ACESSO LIBERADO
# Let's find the start marker
start_marker = '{% if user_role == "admin" %}'
end_marker = '<!-- Footer com Usuário e Logout -->'

start_idx = html.find(start_marker)
end_idx = html.find(end_marker)

if start_idx != -1 and end_idx != -1:
    original_block = html[start_idx:end_idx]
    
    # We will just rewrite the entire block using a clean string
    # We can extract the inner contents of each module from the original HTML
    # and wrap them in our new {% set is_admin = (user_role == "admin") %} check.
    
    # Let's just create the new block string directly.
    new_block = """{% set is_admin = (user_role == "admin") %}
                
                <!-- ========== LÍDER ========== -->
                {% if is_admin or "lider" in allowed_pages %}
                <div>
                    <button @click="openMenus.lider = !openMenus.lider" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                            </div>
                            <span class="font-medium text-sm">Líder</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.lider ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.lider" x-collapse class="ml-4 mt-1 space-y-1 border-l border-cyan-500/30 pl-4">
                        <a href="/smart-flow" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                            <span class="text-sm">Fluxo Inteligente</span>
                        </a>
                        <a href="/lider/checklists" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            <span class="text-sm">Checklists em dia</span>
                        </a>
                        <a href="/lider/rotas" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>
                            <span class="text-sm">Rotas e velocidade</span>
                        </a>
                        <a href="/lider/minhas-ordens" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/></svg>
                            <span class="text-sm">Minhas Ordens</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== GERENTE ========== -->
                {% if is_admin or "gerente" in allowed_pages %}
                <div>
                    <button @click="openMenus.gerente = !openMenus.gerente" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
                            </div>
                            <span class="font-medium text-sm">Gerente</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.gerente ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.gerente" x-collapse class="ml-4 mt-1 space-y-1 border-l border-amber-500/30 pl-4">
                        <a href="/gm/ordens-servico" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
                            <span class="text-sm">Ordens de Serviço</span>
                        </a>
                        <a href="/gm/ordens-servico/kpis" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                            <span class="text-sm">KPIs dos Líderes</span>
                        </a>
                        <a href="/gm/ordens-servico/historico" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            <span class="text-sm">Histórico Ordens</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== PROCESSOS ========== -->
                {% if is_admin or "processos" in allowed_pages %}
                <div>
                    <button @click="openMenus.processos = !openMenus.processos" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-rose-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>
                            </div>
                            <span class="font-medium text-sm">Processos</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.processos ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.processos" x-collapse class="ml-4 mt-1 space-y-1 border-l border-rose-500/30 pl-4">
                        <a href="/separacao" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>
                            <span class="text-sm">Entregas</span>
                        </a>
                        <a href="/devolucoes" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6"/></svg>
                            <span class="text-sm">Devoluções</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== ROTINAS & CHECKLISTS ========== -->
                {% if is_admin or "rotinas" in allowed_pages %}
                <div>
                    <button @click="openMenus.rotinas = !openMenus.rotinas" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path>
                                </svg>
                            </div>
                            <span class="font-medium text-sm">Rotinas & Checklists</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.rotinas ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.rotinas" x-collapse class="ml-4 mt-1 space-y-1 border-l border-emerald-500/30 pl-4">
                        <a href="/admin/routine/checklists" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5h6m-6 4h6m-7 4h8m-5 4h2m-8 2h10a2 2 0 002-2V5a2 2 0 00-2-2H6a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
                            <span class="text-sm">Checklists Operacionais</span>
                        </a>
                        <a href="/admin/routine/checklists/dashboard" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 3v18m-6-6h12M4 21h16a1 1 0 001-1V4a1 1 0 00-1-1H4a1 1 0 00-1 1v16a1 1 0 001 1z"/></svg>
                            <span class="text-sm">Painel Checklists</span>
                        </a>
                        <a href="/admin/routine/checklists/settings" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            <span class="text-sm">Configurações</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== OFICINA ========== -->
                {% if is_admin or "oficina" in allowed_pages %}
                <div>
                    <button @click="openMenus.oficina = !openMenus.oficina" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
                                <i data-lucide="wrench" class="w-5 h-5 text-amber-400"></i>
                            </div>
                            <span class="font-medium text-sm">Oficina</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.oficina ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.oficina" x-collapse class="ml-4 mt-1 space-y-1 border-l border-amber-500/30 pl-4">
                        <a href="/vehicles" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <i data-lucide="truck" class="w-4 h-4"></i>
                            <span class="text-sm">Frota de Veículos</span>
                        </a>
                        <a href="/vehicles/odometer" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <i data-lucide="history" class="w-4 h-4"></i>
                            <span class="text-sm">Histórico Veículos</span>
                        </a>
                        <a href="/admin/equipment/tickets" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
                            <span class="text-sm">Chamados de Equipamento</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== CADASTROS ========== -->
                {% if is_admin or "cadastros" in allowed_pages %}
                <div>
                    <button @click="openMenus.cadastros = !openMenus.cadastros" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-violet-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path>
                                </svg>
                            </div>
                            <span class="font-medium text-sm">Cadastros</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.cadastros ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.cadastros" x-collapse class="ml-4 mt-1 space-y-1 border-l border-violet-500/30 pl-4">
                        <a href="/clients" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            <span class="text-sm">Clientes</span>
                        </a>
                        <a href="/employees" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
                            <span class="text-sm">Colaboradores</span>
                        </a>
                        <a href="/funcoes" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                            <span class="text-sm">Funções (Cargos)</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== PESSOAS & RH ========== -->
                {% if is_admin or "pessoas" in allowed_pages %}
                <div>
                    <button @click="openMenus.pessoas = !openMenus.pessoas" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                                </svg>
                            </div>
                            <span class="font-medium text-sm">Pessoas & RH</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.pessoas ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.pessoas" x-collapse class="ml-4 mt-1 space-y-1 border-l border-indigo-500/30 pl-4">
                        <a href="/people-intelligence" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                            <span class="text-sm">Inteligência de Pessoas</span>
                        </a>
                        <a href="/people-intelligence/vacation-planning" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                            <span class="text-sm">Planejamento de férias</span>
                        </a>
                        <a href="/admin/turnover-analysis" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 17l-4 4m0 0l-4-4m4 4V3"/></svg>
                            <span class="text-sm">Turnover e Rotatividade</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== BI & MÉTRICAS ========== -->
                {% if is_admin or "bi" in allowed_pages %}
                <div>
                    <button @click="openMenus.bi = !openMenus.bi" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3v18h18M8 14l3-3 3 2 4-5"></path>
                                </svg>
                            </div>
                            <span class="font-medium text-sm">BI & Métricas</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.bi ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.bi" x-collapse class="ml-4 mt-1 space-y-1 border-l border-cyan-500/30 pl-4">
                        <a href="/strategy" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                            <span class="text-sm">Estratégia</span>
                        </a>
                        <a href="/relatorio-avaliacao-motorista" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                            <span class="text-sm">Avaliação Motorista</span>
                        </a>
                        <a href="/bi/delivery" class="flex items-center gap-3 px-3 py-2.5 text-cyan-300 hover:text-cyan-200 hover:bg-cyan-500/10 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3v18h18M8 14l3-3 3 2 4-5"/></svg>
                            <span class="text-sm">BI Entregas</span>
                        </a>
                        <a href="/bi/clientes" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7h18M6 7v10a2 2 0 002 2h8a2 2 0 002-2V7M9 11h6M9 15h4"/></svg>
                            <span class="text-sm">BI Clientes</span>
                        </a>
                        <a href="/bi/motorista" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            <span class="text-sm">BI Motorista</span>
                        </a>
                        <a href="/operations/performance" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"/></svg>
                            <span class="text-sm">Avaliação Operacional</span>
                        </a>
                        <a href="/gamificacao/entregas" class="flex items-center gap-3 px-3 py-2.5 text-emerald-300 hover:text-emerald-200 hover:bg-emerald-500/10 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l2.021 6.225a1 1 0 00.95.69h6.545c.969 0 1.371 1.24.588 1.81l-5.295 3.848a1 1 0 00-.364 1.118l2.022 6.225c.3.921-.755 1.688-1.538 1.118l-5.294-3.848a1 1 0 00-1.176 0l-5.294 3.848c-.784.57-1.838-.197-1.539-1.118l2.022-6.225a1 1 0 00-.364-1.118L.98 11.652c-.783-.57-.38-1.81.588-1.81h6.545a1 1 0 00.951-.69l2.021-6.225z"/></svg>
                            <span class="text-sm">Gamificação Entregas</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== SISTEMA ========== -->
                {% if is_admin or "sistema" in allowed_pages %}
                <div>
                    <button @click="openMenus.sistema = !openMenus.sistema" class="menu-toggle w-full flex items-center justify-between px-4 py-2.5 text-slate-400 hover:text-white rounded-xl transition-colors">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-slate-500/20 flex items-center justify-center">
                                <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path>
                                </svg>
                            </div>
                            <span class="font-medium text-sm">Sistema</span>
                        </div>
                        <svg class="w-4 h-4 transition-transform" :class="openMenus.sistema ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div x-show="openMenus.sistema" x-collapse class="ml-4 mt-1 space-y-1 border-l border-slate-700/50 pl-4">
                        <a href="/admin/users" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            <span class="text-sm">Usuários</span>
                        </a>
                        <a href="/admin/substitutions" class="flex items-center gap-3 px-3 py-2.5 text-slate-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
                            <span class="text-sm">Substituições</span>
                        </a>
                        <a href="/mobile/login" target="_blank" class="flex items-center gap-3 px-3 py-2.5 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 rounded-lg transition-colors">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
                            <span class="text-sm">Abrir Portal Mobile</span>
                        </a>
                    </div>
                </div>
                {% endif %}

                <!-- ========== GAME MASTER ========== -->
                {% if is_admin or "admin_game" in allowed_pages %}
                <a href="/admin/game" class="flex items-center gap-3 px-4 py-3 text-yellow-400 hover:text-yellow-300 hover:bg-yellow-500/10 rounded-xl transition-colors mt-2">
                    <div class="w-8 h-8 rounded-lg bg-yellow-500/20 flex items-center justify-center">
                        <i data-lucide="gamepad-2" class="w-5 h-5"></i>
                    </div>
                    <span class="font-medium">Game Master</span>
                </a>
                {% endif %}
                
""" # this will close it naturally.
    
    new_html = html[:start_idx] + new_block + "\n" + html[end_idx:]
    with open("templates/base.html", "w", encoding="utf-8") as f:
        f.write(new_html)
    print("Successfully replaced.")
else:
    print("Could not find markers.")
