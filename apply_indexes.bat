@echo off
echo ============================================================
echo APLICACAO DE INDICES DE PERFORMANCE
echo ============================================================

REM Ativar ambiente virtual se existir
if exist .venv\Scripts\activate.bat (
    echo Ativando ambiente virtual...
    call .venv\Scripts\activate.bat
)

REM Executar script Python
python apply_indexes.py

REM Pausar para ver resultado
pause
