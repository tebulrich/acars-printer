"""Keep WinDivert / SimConnect outside the PyInstaller ``_MEI*`` unpack dir.

Onefile extracts to a temp ``_MEIPASS``. Loading WinDivert (especially the
``.sys`` driver) or SimConnect from there locks those files, so on exit the
bootloader fails to remove the folder and pops:

  Failed to remove temporary directory: ...\\pyi-tmp\\_MEI...

Copying natives into the stable app data dir before first load avoids that.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from acars_bridge.config import data_dir

log = logging.getLogger(__name__)

_prepared = False


def native_root() -> Path:
    root = data_dir() / "native"
    root.mkdir(parents=True, exist_ok=True)
    return root


def windivert_runtime_dir() -> Path:
    return native_root() / "WinDivert"


def simconnect_runtime_dir() -> Path:
    return native_root() / "SimConnect"


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            if dest.stat().st_size == src.stat().st_size:
                return
        except OSError:
            pass
    shutil.copy2(src, dest)


def _meipass() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    raw = getattr(sys, "_MEIPASS", None)
    return Path(raw) if raw else None


def _windivert_sources(meipass: Path) -> list[Path]:
    """Candidate folders that contain WinDivert64.dll + .sys."""
    return [
        meipass / "pydivert" / "windivert_dll",
        meipass / "WinDivert",
        Path(sys.executable).resolve().parent / "WinDivert",
    ]


def _ensure_windivert_copied(meipass: Path) -> Path | None:
    dest_dir = windivert_runtime_dir()
    names = ("WinDivert64.dll", "WinDivert64.sys", "WinDivert.dll", "WinDivert.sys")
    for src_dir in _windivert_sources(meipass):
        if not src_dir.is_dir():
            continue
        dll = src_dir / "WinDivert64.dll"
        if not dll.exists():
            dll = src_dir / "WinDivert.dll"
        sys_file = src_dir / "WinDivert64.sys"
        if not sys_file.exists():
            sys_file = src_dir / "WinDivert.sys"
        if not dll.exists() or not sys_file.exists():
            continue
        for name in names:
            src = src_dir / name
            if src.exists():
                _copy_file(src, dest_dir / name)
        # pydivert expects WinDivert64.dll specifically
        if not (dest_dir / "WinDivert64.dll").exists() and (dest_dir / "WinDivert.dll").exists():
            _copy_file(dest_dir / "WinDivert.dll", dest_dir / "WinDivert64.dll")
        if (dest_dir / "WinDivert64.dll").exists() and (
            (dest_dir / "WinDivert64.sys").exists() or (dest_dir / "WinDivert.sys").exists()
        ):
            return dest_dir
    return None


def _ensure_simconnect_copied(meipass: Path) -> Path | None:
    dest_dir = simconnect_runtime_dir()
    src_dirs = [
        meipass / "SimConnect",
        Path(sys.executable).resolve().parent / "SimConnect",
    ]
    names = (
        "SimConnect.dll",
        "MSVCP140.dll",
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
    )
    for src_dir in src_dirs:
        if not (src_dir / "SimConnect.dll").exists():
            continue
        for name in names:
            src = src_dir / name
            if src.exists():
                _copy_file(src, dest_dir / name)
        if (dest_dir / "SimConnect.dll").exists():
            return dest_dir
    return None


def _redirect_pydivert(windivert_dir: Path) -> None:
    dll = windivert_dir / "WinDivert64.dll"
    if not dll.exists():
        return
    try:
        import pydivert.windivert_dll as wd

        wd.DLL_PATH = str(dll)
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not redirect pydivert DLL_PATH: %s", exc)


def prepare_frozen_natives() -> None:
    """Idempotent: copy locked natives out of ``_MEIPASS`` when frozen."""
    global _prepared
    if _prepared:
        return
    meipass = _meipass()
    if meipass is None:
        _prepared = True
        return

    wd = _ensure_windivert_copied(meipass)
    if wd is not None:
        os.environ["PATH"] = str(wd) + os.pathsep + os.environ.get("PATH", "")
        _redirect_pydivert(wd)
        log.info("WinDivert runtime at %s", wd)

    sc = _ensure_simconnect_copied(meipass)
    if sc is not None:
        os.environ["PATH"] = str(sc) + os.pathsep + os.environ.get("PATH", "")
        log.info("SimConnect runtime at %s", sc)

    _prepared = True
