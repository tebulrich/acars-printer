# -*- mode: python ; coding: utf-8 -*-
# Build: uv run python packaging/generate_icon.py
#        uv run pyinstaller --noconfirm --clean packaging/acars-bridge.spec
#
# Size note: PySide6/Qt Widgets alone is ~40MB+ compressed. 10–20MB is not
# realistic with a Qt desktop UI; we prune everything else aggressively.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
root = Path(SPECPATH).resolve().parent
icon = root / "packaging" / "acars-bridge.ico"
windivert = root / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"

escpos_datas = collect_data_files("escpos")
divert_datas = collect_data_files("pydivert", includes=["**/*.dll", "**/*.sys"])

wd_datas = []
if windivert.exists():
    for name in ("WinDivert.dll", "WinDivert64.sys", "WinDivert.lib"):
        path = windivert / name
        if path.exists():
            wd_datas.append((str(path), "WinDivert"))

_qt_excludes = [
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebView",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtSensors",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtRemoteObjects",
    "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtTest",
    # CLI fluff not used by the frozen UI entrypoint
    "rich",
    "pygments",
    "typer",
    "markdown_it",
    "pytest",
]

# Dropped from collected binaries/datas after Analysis (hooks still pull these).
_DROP_SUBSTR = (
    "opengl32sw",
    "qt6quick",
    "qt6qml",
    "qt6pdf",
    "qt6virtualkeyboard",
    "qt6opengl",
    "qt6svg",
    "qt6designer",
    "qt6uitools",
    "qt6test",
    "qdirect2d",
    "qminimal",
    "qoffscreen",
    "qwebp",
    "qtiff",
    "qjpeg",
    "qgif",
    "qwbmp",
    "qicns",
    "qt_gl.qm",  # keep pruning translations broadly below
    "_avif",
    "/qml/",
    "\\qml\\",
    "/translations/",
    "\\translations\\",
)


def _prune_toc(toc):
    kept = []
    for entry in toc:
        name = str(entry[0]).replace("\\", "/").lower()
        if any(token in name for token in _DROP_SUBSTR):
            continue
        if "/plugins/imageformats/" in name and not (
            name.endswith("qpng.dll") or name.endswith("qico.dll")
        ):
            continue
        if "/plugins/platforms/" in name and not name.endswith("qwindows.dll"):
            continue
        if "/plugins/sqldrivers/" in name:
            continue
        if "/plugins/generic/" in name:
            continue
        if "/plugins/iconengines/" in name:
            continue
        if "/plugins/networkinformation/" in name:
            continue
        kept.append(entry)
    return kept


a = Analysis(
    [str(root / "src" / "acars_bridge" / "__main__.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=escpos_datas + divert_datas + wd_datas,
    hiddenimports=[
        "pydivert",
        "acars_bridge",
        "acars_bridge.ui.app",
        "acars_bridge.tap.service",
        "win32print",
        "win32api",
        "win32event",
        "pywintypes",
        "escpos",
        "escpos.printer",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_qt_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = _prune_toc(a.binaries)
a.datas = _prune_toc(a.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ACARS Print Bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=str(icon) if icon.exists() else None,
)
