from __future__ import annotations

import httpx
import pytest

from acars_bridge.services.updater import (
    UpdateError,
    check_for_update,
    fetch_latest_release,
    is_newer,
    parse_version,
    pick_windows_asset,
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
