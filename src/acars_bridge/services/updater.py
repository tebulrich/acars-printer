"""Check GitHub Releases and apply a one-click Windows exe update."""

from __future__ import annotations

import hashlib
import logging
import os
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

log = logging.getLogger(__name__)

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
    digest: str | None = None
    size: int | None = None


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


def can_auto_install() -> bool:
    """True when we know which Windows EXE to replace (shell or frozen app)."""
    return sys.platform == "win32" and current_executable() is not None


def current_executable() -> Path | None:
    """Path of the user-facing app EXE to replace on update.

    Prefer ``ACARS_BRIDGE_SHELL_EXE`` (Tauri desktop shell). Fall back to the
    frozen Python EXE for the legacy Qt onefile build.
    """
    raw = (os.environ.get("ACARS_BRIDGE_SHELL_EXE") or "").strip()
    if raw:
        path = Path(raw)
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            pass
    if not is_frozen_app():
        return None
    return Path(sys.executable).resolve()


def shell_wait_pid() -> int:
    """PID the updater script must wait on before replacing the EXE."""
    raw = (os.environ.get("ACARS_BRIDGE_SHELL_PID") or "").strip()
    if raw.isdigit():
        return int(raw)
    return os.getpid()


def pick_windows_asset(assets: list[dict]) -> dict | None:
    """Prefer the packaged Windows x64 portable exe (not the NSIS setup)."""
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
        if "setup" in lower or "installer" in lower or "nsis" in lower:
            score -= 6
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
    digest = _asset_digest(asset) or _digest_from_body(str(data.get("body") or ""), name)
    size_raw = asset.get("size")
    try:
        size = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size = None
    return ReleaseInfo(
        version=version,
        tag=tag,
        name=str(data.get("name") or tag),
        body=str(data.get("body") or "").strip(),
        html_url=str(data.get("html_url") or "").strip(),
        asset_name=name,
        download_url=url,
        digest=digest,
        size=size,
    )


def _asset_digest(asset: dict) -> str | None:
    """GitHub may publish digest as ``sha256:…`` on the asset."""
    raw = str(asset.get("digest") or "").strip().lower()
    if raw.startswith("sha256:"):
        return raw.split(":", 1)[1].strip() or None
    return None


