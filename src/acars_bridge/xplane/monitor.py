from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable

from acars_bridge.simconnect.monitor import SimSnapshot
from acars_bridge.xplane.detect import RunningSim, detect_running_sims
from acars_bridge.xplane.protocol import (
    DATAREFS,
    RREF_INDEX,
    kinematics_to_snapshot,
    normalize_xplane_host,
    normalize_xplane_port,
    pack_rref_subscribe,
    parse_becn,
    parse_rref_values,
    values_by_key,
)

log = logging.getLogger(__name__)

DEFAULT_XP_PORT = 49000
BEACON_GROUP = "239.255.1.1"
BEACON_PORT = 49707


class XPlaneUdpMonitor:
    """Subscribe to stock X-Plane datarefs over UDP RREF (localhost by default)."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_XP_PORT,
        stale_seconds: float = 3.0,
        subscribe_interval: float = 5.0,
        hz: int = 2,
        detect_fn: Callable[[], list[RunningSim]] | None = None,
    ) -> None:
        self._auto = False
        self._host = "127.0.0.1"
        self._port = DEFAULT_XP_PORT
        self._beacon_host: str | None = None
        self._beacon_port: int | None = None
        self.set_endpoint(host, port)
        self._stale_seconds = stale_seconds
        self._subscribe_interval = subscribe_interval
        self._hz = hz
        self._detect_fn = detect_fn or detect_running_sims
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot: SimSnapshot | None = None
        self._values: dict[str, float] = {}
        self._last_rref = 0.0
        self._detail = "X-Plane"
        self._detect_cache: list[RunningSim] = []
        self._detect_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="xplane-udp-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._snapshot = None
            self._values = {}

    def set_endpoint(self, host: str, port: int | str) -> None:
        """Update UDP target. ``auto`` keeps localhost and also uses the LAN beacon."""
        normalized = normalize_xplane_host(host)
        self._auto = normalized == "auto"
        self._host = "127.0.0.1" if self._auto else normalized
        self._port = normalize_xplane_port(port)
        if not self._auto:
            self._beacon_host = None
            self._beacon_port = None

    def destinations(self) -> list[tuple[str, int]]:
        dests: list[tuple[str, int]] = [(self._host, self._port)]
        if self._auto and self._beacon_host:
            extra = (self._beacon_host, self._beacon_port or self._port)
            if extra not in dests:
                dests.append(extra)
        return dests

    def snapshot(self) -> SimSnapshot | None:
        with self._lock:
            return self._snapshot

    def _set(self, snap: SimSnapshot | None) -> None:
        with self._lock:
            self._snapshot = snap

    def _running_xplane(self) -> RunningSim | None:
        now = time.monotonic()
        if now - self._detect_at >= 2.0:
            try:
                self._detect_cache = list(self._detect_fn() or [])
            except Exception:
                self._detect_cache = []
            self._detect_at = now
        for sim in self._detect_cache:
            if sim.kind == "xplane":
                return sim
        return None

    def _label(self, xp: RunningSim | None) -> str:
        if xp is not None and xp.xplane_major:
            return f"X-Plane {xp.xplane_major}"
        return self._detail or "X-Plane"

    def _run(self) -> None:
        sock: socket.socket | None = None
        beacon: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", 0))
            sock.settimeout(0.25)
            beacon = _try_open_beacon()
            last_sub = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_sub >= self._subscribe_interval:
                    self._subscribe(sock)
                    last_sub = now
                self._recv(sock)
                if beacon is not None:
                    self._recv_beacon(beacon)
                self._publish(now)
        except Exception as exc:
            log.info("X-Plane UDP monitor ended: %s", exc)
            self._set(SimSnapshot(connected=False, source="xplane", detail=str(exc)))
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if beacon is not None:
                try:
                    beacon.close()
                except OSError:
                    pass

    def _subscribe(self, sock: socket.socket) -> None:
        for dest in self.destinations():
            for key, dataref in DATAREFS.items():
                packet = pack_rref_subscribe(
                    index=RREF_INDEX[key], dataref=dataref, hz=self._hz
                )
                try:
                    sock.sendto(packet, dest)
                except OSError:
                    return

    def _recv(self, sock: socket.socket) -> None:
        try:
            data, _addr = sock.recvfrom(4096)
        except TimeoutError:
            return
        except OSError:
            return
        indexed = parse_rref_values(data)
        if not indexed:
            return
        self._values.update(values_by_key(indexed))
        self._last_rref = time.monotonic()

    def _recv_beacon(self, sock: socket.socket) -> None:
        try:
            data, addr = sock.recvfrom(2048)
        except TimeoutError:
            return
        except OSError:
            return
        parsed = parse_becn(data)
        if parsed is None:
            return
        if parsed.xplane_major:
            self._detail = f"X-Plane {parsed.xplane_major}"
        if self._auto and addr:
            host = addr[0]
            if host and not host.startswith("127."):
                self._beacon_host = host
                self._beacon_port = parsed.port or self._port

    def _publish(self, now: float) -> None:
        xp = self._running_xplane()
        label = self._label(xp)
        fresh = self._last_rref > 0 and (now - self._last_rref) <= self._stale_seconds
        if fresh and self._values:
            self._set(kinematics_to_snapshot(self._values, detail=label))
            return
        if xp is not None:
            self._set(
                SimSnapshot(
                    connected=False,
                    source="xplane",
                    detail=(
                        f"{label} is running but not sending data. "
                        "Enable Settings → Network → Accept incoming connections."
                    ),
                )
            )
            return
        self._set(SimSnapshot(connected=False, source="xplane", detail=""))


def _try_open_beacon() -> socket.socket | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", BEACON_PORT))
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton(BEACON_GROUP) + socket.inet_aton("0.0.0.0"),
        )
        sock.settimeout(0.01)
        return sock
    except OSError:
        return None
