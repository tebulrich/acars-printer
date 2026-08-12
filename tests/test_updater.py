from __future__ import annotations

import os
import sys

import httpx
import pytest

from acars_bridge.services.updater import (
    UpdateError,
    can_auto_install,
    check_for_update,
    current_executable,
    fetch_latest_release,
    is_newer,
    parse_version,
    pick_windows_asset,
    schedule_windows_replace_and_restart,
    shell_wait_pid,
)


def _client_with(payload: dict, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_and_compare_versions():
    assert parse_version("v0.1.0") == (0, 1, 0)
    assert parse_version("1.2.3") == (1, 2, 3)
    assert is_newer("0.2.0", "0.1.0")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.1.0", "0.2.0")


def test_pick_windows_asset_prefers_named_exe():
    assets = [
        {"name": "notes.txt", "browser_download_url": "http://x/notes"},
        {
            "name": "ACARS-Print-Bridge-0.2.0-windows-x64.exe",
            "browser_download_url": "http://x/exe",
        },
        {"name": "other.exe", "browser_download_url": "http://x/other"},
    ]
    picked = pick_windows_asset(assets)
    assert picked is not None
    assert picked["name"].endswith("windows-x64.exe")


def test_pick_windows_asset_prefers_portable_over_setup():
    assets = [
        {
            "name": "ACARS.Print.Bridge_1.3.0_x64-setup.exe",
            "browser_download_url": "http://x/setup",
        },
        {
            "name": "ACARS-Print-Bridge-1.3.0-windows-x64.exe",
            "browser_download_url": "http://x/portable",
        },
    ]
    picked = pick_windows_asset(assets)
    assert picked is not None
    assert picked["name"].endswith("windows-x64.exe")


def test_current_executable_prefers_shell_env(tmp_path, monkeypatch):
    shell = tmp_path / "ACARS-Print-Bridge.exe"
    shell.write_bytes(b"fake")
    monkeypatch.setenv("ACARS_BRIDGE_SHELL_EXE", str(shell))
    monkeypatch.setattr(
        "acars_bridge.services.updater.is_frozen_app", lambda: False
    )
    assert current_executable() == shell.resolve()
    assert can_auto_install() is True

    monkeypatch.delenv("ACARS_BRIDGE_SHELL_EXE", raising=False)
    assert current_executable() is None
    assert can_auto_install() is False


def test_shell_wait_pid_prefers_env(monkeypatch):
    monkeypatch.setenv("ACARS_BRIDGE_SHELL_PID", "424242")
    assert shell_wait_pid() == 424242
    monkeypatch.delenv("ACARS_BRIDGE_SHELL_PID", raising=False)
    assert shell_wait_pid() == os.getpid()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_schedule_replace_uses_wait_pid(tmp_path, monkeypatch):
    new_exe = tmp_path / "new.exe"
    current = tmp_path / "app.exe"
    new_exe.write_bytes(b"new")
    current.write_bytes(b"old")

    launched: list[list[str]] = []
    flags: list[int] = []

    def fake_popen(args, **kwargs):
        launched.append(list(args))
        flags.append(int(kwargs.get("creationflags") or 0))

        class _P:
            pass

        return _P()

    monkeypatch.setattr(
        "acars_bridge.services.updater.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "acars_bridge.services.updater._unblock_windows_file", lambda _p: None
    )
    script = schedule_windows_replace_and_restart(
        new_exe=new_exe, current_exe=current, wait_pid=999001
    )
    text = script.read_text(encoding="utf-8")
    assert script.suffix.lower() == ".ps1"
    assert "Wait-Process -Id 999001 -Timeout 45" in text
    assert "tasklist" not in text.lower()
    assert " find " not in text.lower()
    assert launched
    assert launched[0][0].lower().endswith("powershell.exe") or launched[0][
        0
    ].lower() == "powershell.exe"
    assert "-File" in launched[0]
    assert str(script) in launched[0]
    # CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    assert flags and (flags[0] & 0x08000000) == 0x08000000


def test_fetch_latest_release_mock():
    payload = {
        "tag_name": "v0.9.0",
        "name": "0.9.0",
        "body": "Fixes",
        "html_url": "https://github.com/tebulrich/acars-printer/releases/tag/v0.9.0",
        "assets": [
            {
                "name": "ACARS-Print-Bridge-0.9.0-windows-x64.exe",
                "browser_download_url": "https://example.test/app.exe",
            }
        ],
    }
    with _client_with(payload) as client:
        release = fetch_latest_release(client=client)
    assert release.version == "0.9.0"
    assert release.asset_name.endswith(".exe")


def test_check_for_update_respects_skip():
    payload = {
        "tag_name": "v9.9.9",
        "name": "9.9.9",
        "body": "",
        "html_url": "https://github.com/example/x",
        "assets": [
            {
                "name": "ACARS-Print-Bridge-9.9.9-windows-x64.exe",
                "browser_download_url": "https://example.test/app.exe",
            }
        ],
    }
    with _client_with(payload) as client:
        assert check_for_update(current="0.1.0", client=client) is not None
        assert (
            check_for_update(current="0.1.0", skipped_version="9.9.9", client=client)
            is None
        )
        assert check_for_update(current="9.9.9", client=client) is None


def test_fetch_latest_missing_asset():
    with _client_with({"tag_name": "v1.0.0", "assets": []}) as client:
        with pytest.raises(UpdateError, match="no Windows"):
            fetch_latest_release(client=client)


def test_fetch_latest_parses_asset_digest():
    digest = "a" * 64
    payload = {
        "tag_name": "v0.9.1",
        "name": "0.9.1",
        "body": "",
        "html_url": "https://github.com/example/x",
        "assets": [
            {
                "name": "ACARS-Print-Bridge-0.9.1-windows-x64.exe",
                "browser_download_url": "https://example.test/app.exe",
                "digest": f"sha256:{digest}",
                "size": 12345,
            }
        ],
    }
    with _client_with(payload) as client:
        release = fetch_latest_release(client=client)
    assert release.digest == digest
    assert release.size == 12345


def test_fetch_latest_parses_body_digest():
    digest = "b" * 64
    name = "ACARS-Print-Bridge-0.9.2-windows-x64.exe"
    payload = {
        "tag_name": "v0.9.2",
        "name": "0.9.2",
        "body": f"SHA256 ({name}) = {digest}",
        "html_url": "https://github.com/example/x",
        "assets": [
            {
                "name": name,
                "browser_download_url": "https://example.test/app.exe",
            }
        ],
    }
    with _client_with(payload) as client:
        release = fetch_latest_release(client=client)
    assert release.digest == digest