def _digest_from_body(body: str, asset_name: str) -> str | None:
    """Parse ``SHA256 (name) = hex`` or ``hex  name`` lines from release notes."""
    if not body or not asset_name:
        return None
    patterns = [
        rf"SHA256\s*\({re.escape(asset_name)}\)\s*=\s*([A-Fa-f0-9]{{64}})",
        rf"([A-Fa-f0-9]{{64}})\s+\*?{re.escape(asset_name)}\b",
        rf"{re.escape(asset_name)}\s*[:=]\s*([A-Fa-f0-9]{{64}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return match.group(1).lower()
    return None


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
            if release.size and total and release.size != total:
                raise UpdateError("Download size does not match the GitHub asset.")
            hasher = hashlib.sha256()
            done = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    handle.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total or release.size or 0)
        if release.size and done != release.size:
            raise UpdateError("Downloaded file size does not match the GitHub asset.")
        if release.digest:
            actual = hasher.hexdigest().lower()
            if actual != release.digest.lower():
                raise UpdateError(
                    "Downloaded update failed SHA-256 verification. "
                    "Install cancelled."
                )
        else:
            log.warning(
                "Release has no SHA-256 digest; verifying size only (%s bytes)",
                done,
            )
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
    wait_seconds: int = 2,
    wait_pid: int | None = None,
) -> Path:
    """Write a helper script that replaces the running exe after this process exits.

    Waits for ``wait_pid`` (desktop shell) with a hard timeout, force-kills if
    needed, replaces the EXE, then relaunches. Runs hidden (no console windows).
    Avoids ``tasklist | find`` which can hang with a visible cmd window.
    """
    if sys.platform != "win32":
        raise UpdateError("Automatic install is only supported on Windows.")
    new_exe = new_exe.resolve()
    current_exe = current_exe.resolve()
    if not new_exe.is_file():
        raise UpdateError("Downloaded updater file is missing.")

    staged = current_exe.with_name(current_exe.stem + ".new.exe")
    shutil.copy2(new_exe, staged)
    _unblock_windows_file(staged)
    _unblock_windows_file(new_exe)

    pid = int(wait_pid) if wait_pid is not None else shell_wait_pid()
    work_dir = current_exe.parent
    local = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    app_data = local / "acars-bridge" / "acars-bridge"
    pyi_tmp = app_data / "pyi-tmp"
    pyi_tmp.mkdir(parents=True, exist_ok=True)
    log_file = app_data / "update-helper.log"
    helper = Path(tempfile.gettempdir()) / "acars-bridge-update.ps1"

    def _ps_sq(path: Path | str) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    helper.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'SilentlyContinue'",
                f"$Log = {_ps_sq(log_file)}",
                "function Write-UpdateLog([string]$Message) {",
                "  $line = (Get-Date).ToString('s') + ' ' + $Message",
                "  Add-Content -LiteralPath $Log -Value $line",
                "}",
                f"Write-UpdateLog 'helper start wait_pid={pid}'",
                f"Start-Sleep -Seconds {max(1, int(wait_seconds))}",
                f"try {{ Wait-Process -Id {pid} -Timeout 45 }} catch {{",
                "  Write-UpdateLog \"wait: $($_.Exception.Message)\"",
                "}",
                f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{",
                f"  Write-UpdateLog 'force-killing pid={pid}'",
                f"  Stop-Process -Id {pid} -Force",
                "  Start-Sleep -Seconds 2",
                "}",
                "$names = @('acars-bridge','ACARS-Print-Bridge','acars-print-bridge')",
                "Get-Process -Name $names -ErrorAction SilentlyContinue |",
                "  Where-Object { $_.Id -ne $PID } |",
                "  Stop-Process -Force",
                "Start-Sleep -Seconds 1",
                f"$Target = {_ps_sq(current_exe)}",
                f"$Staged = {_ps_sq(staged)}",
                f"$WorkDir = {_ps_sq(work_dir)}",
                f"$PyiTmp = {_ps_sq(pyi_tmp)}",
                "$moved = $false",
                "for ($i = 0; $i -lt 45; $i++) {",
                "  try {",
                "    Move-Item -LiteralPath $Staged -Destination $Target -Force -ErrorAction Stop",
                "    $moved = $true",
                "    break",
                "  } catch {",
                "    Start-Sleep -Seconds 1",
                "  }",
                "}",
                "if (-not $moved) {",
                "  Write-UpdateLog 'move failed'",
                "  exit 1",
                "}",
                "Write-UpdateLog 'moved ok'",
                "try { Unblock-File -LiteralPath $Target } catch {}",
                "New-Item -ItemType Directory -Force -Path $PyiTmp | Out-Null",
                "$env:TEMP = $PyiTmp",
                "$env:TMP = $PyiTmp",
                "Start-Process -FilePath $Target -WorkingDirectory $WorkDir",
                "Write-UpdateLog 'relaunched'",
                f"Remove-Item -LiteralPath {_ps_sq(helper)} -Force",
                "",
            ]
        ),
        encoding="utf-8",
    )

    create_no_window = 0x08000000
    detached = 0x00000008
    new_group = 0x00000200
    subprocess.Popen(  # noqa: S603
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(helper),
        ],
        close_fds=True,
        creationflags=create_no_window | detached | new_group,
        cwd=str(work_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "TEMP": str(pyi_tmp), "TMP": str(pyi_tmp)},
    )
    return helper


def _unblock_windows_file(path: Path) -> None:
    """Clear Mark-of-the-Web so SmartScreen does not break PyInstaller extract."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f'Unblock-File -LiteralPath "{path}" -ErrorAction SilentlyContinue',
            ],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        pass
