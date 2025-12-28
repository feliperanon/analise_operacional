patterns = {
    "ATENÃ‡ÃƒO": "ATENÇÃO",
    "operaÃ§Ã£o": "operação",
    "irÃ¡": "irá",
    "nÃºmeros": "números",
    "perÃ­odo": "período",
    "fÃ©rias": "férias",
    "InÃ­cio": "Início",
    "conexÃ£o": "conexão"
}

file_path = r"e:\Projeto\analise_operacional\templates\smart_flow.html"

with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

for bad, good in patterns.items():
    content = content.replace(bad, good)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed encoding issues.")
