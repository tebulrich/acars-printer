from __future__ import annotations

import random
import time
from pathlib import Path

import typer

from acars_bridge import __version__
from acars_bridge.config import JITTER_SECONDS, AppPaths
from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.redaction import mask_logon
from acars_bridge.services.backoff import delay_seconds
from acars_bridge.services.session import build_session

app = typer.Typer(
    name="acars-bridge",
    help="Hoppie ACARS print bridge (Observer peek + thermal print).",
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
    """Open the desktop UI (Qt / PySide6)."""
    from acars_bridge.ui.app import run_app

    paths = AppPaths.for_testing(Path(data_dir)) if data_dir else None
    try:
        run_app(paths)
    except Exception as exc:  # noqa: BLE001 - surface display failures cleanly
        typer.secho(f"UI failed to start: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@app.command()
def configure(
    callsign: str | None = typer.Option(None, help="Flight callsign"),
    logon: str | None = typer.Option(None, help="Hoppie logon (stored encrypted)"),
    printer: str | None = typer.Option(
        None, help="console | cups://Name | win32://Name | file:// | tcp://"
    ),
    width: str | None = typer.Option(None, help="58 or 80"),
    auto_print: bool | None = typer.Option(None, help="Enable automatic printing"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Store local settings. Logon is encrypted at rest."""
    session = _session(data_dir)
    try:
        if callsign:
            session.settings.set_callsign(callsign)
        if logon:
            session.settings.set_hoppie_logon(logon)
        if printer:
            session.settings.set_printer_destination(printer)
        if width:
            session.settings.set_paper_width(width)
        if auto_print is not None:
            session.settings.set_auto_print(auto_print)

        typer.echo("Settings saved.")
        typer.echo(f"Callsign: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Logon: {mask_logon(session.settings.hoppie_logon())}")
        typer.echo("Mode: observer")
        typer.echo(f"Printer: {session.settings.printer_destination()}")
        typer.echo(f"Width: {session.settings.paper_width()}mm")
        typer.echo(f"Auto-print: {'yes' if session.settings.auto_print() else 'no'}")
        typer.echo(f"Data: {session.paths.root}")
    finally:
        session.close()


@app.command("status")
def status_cmd(data_dir: str | None = typer.Option(None, hidden=True)) -> None:
    """Show current session configuration (secrets masked)."""
    session = _session(data_dir)
    try:
        typer.echo(f"acars-bridge {__version__}")
        typer.echo("Mode: observer")
        typer.echo(f"Callsign: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Logon: {mask_logon(session.settings.hoppie_logon())}")
        typer.echo(f"Printer: {session.settings.printer_destination()}")
        typer.echo(f"Peek interval: {session.settings.poll_interval()}s")
        typer.echo(f"Data: {session.paths.root}")
    finally:
        session.close()


def _run_observe(session, *, once: bool, loop: bool) -> None:
    logon = session.settings.hoppie_logon()
    callsign = session.settings.callsign()
    if not logon or not callsign:
        raise typer.Exit("Configure --callsign and --logon first (acars-bridge configure).")

    failures = 0
    first = True
    while first or loop:
        first = False
        try:
            messages = session.observer.fetch(logon, callsign)
            stats = session.ingestion.ingest(messages)
            typer.echo(
                f"observe: stored={stats['stored']} printed={stats['printed']} "
                f"duplicates={stats['duplicates']} failed_prints={stats['failed_prints']}"
            )
            failures = 0
            interval = session.settings.poll_interval()
        except CallsignInUseError as exc:
            typer.secho(
                f"Callsign in use: {exc}. Use the same Hoppie logon as the aircraft client.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=2) from exc
        except HoppieError as exc:
            failures += 1
            typer.secho(f"Hoppie error: {exc}", fg=typer.colors.RED)
            interval = delay_seconds(failures)
            if once and not loop:
                raise typer.Exit(code=1) from exc
        if once and not loop:
            break
        sleep_for = interval + (0 if failures else random.randint(0, JITTER_SECONDS))
        typer.echo(f"Sleeping {sleep_for}s...")
        time.sleep(sleep_for)


@app.command()
def observe(
    once: bool = typer.Option(True, "--once/--loop", help="One peek or continuous loop"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Peek for queued Hoppie traffic and auto-print (non-destructive)."""
    session = _session(data_dir)
    try:
        _run_observe(session, once=once, loop=not once)
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
        settings = PrinterSettings(
            destination=destination or session.settings.printer_destination(),
            paper_width=width or session.settings.paper_width(),
            cut_enabled=session.settings.cut_enabled(),
            aircraft_registration=session.settings.aircraft_registration(),
        )
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
    """ACARS Print Bridge CLI."""


if __name__ == "__main__":
    app()
