from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HotkeyAction:
    action: str
    label: str


# Shared action catalog — no default key bindings.
HOTKEY_ACTIONS: tuple[HotkeyAction, ...] = (
    HotkeyAction("check_now", "Check now / refresh link"),
    HotkeyAction("start", "Start monitoring"),
    HotkeyAction("pause", "Pause monitoring"),
    HotkeyAction("reload", "Reload message list"),
    HotkeyAction("tab_messages", "Messages tab"),
    HotkeyAction("tab_settings", "Settings tab"),
    HotkeyAction("save_settings", "Save settings"),
    HotkeyAction("reprint", "Print / reprint selected"),
    HotkeyAction("test_print", "Test print"),
    HotkeyAction("send_telex", "Send telex"),
    HotkeyAction("focus_telex", "Focus telex compose"),
    HotkeyAction("focus_telex_to", "Focus telex TO field"),
    HotkeyAction("select_prev", "Previous message"),
    HotkeyAction("select_next", "Next message"),
    HotkeyAction("help", "Show shortcuts"),
    HotkeyAction("reply_wilco", "Reply WILCO"),
    HotkeyAction("reply_roger", "Reply ROGER"),
    HotkeyAction("reply_unable", "Reply UNABLE"),
    HotkeyAction("reply_standby", "Reply STANDBY"),
)
