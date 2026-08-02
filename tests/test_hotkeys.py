from __future__ import annotations

import pytest

from acars_bridge.ui.hotkeys import (
    HOTKEY_ACTIONS,
    HotkeyBindingError,
    conflict_errors,
    help_text,
    load_bindings,
    normalize_sequence,
    qt_to_pynput,
    save_binding,
    sequence_is_safe_global,
    validate_bindings,
)


class _MemSettings:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = value


def test_actions_cover_core_operations():
    actions = {item.action for item in HOTKEY_ACTIONS}
    for required in (
        "check_now",
        "start",
        "pause",
        "reply_wilco",
        "reply_roger",
        "reply_unable",
        "reply_standby",
        "send_telex",
        "reprint",
        "test_print",
        "help",
        "select_prev",
        "select_next",
        "tab_settings",
        "save_settings",
    ):
        assert required in actions


def test_defaults_are_unset():
    settings = _MemSettings()
    assert load_bindings(settings) == {}


def test_save_and_load_binding():
    settings = _MemSettings()
    save_binding(settings, "start", "Ctrl+Shift+S")
    assert load_bindings(settings) == {"start": "Ctrl+Shift+S"}
    save_binding(settings, "start", "")
    assert load_bindings(settings) == {}


def test_help_text_shows_unset_by_default():
    text = help_text({})
    assert "(unset)" in text
    assert "No shortcuts configured" in text


def test_qt_to_pynput_conversion():
    assert qt_to_pynput("Ctrl+Shift+S") == "<ctrl>+<shift>+s"
    assert qt_to_pynput("F5") == "<f5>"
    assert qt_to_pynput("Alt+1") == "<alt>+1"


def test_global_safety_rules():
    assert sequence_is_safe_global("Ctrl+S")
    assert sequence_is_safe_global("F2")
    assert sequence_is_safe_global("Alt+R")
    assert not sequence_is_safe_global("W")
    assert not sequence_is_safe_global("1")
    assert not sequence_is_safe_global("Shift+W")
    assert not sequence_is_safe_global("")


def test_validate_bindings_rejects_conflicts_and_unsafe():
    with pytest.raises(HotkeyBindingError):
        validate_bindings({"start": "W"})
    with pytest.raises(HotkeyBindingError):
        validate_bindings({"start": "Ctrl+S", "pause": "Ctrl+S"})
    validate_bindings({"start": "Ctrl+Shift+S", "check_now": "F5"})


def test_normalize_empty():
    assert normalize_sequence("") == ""
    assert normalize_sequence(None) == ""


def test_conflict_errors_helper():
    errs = conflict_errors({"a": "Ctrl+A", "b": "Ctrl+A"})
    assert errs
