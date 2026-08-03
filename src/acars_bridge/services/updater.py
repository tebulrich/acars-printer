"""Check GitHub Releases and apply a one-click Windows exe update."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from acars_bridge import __version__

GITHUB_OWNER = "tebulrich"
GITHUB_REPO = "acars-printer"
LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
USER_AGENT = f"ACARS-Print-Bridge/{__version__}"
_REQUEST_TIMEOUT = 20.0
_DOWNLOAD_TIMEOUT = 300.0


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    tag: str
    name: str
    body: str
    html_url: str
    asset_name: str
    download_url: str


class UpdateError(Exception):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    """Parse ``v1.2.3`` / ``1.2.3-rc1`` into a comparable int tuple."""
    text = (value or "").strip().lstrip("vV")
    if not text:
        return (0,)
    parts: list[int] = []
    for chunk in text.split("."):
        match = re.match(r"(\d+)", chunk)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, current: str = __version__) -> bool:
    return parse_version(remote) > parse_version(current)


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def current_executable() -> Path | None:
    if not is_frozen_app():
        return None
    return Path(sys.executable).resolve()


def pick_windows_asset(assets: list[dict]) -> dict | None:
    """Prefer the packaged Windows x64 exe asset from a release."""
    candidates: list[tuple[int, dict]] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        lower = name.lower()
        if not lower.endswith(".exe"):
            continue
        score = 0
        if "windows" in lower or "win" in lower:
            score += 3
        if "x64" in lower or "amd64" in lower:
            score += 2
        if "acars" in lower or "print" in lower or "bridge" in lower:
            score += 2
        candidates.append((score, asset))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def fetch_latest_release(client: httpx.Client | None = None) -> ReleaseInfo:
    own = client is None
    http = client or httpx.Client(
        timeout=_REQUEST_TIMEOUT,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        follow_redirects=True,
    )
    try:
        response = http.get(LATEST_RELEASE_URL)
        if response.status_code == 404:
            raise UpdateError("No GitHub releases published yet.")
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    finally:
        if own:
            http.close()

    tag = str(data.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("Latest release has no version tag.")
    asset = pick_windows_asset(list(data.get("assets") or []))
    if asset is None:
        raise UpdateError("Latest release has no Windows .exe asset.")
    url = str(asset.get("browser_download_url") or "").strip()
    name = str(asset.get("name") or "").strip()
    if not url or not name:
        raise UpdateError("Release asset is missing a download URL.")
    return ReleaseInfo(
        version=version,
        tag=tag,
        name=str(data.get("name") or tag),
        body=str(data.get("body") or "").strip(),
        html_url=str(data.get("html_url") or "").strip(),
        asset_name=name,
        download_url=url,
    )


def check_for_update(
    *,
    current: str = __version__,
    skipped_version: str | None = None,
    client: httpx.Client | None = None,
) -> ReleaseInfo | None:
    """Return newer release info, or None if up to date / skipped."""
    release = fetch_latest_release(client=client)
    if skipped_version and parse_version(skipped_version) >= parse_version(release.version):
        return None
    if not is_newer(release.version, current):
        return None
    return release


def download_release(
    release: ReleaseInfo,
    dest_dir: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    client: httpx.Client | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / release.asset_name
    partial = target.with_suffix(target.suffix + ".part")
    own = client is None
    http = client or httpx.Client(
        timeout=_DOWNLOAD_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
        follow_redirects=True,
    )
    try:
        with http.stream("GET", release.download_url) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
        partial.replace(target)
    except httpx.HTTPError as exc:
        raise UpdateError(f"Download failed: {exc}") from exc
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
        if own:
            http.close()
    if not target.is_file() or target.stat().st_size < 1024:
        raise UpdateError("Downloaded file looks incomplete.")
    return target


def schedule_windows_replace_and_restart(
    *,
    new_exe: Path,
    current_exe: Path,
    wait_seconds: int = 3,
) -> Path:
    """Write a helper script that replaces the running exe after this process exits."""
    if sys.platform != "win32":
        raise UpdateError("Automatic install is only supported on Windows.")
    new_exe = new_exe.resolve()
    current_exe = current_exe.resolve()
    if not new_exe.is_file():
        raise UpdateError("Downloaded updater file is missing.")

    # Stage next to the running exe so the move stays on one volume when possible.
    staged = current_exe.with_name(current_exe.stem + ".new.exe")
    shutil.copy2(new_exe, staged)

    script = Path(tempfile.gettempdir()) / "acars-bridge-update.cmd"
    # cmd.exe delayed replace: wait, swap, relaunch elevated-capable exe, clean up.
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                "set /a tries=0",
                f"timeout /t {max(1, wait_seconds)} /nobreak >nul",
                ":retry",
                "set /a tries+=1",
                f'move /Y "{staged}" "{current_exe}" >nul 2>&1',
                "if not errorlevel 1 goto launch",
                "if %tries% GEQ 30 (",
                f'  echo Update failed: could not replace "{current_exe}"',
                "  pause",
                "  exit /b 1",
                ")",
                "timeout /t 1 /nobreak >nul",
                "goto retry",
                ":launch",
                f'start "" "{current_exe}"',
                'del "%~f0" >nul 2>&1',
                "",
            ]
        ),
        encoding="utf-8",
    )
    # DETACHED_PROCESS so the helper outlives us.
    creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603
        ["cmd.exe", "/c", str(script)],
        close_fds=True,
        creationflags=creationflags,
        cwd=str(current_exe.parent),
    )
    return script
