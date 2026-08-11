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

from acars_bridge.network import NetworkProfile, WireFormat
from acars_bridge.services.session import AppSession
from acars_bridge.tap.divert import HoppieForceRedirect
from acars_bridge.hoppie.parser import hoppie_error_detail
from acars_bridge.tap.extract import messages_from_gfo_exchange, messages_from_hoppie_exchange
from acars_bridge.tap.hosts import install_tap_hosts, remove_tap_hosts
from acars_bridge.tap.proxy import HoppieForwardProxy, ProxyConfig
from acars_bridge.tap.tls_certs import ensure_tap_certs, install_ca_trust


@dataclass
class TapStatus:
    running: bool = False
    last_check: datetime | None = None
    last_error: str | None = None
    last_note: str | None = None
    last_stats: dict[str, int] = field(default_factory=dict)
    exchanges: int = 0
    sniffer_hits: int = 0
    redirects: int = 0
    passthrough: int = 0
    upstream_ip: str | None = None
    upstream_ips: tuple[str, ...] = ()
    upstream_host: str | None = None
    network_id: str | None = None
    network_label: str | None = None
    https_enabled: bool = False
    last_mode: str = "tap"
    last_hoppie_type: str = "tap"
    last_hoppie_error: str | None = None
    callsign_in_use: bool = False


