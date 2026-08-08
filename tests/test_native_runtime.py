"""Tests for copying frozen natives out of _MEIPASS."""

from __future__ import annotations

from pathlib import Path

from acars_bridge.native_runtime import _copy_file


def test_copy_file_skips_identical(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    dest = tmp_path / "nested" / "dest.bin"
    src.write_bytes(b"abc123")
    _copy_file(src, dest)
    assert dest.read_bytes() == b"abc123"
    mtime = dest.stat().st_mtime_ns
    _copy_file(src, dest)
    assert dest.stat().st_mtime_ns == mtime


def test_copy_file_replaces_different_size(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    dest = tmp_path / "dest.bin"
    dest.write_bytes(b"old")
    src.write_bytes(b"new-content")
    _copy_file(src, dest)
    assert dest.read_bytes() == b"new-content"
