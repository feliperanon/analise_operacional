
try:
    with open('error.log', 'r', encoding='utf-16') as f:
        lines = f.readlines()
        for line in lines[:100]:
            print(line.strip())
except Exception as e:
    print(e)
