"""Map local TCP sockets to owning process (Windows)."""

from __future__ import annotations

import ctypes
import os
import socket
import threading
from ctypes import wintypes
from dataclasses import dataclass

_AF_INET = 2
_TCP_TABLE_OWNER_PID_ALL = 5


class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class TcpOwner:
    pid: int
    name: str
    """Lowercase executable basename, e.g. ``flightsimulator.exe``."""


def _ntohs_port(value: int) -> int:
    return socket.ntohs(value & 0xFFFF)


def _ipv4_string(addr: int) -> str:
    return socket.inet_ntoa(ctypes.c_uint32(addr).value.to_bytes(4, "little"))


def _process_basename(pid: int) -> str:
    if pid <= 0:
        return ""
    if pid == os.getpid():
        return _self_basename()
    try:
        import win32api
        import win32con
        import win32process
    except ImportError:
        return ""
    handle = None
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        path = win32process.GetModuleFileNameEx(handle, 0)
        return os.path.basename(path).lower()
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if handle is not None:
            try:
                win32api.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass


_self_name: str | None = None


def _self_basename() -> str:
    global _self_name
    if _self_name is None:
        import sys

        _self_name = os.path.basename(os.path.abspath(sys.argv[0] or "python")).lower()
    return _self_name


def snapshot_tcp_owners() -> dict[tuple[str, int], TcpOwner]:
    """Return ``{(local_ip, local_port): TcpOwner}`` for IPv4 TCP rows."""
    if os.name != "nt":
        return {}
    iphlpapi = ctypes.windll.iphlpapi
    size = wintypes.DWORD(0)
    iphlpapi.GetExtendedTcpTable(
        None,
        ctypes.byref(size),
        False,
        _AF_INET,
        _TCP_TABLE_OWNER_PID_ALL,
        0,
    )
    if size.value == 0:
        return {}
    buf = ctypes.create_string_buffer(size.value)
    ret = iphlpapi.GetExtendedTcpTable(
        buf,
        ctypes.byref(size),
        False,
        _AF_INET,
        _TCP_TABLE_OWNER_PID_ALL,
        0,
    )
    if ret != 0:
        return {}

    class Table(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wintypes.DWORD),
            ("table", _MIB_TCPROW_OWNER_PID * 1),
        ]

    header = ctypes.cast(buf, ctypes.POINTER(Table)).contents
    n = int(header.dwNumEntries)
    rows_type = _MIB_TCPROW_OWNER_PID * max(n, 1)

    class FullTable(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wintypes.DWORD),
            ("table", rows_type),
        ]

    full = ctypes.cast(buf, ctypes.POINTER(FullTable)).contents
    out: dict[tuple[str, int], TcpOwner] = {}
    name_cache: dict[int, str] = {}
    for i in range(n):
        row = full.table[i]
        pid = int(row.dwOwningPid)
        if pid not in name_cache:
            name_cache[pid] = _process_basename(pid)
        local_ip = _ipv4_string(int(row.dwLocalAddr))
        local_port = _ntohs_port(int(row.dwLocalPort))
        out[(local_ip, local_port)] = TcpOwner(pid=pid, name=name_cache[pid])
        # Bind-all listeners / some stacks report 0.0.0.0 — also index by port alone.
        out[("0.0.0.0", local_port)] = out[(local_ip, local_port)]
    return out


class TcpOwnerIndex:
    """Cached TCP owner lookups safe to call from the divert hot path."""

    def __init__(self, *, refresh_seconds: float = 0.25) -> None:
        self._refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._map: dict[tuple[str, int], TcpOwner] = {}
        self._last_refresh = 0.0

    def refresh(self, *, force: bool = False) -> None:
        import time

        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_refresh) < self._refresh_seconds:
                return
            self._map = snapshot_tcp_owners()
            self._last_refresh = now

    def owner_for(self, local_ip: str, local_port: int) -> TcpOwner | None:
        self.refresh()
        with self._lock:
            hit = self._map.get((local_ip, local_port))
            if hit is not None:
                return hit
            return self._map.get(("0.0.0.0", local_port))


def process_matches(name: str, needles: tuple[str, ...]) -> bool:
    """True if lowercase process basename contains any needle."""
    if not name or not needles:
        return False
    lowered = name.lower()
    return any(needle in lowered for needle in needles if needle)
