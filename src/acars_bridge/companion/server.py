"""Threading HTTP server for the phone companion."""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from acars_bridge.companion.api import CompanionApi, dumps, error_payload

if TYPE_CHECKING:
    from acars_bridge.bridge.runtime import BridgeRuntime
    from acars_bridge.services.companion_station import CompanionStationPoller

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class CompanionServer:
    def __init__(
        self,
        runtime: BridgeRuntime,
        *,
        poller: CompanionStationPoller | None = None,
    ) -> None:
        self.runtime = runtime
        self.poller = poller
        self.api = CompanionApi(runtime, poller=poller)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        settings = self.runtime.session.settings
        if not settings.companion_enabled():
            return
        port = settings.companion_port()
        api = self.api

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                log.debug("companion: " + fmt, *args)

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: dict[str, Any]) -> None:
                self._send(code, dumps(payload), "application/json; charset=utf-8")

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                return data

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                qs = parse_qs(parsed.query)

                if path.startswith("/api/"):
                    try:
                        if path == "/api/status":
                            self._json(200, api.status())
                            return
                        if path == "/api/messages":
                            since = int((qs.get("since_id") or ["0"])[0] or 0)
                            before_raw = (qs.get("before_id") or [None])[0]
                            before = int(before_raw) if before_raw else None
                            limit = int((qs.get("limit") or ["50"])[0] or 50)
                            self._json(
                                200,
                                api.messages(
                                    since_id=since, before_id=before, limit=limit
                                ),
                            )
                            return
                        if path.startswith("/api/messages/"):
                            mid = int(path.rsplit("/", 1)[-1])
                            self._json(200, api.message(mid))
                            return
                        self._json(404, {"ok": False, "error": "Not found"})
                    except Exception as exc:  # noqa: BLE001
                        code, payload = error_payload(exc)
                        self._json(code, payload)
                    return

                if path == "/" or path == "/index.html":
                    self._serve_static("index.html")
                    return
                name = path.lstrip("/")
                if ".." in name or name.startswith("/"):
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                self._serve_static(name)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                if not path.startswith("/api/"):
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                try:
                    body = self._read_json()
                    if path == "/api/telex":
                        self._json(
                            200,
                            api.send_telex(
                                str(body.get("to") or ""),
                                str(body.get("text") or ""),
                            ),
                        )
                        return
                    if path == "/api/weather":
                        self._json(
                            200,
                            api.request_weather(
                                str(body.get("kind") or "metar"),
                                str(body.get("icao") or ""),
                            ),
                        )
                        return
                    if path == "/api/atis":
                        self._json(
                            200,
                            api.request_atis(
                                str(body.get("icao") or ""),
                                side=body.get("side", "dep"),
                                source=str(body.get("source") or "vatatis"),
                            ),
                        )
                        return
                    if path == "/api/pdc":
                        self._json(200, api.request_pdc(body))
                        return
                    if path.endswith("/print") and path.startswith("/api/messages/"):
                        mid = int(path.split("/")[3])
                        self._json(200, api.print_message(mid))
                        return
                    if path.endswith("/reply") and path.startswith("/api/messages/"):
                        mid = int(path.split("/")[3])
                        self._json(
                            200,
                            api.reply_cpdlc(mid, str(body.get("reply") or "")),
                        )
                        return
                    self._json(404, {"ok": False, "error": "Not found"})
                except Exception as exc:  # noqa: BLE001
                    code, payload = error_payload(exc)
                    self._json(code, payload)

            def _serve_static(self, name: str) -> None:
                target = (STATIC_DIR / name).resolve()
                if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                data = target.read_bytes()
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if name.endswith(".html"):
                    ctype = "text/html; charset=utf-8"
                elif name.endswith(".css"):
                    ctype = "text/css; charset=utf-8"
                elif name.endswith(".js"):
                    ctype = "application/javascript; charset=utf-8"
                self._send(200, data, ctype)

        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        except OSError as exc:
            log.error("companion server bind failed on %s: %s", port, exc)
            raise
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever, name="companion-http", daemon=True
        )
        self._thread.start()
        log.info("companion listening on 0.0.0.0:%s", port)

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def restart_if_needed(self) -> None:
        """Start/stop to match settings."""
        enabled = self.runtime.session.settings.companion_enabled()
        if enabled and not self.running:
            self.start()
        elif not enabled and self.running:
            self.stop()
