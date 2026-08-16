from __future__ import annotations

from unittest.mock import patch

from acars_bridge.printing.discovery import (
    destination_from_label,
    destination_from_manual_draft,
    infer_printer_input_mode,
    is_device_printer_destination,
    list_cups_printer_names,
    list_printer_choices,
    normalize_printer_destination,
    parse_tcp_printer,
    tcp_printer_destination,
    windows_share_path,
)


def test_list_printer_choices_includes_console_and_cups(monkeypatch):
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.list_cups_printer_names",
        lambda: ["Brother_MFC", "Kitchen_Thermal"],
    )
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.list_win32_printer_names",
        lambda: [],
    )
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.sys.platform",
        "linux",
    )
    choices = list_printer_choices()
    assert choices[0].destination == "console"
    assert choices[0].label == "console (log only)"
    assert any(c.destination == "cups://Brother_MFC" for c in choices)
    assert any(c.destination == "cups-raw://Brother_MFC" for c in choices)
    assert any(c.label == "Kitchen_Thermal · POS ESC/POS" for c in choices)
    assert any(c.label == "Brother_MFC · driver" for c in choices)


def test_list_printer_choices_preserves_custom_tcp():
    with (
        patch("acars_bridge.printing.discovery.list_cups_printer_names", return_value=[]),
        patch("acars_bridge.printing.discovery.list_win32_printer_names", return_value=[]),
        patch("acars_bridge.printing.discovery.sys.platform", "linux"),
    ):
        choices = list_printer_choices("tcp://192.168.1.50:9100")
    assert any(c.destination == "tcp://192.168.1.50:9100" for c in choices)


def test_destination_from_label_maps_cups_name():
    from acars_bridge.printing.discovery import PrinterChoice

    choices = [
        PrinterChoice("console", "console"),
        PrinterChoice("Brother_MFC · driver", "cups://Brother_MFC"),
        PrinterChoice("Brother_MFC · POS ESC/POS", "cups-raw://Brother_MFC"),
    ]
    assert destination_from_label("Brother_MFC · driver", choices) == "cups://Brother_MFC"
    assert (
        destination_from_label("Brother_MFC · POS ESC/POS", choices)
        == "cups-raw://Brother_MFC"
    )
    assert destination_from_label("console", choices) == "console"


def test_tcp_printer_destination_normalizes_host_and_port():
    assert tcp_printer_destination("192.168.1.50", 9100) == "tcp://192.168.1.50:9100"
    assert tcp_printer_destination("  10.0.0.8  ", "9100") == "tcp://10.0.0.8:9100"
    assert tcp_printer_destination("pos.local", None) == "tcp://pos.local:9100"
    assert tcp_printer_destination("pos.local", 0) == "tcp://pos.local:9100"
    assert tcp_printer_destination("", 9100) == ""
    assert tcp_printer_destination("   ") == ""


def test_parse_tcp_printer_reads_host_and_default_port():
    assert parse_tcp_printer("tcp://192.168.1.50:9100") == ("192.168.1.50", 9100)
    assert parse_tcp_printer("tcp://pos.local") == ("pos.local", 9100)
    assert parse_tcp_printer("tcp://10.0.0.8:9101/") == ("10.0.0.8", 9101)
    assert parse_tcp_printer("win32://EPSON") is None
    assert parse_tcp_printer("console") is None
    assert parse_tcp_printer("") is None


def test_is_device_printer_destination():
    assert is_device_printer_destination("cups://Brother")
    assert is_device_printer_destination("cups-raw://Thermal")
    assert is_device_printer_destination("win32://EPSON")
    assert is_device_printer_destination("tcp://10.0.0.1:9100")
    assert is_device_printer_destination(r"\\192.168.1.10\POS-80")
    assert not is_device_printer_destination("console")


def test_normalize_accepts_unc_share_path():
    assert normalize_printer_destination(r"\\192.168.1.10\POS-80") == (
        r"win32://\\192.168.1.10\POS-80"
    )
    assert normalize_printer_destination("//pedestal/POS-80") == (
        r"win32://\\pedestal\POS-80"
    )
    assert normalize_printer_destination(r"win32://\\192.168.1.10\POS-80") == (
        r"win32://\\192.168.1.10\POS-80"
    )
    assert normalize_printer_destination("win32://EPSON TM") == "win32://EPSON TM"
    assert normalize_printer_destination("tcp://10.0.0.8:9100") == "tcp://10.0.0.8:9100"
    assert normalize_printer_destination("console") == "console"
    assert normalize_printer_destination("") == "console"


def test_windows_share_path_roundtrip():
    assert windows_share_path(r"win32://\\192.168.1.10\POS-80") == (
        r"\\192.168.1.10\POS-80"
    )
    assert windows_share_path(r"\\SERVER\Kitchen Thermal") == r"\\SERVER\Kitchen Thermal"
    assert windows_share_path("win32://EPSON") is None
    assert windows_share_path("tcp://10.0.0.1:9100") is None


def test_destination_from_label_accepts_unc():
    from acars_bridge.printing.discovery import PrinterChoice

    choices = [PrinterChoice("console (log only)", "console")]
    assert destination_from_label(r"\\192.168.1.10\POS-80", choices) == (
        r"win32://\\192.168.1.10\POS-80"
    )


def test_infer_printer_input_mode() -> None:
    assert infer_printer_input_mode("console") == "list"
    assert infer_printer_input_mode("win32://EPSON") == "list"
    assert infer_printer_input_mode(r"win32://\\192.168.1.10\POS-80") == "path"
    assert infer_printer_input_mode("tcp://10.0.0.8:9100") == "ip"


def test_destination_from_manual_draft() -> None:
    assert destination_from_manual_draft(r"\\192.168.1.10\POS-80") == (
        r"win32://\\192.168.1.10\POS-80"
    )
    assert destination_from_manual_draft("10.0.0.8") == "tcp://10.0.0.8:9100"
    assert destination_from_manual_draft("10.0.0.8:9101") == "tcp://10.0.0.8:9101"
    assert destination_from_manual_draft("pos.local", 9100) == "tcp://pos.local:9100"
    assert destination_from_manual_draft("") == "console"


def test_list_printer_choices_preserves_unc(monkeypatch):
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.list_win32_printer_names",
        lambda: [r"\\192.168.1.10\POS-80"],
    )
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.list_cups_printer_names",
        lambda: [],
    )
    monkeypatch.setattr(
        "acars_bridge.printing.discovery.sys.platform",
        "win32",
    )
    choices = list_printer_choices(r"\\10.0.0.5\Other")
    dests = {c.destination for c in choices}
    assert r"win32://\\192.168.1.10\POS-80" in dests
    assert r"win32://\\10.0.0.5\Other" in dests


def test_list_cups_printer_names_parses_lpstat_e():
    with patch(
        "acars_bridge.printing.discovery._run",
        return_value="Brother_MFC_L2710DW_series\nOffice_Laser\n",
    ):
        assert list_cups_printer_names() == [
            "Brother_MFC_L2710DW_series",
            "Office_Laser",
        ]
