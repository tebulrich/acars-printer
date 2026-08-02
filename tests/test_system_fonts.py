from __future__ import annotations

from unittest.mock import patch

from acars_bridge.ui.system_fonts import (
    _parse_gnome_font_name,
    preferred_mono_font,
    preferred_ui_font,
)


def test_parse_gnome_font_name_strips_size():
    assert _parse_gnome_font_name("'Inter Display 11'") == "Inter Display"
    assert _parse_gnome_font_name('"Jetbrains Mono 12"') == "Jetbrains Mono"


def test_preferred_ui_font_uses_gsettings_on_linux():
    preferred_ui_font.cache_clear()

    def fake_run(cmd, **_kwargs):
        if cmd[:2] == ["gsettings", "get"] and cmd[-1] == "font-name":
            return "'Inter Display 11'"
        if cmd[0] == "fc-match":
            return "/usr/share/fonts/opentype/inter/InterDisplay-Regular.otf"
        return ""

    with (
        patch("acars_bridge.ui.system_fonts.sys.platform", "linux"),
        patch("acars_bridge.ui.system_fonts._run", side_effect=fake_run),
        patch("acars_bridge.ui.system_fonts.os.path.isfile", return_value=True),
    ):
        spec = preferred_ui_font()
    assert spec.family == "Inter Display"
    assert spec.file_path.endswith("InterDisplay-Regular.otf")


def test_preferred_mono_font_uses_gsettings_on_linux():
    preferred_mono_font.cache_clear()

    def fake_run(cmd, **_kwargs):
        if cmd[:2] == ["gsettings", "get"] and cmd[-1] == "monospace-font-name":
            return "'Jetbrains Mono 12'"
        if cmd[0] == "fc-match":
            return "/tmp/JetBrainsMono-Regular.ttf"
        return ""

    with (
        patch("acars_bridge.ui.system_fonts.sys.platform", "linux"),
        patch("acars_bridge.ui.system_fonts._run", side_effect=fake_run),
        patch("acars_bridge.ui.system_fonts.os.path.isfile", return_value=True),
    ):
        spec = preferred_mono_font()
    assert spec.family == "Jetbrains Mono"
