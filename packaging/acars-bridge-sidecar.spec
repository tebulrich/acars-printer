# -*- mode: python ; coding: utf-8 -*-
# Headless NDJSON bridge for the Tauri shell (no Qt UI).
#
# Build:
#   uv sync --group dev
#   uv run pyinstaller --noconfirm --clean packaging/acars-bridge-sidecar.spec
#   node scripts/stage-sidecar.mjs

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
root = Path(SPECPATH).resolve().parent
icon = root / "packaging" / "acars-bridge.ico"
windivert = root / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"

escpos_datas = collect_data_files("escpos")
divert_datas = collect_data_files("pydivert", includes=["**/*.dll", "**/*.sys"])
companion_datas = collect_data_files(
    "acars_bridge", includes=["companion/static/*"]
)

wd_datas = []
if windivert.exists():
    for name in ("WinDivert.dll", "WinDivert64.sys", "WinDivert.lib"):
        path = windivert / name
        if path.exists():
            wd_datas.append((str(path), "WinDivert"))

simconnect = root / "third_party" / "SimConnect"
sc_datas = []
if simconnect.exists():
    for name in (
        "SimConnect.dll",
        "MSVCP140.dll",
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
    ):
        path = simconnect / name
        if path.exists():
            sc_datas.append((str(path), "SimConnect"))

_excludes = [
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "shiboken6",
    "pytest",
    "ruff",
    "rich",
    "pygments",
    "typer",
    "markdown_it",
]

a = Analysis(
    [str(root / "src" / "acars_bridge" / "bridge" / "__main__.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=escpos_datas + divert_datas + companion_datas + wd_datas + sc_datas,
    hiddenimports=[
        "pydivert",
        "acars_bridge",
        "acars_bridge.bridge",
        "acars_bridge.bridge.runtime",
        "acars_bridge.tap.service",
        "acars_bridge.companion.server",
        "win32print",
        "win32api",
        "win32event",
        "pywintypes",
        "escpos",
        "escpos.printer",
        "PIL",
        "cryptography",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="acars-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=r"%LOCALAPPDATA%\acars-bridge\acars-bridge\pyi-tmp",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    icon=str(icon) if icon.exists() else None,
)
