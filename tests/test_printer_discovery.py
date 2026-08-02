from __future__ import annotations

from unittest.mock import patch

from acars_bridge.printing.discovery import (
    destination_from_label,
    is_device_printer_destination,
    list_cups_printer_names,
    list_printer_choices,
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


def test_is_device_printer_destination():
    assert is_device_printer_destination("cups://Brother")
    assert is_device_printer_destination("cups-raw://Thermal")
    assert is_device_printer_destination("win32://EPSON")
    assert is_device_printer_destination("tcp://10.0.0.1:9100")
    assert not is_device_printer_destination("console")


def test_list_cups_printer_names_parses_lpstat_e():
    with patch(
        "acars_bridge.printing.discovery._run",
        return_value="Brother_MFC_L2710DW_series\nOffice_Laser\n",
    ):
        assert list_cups_printer_names() == [
            "Brother_MFC_L2710DW_series",
            "Office_Laser",
        ]
