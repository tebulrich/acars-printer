# Build ACARS Print Bridge.exe (UAC admin on launch).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Syncing deps (incl. PyInstaller)..."
uv sync --group dev
uv run python packaging/generate_icon.py
Write-Host "Building exe (usually 3-8 minutes)..."
uv run pyinstaller --noconfirm --clean packaging/acars-bridge.spec

$Exe = Join-Path $Root "dist\ACARS Print Bridge.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but exe not found: $Exe"
}
Write-Host ""
Write-Host "Built: $Exe"
Write-Host "Double-click it - Windows will ask for Administrator."
