
import re

def fix_indentation(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    for i, line in enumerate(lines):
        # Replace tabs
        line_no_tabs = line.replace('\t', '    ')
        
        # Check indentation level
        stripped = line_no_tabs.lstrip()
        indent = len(line_no_tabs) - len(stripped)
        
        if indent % 4 != 0:
            print(f"⚠️ Line {i+1} has irregular indentation ({indent} spaces): {stripped.strip()}")
            # Force fix? Round to nearest 4?
            rounded = round(indent / 4) * 4
            line_no_tabs = (' ' * rounded) + stripped
            
        new_lines.append(line_no_tabs)

    with open(filename, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"Fixed indentation for {filename}")

if __name__ == "__main__":
    fix_indentation(r"c:\Projeto\analise_operacional\main.py")
