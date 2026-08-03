from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.hoppie.atis_text import inforeq_station_title
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
        received_at="2026-08-02T14:30:00+00:00",
    )
    base.update(kwargs)
    return StoredMessage(**base)


def test_80mm_cpdlc_uses_acars_begin_end_wrapper():
    out = ThermalMessageFormatter().format(
        _msg(),
        PrinterSettings(
            "console",
            paper_width="80",
            aircraft_registration="HB-IJK",
        ),
        now=datetime(2026, 8, 2, 14, 32, tzinfo=UTC),
    )
    lines = out.splitlines()
    assert lines[0] == "ACARS BEGIN"
    assert lines[1] == "02 AUG 2026  1432Z  REG HB-IJK"
    assert lines[2] == ""
    assert lines[3] == "02 AUG 2026  1430Z"
    assert lines[4] == ""
    assert "FROM LSAS_CTR" in out
    assert "CLIMB TO AND MAINTAIN FL360" in out
    assert lines[-2] == ""
    assert lines[-1] == "ACARS END"
    assert "FLT" not in out
    assert "REQ" not in out
    assert "ACARS PRINT BRIDGE" not in out
    assert "TYPE:" not in out
    assert "-----" not in out
    assert PrinterSettings("console", paper_width="80").characters_per_line() == 48


def test_no_reg_when_registration_not_configured():
    out = ThermalMessageFormatter().format(
        _msg(callsign="DLH9911", received_at=""),
        PrinterSettings("console", paper_width="80"),
        now=datetime(2026, 8, 2, 13, 19, tzinfo=UTC),
    )
    assert out.splitlines()[1] == "02 AUG 2026  1319Z"
    assert "REG" not in out
    # No received_at → message time equals print time.
    assert out.splitlines()[3] == "02 AUG 2026  1319Z"
    assert "\n\nACARS END" in out


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
    assert out.startswith("ACARS BEGIN")
    assert "ACARS END" in out


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
            received_at="2026-08-02T18:10:00+00:00",
        ),
        PrinterSettings(
            "console",
            paper_width="80",
            aircraft_registration="D-AIXX",
        ),
        now=datetime(2026, 8, 2, 18, 14, tzinfo=UTC),
    )
    assert out.splitlines()[0] == "ACARS BEGIN"
    assert out.splitlines()[1] == "02 AUG 2026  1814Z  REG D-AIXX"
    assert out.splitlines()[3] == "02 AUG 2026  1810Z"
    assert "VATATIS" not in out
    assert "REQ" not in out
    assert "FLT" not in out
    assert "FROM acars" not in out
    assert "EDDH DEP ATIS H" in out
    assert "RWY 23 IN USE" in out
    assert "QNH 1015" in out
    assert out.rstrip().endswith("ACARS END")
    assert "\n\nACARS END" in out


def test_inforeq_unavailable_shows_station():
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH9911",
            sender="acars",
            message_type="inforeq",
            normalized_body="VATATIS EDDH_D\nTHIS ATIS IS NOT\nAVAILABLE",
            min=None,
            ra=None,
            received_at="2026-08-02T13:18:00+00:00",
        ),
        PrinterSettings(
            "console",
            paper_width="80",
            aircraft_registration="D-AIXX",
        ),
        now=datetime(2026, 8, 2, 13, 19, tzinfo=UTC),
    )
    assert "ACARS BEGIN" in out
    assert "02 AUG 2026  1319Z  REG D-AIXX" in out
    assert "02 AUG 2026  1318Z" in out
    assert "EDDH DEP ATIS" in out
    assert "VATATIS" not in out
    assert "REQ" not in out
    assert "THIS ATIS IS NOT" in out
    assert "AVAILABLE" in out
    assert "\n\nACARS END" in out


def test_inforeq_station_title_helpers():
    assert inforeq_station_title("VATATIS EDDH_D") == "EDDH DEP ATIS"
    assert inforeq_station_title("VATATIS EDDH_A") == "EDDH ARR ATIS"
    assert inforeq_station_title("METAR LOWW") == "METAR LOWW"


def test_test_page_uses_wrapper():
    out = ThermalMessageFormatter().test_page(
        PrinterSettings("console", paper_width="80", aircraft_registration="D-AIXX"),
        now=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )
    assert out.startswith("ACARS BEGIN\n")
    assert "REG D-AIXX" in out
    assert "TEST PRINT" in out
    assert out.rstrip().endswith("ACARS END")
    assert "\n\nACARS END" in out
