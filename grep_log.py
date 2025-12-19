
try:
    with open('error.log', 'r', encoding='utf-16') as f:
        for line in f:
            if "Error" in line or "Exception" in line or "no such column" in line:
                print(line.strip())
except Exception as e:
    print(e)
