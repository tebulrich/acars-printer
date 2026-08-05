"""Force already-running planes through our local Hoppie proxy via WinDivert."""

from __future__ import annotations

import logging
import threading

from acars_bridge.tap.ports import PROXY_UPSTREAM_PORT_MAX, PROXY_UPSTREAM_PORT_MIN
from acars_bridge.tap.windivert_path import ensure_windivert_on_path

log = logging.getLogger(__name__)


class HoppieForceRedirect:
    """Reflect Hoppie-bound TCP into the local forwarder (WinDivert streamdump).

    Hosts-file clients already dial 127.0.0.1 and need no divert. This path
    catches processes that still use the real Hoppie IPv4 (DNS cache, etc.).

    Reflection (not a plain dst=127.0.0.1 rewrite) is required so Windows
    delivers the packets to a local listener — see WinDivert streamdump.
    """

    def __init__(self, hoppie_ip: str, *, redirect_https: bool = True) -> None:
        self._hoppie_ip = hoppie_ip
        self._redirect_https = redirect_https
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle = None
        self.redirects = 0
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_windivert_on_path()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="hoppie-force-redirect", daemon=True
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
            # Do not block quit forever if recv() never wakes.

    def _loop(self) -> None:
        try:
            import pydivert
        except ImportError as exc:
            self.last_error = f"pydivert not installed: {exc}"
            return

        ip = self._hoppie_ip
        # Client→Hoppie and Proxy→(spoofed) Hoppie peer. Hosts-file traffic to
        # 127.0.0.1 never matches and is left alone.
        if self._redirect_https:
            filt = (
                f"ip.DstAddr == {ip} and "
                f"(tcp.DstPort == 80 or tcp.DstPort == 443 or "
                f"tcp.SrcPort == 80 or tcp.SrcPort == 443)"
            )
        else:
            filt = (
                f"ip.DstAddr == {ip} and "
                f"(tcp.DstPort == 80 or tcp.SrcPort == 80)"
            )
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

    def _handle_packet(self, w: object, packet: object, pydivert: object) -> None:
        if bool(getattr(packet, "is_impostor", False)):
            w.send(packet)  # type: ignore[attr-defined]
            return

        src = str(getattr(packet, "src_addr", ""))
        dst = str(getattr(packet, "dst_addr", ""))
        sport = int(getattr(packet, "src_port", 0) or 0)
        dport = int(getattr(packet, "dst_port", 0) or 0)
        hoppie_ports = {80, 443} if self._redirect_https else {80}
        direction = getattr(pydivert, "Direction")

        # Forwarder → real Hoppie (reserved local source ports): never touch.
        if (
            dport in hoppie_ports
            and dst == self._hoppie_ip
            and PROXY_UPSTREAM_PORT_MIN <= sport <= PROXY_UPSTREAM_PORT_MAX
        ):
            w.send(packet)  # type: ignore[attr-defined]
            return

        # Client → Hoppie : reflect inbound to local proxy (streamdump).
        # CLIENT:ephem → HOPPIE:443  =>  HOPPIE:ephem → CLIENT:443 (inbound)
        if (
            bool(getattr(packet, "is_outbound", False))
            and dport in hoppie_ports
            and dst == self._hoppie_ip
        ):
            packet.dst_addr = src
            packet.src_addr = self._hoppie_ip
            packet.direction = direction.INBOUND
            packet.recalculate_checksums()
            w.send(packet)  # type: ignore[attr-defined]
            self.redirects += 1
            return

        # Proxy → diverted client (peer still looks like Hoppie).
        # CLIENT:443 → HOPPIE:ephem  =>  HOPPIE:443 → CLIENT:ephem (inbound)
        if (
            bool(getattr(packet, "is_outbound", False))
            and sport in hoppie_ports
            and dst == self._hoppie_ip
            and dport not in hoppie_ports
        ):
            packet.dst_addr = src
            packet.src_addr = self._hoppie_ip
            packet.direction = direction.INBOUND
            packet.recalculate_checksums()
            w.send(packet)  # type: ignore[attr-defined]
            self.redirects += 1
            return

        w.send(packet)  # type: ignore[attr-defined]
