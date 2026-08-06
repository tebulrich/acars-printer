"""Force already-running planes through our local ACARS proxy via WinDivert."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterable

from acars_bridge.tap.ports import PROXY_UPSTREAM_PORT_MAX, PROXY_UPSTREAM_PORT_MIN
from acars_bridge.tap.tcp_owner import TcpOwnerIndex, process_matches
from acars_bridge.tap.windivert_path import ensure_windivert_on_path

log = logging.getLogger(__name__)


class HoppieForceRedirect:
    """Reflect upstream-bound TCP into the local forwarder (WinDivert streamdump).

    Hosts-file clients already dial 127.0.0.1 and need no divert. This path
    catches processes that still use a real upstream IPv4 (DNS cache, etc.).

    Reflection (not a plain dst=127.0.0.1 rewrite) is required so Windows
    delivers the packets to a local listener — see WinDivert streamdump.

    ``upstream_ips`` may contain several addresses (CDN / multi-A records).

    Process filters (SayIntentions coexistence):
    - ``process_denylist``: never divert (e.g. SayIntentions companion app).
    - ``process_allowlist``: when non-empty, only divert matching processes
      (typically the flight sim). Unknown / non-matching sockets pass through
      so pinned-TLS apps keep a direct path to the real host.
    """

    def __init__(
        self,
        upstream_ips: str | Iterable[str],
        *,
        redirect_https: bool = True,
        process_allowlist: tuple[str, ...] = (),
        process_denylist: tuple[str, ...] = (),
    ) -> None:
        if isinstance(upstream_ips, str):
            ips = (upstream_ips,)
        else:
            ips = tuple(upstream_ips)
        cleaned = tuple(dict.fromkeys(ip for ip in ips if ip and not ip.startswith("127.")))
        if not cleaned:
            raise ValueError("upstream_ips must contain at least one public IPv4")
        self._upstream_ips = frozenset(cleaned)
        self._primary_ip = cleaned[0]
        self._redirect_https = redirect_https
        self._allowlist = tuple(s.lower() for s in process_allowlist if s.strip())
        self._denylist = tuple(s.lower() for s in process_denylist if s.strip())
        self._owners = TcpOwnerIndex() if (self._allowlist or self._denylist) else None
        self._flow_policy: dict[tuple[str, int, str, int], bool] = {}
        self._diverted_client_ports: set[tuple[str, int]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle = None
        self.redirects = 0
        self.skipped_passthrough = 0
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._self_pid = os.getpid()

    @property
    def upstream_ips(self) -> frozenset[str]:
        return self._upstream_ips

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_windivert_on_path()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="acars-force-redirect", daemon=True
        )
        self._thread.start()
        import time

        time.sleep(0.4)
        if self.last_error:
            raise RuntimeError(self.last_error)

    def stop(self) -> None:
        self._stop.set()
        handle = self._handle
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)

    def _loop(self) -> None:
        try:
            import pydivert
        except ImportError as exc:
            self.last_error = f"pydivert not installed: {exc}"
            return

        addr_clause = " or ".join(f"ip.DstAddr == {ip}" for ip in sorted(self._upstream_ips))
        if self._redirect_https:
            filt = (
                f"({addr_clause}) and "
                f"(tcp.DstPort == 80 or tcp.DstPort == 443 or "
                f"tcp.SrcPort == 80 or tcp.SrcPort == 443)"
            )
        else:
            filt = f"({addr_clause}) and (tcp.DstPort == 80 or tcp.SrcPort == 80)"
        try:
            w = pydivert.WinDivert(filt)
            w.open()
            self._handle = w
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"WinDivert open failed: {exc}"
            log.warning(self.last_error)
            return

        try:
            while not self._stop.is_set():
                try:
                    packet = w.recv()
                except Exception:  # noqa: BLE001
                    if self._stop.is_set():
                        break
                    continue
                try:
                    self._handle_packet(w, packet, pydivert)
                except Exception as exc:  # noqa: BLE001
                    log.debug("divert handle failed: %s", exc)
        finally:
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None

    def _should_divert_flow(
        self, local_ip: str, local_port: int, remote_ip: str, remote_port: int
    ) -> bool:
        """Return True if this client→upstream flow should be reflected into the proxy."""
        if self._owners is None:
            return True
        key = (local_ip, local_port, remote_ip, remote_port)
        cached = self._flow_policy.get(key)
        if cached is not None:
            return cached

        owner = self._owners.owner_for(local_ip, local_port)
        if owner is None:
            # SYN may race the TCP table; refresh once and retry.
            self._owners.refresh(force=True)
            owner = self._owners.owner_for(local_ip, local_port)

        divert = True
        if owner is None:
            # Unknown owner + allowlist active → leave alone (protect SI app).
            divert = not bool(self._allowlist)
        elif owner.pid == self._self_pid:
            divert = False
        elif process_matches(owner.name, self._denylist):
            divert = False
        elif self._allowlist and not process_matches(owner.name, self._allowlist):
            divert = False

        # Cap policy map so long sessions cannot grow without bound.
        if len(self._flow_policy) > 4000:
            self._flow_policy.clear()
            self._diverted_client_ports.clear()
        self._flow_policy[key] = divert
        return divert

    def _handle_packet(self, w: object, packet: object, pydivert: object) -> None:
        if bool(getattr(packet, "is_impostor", False)):
            w.send(packet)  # type: ignore[attr-defined]
            return

        src = str(getattr(packet, "src_addr", ""))
        dst = str(getattr(packet, "dst_addr", ""))
        sport = int(getattr(packet, "src_port", 0) or 0)
        dport = int(getattr(packet, "dst_port", 0) or 0)
        ports = {80, 443} if self._redirect_https else {80}
        direction = getattr(pydivert, "Direction")

        # Forwarder → real upstream (reserved local source ports): never touch.
        if (
            dport in ports
            and dst in self._upstream_ips
            and PROXY_UPSTREAM_PORT_MIN <= sport <= PROXY_UPSTREAM_PORT_MAX
        ):
            w.send(packet)  # type: ignore[attr-defined]
            return

        # Client → upstream : reflect inbound to local proxy (streamdump).
        if (
            bool(getattr(packet, "is_outbound", False))
            and dport in ports
            and dst in self._upstream_ips
        ):
            if not self._should_divert_flow(src, sport, dst, dport):
                self.skipped_passthrough += 1
                w.send(packet)  # type: ignore[attr-defined]
                return
            self._diverted_client_ports.add((src, sport))
            peer = dst
            packet.dst_addr = src
            packet.src_addr = peer
            packet.direction = direction.INBOUND
            packet.recalculate_checksums()
            w.send(packet)  # type: ignore[attr-defined]
            self.redirects += 1
            return

        # Proxy → diverted client (peer still looks like upstream).
        if (
            bool(getattr(packet, "is_outbound", False))
            and sport in ports
            and dst in self._upstream_ips
            and dport not in ports
        ):
            # Only reflect sockets we already decided to divert. Passthrough
            # apps (SayIntentions) must keep a normal path to the real host.
            if (src, dport) not in self._diverted_client_ports:
                self.skipped_passthrough += 1
                w.send(packet)  # type: ignore[attr-defined]
                return
            peer = dst
            packet.dst_addr = src
            packet.src_addr = peer
            packet.direction = direction.INBOUND
            packet.recalculate_checksums()
            w.send(packet)  # type: ignore[attr-defined]
            self.redirects += 1
            return

        w.send(packet)  # type: ignore[attr-defined]
