from __future__ import annotations

import pytest

from acars_bridge.printing.profiles import (
    BUILTIN_PROFILE_IDS,
    builtin_profiles,
    profile_payload_from_settings,
)


def test_builtin_profiles_include_58_and_80() -> None:
    names = {p.id for p in builtin_profiles()}
    assert "pos80_default" in names
    assert "pos58_readable" in names
    assert "pos80_compact" in names
    assert names == set(BUILTIN_PROFILE_IDS)


def test_list_profiles_starts_with_builtins(app_session) -> None:
    profiles = app_session.settings.list_print_profiles()
    ids = [p.id for p in profiles]
    assert ids[:3] == list(BUILTIN_PROFILE_IDS)
    assert all(p.builtin for p in profiles[:3])


def test_apply_pos58_readable_sets_paper_and_format(app_session) -> None:
    s = app_session.settings
    s.set_printer_destination("fake")
    s.set_paper_width("80")
    s.apply_print_profile("pos58_readable")
    assert s.paper_width() == "58"
    assert s.print_render_mode() == "bitmap"
    assert s.print_glyph_px() >= 24
    assert s.active_print_profile() == "pos58_readable"
    # Destination unchanged by builtins
    assert s.printer_destination() == "fake"
    assert s.printer_input_mode() == "list"
    s.set_printer_input_mode("path")
    assert s.printer_input_mode() == "path"
    s.set_printer_input_mode("ip")
    assert s.printer_input_mode() == "ip"


def test_save_user_profile_roundtrip_and_apply(app_session) -> None:
    s = app_session.settings
    s.set_paper_width("80")
    s.set_print_glyph_px(20)
    s.set_print_lead_in(4)
    s.set_cut_enabled(False)
    s.save_user_print_profile("My cockpit")
    assert s.active_print_profile() == "My cockpit"

    s.set_print_glyph_px(40)
    s.set_print_lead_in(1)
    s.apply_print_profile("pos80_default")
    assert s.print_glyph_px() == 28

    s.apply_print_profile("My cockpit")
    assert s.print_glyph_px() == 20
    assert s.print_lead_in() == 4
    assert s.cut_enabled() is False


def test_cannot_delete_builtin_can_delete_user(app_session) -> None:
    s = app_session.settings
    with pytest.raises(ValueError):
        s.delete_user_print_profile("pos80_default")
    s.set_print_glyph_px(22)
    s.save_user_print_profile("Temp")
    s.delete_user_print_profile("Temp")
    ids = [p.id for p in s.list_print_profiles()]
    assert "Temp" not in ids


def test_overwrite_user_profile(app_session) -> None:
    s = app_session.settings
    s.set_print_glyph_px(18)
    s.save_user_print_profile("Mine")
    s.set_print_glyph_px(30)
    s.save_user_print_profile("Mine")
    s.apply_print_profile("pos80_default")
    s.apply_print_profile("Mine")
    assert s.print_glyph_px() == 30


def test_profile_payload_omits_destination() -> None:
    class _S:
        def paper_width(self) -> str:
            return "80"

        def cut_enabled(self) -> bool:
            return True

        def print_font(self) -> str:
            return "a"

        def print_bold(self) -> bool:
            return False

        def print_render_mode(self) -> str:
            return "bitmap"

        def print_char_width(self) -> int:
            return 1

        def print_char_height(self) -> int:
            return 1

        def print_line_spacing_dots(self):
            return None

        def print_glyph_px(self) -> int:
            return 28

        def print_line_gap_px(self) -> int:
            return 2

        def print_columns(self):
            return None

        def print_lead_in(self) -> int:
            return 2

        def print_tear_feed(self) -> int:
            return 6

    payload = profile_payload_from_settings(_S())
    assert "destination" not in payload
    assert payload["paper_width"] == "80"
