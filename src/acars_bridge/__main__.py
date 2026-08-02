"""Launch the desktop UI (used by the Windows exe)."""

from __future__ import annotations


def main() -> None:
    from acars_bridge.ui.app import run_app

    run_app()


if __name__ == "__main__":
    main()
