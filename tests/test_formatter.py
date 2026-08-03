from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.formatter import ThermalMessageFormatter


def _msg(**kwargs) -> StoredMessage:
    base = dict(
        id=1,
        fingerprint="8f31a2c4deadbeef",
        direction="in",
        callsign="SWR14",
        sender="LSAS_CTR",
        recipient="SWR14",
        to_station=None,
        message_type="cpdlc",
        raw_payload="raw",
        normalized_body="CLIMB TO AND MAINTAIN FL360",
        min=15,
        mrn=None,
        ra="WU",
        send_status=None,
        received_at="",
    )
    base.update(kwargs)
    return StoredMessage(**base)


def test_80mm_cpdlc_looks_like_uplink_strip():
    out = ThermalMessageFormatter().format(
        _msg(),
        PrinterSettings("console", paper_width="80"),
        now=datetime(2026, 8, 2, 14, 32, tzinfo=UTC),
    )
    assert out.splitlines()[0] == "1432Z"
    assert "FROM LSAS_CTR" in out
    assert "CLIMB TO AND MAINTAIN FL360" in out
    assert "FLT" not in out
    assert "REQ" not in out
    assert "ACARS PRINT BRIDGE" not in out
    assert "TYPE:" not in out
    assert "-----" not in out
    assert PrinterSettings("console", paper_width="80").characters_per_line() == 48


def test_58mm_width_and_token_wrap():
    out = ThermalMessageFormatter().format(
        _msg(
            normalized_body="CLEARED TO LSZH VIA N850 TOLEN DCT RUDUS T161 HAREM",
            message_type="cpdlc",
        ),
        PrinterSettings("console", paper_width="58"),
    )
    assert PrinterSettings("console", paper_width="58").characters_per_line() == 32
    assert "N850" in out
    assert "N85\n0" not in out


def test_inforeq_prints_atis_body_not_hoppie_request():
    """Real D-ATIS strips are the uplink text — not REQ VATATIS EDDH_D."""
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH9911",
            sender="acars",
            message_type="inforeq",
            normalized_body=(
                "VATATIS EDDH_D\n"
                "EDDH DEP ATIS H\n"
                "1400Z\n"
                "RWY 23 IN USE\n"
                "WIND 240 DEG 8 KT\n"
                "QNH 1015"
            ),
            min=None,
            ra=None,
        ),
        PrinterSettings("console", paper_width="80"),
        now=datetime(2026, 8, 2, 18, 14, tzinfo=UTC),
    )
    assert out.splitlines()[0] == "1814Z"
    assert "VATATIS" not in out
    assert "REQ" not in out
    assert "FLT" not in out
    assert "FROM acars" not in out
    assert "EDDH DEP ATIS H" in out
    assert "RWY 23 IN USE" in out
    assert "QNH 1015" in out


def test_inforeq_without_packet_keeps_full_body():
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH9911",
            sender="acars",
            message_type="inforeq",
            normalized_body="THIS ATIS IS NOT\nAVAILABLE",
            min=None,
            ra=None,
        ),
        PrinterSettings("console", paper_width="80"),
        now=datetime(2026, 8, 2, 18, 14, tzinfo=UTC),
    )
    assert "REQ" not in out
    assert "FROM acars" not in out
    assert "THIS ATIS IS NOT" in out
    assert "AVAILABLE" in out
