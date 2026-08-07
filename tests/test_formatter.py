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


def test_characters_per_line_font_b_and_wide():
    assert PrinterSettings("console", paper_width="80", font="b").characters_per_line() == 64
    assert (
        PrinterSettings(
            "console", paper_width="80", char_width=2
        ).characters_per_line()
        == 24
    )
    assert (
        PrinterSettings(
            "console", paper_width="80", character_width_override=40
        ).characters_per_line()
        == 40
    )


def test_header_reg_callsign_stamp():
    """Real strip: D-AILA ----  DLH4MC 04AUG 1809Z"""
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH4MC",
            message_type="telex",
            normalized_body="CLEARANCE REQUEST RECEIVED\nSTANDBY",
            received_at="2026-08-04T18:09:00+00:00",
        ),
        PrinterSettings(
            "console",
            paper_width="80",
            aircraft_registration="D-AILA",
        ),
    )
    lines = out.splitlines()
    assert lines[0] == "ACARS START"
    assert lines[1] == "=" * 48  # 80mm default columns
    assert lines[2] == "D-AILA ----  DLH4MC 04AUG 1809Z"
    assert lines[3] == "-" * 48
    assert "CLEARANCE REQUEST RECEIVED" in out
    assert "STANDBY" in out
    assert lines[-1] == "ACARS END"
    assert "----" in lines[2]


def test_empty_registration_omits_dashes():
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH4MC",
            received_at="2026-08-04T18:09:00+00:00",
        ),
        PrinterSettings("console", paper_width="80"),
    )
    header = out.splitlines()[2]
    assert header == "DLH4MC 04AUG 1809Z"
    assert "----" not in header
    assert not header.startswith("D-")


def test_atis_with_registration_includes_callsign():
    out = ThermalMessageFormatter().format(
        _msg(
            callsign="DLH4MC",
            sender="acars",
            message_type="inforeq",
            normalized_body=(
                "VATATIS EDDF_D\n"
                "DEP-ATIS EDDF G METAR 041750\n"
                "RWY 25C 18\n"
                "TREND NOSIG"
            ),
            min=None,
            ra=None,
            received_at="2026-08-04T18:05:00+00:00",
        ),
        PrinterSettings(
            "console",
            paper_width="80",
            aircraft_registration="D-AILA",
        ),
    )
    assert out.splitlines()[2] == "D-AILA ----  DLH4MC 04AUG 1805Z"
    assert "VATATIS" not in out
    assert "DEP-ATIS EDDF G METAR 041750" in out
    assert out.startswith("ACARS START")
    assert "=" * 8 in out


def test_58mm_width_and_token_wrap():
    out = ThermalMessageFormatter().format(
        _msg(
            normalized_body="CLEARED TO LSZH VIA N850 TOLEN DCT RUDUS T161 HAREM",
            message_type="cpdlc",
        ),
        PrinterSettings("console", paper_width="58", aircraft_registration="D-AILA"),
    )
    assert PrinterSettings("console", paper_width="58").characters_per_line() == 32
    assert "N850" in out
    assert "N85\n0" not in out
    assert out.startswith("ACARS START")
    assert "ACARS END" in out


def test_inforeq_prints_atis_body_not_hoppie_request():
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
    )
    assert out.splitlines()[2] == "D-AIXX ----  DLH9911 02AUG 1810Z"
    assert "VATATIS" not in out
    assert "EDDH DEP ATIS H" in out
    assert out.rstrip().endswith("ACARS END")


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
    )
    assert "D-AIXX ----  DLH9911 02AUG 1318Z" in out
    assert "EDDH DEP ATIS" in out
    assert "VATATIS" not in out
    assert "THIS ATIS IS NOT" in out
    assert "ACARS START" in out
    assert out.rstrip().endswith("ACARS END")


def test_inforeq_station_title_helpers():
    assert inforeq_station_title("VATATIS EDDH_D") == "EDDH DEP ATIS"
    assert inforeq_station_title("VATATIS EDDH_A") == "EDDH ARR ATIS"
    assert inforeq_station_title("METAR LOWW") == "METAR LOWW"


def test_test_page_is_demo_pdc_strip():
    out = ThermalMessageFormatter().test_page(
        PrinterSettings("console", paper_width="80"),
    )
    lines = out.splitlines()
    assert lines[0] == "ACARS START"
    # Empty registration → no sample tail injected.
    assert lines[2] == "DLH4MC 04AUG 1809Z"
    assert "----" not in lines[2]
    assert "CLD 1807 260804 EDDF PDC 001" in out
    assert "CINDY8S SQUAWK 1000 NEXT FREQ" in out
    assert "TEST PRINT" not in out
    assert out.rstrip().endswith("ACARS END")


def test_test_page_uses_configured_registration():
    out = ThermalMessageFormatter().test_page(
        PrinterSettings("console", paper_width="80", aircraft_registration="D-AIXX"),
    )
    assert out.splitlines()[2] == "D-AIXX ----  DLH4MC 04AUG 1809Z"


def test_test_page_empty_registration_omits_dashes():
    out = ThermalMessageFormatter().test_page(
        PrinterSettings("console", paper_width="80", aircraft_registration=""),
    )
    header = out.splitlines()[2]
    assert header == "DLH4MC 04AUG 1809Z"
    assert "D-AILA" not in out
    assert "----" not in header


def test_body_forced_uppercase():
    out = ThermalMessageFormatter().format(
        _msg(normalized_body="climb to fl360"),
        PrinterSettings("console", paper_width="80", aircraft_registration="D-AILA"),
    )
    assert "CLIMB TO FL360" in out
    assert "climb to fl360" not in out
