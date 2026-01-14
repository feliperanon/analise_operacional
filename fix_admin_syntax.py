
import os

file_path = r"c:\Projeto\analise_operacional\templates\admin_game_settings.html"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the specific broken line
broken = "window.GAME_CONFIG = {{ config_json | safe }"
fixed = "window.GAME_CONFIG = {{ config_json | safe }};"

if broken in content and fixed not in content:
    new_content = content.replace(broken, fixed)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Fixed syntax in admin_game_settings.html")
else:
    # Try generic fix for missing brace
    broken_generic = "{{ config_json | safe }"
    fixed_generic = "{{ config_json | safe }}"
    if broken_generic in content and fixed_generic not in content:
         new_content = content.replace(broken_generic, fixed_generic)
         with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
         print("Fixed generic brace error")
    else:
        print("Pattern not found or already fixed")
