from __future__ import annotations

import random
import time
from enum import Enum
from pathlib import Path

import typer

from acars_bridge import __version__
from acars_bridge.config import FAST_POLL_SECONDS, JITTER_SECONDS, AppPaths
from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError, SendNotAllowedError
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.redaction import mask_logon
from acars_bridge.services.backoff import delay_seconds
from acars_bridge.services.session import build_session

app = typer.Typer(
    name="acars-bridge",
    help="Standalone Hoppie ACARS client with thermal printing (Station + Observer).",
    no_args_is_help=True,
)


class ReplyChoice(str, Enum):  # noqa: UP042 - Typer works best with str, Enum
    WILCO = "WILCO"
    ROGER = "ROGER"
    UNABLE = "UNABLE"
    STANDBY = "STANDBY"


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
    mode: ClientMode | None = typer.Option(None, help="station or observer"),
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
        if mode:
            session.settings.set_mode(mode)
        if printer:
            session.settings.set_printer_destination(printer)
        if width:
            session.settings.set_paper_width(width)
        if auto_print is not None:
            session.settings.set_auto_print(auto_print)

        typer.echo("Settings saved.")
        typer.echo(f"Callsign: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Logon: {mask_logon(session.settings.hoppie_logon())}")
        typer.echo(f"Mode: {session.settings.mode().value}")
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
        typer.echo(f"Mode: {session.settings.mode().value}")
        typer.echo(f"Callsign: {session.settings.callsign() or '(unset)'}")
        typer.echo(f"Logon: {mask_logon(session.settings.hoppie_logon())}")
        typer.echo(f"Printer: {session.settings.printer_destination()}")
        typer.echo(f"Poll interval: {session.settings.poll_interval()}s")
        typer.echo(f"Data: {session.paths.root}")
    finally:
        session.close()


