# Script auxiliar para rodar o servidor usando o ambiente virtual configurado

# Verifica se o arquivo python existe no venv
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "Iniciando servidor FastAPI..."
    & ".\.venv\Scripts\python" -m uvicorn main:app --reload
}
else {
    Write-Error "Ambiente virtual não encontrado ou incompleto. Execute 'python -m venv .venv' e instale as dependências com '.venv\Scripts\pip install -r requirements.txt'."
}
