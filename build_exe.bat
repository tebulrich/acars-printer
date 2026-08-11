@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === ACARS Print Bridge — Tauri Windows build ===
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

if exist ".venv\Scripts\python.exe" (
  set "ACARS_BRIDGE_PYTHON=%CD%\.venv\Scripts\python.exe"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo WARNING: Python not found. The built EXE needs Python 3.12+ at runtime.
    echo          Run "uv sync --group dev" first, or set ACARS_BRIDGE_PYTHON.
    echo.
  )
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

echo Building Tauri release ^(this can take several minutes^)...
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
) else (
  echo Check:     %CD%\src-tauri\target\release\acars-print-bridge.exe
)
for %%F in ("dist\*setup.exe") do (
  echo Installer: %%~fF
)
echo.
echo Run the EXE elevated ^(Administrator^) for Connect.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
