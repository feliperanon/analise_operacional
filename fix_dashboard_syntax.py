
path = r"c:\Projeto\analise_operacional\templates\mobile\dashboard.html"

try:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Fix the specific broken pattern
    new_content = content.replace("{ {", "{{").replace("} }", "}}")

    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("FIXED: Replaced '{ {' with '{{'")
    else:
        print("NO CHANGE: Pattern '{ {' not found.")

except Exception as e:
    print(f"ERROR: {e}")