def _run_cycle(session, transport, *, once: bool, loop: bool, label: str) -> None:
    logon = session.settings.hoppie_logon()
    callsign = session.settings.callsign()
    if not logon or not callsign:
        raise typer.Exit("Configure --callsign and --logon first (acars-bridge configure).")

    failures = 0
    first = True
    while first or loop:
        first = False
        try:
            messages = transport.fetch(logon, callsign)
            stats = session.ingestion.ingest(messages)
            typer.echo(
                f"{label}: stored={stats['stored']} printed={stats['printed']} "
                f"duplicates={stats['duplicates']} failed_prints={stats['failed_prints']}"
            )
            failures = 0
            interval = session.settings.poll_interval()
        except CallsignInUseError as exc:
            typer.secho(
                f"Callsign in use: {exc}. Another client owns this callsign. "
                "Use Observer mode (`acars-bridge configure --mode observer` / "
                "`acars-bridge observe`) or stop the other client.",
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
def poll(
    once: bool = typer.Option(True, "--once/--loop", help="One poll or continuous station loop"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Station poll (consumes messages, takes callsign lock)."""
    session = _session(data_dir)
    try:
        if session.settings.mode() is ClientMode.OBSERVER:
            typer.secho(
                "Configured mode is observer. Use `acars-bridge observe`, "
                "or `configure --mode station` to own the callsign.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=2)
        _run_cycle(session, session.station, once=once, loop=not once, label="poll")
    finally:
        session.close()


@app.command()
def observe(
    once: bool = typer.Option(True, "--once/--loop", help="One peek or continuous observer loop"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Observer peek (non-destructive; does not send). Keep frequency low."""
    session = _session(data_dir)
    try:
        _run_cycle(session, session.observer, once=once, loop=not once, label="observe")
    finally:
        session.close()


@app.command("send-telex")
def send_telex(
    to: str = typer.Argument(..., help="Destination station / ATC"),
    text: str = typer.Argument(..., help="Telex body"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Send a telex (Station mode only)."""
    session = _session(data_dir)
    try:
        stored = session.outbound.send_telex(to, text)
        typer.echo(f"Sent telex #{stored.id} to {stored.to_station}")
    except (HoppieError, SendNotAllowedError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command("request-metar")
def request_metar(
    icao: str = typer.Argument(..., help="Airport ICAO"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Request METAR via Hoppie inforeq (Station mode)."""
    from acars_bridge.hoppie.requests import WeatherKind

    session = _session(data_dir)
    try:
        rows = session.outbound.request_weather(WeatherKind.METAR, icao)
        _echo_request_result("METAR", rows)
    except (HoppieError, SendNotAllowedError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command("request-atis")
def request_atis(
    icao: str = typer.Argument(..., help="Airport ICAO"),
    side: str = typer.Option("dep", "--side", help="dep or arr (VATSIM D-ATIS)"),
    source: str = typer.Option("vatatis", "--source", help="vatatis|ivaoatis|peatis"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Request ATIS via Hoppie inforeq (Station mode)."""
    from acars_bridge.hoppie.requests import AtisSide, AtisSource

    session = _session(data_dir)
    try:
        rows = session.outbound.request_atis(
            icao,
            source=AtisSource(source.lower()),
            side=AtisSide(side.lower()),
        )
        _echo_request_result("ATIS", rows)
    except (HoppieError, SendNotAllowedError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command("request-pdc")
def request_pdc(
    station: str = typer.Option(..., "--station", help="ATC / delivery callsign"),
    departure: str = typer.Option(..., "--dep", help="Departure ICAO"),
    destination: str = typer.Option(..., "--dest", help="Destination ICAO"),
    stand: str = typer.Option(..., "--stand", help="Stand / gate"),
    atis: str = typer.Option(..., "--atis", help="Current ATIS letter"),
    aircraft_type: str = typer.Option("A320", "--type", help="Aircraft type"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Send a PREDEP CLEARANCE telex (Station mode)."""
    session = _session(data_dir)
    try:
        stored = session.outbound.request_pdc(
            station=station,
            departure=departure,
            destination=destination,
            aircraft_type=aircraft_type,
            stand=stand,
            atis_letter=atis,
        )
        typer.echo(f"PDC #{stored.id} sent to {stored.to_station}")
        typer.echo(f"Tip: poll soon (~{FAST_POLL_SECONDS}s) for the clearance reply.")
    except (HoppieError, SendNotAllowedError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command("send-position")
def send_position(
    to: str = typer.Argument(..., help="Destination station"),
    latitude: str = typer.Option(..., "--lat", help="Latitude (e.g. N5030.0)"),
    longitude: str = typer.Option(..., "--lon", help="Longitude (e.g. E00845.0)"),
    altitude: str = typer.Option(..., "--alt", help="Altitude / FL"),
    time_utc: str = typer.Option(..., "--time", help="UTC time HHMMZ"),
    next_waypoint: str | None = typer.Option(None, "--next", help="Next waypoint"),
    eta: str | None = typer.Option(None, "--eta", help="ETA HHMMZ"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Send a manual position report (Station mode)."""
    session = _session(data_dir)
    try:
        stored = session.outbound.send_position(
            to=to,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            time_utc=time_utc,
            next_waypoint=next_waypoint,
            eta=eta,
        )
        typer.echo(f"Position #{stored.id} sent to {stored.to_station}")
    except (HoppieError, SendNotAllowedError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


def _echo_request_result(label: str, rows: list) -> None:
    inbound = [r for r in rows if getattr(r, "direction", None) == "in"]
    if not inbound:
        typer.echo(f"{label} request sent — no inline reply body.")
        return
    for row in inbound:
        typer.echo(f"#{row.id} [{row.message_type}]")
        typer.echo(row.normalized_body)


@app.command()
def reply(
    message_id: int = typer.Argument(..., help="Inbound message id from history"),
    response: ReplyChoice = typer.Argument(..., help="WILCO|ROGER|UNABLE|STANDBY"),
    data_dir: str | None = typer.Option(None, hidden=True),
) -> None:
    """Send a CPDLC standard reply (Station mode only)."""
    session = _session(data_dir)
    try:
        stored = session.outbound.reply_cpdlc(message_id, response.value)
        typer.echo(f"Sent CPDLC reply #{stored.id}: {stored.normalized_body}")
        # Temporarily faster poll hint for the operator.
        typer.echo(f"Tip: poll again soon (~{FAST_POLL_SECONDS}s) for follow-up uplinks.")
    except (HoppieError, SendNotAllowedError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
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
        )
        from acars_bridge.printing.discovery import is_device_printer_destination

        # Rebuild print manager if destination override needs escpos
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
    """Show recent inbound/outbound messages."""
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


# Typer object is the console script entry (`acars-bridge = acars_bridge.cli:app`).
# Also allow `python -m acars_bridge.cli`.
if __name__ == "__main__":
    app()
