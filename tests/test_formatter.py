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


def test_80mm_layout():
    out = ThermalMessageFormatter().format(
        _msg(),
        PrinterSettings("console", paper_width="80"),
        now=datetime(2026, 8, 2, 14, 32, tzinfo=UTC),
    )
    assert "ACARS PRINT BRIDGE" in out
    assert "UTC: 02 AUG 2026  1432Z" in out
    assert "FLT: SWR14" in out
    assert "TYPE: CPDLC UPLINK" in out
    assert "MSG ID: 8F31A2C4" in out
    assert len(out.splitlines()[0]) == 42


def test_58mm_width_and_token_wrap():
    out = ThermalMessageFormatter().format(
        _msg(
            normalized_body="CLEARED TO LSZH VIA N850 TOLEN DCT RUDUS T161 HAREM",
            message_type="cpdlc",
        ),
        PrinterSettings("console", paper_width="58"),
    )
    assert len(out.splitlines()[0]) == 32
    assert "N850" in out
    assert "N85\n0" not in out
