"""
Script para comentar código JavaScript inline no smart_flow.html
"""
import re

# Ler arquivo
with open('templates/smart_flow.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Encontrar início e fim do bloco <script> inline
script_start = None
script_end = None

for i, line in enumerate(lines):
    # Procurar por linhas que indicam início do script inline
    if 'ALL_EMPLOYEES = [' in line and script_start is None:
        script_start = i
    
    # Procurar pelo fechamento antes dos módulos
    if '<!-- MÓDULOS JAVASCRIPT MODULARES' in line and script_end is None:
        script_end = i - 2  # Linha antes do comentário

if script_start and script_end:
    print(f"📍 Código inline encontrado: linhas {script_start+1} a {script_end+1}")
    
    # Comentar o bloco
    lines.insert(script_start, '<!-- CÓDIGO INLINE ANTIGO - COMENTADO (agora usando módulos)\n')
    lines.insert(script_end + 2, '-->\n')
    
    # Salvar
    with open('templates/smart_flow.html', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print(f"✅ Código inline comentado!")
    print(f"   Linhas {script_start+1} a {script_end+1} agora estão comentadas")
else:
    print("❌ Não encontrou o bloco de código inline")
    print(f"   script_start: {script_start}, script_end: {script_end}")
