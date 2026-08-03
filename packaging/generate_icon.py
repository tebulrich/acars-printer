"""Write packaging/acars-bridge.ico (used by PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python packaging/generate_icon.py` without installing the package first.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from acars_bridge.ui.icons import write_ico  # noqa: E402


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "acars-bridge.ico"
    write_ico(out)
    print(out)
