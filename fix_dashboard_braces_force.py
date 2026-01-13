
import os

file_path = r"c:\Projeto\analise_operacional\templates\mobile\dashboard.html"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace invalid tags
new_content = content.replace('{ {', '{{').replace('} }', '}}')

if content != new_content:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Fixed braces in dashboard.html")
else:
    print("No changes needed or pattern not found")
