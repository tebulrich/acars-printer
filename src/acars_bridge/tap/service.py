from __future__ import annotations

import atexit
import ctypes
import os
import socket
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from acars_bridge.services.session import AppSession
from acars_bridge.tap.divert import HoppieForceRedirect
from acars_bridge.tap.extract import messages_from_hoppie_exchange
from acars_bridge.tap.hosts import install_tap_hosts, remove_tap_hosts
from acars_bridge.tap.proxy import HoppieForwardProxy, ProxyConfig
from acars_bridge.tap.tls_certs import ensure_tap_certs, install_ca_trust

UPSTREAM_HOST = "www.hoppie.nl"


@dataclass
class TapStatus:
    running: bool = False
    last_check: datetime | None = None
    last_error: str | None = None
    last_stats: dict[str, int] = field(default_factory=dict)
    exchanges: int = 0
    sniffer_hits: int = 0
    redirects: int = 0
    upstream_ip: str | None = None
    https_enabled: bool = False
    last_mode: str = "tap"
    last_hoppie_type: str = "tap"
    callsign_in_use: bool = False


class TapService:
    """Catch plane↔Hoppie traffic and print replies (any aircraft client)."""

    def __init__(
        self,
        session: AppSession,
        *,
        on_update: Callable[[TapStatus], None] | None = None,
        on_new_messages: Callable[[int], None] | None = None,
        on_debug: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._on_update = on_update
        self._on_new_messages = on_new_messages
        self._on_debug = on_debug
        self.status = TapStatus()
        self._proxy: HoppieForwardProxy | None = None
        self._sniffer = None
        self._divert: HoppieForceRedirect | None = None
        self._lock = threading.Lock()
        self._hosts_owned = False
        atexit.register(self._atexit_cleanup)

    def start(self) -> None:
        with self._lock:
            if self.status.running:
                return
            try:
                if not _is_elevated():
                    raise RuntimeError(
                        "Run this app as Administrator so it can intercept "
                        "Hoppie traffic from any aircraft on this PC."
                    )

                try:
                    remove_tap_hosts()
                except OSError:
                    pass
                _flush_dns()

                upstream_ip = _resolve_host(UPSTREAM_HOST)
                proxy_note, https_ok = self._start_proxy(upstream_ip)

                # No raw sniffer — it was counting empty "tap" hits and hiding
                # real failures. Proxy + WinDivert is the supported path.
                divert = HoppieForceRedirect(
                    upstream_ip, redirect_https=https_ok
                )
                divert.start()
                self._divert = divert
                if not https_ok:
                    note = (
                        "HTTPS intercept off (CA not trusted). "
                        "HTTP Hoppie clients still work."
                    )
                    proxy_note = f"{proxy_note} | {note}" if proxy_note else note

                self.status.running = True
                self.status.upstream_ip = upstream_ip
                self.status.https_enabled = https_ok
                self.status.last_error = proxy_note
                self.status.last_check = datetime.now(UTC)
            except Exception as exc:  # noqa: BLE001
                self._cleanup_unlocked()
                self.status.running = False
                self.status.last_error = str(exc)
                self.status.last_check = datetime.now(UTC)
                self._emit()
                raise
        self._emit()

    def _start_proxy(self, upstream_ip: str) -> tuple[str | None, bool]:
        """Start forwarder. Returns (status_note, https_mitm_ready)."""
        cert_dir = self._session.paths.root / "tap-certs"
        ca_cert, server_cert, server_key = ensure_tap_certs(cert_dir)
        ca_err = install_ca_trust(ca_cert)
        https_ok = ca_err is None
        install_tap_hosts(redirect_ip="127.0.0.1")
        self._hosts_owned = True
        _flush_dns()
        fill_from = (self._session.settings.callsign() or "").strip().upper() or None
        fill_logon = (self._session.settings.hoppie_logon() or "").strip() or None
        proxy = HoppieForwardProxy(
            ProxyConfig(
                upstream_host=UPSTREAM_HOST,
                upstream_ip=upstream_ip,
                server_cert=server_cert,
                server_key=server_key,
                enable_https=True,
                fill_from_callsign=fill_from,
                fill_logon=fill_logon,
            ),
            on_exchange=self._on_exchange,
            on_debug=self._on_debug,
        )
        proxy.start()
        self._proxy = proxy
        if proxy.last_error:
            return proxy.last_error, https_ok
        if ca_err:
            return f"HTTPS CA trust: {ca_err}", False
        return None, True

    def stop(self) -> None:
        with self._lock:
            self._cleanup_unlocked()
            self.status.running = False
            self.status.last_check = datetime.now(UTC)
            self.status.last_error = None
        self._emit()

    def check_now(self) -> None:
        with self._lock:
            self._refresh_counters_unlocked()
            self.status.last_check = datetime.now(UTC)
            if self.status.running:
                self.status.last_stats = {
                    "stored": 0,
                    "printed": 0,
                    "duplicates": 0,
                    "failed_prints": 0,
                    "exchanges": self.status.exchanges,
                    "sniffer_hits": self.status.sniffer_hits,
                    "redirects": self.status.redirects,
                }
        self._emit()

    def _on_exchange(self, form: dict[str, str], response_text: str) -> None:
        callsign = self._session.settings.callsign() or None
        messages, force_print = messages_from_hoppie_exchange(
            request_form=form,
            response_text=response_text,
            callsign_filter=callsign,
        )
        stats = {
            "stored": 0,
            "printed": 0,
            "duplicates": 0,
            "failed_prints": 0,
        }
        if messages:
            stats = self._session.ingestion.ingest(messages, force_print=force_print)
        elif self._on_debug:
            self._on_debug(
                f"no printable messages type={form.get('type')!r} "
                f"from={form.get('from')!r} filter={callsign!r} "
                f"resp={response_text[:100]!r}"
            )
        with self._lock:
            self._refresh_counters_unlocked()
            self.status.last_stats = stats
            self.status.last_check = datetime.now(UTC)
            # Keep proxy TLS notes visible; don't wipe on every exchange.
            if self._proxy is not None and self._proxy.last_error:
                self.status.last_error = self._proxy.last_error
            self.status.last_hoppie_type = (form.get("type") or "tap").lower()
        new_count = stats.get("printed", 0) + stats.get("stored", 0)
        if new_count and self._on_new_messages:
            self._on_new_messages(new_count)
        self._emit()

    def _refresh_counters_unlocked(self) -> None:
        exchanges = 0
        hits = 0
        redirects = 0
        if self._proxy is not None:
            exchanges += self._proxy.exchanges
            if self._proxy.last_error:
                self.status.last_error = self._proxy.last_error
        if self._sniffer is not None:
            hits = self._sniffer.http_hits
            exchanges += hits
        if self._divert is not None:
            redirects = self._divert.redirects
            if self._divert.last_error and not self.status.last_error:
                self.status.last_error = self._divert.last_error
        self.status.exchanges = exchanges
        self.status.sniffer_hits = hits
        self.status.redirects = redirects

    def _emit(self) -> None:
        if self._on_update:
            self._on_update(self.status)

    def _cleanup_unlocked(self) -> None:
        if self._divert is not None:
            self._divert.stop()
            self._divert = None
        if self._sniffer is not None:
            self._sniffer.stop()
            self._sniffer = None
        if self._proxy is not None:
            self._proxy.stop()
            self._proxy = None
        if self._hosts_owned:
            try:
                remove_tap_hosts()
            except OSError:
                pass
            self._hosts_owned = False
            _flush_dns()

    def _atexit_cleanup(self) -> None:
        try:
            with self._lock:
                self._cleanup_unlocked()
        except Exception:  # noqa: BLE001
            pass


def _resolve_host(host: str) -> str:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    for info in infos:
        ip = info[4][0]
        if ip and not ip.startswith("127."):
            return ip
    raise RuntimeError(f"Could not resolve {host} to a public IP.")


def _flush_dns(*, timeout: float = 3.0) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:  # noqa: BLE001
        pass


def _is_elevated() -> bool:
    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return True
