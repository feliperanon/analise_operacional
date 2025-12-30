"""
Script para extrair e modularizar o JavaScript do smart_flow.html
"""
import re
import os

# Ler o arquivo original
with open('templates/smart_flow.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Encontrar o bloco <script>
script_match = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if not script_match:
    print("❌ Não encontrou bloco <script>")
    exit(1)

script_content = script_match.group(1)

# Criar diretório se não existir
os.makedirs('static/js/smart-flow', exist_ok=True)

# 1. Extrair variáveis de estado (state.js)
state_vars = []
for line in script_content.split('\n')[:100]:  # Primeiras 100 linhas
    if re.match(r'\s*(let|const|var)\s+\w+\s*=', line):
        state_vars.append(line.strip())

state_js = '''// Estado global do Smart Flow
const SmartFlowState = {
    currentShift: 'Manhã',
    currentDate: new Date().toISOString().split('T')[0],
    shiftTargetHr: 0,
    config: {},
    employees: [],
    ALL_EMPLOYEES: [],
    isDirty: false
};

// Getters e setters
function getCurrentShift() { return SmartFlowState.currentShift; }
function setCurrentShift(shift) { SmartFlowState.currentShift = shift; }
function getCurrentDate() { return SmartFlowState.currentDate; }
function setCurrentDate(date) { SmartFlowState.currentDate = date; }
function markDirty() { SmartFlowState.isDirty = true; }
function clearDirty() { SmartFlowState.isDirty = false; }
function isDirty() { return SmartFlowState.isDirty; }
'''

with open('static/js/smart-flow/state.js', 'w', encoding='utf-8') as f:
    f.write(state_js)
print("✅ state.js criado")

# 2. Criar main.js básico
main_js = '''// Inicialização do Smart Flow
document.addEventListener('DOMContentLoaded', () => {
    console.log('Smart Flow inicializado');
    
    // Inicializar estado com dados do servidor
    if (typeof INITIAL_DATA !== 'undefined') {
        SmartFlowState.employees = INITIAL_DATA.employees || [];
        SmartFlowState.config = INITIAL_DATA.config || {};
        SmartFlowState.ALL_EMPLOYEES = INITIAL_DATA.all_employees || [];
    }
    
    // Carregar rotina do dia
    loadRoutine();
});
'''

with open('static/js/smart-flow/main.js', 'w', encoding='utf-8') as f:
    f.write(main_js)
print("✅ main.js criado")

# 3. Criar template HTML otimizado (apenas estrutura)
html_template = '''{% extends "base.html" %}

{% block content %}
<!-- Estilos inline mantidos -->
<style>
    @keyframes slideUp {
        from { transform: translateY(100%); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
    .animate-slide-up { animation: slideUp 0.3s ease-out forwards; }
</style>

<!-- Estrutura HTML mantida -->
<div class="flex flex-col h-full">
    <!-- Header, KPIs, Setores, etc. -->
    <!-- TODO: Manter estrutura HTML existente -->
</div>

<!-- Scripts modulares -->
<script src="/static/js/utils/format-br.js"></script>
<script src="/static/js/smart-flow/state.js"></script>
<script src="/static/js/smart-flow/main.js"></script>

<!-- Dados iniciais do servidor -->
<script>
    const INITIAL_DATA = {
        employees: {{ employees_json | safe }},
        config: {{ config_json | safe }},
        all_employees: {{ all_employees_json | safe }}
    };
</script>

<!-- JavaScript inline temporário (será migrado gradualmente) -->
<script>
    // TODO: Migrar funções para módulos separados
    // Por enquanto, manter código existente aqui
</script>
{% endblock %}
'''

print("\n📊 Resumo:")
print(f"   - state.js: {len(state_js)} bytes")
print(f"   - main.js: {len(main_js)} bytes")
print("\n⚠️  Próximos passos:")
print("   1. Revisar state.js e main.js")
print("   2. Extrair funções para módulos específicos")
print("   3. Atualizar smart_flow.html com imports")
print("   4. Testar funcionalidade")
