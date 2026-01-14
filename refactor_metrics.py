import os

files = [
    r"c:\Projeto\analise_operacional\templates\routes.html",
    r"c:\Projeto\analise_operacional\templates\mobile\dashboard.html",
    r"c:\Projeto\analise_operacional\templates\rankings.html",
    r"c:\Projeto\analise_operacional\templates\strategy.html"
]

for fp in files:
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = content.replace("Kg/h", "Kg/min")
        
        if content != new_content:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {fp}")
        else:
            print(f"No changes: {fp}")
    else:
        print(f"Missing: {fp}")
