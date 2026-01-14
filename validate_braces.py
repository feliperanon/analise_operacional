
import re

path = r"c:\Projeto\analise_operacional\templates\mobile\dashboard.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Extract script content
match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
if not match:
    print("No <script> tag found!")
    exit()

script_content = match.group(1)
lines = script_content.split('\n')

balance = 0
for i, line in enumerate(lines):
    # Filter out comments roughly
    clean_line = re.sub(r"//.*", "", line)
    
    # Check braces
    for char in clean_line:
        if char == '{':
            balance += 1
        elif char == '}':
            balance -= 1
            if balance < 0:
                print(f"ERROR: Extra closing brace '}}' found at line {i + 1} (relative to script start)")
                print(f"Line content: {line.strip()}")
                exit()

if balance > 0:
    print(f"ERROR: Unclosed opening brace '{{' detected. Final balance: {balance}")
elif balance == 0:
    print("SUCCESS: Braces are balanced!")
