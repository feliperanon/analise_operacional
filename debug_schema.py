with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '@app.get("/")' in line or '@app.get(\'/\')' in line:
            print(f"FOUND ROOT at line {i+1}: {line.strip()}")
            # Print context
            for j in range(i, min(i+50, len(lines))):
                 print(f"{j+1}: {lines[j].strip()}")
            break
