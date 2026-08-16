from __future__ import annotations

from acars_bridge.config import AppPaths
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.companion_qr import pairing_caption, qr_bitmap, should_emit_pairing_qr
from acars_bridge.services.session import build_session


def test_should_emit_only_when_companion_url_ready_and_not_yet_printed() -> None:
    assert should_emit_pairing_qr(
        enabled=True,
        url="http://192.168.1.20:8765/",
        already=False,
        ticket_type="flight_plan",
    )
    assert not should_emit_pairing_qr(
        enabled=True,
        url="http://192.168.1.20:8765/",
        already=False,
        ticket_type="loadsheet_final",
    )
    assert not should_emit_pairing_qr(
        enabled=False, url="http://192.168.1.20:8765/", already=False, ticket_type="flight_plan"
    )
    assert not should_emit_pairing_qr(
        enabled=True, url="", already=False, ticket_type="flight_plan"
    )
    assert not should_emit_pairing_qr(
        enabled=True, url="http://192.168.1.20:8765/", already=True, ticket_type="flight_plan"
    )


def test_pairing_caption_tells_the_phone_to_scan() -> None:
    text = pairing_caption("http://192.168.1.20:8765/")
    assert "PHONE INBOX" in text
    assert "SCAN TO OPEN" in text
    assert "http://192.168.1.20:8765/" in text


def test_qr_bitmap_is_scannable_square() -> None:
    img = qr_bitmap("http://192.168.1.20:8765/")
    assert img.mode in {"1", "L"}
    assert img.size[0] == img.size[1]
    assert img.size[0] >= 80


def _print_ofp(session, ticket_type: str, body: str = "EDDF -> LSZH\nRoute: SID DCT STAR") -> None:
    session.print_manager.print_ticket(
        body,
        PrinterSettings("fake"),
        callsign="DLH4A",
        ticket_type=ticket_type,
    )


def test_first_print_appends_pairing_qr_once(tmp_path) -> None:
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_companion_enabled(True)
    session.settings.set_companion_port(8765)
    url = "http://192.168.1.20:8765/"
    session.print_manager.set_pairing_url(url)

    _print_ofp(session, "flight_plan")
    printer = session.print_manager._printer
    assert len(printer.printed) == 1
    body = printer.printed[0][1]
    assert "PHONE INBOX" in body
    assert url in body
    assert printer.pairing_urls == [url]

    _print_ofp(session, "flight_plan")
    assert len(printer.printed) == 2
    assert "PHONE INBOX" not in printer.printed[1][1]
    assert printer.pairing_urls == [url]


def test_pairing_qr_stays_off_final_loadsheet(tmp_path) -> None:
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    url = "http://192.168.1.20:8765/"
    session.print_manager.set_pairing_url(url)

    _print_ofp(session, "loadsheet_final", "FINAL LOADSHEET\nZFW 140.0")
    printer = session.print_manager._printer
    assert "PHONE INBOX" not in printer.printed[0][1]
    assert printer.pairing_urls == []

    _print_ofp(session, "flight_plan")
    assert "PHONE INBOX" in printer.printed[1][1]
    assert printer.pairing_urls == [url]


def test_pairing_qr_returns_after_ofp_unlock(tmp_path) -> None:
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    url = "http://192.168.1.20:8765/"
    session.print_manager.set_pairing_url(url)
    _print_ofp(session, "flight_plan")
    assert session.print_manager._printer.pairing_urls == [url]

    session.ensure_simbrief_watcher().unlock(reason="manual")
    _print_ofp(session, "flight_plan")
    assert session.print_manager._printer.pairing_urls == [url, url]


def test_pairing_qr_resets_when_url_changes(tmp_path) -> None:
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.print_manager.set_pairing_url("http://192.168.1.20:8765/")
    _print_ofp(session, "flight_plan")
    session.print_manager.set_pairing_url("http://192.168.1.21:8765/")
    _print_ofp(session, "flight_plan")
    printer = session.print_manager._printer
    assert printer.pairing_urls == [
        "http://192.168.1.20:8765/",
        "http://192.168.1.21:8765/",
    ]
