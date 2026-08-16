from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Literal

SimKind = Literal["msfs", "xplane", "p3d", "fsx"]

ProcessRow = tuple[str, str]
"""(basename, full_path) — path may be empty when the OS denies it."""


@dataclass(frozen=True, slots=True)
class RunningSim:
    kind: SimKind
    exe_name: str
    exe_path: str = ""
    xplane_major: int | None = None


def xplane_major_from_version(version_number: int | None) -> int | None:
    """Beacon / installer version: 12xxxxx → 12, 11xxxxx → 11."""
    if version_number is None:
        return None
    try:
        value = int(version_number)
    except (TypeError, ValueError):
        return None
    if value >= 120000:
        return 12
    if value >= 110000:
        return 11
    return None


def _xplane_major_from_path(path: str) -> int | None:
    lowered = (path or "").replace("/", "\\").lower()
    if "x-plane 11" in lowered or "x-plane11" in lowered:
        return 11
    if "x-plane 12" in lowered or "x-plane12" in lowered:
        return 12
    return None


def classify_sim_executable(
    basename: str, full_path: str = ""
) -> RunningSim | None:
    name = (basename or "").strip()
    if not name:
        return None
    base = name.lower()
    path = full_path or ""

    if "flightsimulator" in base:
        return RunningSim(kind="msfs", exe_name=name, exe_path=path)
    if "prepar3d" in base or base.startswith("p3d"):
        return RunningSim(kind="p3d", exe_name=name, exe_path=path)
    if base == "fsx.exe" or base.startswith("fsx."):
        return RunningSim(kind="fsx", exe_name=name, exe_path=path)
    if "x-plane" in base or base.startswith("xplane"):
        return RunningSim(
            kind="xplane",
            exe_name=name,
            exe_path=path,
            xplane_major=_xplane_major_from_path(path),
        )
    return None


def detect_running_sims(
    processes: Iterable[ProcessRow] | None = None,
    *,
    enumerator: Callable[[], Iterable[ProcessRow]] | None = None,
) -> list[RunningSim]:
    """Classify running sim executables. Inject ``processes`` in tests."""
    rows = list(processes) if processes is not None else list(
        (enumerator or iter_windows_processes)()
    )
    found: list[RunningSim] = []
    seen: set[tuple[str, str]] = set()
    for basename, path in rows:
        sim = classify_sim_executable(basename, path)
        if sim is None:
            continue
        key = (sim.kind, sim.exe_path.lower() or sim.exe_name.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append(sim)
    return found


def preferred_sim(sims: Iterable[RunningSim]) -> RunningSim | None:
    """MSFS wins if both are running (SimConnect is the richer backend)."""
    ordered = list(sims)
    for kind in ("msfs", "xplane", "p3d", "fsx"):
        for sim in ordered:
            if sim.kind == kind:
                return sim
    return None


def iter_windows_processes() -> list[ProcessRow]:
    """Best-effort (basename, path) list. Empty on non-Windows or on failure."""
    if sys.platform != "win32":
        return []
    try:
        import win32api
        import win32con
        import win32process
    except ImportError:
        return []

    try:
        pids = win32process.EnumProcesses()
    except Exception:
        return []

    rows: list[ProcessRow] = []
    for pid in pids:
        if not pid:
            continue
        handle = None
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            path = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            continue
        finally:
            if handle is not None:
                try:
                    win32api.CloseHandle(handle)
                except Exception:
                    pass
        if not path:
            continue
        rows.append((os.path.basename(path), path))
    return rows
