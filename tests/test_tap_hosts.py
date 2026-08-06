from __future__ import annotations

from acars_bridge.tap.hosts import (
    MARKER_BEGIN,
    MARKER_END,
    is_tap_installed,
    remove_tap_block,
    render_block,
)


def test_render_and_remove_block():
    base = "127.0.0.1 localhost\n"
    installed = base + "\n" + render_block()
    assert is_tap_installed(installed)
    assert MARKER_BEGIN in installed
    assert "www.hoppie.nl" in installed
    cleaned = remove_tap_block(installed)
    assert MARKER_BEGIN not in cleaned
    assert MARKER_END not in cleaned
    assert "localhost" in cleaned
    assert not is_tap_installed(cleaned)


def test_render_sayintentions_hosts_only():
    block = render_block(hosts=("acars.sayintentions.ai",))
    assert "acars.sayintentions.ai" in block
    assert "www.hoppie.nl" not in block
    assert "hoppie.nl" not in block
