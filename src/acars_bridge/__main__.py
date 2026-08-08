"""Launch the desktop UI (used by the Windows exe)."""

from __future__ import annotations


def main() -> None:
    # Before Qt / WinDivert / SimConnect: keep natives out of _MEIPASS so the
    # onefile bootloader can delete the unpack dir on exit without a warning.
    from acars_bridge.native_runtime import prepare_frozen_natives

    prepare_frozen_natives()
    from acars_bridge.ui.app import run_app

    run_app()


if __name__ == "__main__":
    main()
