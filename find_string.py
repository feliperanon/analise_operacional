
target_file = "main.py"
search_str = '@app.get("/admin/routine/checklists"'

with open(target_file, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if search_str in line:
            print(f"Found at line {i}: {line.strip()}")
