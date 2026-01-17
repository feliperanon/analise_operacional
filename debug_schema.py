with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '@app.get("/employees/{' in line:
            print(f"FOUND at line {i+1}: {line.strip()}")
            break
