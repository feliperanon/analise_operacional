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
        
        # Replace min/Ton -> Kg/h
        new_content = content.replace("min/Ton", "Kg/h")
        # Replace Kg/min -> Kg/h (if any left)
        new_content = new_content.replace("Kg/min", "Kg/h")
        
        if content != new_content:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {fp}")
        else:
            print(f"No changes: {fp}")
    else:
        print(f"Missing: {fp}")
