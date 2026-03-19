# Script auxiliar para rodar o servidor usando o ambiente virtual configurado

# Verifica se o arquivo python existe no venv
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "Iniciando servidor FastAPI..."
    if (-not $env:FORCE_LOCAL_DB) {
        $env:FORCE_LOCAL_DB = "false"
    }
    if ($env:FORCE_LOCAL_DB -eq "true") {
        Write-Host "Banco local SQLite habilitado para esta sessao (FORCE_LOCAL_DB=true)."
    }
    else {
        Write-Host "Banco remoto habilitado para esta sessao (FORCE_LOCAL_DB=$env:FORCE_LOCAL_DB)."
    }
    # --reload-delay: evita dois reloads seguidos; reload-exclude database.py: mudanças só em pool/URL
    # exigem reinício manual (Ctrl+C), mas evita ficar preso reabrindo Postgres a cada save.
    & ".\.venv\Scripts\python" -m uvicorn main:app --reload --reload-delay 1 --reload-exclude "database.py"
}
else {
    Write-Error "Ambiente virtual nao encontrado ou incompleto. Execute 'python -m venv .venv' e instale as dependencias com '.venv\Scripts\pip install -r requirements.txt'."
}
