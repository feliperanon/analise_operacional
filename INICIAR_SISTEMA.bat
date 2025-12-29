@echo off
cd /d "%~dp0"
echo Iniciando Analise Operacional...
powershell -ExecutionPolicy Bypass -File "run.ps1"
pause
