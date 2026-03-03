param(
    [int]$MaxLogMB = 20,
    [switch]$CleanTmp = $true
)

$ErrorActionPreference = "Stop"

Write-Host "== Limpando dados locais de desenvolvimento =="

if (Test-Path "logs.txt") {
    $sizeMB = [math]::Round((Get-Item "logs.txt").Length / 1MB, 2)
    if ($sizeMB -gt $MaxLogMB) {
        Write-Host "Truncando logs.txt ($sizeMB MB > $MaxLogMB MB)"
        Clear-Content "logs.txt"
    } else {
        Write-Host "logs.txt dentro do limite ($sizeMB MB)"
    }
}

if ($CleanTmp -and (Test-Path "tmp")) {
    Write-Host "Removendo arquivos em tmp/"
    Get-ChildItem "tmp" -Recurse -File | Remove-Item -Force
}

if (Test-Path "__pycache__") {
    Write-Host "Removendo __pycache__/"
    Remove-Item "__pycache__" -Recurse -Force
}

Write-Host "Concluido."
