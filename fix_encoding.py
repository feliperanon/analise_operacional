
import os
import codecs

file_path = r"c:\Projeto\analise_operacional\templates\smart_flow.html"
encodings_to_try = ['utf-16', 'utf-16-le', 'cp1252', 'latin1', 'iso-8859-1']

content = None
successful_encoding = None

for enc in encodings_to_try:
    try:
        with open(file_path, 'r', encoding=enc) as f:
            content = f.read()
            # Basic sanity check: look for a known string
            if "html" in content:
                successful_encoding = enc
                print(f"Success reading with {enc}")
                break
    except Exception as e:
        print(f"Failed {enc}: {e}")

if content:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Saved successfully as UTF-8")
else:
    print("CRITICAL: Could not read file with any common encoding.")
    exit(1)