class TapService:
    """Catch plane↔ACARS-upstream traffic and print replies (any aircraft client)."""

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
                        "ACARS traffic from any aircraft on this PC."
                    )

                profile = self._session.settings.network_profile()
                try:
                    remove_tap_hosts()
                except OSError:
                    pass
                _flush_dns()

                upstream_ips = _resolve_host_ips(profile.primary_host)
                proxy_note, https_ok = self._start_proxy(profile, upstream_ips[0])

                # No raw sniffer — it was counting empty "tap" hits and hiding
                # real failures. Proxy + WinDivert is the supported path.
                divert = HoppieForceRedirect(
                    upstream_ips,
                    redirect_https=https_ok,
                    process_allowlist=profile.divert_process_allowlist,
                    process_denylist=profile.divert_process_denylist,
                )
                divert.start()
                self._divert = divert
                if not https_ok:
                    note = (
                        "HTTPS intercept off (CA not trusted). "
                        "HTTP ACARS clients still work."
                    )
                    proxy_note = f"{proxy_note} | {note}" if proxy_note else note
                if not profile.hosts_redirect:
                    coexist = (
                        f"{profile.label}: sim traffic only "
                        "(website / companion apps stay direct)"
                    )
                    proxy_note = f"{proxy_note} | {coexist}" if proxy_note else coexist

                self.status.running = True
                self.status.upstream_ip = upstream_ips[0]
                self.status.upstream_ips = upstream_ips
                self.status.upstream_host = profile.primary_host
                self.status.network_id = profile.id.value
                self.status.network_label = profile.label
                self.status.https_enabled = https_ok
                self.status.last_error = None
                self.status.last_note = proxy_note
                self.status.last_check = datetime.now(UTC)
            except Exception as exc:  # noqa: BLE001
                self._cleanup_unlocked()
                self.status.running = False
                self.status.last_error = str(exc)
                self.status.last_check = datetime.now(UTC)
                self._emit()
                raise
        self._emit()

    def _start_proxy(
        self, profile: NetworkProfile, upstream_ip: str
    ) -> tuple[str | None, bool]:
        """Start forwarder. Returns (status_note, https_mitm_ready)."""
        cert_dir = self._session.paths.root / "tap-certs"
        ca_cert, server_cert, server_key = ensure_tap_certs(
            cert_dir, common_name=profile.primary_host
        )
        ca_err = install_ca_trust(ca_cert)
        https_ok = ca_err is None
        if profile.hosts_redirect:
            install_tap_hosts(redirect_ip="127.0.0.1", hosts=profile.tap_hosts)
            self._hosts_owned = True
            _flush_dns()
        else:
            # Leave DNS alone so companion apps (SayIntentions) keep a direct path.
            self._hosts_owned = False
        fill_from = (self._session.settings.callsign() or "").strip().upper() or None
        if profile.wire_format is WireFormat.GFO:
            fill_from = None
        # Prefer leaf+CA chain so the sim validates against the key we just installed.
        chain = cert_dir / "tap-server-chain.pem"
        serve_cert = chain if chain.is_file() else server_cert
        proxy = HoppieForwardProxy(
            ProxyConfig(
                upstream_host=profile.primary_host,
                upstream_ip=upstream_ip,
                server_cert=serve_cert,
                server_key=server_key,
                enable_https=True,
                fill_from_callsign=fill_from,
                wire_format=profile.wire_format.value,
            ),
            on_exchange=self._on_exchange,
            on_debug=self._on_debug,
            on_tls_failure=self._on_tls_failure,
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
            self.status.last_note = None
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

    def _on_tls_failure(self, count: int, detail: str) -> None:
        """Stop stealing HTTPS so the plane can reach the real host again."""
        host = self.status.upstream_host or "upstream"
        if self._divert is not None:
            self._divert.set_https_redirect(False)
        note = (
            f"TLS MITM failed {count}x — HTTPS passthrough ON so the aircraft "
            f"can reach {host} again. Disconnect/Connect after fixing certs, "
            f"or restart MSFS. Detail: {detail}"
        )
        self.status.last_error = note
        if self._on_debug:
            self._on_debug(note)
        self._emit()

    def _on_exchange(self, form: dict[str, str], response_text: str) -> None:
        callsign = self._session.settings.callsign() or None
        profile = self._session.settings.network_profile()
        if profile.wire_format is not WireFormat.GFO:
            logon = (form.get("logon") or "").strip()
            from_cs = (form.get("from") or "").strip().upper()
            if logon and from_cs:
                self._session.wire_session.update(
                    logon=logon,
                    from_cs=from_cs,
                    network_id=profile.id.value,
                )
        if profile.wire_format is WireFormat.GFO:
            messages, force_print = messages_from_gfo_exchange(
                request_path=form.get("path") or "",
                response_text=response_text,
                callsign_filter=callsign,
            )
        else:
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
        wire_fault = hoppie_error_detail(response_text)
        if messages:
            stats = self._session.ingestion.ingest(messages, force_print=force_print)
        elif self._on_debug:
            self._on_debug(
                f"no printable messages type={form.get('type')!r} "
                f"from={form.get('from')!r} path={form.get('path')!r} "
                f"filter={callsign!r} resp={response_text[:100]!r}"
            )
        with self._lock:
            self._refresh_counters_unlocked()
            self.status.last_stats = stats
            self.status.last_check = datetime.now(UTC)
            if wire_fault:
                self.status.last_hoppie_error = wire_fault
            elif (response_text or "").lstrip().lower().startswith("ok"):
                self.status.last_hoppie_error = None
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
            self.status.passthrough = int(
                getattr(self._divert, "skipped_passthrough", 0) or 0
            )
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
        try:
            self._session.wire_session.clear()
        except Exception:  # noqa: BLE001
            pass

    def _atexit_cleanup(self) -> None:
        try:
            with self._lock:
                self._cleanup_unlocked()
        except Exception:  # noqa: BLE001
            pass


def _resolve_host(host: str) -> str:
    ips = _resolve_host_ips(host)
    return ips[0]


def _resolve_host_ips(host: str) -> tuple[str, ...]:
    """All public IPv4 addresses for *host* (multi-A / CDN-safe)."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        ip = info[4][0]
        if not ip or ":" in ip or ip.startswith("127."):
            continue
        if ip not in seen:
            seen.append(ip)
    if not seen:
        raise RuntimeError(f"Could not resolve {host} to a public IPv4.")
    return tuple(seen)


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
