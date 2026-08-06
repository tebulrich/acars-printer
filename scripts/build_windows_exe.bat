@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if errorlevel 1 (
  echo Failed to change to repo root.
  exit /b 1
)

echo Syncing deps (incl. PyInstaller^)...
uv sync --group dev
if errorlevel 1 exit /b 1

uv run python packaging/generate_icon.py
if errorlevel 1 exit /b 1

echo Building exe (usually 3-8 minutes^)...
uv run pyinstaller --noconfirm --clean packaging/acars-bridge.spec
if errorlevel 1 exit /b 1

set "EXE=%CD%\dist\ACARS Print Bridge.exe"
if not exist "%EXE%" (
  echo Build finished but exe not found: %EXE%
  exit /b 1
)

echo.
echo Built: %EXE%
echo Double-click it - Windows will ask for Administrator.
exit /b 0
