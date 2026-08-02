from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from acars_bridge.hotkey_actions import HOTKEY_ACTIONS, HotkeyAction

__all__ = [
    "HOTKEY_ACTIONS",
    "HotkeyAction",
    "HotkeyBindingError",
    "conflict_errors",
    "help_text",
    "load_bindings",
    "normalize_sequence",
    "qt_to_pynput",
    "save_binding",
    "sequence_is_safe_global",
    "sequence_is_valid",
    "setting_key",
    "validate_bindings",
]

_HOTKEY_SETTING_PREFIX = "hotkey."


class HotkeyBindingError(ValueError):
    """Invalid or conflicting hotkey binding."""


def setting_key(action: str) -> str:
    return f"{_HOTKEY_SETTING_PREFIX}{action}"


def normalize_sequence(sequence: str | QKeySequence | None) -> str:
    """Return portable Qt sequence text, or '' if unset/invalid."""
    if sequence is None:
        return ""
    if isinstance(sequence, str):
        sequence = sequence.strip()
        if not sequence:
            return ""
        parsed = QKeySequence(sequence)
    else:
        parsed = sequence
    if parsed.isEmpty():
        return ""
    text = str(parsed.toString(QKeySequence.SequenceFormat.PortableText)).strip()
    return text


def sequence_is_valid(sequence: str) -> bool:
    return bool(normalize_sequence(sequence))


def sequence_is_safe_global(sequence: str) -> bool:
    """
    Global grabs steal keys from every app. Allow:
    - any chord that includes Ctrl/Alt/Meta (Shift alone is not enough)
    - bare function keys F1–F35
    """
    seq = normalize_sequence(sequence)
    if not seq:
        return False
    parsed = QKeySequence(seq)
    key = parsed[0]
    mods = key.keyboardModifiers()
    if mods & (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    ):
        return True
    qt_key = Qt.Key(key.key())
    return Qt.Key.Key_F1 <= qt_key <= Qt.Key.Key_F35


def qt_to_pynput(sequence: str) -> str:
    """Convert portable Qt sequence (Ctrl+Shift+S) to pynput (<ctrl>+<shift>+s)."""
    seq = normalize_sequence(sequence)
    if not seq:
        raise HotkeyBindingError("Empty key sequence")
    parts = [p.strip() for p in seq.split("+") if p.strip()]
    if not parts:
        raise HotkeyBindingError(f"Invalid key sequence: {sequence!r}")

    special = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "meta": "<cmd>",
        "super": "<cmd>",
        "return": "<enter>",
        "enter": "<enter>",
        "esc": "<esc>",
        "escape": "<esc>",
        "space": "<space>",
        "tab": "<tab>",
        "backspace": "<backspace>",
        "delete": "<delete>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "home": "<home>",
        "end": "<end>",
        "pgup": "<page_up>",
        "pageup": "<page_up>",
        "pgdown": "<page_down>",
        "pagedown": "<page_down>",
        "comma": ",",
        "period": ".",
        "slash": "/",
        "plus": "+",
        "minus": "-",
    }
    out: list[str] = []
    for part in parts:
        low = part.lower()
        if low in special:
            out.append(special[low])
            continue
        if len(part) >= 2 and low.startswith("f") and part[1:].isdigit():
            out.append(f"<{low}>")
            continue
        if len(part) == 1:
            out.append(part.lower())
            continue
        # Fallback: wrap token
        out.append(f"<{low}>")
    return "+".join(out)


def load_bindings(settings: object) -> dict[str, str]:
    """action -> portable Qt sequence (only set actions)."""
    bindings: dict[str, str] = {}
    getter = getattr(settings, "get", None)
    if getter is None:
        return bindings
    for item in HOTKEY_ACTIONS:
        raw = getter(setting_key(item.action), "") or ""
        seq = normalize_sequence(raw)
        if seq:
            bindings[item.action] = seq
    return bindings


def save_binding(settings: object, action: str, sequence: str | None) -> None:
    seq = normalize_sequence(sequence)
    settings.set(setting_key(action), seq if seq else None)


def conflict_errors(bindings: dict[str, str]) -> list[str]:
    seen: dict[str, str] = {}
    errors: list[str] = []
    for action, seq in bindings.items():
        if seq in seen:
            errors.append(f"{seq!r} used by both {seen[seq]!r} and {action!r}")
        else:
            seen[seq] = action
    return errors


def validate_bindings(bindings: dict[str, str]) -> None:
    errors: list[str] = []
    for action, seq in bindings.items():
        if not sequence_is_valid(seq):
            errors.append(f"{action}: invalid sequence {seq!r}")
        elif not sequence_is_safe_global(seq):
            errors.append(
                f"{action}: {seq!r} is unsafe as a global shortcut "
                "(use Ctrl/Alt/Meta or an F-key)"
            )
    errors.extend(conflict_errors(bindings))
    if errors:
        raise HotkeyBindingError("\n".join(errors))


def help_text(bindings: dict[str, str] | None = None) -> str:
    lines = ["ACARS Print Bridge — keyboard shortcuts", ""]
    bindings = bindings or {}
    any_set = False
    for item in HOTKEY_ACTIONS:
        seq = bindings.get(item.action, "")
        if not seq:
            lines.append(f"{'(unset)':28}  {item.label}")
        else:
            any_set = True
            lines.append(f"{seq:28}  {item.label}")
    lines.append("")
    if not any_set:
        lines.append("No shortcuts configured. Assign them under Settings → Shortcuts.")
    else:
        lines.append("Shortcuts are global (work even when this window is unfocused).")
    return "\n".join(lines)
