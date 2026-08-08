from __future__ import annotations

import os
import sys
from pathlib import Path

from acars_bridge.native_runtime import (
    prepare_frozen_natives,
    windivert_runtime_dir,
)


def windivert_dir() -> Path | None:
    """Locate WinDivert x64 binaries (stable runtime, then MEIPASS / dev tree)."""
    prepare_frozen_natives()
    candidates: list[Path] = [windivert_runtime_dir()]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "WinDivert")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "WinDivert")
            candidates.append(Path(meipass) / "pydivert" / "windivert_dll")
    here = Path(__file__).resolve()
    candidates.append(
        here.parents[3] / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"
    )
    candidates.append(
        here.parents[2] / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"
    )
    for path in candidates:
        has_dll = (path / "WinDivert64.dll").exists() or (path / "WinDivert.dll").exists()
        has_sys = (path / "WinDivert64.sys").exists() or (path / "WinDivert.sys").exists()
        if has_dll and has_sys:
            return path
    return None


def ensure_windivert_on_path() -> Path:
    prepare_frozen_natives()
    directory = windivert_dir()
    if directory is None:
        raise RuntimeError(
            "WinDivert binaries missing. Expected third_party/WinDivert/.../x64."
        )
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    # pydivert loads WinDivert64.dll by absolute path — keep it outside _MEIPASS.
    dll64 = directory / "WinDivert64.dll"
    if not dll64.exists() and (directory / "WinDivert.dll").exists():
        dll64 = directory / "WinDivert.dll"
    if dll64.exists():
        try:
            import pydivert.windivert_dll as wd

            wd.DLL_PATH = str(
                directory / "WinDivert64.dll"
                if (directory / "WinDivert64.dll").exists()
                else dll64
            )
        except Exception:
            pass
    return directory
