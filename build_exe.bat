@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === ACARS Print Bridge — Tauri + Python sidecar Windows build ===
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js not found on PATH. Install Node 20+ and retry.
  goto :fail
)

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm not found on PATH.
  goto :fail
)

where cargo >nul 2>&1
if errorlevel 1 (
  echo ERROR: Rust/Cargo not found on PATH. Install from https://rustup.rs and retry.
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo Syncing Python env ^(uv sync --group dev^)...
  where uv >nul 2>&1
  if errorlevel 1 (
    echo ERROR: uv not found. Install uv, then run "uv sync --group dev".
    goto :fail
  )
  call uv sync --group dev
  if errorlevel 1 goto :fail
)

if not exist "node_modules\" (
  echo Installing npm dependencies...
  call npm install
  if errorlevel 1 (
    echo ERROR: npm install failed.
    goto :fail
  )
  echo.
)

echo Building ^(Python sidecar + Tauri^) — this can take several minutes...
call npm run build:exe
if errorlevel 1 (
  echo.
  echo ERROR: Build failed.
  goto :fail
)

echo.
echo Done.
if exist "dist\ACARS-Print-Bridge.exe" (
  echo EXE:       %CD%\dist\ACARS-Print-Bridge.exe
)
for %%F in ("dist\ACARS-Print-Bridge-*-windows-x64.exe") do (
  echo Portable:  %%~fF
)
for %%F in ("dist\*setup.exe") do (
  echo Installer: %%~fF
)
echo Log file:  acars-print-bridge.log ^(created next to the EXE on first run^)
echo.
echo Run the EXE elevated ^(Administrator^) for Connect.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
