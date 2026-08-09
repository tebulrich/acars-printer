from __future__ import annotations

from acars_bridge.models.settings import SettingsStore


def test_hotkey_defaults(app_session) -> None:
    settings = app_session.settings
    assert settings.hotkeys_enabled() is True
    bindings = settings.hotkey_bindings()
    assert bindings["reprint_last"] == "Ctrl+Shift+R"
    assert bindings["toggle_auto_print"] == "Ctrl+Shift+A"
    assert bindings["test_print"] == "Ctrl+Shift+T"
    assert bindings["feed"] == "Ctrl+Shift+F"


def test_set_hotkey_bindings_roundtrip(app_session) -> None:
    settings = app_session.settings
    settings.set_hotkey_bindings(
        {
            "reprint_last": "Ctrl+Alt+R",
            "toggle_auto_print": "Ctrl+Alt+A",
            "test_print": "",
            "feed": "F9",
            "bogus": "Ctrl+X",
        }
    )
    bindings = settings.hotkey_bindings()
    assert bindings["reprint_last"] == "Ctrl+Alt+R"
    assert bindings["toggle_auto_print"] == "Ctrl+Alt+A"
    assert bindings["test_print"] == ""
    assert bindings["feed"] == "F9"
    assert "bogus" not in bindings


def test_set_single_hotkey(app_session) -> None:
    settings = app_session.settings
    settings.set_hotkey_sequence("feed", "Ctrl+Shift+Space")
    assert settings.hotkey_sequence("feed") == "Ctrl+Shift+Space"
    assert settings.hotkey_sequence("reprint_last") == "Ctrl+Shift+R"


def test_window_title_includes_size() -> None:
    from acars_bridge.ui.app import format_window_title

    title = format_window_title("0.7.0", 1280, 800)
    assert "0.7.0" in title
    assert "1280" in title
    assert "800" in title
