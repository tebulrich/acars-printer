from __future__ import annotations

import os
import sys
from pathlib import Path


def windivert_dir() -> Path | None:
    """Locate WinDivert x64 binaries (dev tree or frozen exe)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "WinDivert")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "WinDivert")
    here = Path(__file__).resolve()
    candidates.append(
        here.parents[3] / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"
    )
    candidates.append(
        here.parents[2] / "third_party" / "WinDivert" / "WinDivert-2.2.2-A" / "x64"
    )
    for path in candidates:
        if (path / "WinDivert.dll").exists() and (
            (path / "WinDivert64.sys").exists() or (path / "WinDivert.sys").exists()
        ):
            return path
    return None


def ensure_windivert_on_path() -> Path:
    directory = windivert_dir()
    if directory is None:
        raise RuntimeError(
            "WinDivert binaries missing. Expected third_party/WinDivert/.../x64."
        )
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    return directory
