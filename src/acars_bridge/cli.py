from __future__ import annotations

from pathlib import Path

import typer

from acars_bridge import __version__
from acars_bridge.config import AppPaths
from acars_bridge.services.session import build_session

app = typer.Typer(
    name="acars-bridge",
    help="Hoppie ACARS print bridge (local tap + thermal print).",
    no_args_is_help=True,
)


def _session(data_dir: str | None = None, *, fake_printer: bool = False):
    paths = AppPaths.for_testing(Path(data_dir)) if data_dir else None
    return build_session(paths, use_fake_printer=fake_printer)


@app.command()
def version() -> None:
    """Show application version."""
    typer.echo(__version__)


@app.command()
def ui(data_dir: str | None = typer.Option(None, hidden=True)) -> None:
    """Open the desktop UI (Tauri + React; falls back to Qt)."""
    import os
    import shutil
    import subprocess

    # Prefer the Tauri shell when available (npm run tauri / built exe).
    root = Path(__file__).resolve().parents[2]
    tauri_exe = root / "src-tauri" / "target" / "release" / "acars-print-bridge.exe"
    npm = shutil.which("npm")
    if tauri_exe.is_file():
        env = os.environ.copy()
        if data_dir:
            env["ACARS_BRIDGE_DATA_DIR"] = data_dir
        raise SystemExit(subprocess.call([str(tauri_exe)], env=env, cwd=str(root)))
    if npm and (root / "package.json").is_file():
        env = os.environ.copy()
        if data_dir:
            env["ACARS_BRIDGE_DATA_DIR"] = data_dir
        raise SystemExit(
            subprocess.call([npm, "run", "tauri", "--", "dev"], env=env, cwd=str(root))
        )

    from acars_bridge.ui.app import run_app

    paths = AppPaths.for_testing(Path(data_dir)) if data_dir else None
    try:
        run_app(paths)
    except Exception as exc:  # noqa: BLE001 - surface display failures cleanly
        typer.secho(f"UI failed to start: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@app.command()
def configure(
    callsign: str | None = typer.Option(None, help="Optional callsign print filter"),
    printer: str | None = typer.Option(
        None, help="console | cups://Name | win32://Name | file:// | tcp://"
    ),
    width: str | None = typer.Option(None, help="58 or 80"),
    auto_print: bool | None = typer.Option(None, help="Enable automatic printing"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Store local settings (printer / filter). Logon comes from the aircraft."""
    session = _session(data_dir)
    try:
        if callsign:
            session.settings.set_callsign(callsign)
        if printer:
            session.settings.set_printer_destination(printer)
        if width:
            session.settings.set_paper_width(width)
        if auto_print is not None:
            session.settings.set_auto_print(auto_print)

        typer.echo("Settings saved.")
        typer.echo(f"Callsign filter: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Printer: {session.settings.printer_destination()}")
        typer.echo(f"Width: {session.settings.paper_width()}mm")
        typer.echo(f"Auto-print: {'yes' if session.settings.auto_print() else 'no'}")
        typer.echo(f"Data: {session.paths.root}")
    finally:
        session.close()


@app.command("status")
def status_cmd(data_dir: str | None = typer.Option(None, hidden=True)) -> None:
    """Show current session configuration."""
    session = _session(data_dir)
    try:
        typer.echo(f"acars-bridge {__version__}")
        typer.echo("Mode: tap")
        typer.echo(f"Callsign filter: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Printer: {session.settings.printer_destination()}")
        typer.echo(f"Data: {session.paths.root}")
    finally:
        session.close()


@app.command("test-print")
def test_print(
    destination: str | None = typer.Option(None, help="Override printer destination"),
    width: str | None = typer.Option(None, help="58 or 80"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Send a test page to the configured printer."""
    session = _session(data_dir)
    try:
        settings = session.settings.as_printer_settings(
            destination=destination or session.settings.printer_destination(),
        )
        if width:
            from dataclasses import replace

            settings = replace(settings, paper_width="58" if width == "58" else "80")
        from acars_bridge.printing.discovery import is_device_printer_destination

        if is_device_printer_destination(settings.destination):
            from acars_bridge.printing.escpos_printer import EscPosMessagePrinter
            from acars_bridge.services.print_manager import PrintManager

            pm = PrintManager(session.messages, EscPosMessagePrinter())
            pm.test_print(settings)
        else:
            session.print_manager.test_print(settings)
        typer.echo(f"Test print sent to {settings.destination}")
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Test print failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command()
def history(
    limit: int = typer.Option(20, help="Number of recent messages"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Show recent messages."""
    session = _session(data_dir)
    try:
        rows = session.messages.list_recent(limit)
        if not rows:
            typer.echo("No messages yet.")
            return
        for row in rows:
            preview = row.normalized_body.replace("\n", " / ")[:80]
            typer.echo(
                f"#{row.id} [{row.direction}/{row.message_type}] "
                f"{row.sender or '-'} -> {row.to_station or row.recipient or '-'} | {preview}"
            )
    finally:
        session.close()


@app.callback()
def main_callback() -> None:
    """ACARS Print Bridge CLI (local/source helper only)."""


if __name__ == "__main__":
    app()
