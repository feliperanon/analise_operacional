"""
Script para corrigir formatação de números e encoding no smart_flow.html
"""
import re

# Ler o arquivo
with open('templates/smart_flow.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Corrigir caracteres corrompidos
replacements = {
    'Produçço': 'Produção',
    'Manhç': 'Manhã',
    'Movimenta��o': 'Movimentação',
    'Movimentação Bruta': 'Movimentação Bruta',
}

for old, new in replacements.items():
    content = content.replace(old, new)

# 2. Adicionar função formatBR no início do script
script_start = content.find('<script>')
if script_start != -1:
    # Encontrar o final da tag <script>
    script_tag_end = content.find('>', script_start) + 1
    
    # Função formatBR
    format_function = '''
    // Função para formatar números no padrão brasileiro
    function formatBR(value) {
        let str = String(value).trim().replace(/\\./g, '').replace(',', '.');
        const number = parseFloat(str);
        if (isNaN(number)) return '0,00';
        return number.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Função para parsear número brasileiro
    function parseBR(value) {
        let str = String(value).trim().replace(/\\./g, '').replace(',', '.');
        return parseFloat(str) || 0;
    }
'''
    
    # Verificar se já existe
    if 'function formatBR' not in content:
        content = content[:script_tag_end] + format_function + content[script_tag_end:]
        print("✅ Função formatBR adicionada")
    else:
        print("ℹ️  Função formatBR já existe")

# 3. Aplicar formatação nos elementos de exibição de tonelagem
# Procurar onde a tonelagem é exibida e aplicar formatBR
content = re.sub(
    r"tonnageEl\.innerText\s*=\s*([^;]+);",
    r"tonnageEl.innerText = formatBR(\1) + ' kg';",
    content
)

# 4. Salvar o arquivo
with open('templates/smart_flow.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Correções aplicadas com sucesso!")
print("   - Caracteres corrompidos corrigidos")
print("   - Função formatBR adicionada")
print("   - Formatação aplicada nos elementos de tonelagem")
