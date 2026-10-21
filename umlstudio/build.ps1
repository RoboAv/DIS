# Собирает UML Studio в один exe со значком файла и значком окна.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python -m PyInstaller --noconfirm --onefile --windowed `
    --name "UML Studio" `
    --icon "assets\logo.ico" `
    --add-data "assets\logo.ico;assets" `
    --hidden-import PIL.ImageTk `
    main.py

Write-Host ""
Write-Host "Готово: $PSScriptRoot\dist\UML Studio.exe"
