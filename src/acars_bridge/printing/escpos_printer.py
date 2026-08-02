from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterError, PrinterSettings


class EscPosMessagePrinter:
    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        try:
            from escpos.printer import Dummy, File, Network
        except ImportError as exc:  # pragma: no cover
            raise PrinterError("python-escpos is not installed") from exc

        destination = settings.destination
        printer = None
        try:
            if destination.startswith("tcp://"):
                parsed = urlparse(destination)
                if not parsed.hostname:
                    raise PrinterError("Invalid TCP printer destination.")
                port = parsed.port or 9100
                printer = Network(parsed.hostname, port=port, timeout=5)
                self._render(printer, formatted_body, settings)
                printer.close()
            elif destination.startswith("file://"):
                path = Path(destination.removeprefix("file://"))
                path.parent.mkdir(parents=True, exist_ok=True)
                printer = File(str(path))
                self._render(printer, formatted_body, settings)
                printer.close()
            elif destination.startswith("win32://"):
                printer_name = destination.removeprefix("win32://")
                try:
                    from escpos.printer import Win32Raw
                except Exception as exc:  # pragma: no cover
                    raise PrinterError("Win32Raw printer unavailable on this platform") from exc
                printer = Win32Raw(printer_name)
                printer.open()
                self._render(printer, formatted_body, settings)
                printer.close()
            elif destination.startswith("cups://"):
                printer_name = destination.removeprefix("cups://")
                if not printer_name:
                    raise PrinterError("Invalid CUPS printer destination.")
                # System printers (Brother, etc.) need driver-rendered text.
                # Raw ESC/POS (`-o raw`) only works on thermal queues — use tcp://
                # for those. Optional cups-raw:// keeps the old ESC/POS path.
                self._print_via_cups_text(printer_name, formatted_body)
            elif destination.startswith("cups-raw://"):
                printer_name = destination.removeprefix("cups-raw://")
                if not printer_name:
                    raise PrinterError("Invalid CUPS-raw printer destination.")
                self._print_via_cups_raw(printer_name, formatted_body, settings, Dummy)
            else:
                raise PrinterError(
                    "Unsupported ESC/POS destination. "
                    "Use tcp://, file://, win32://, cups://, or cups-raw://"
                )
        except PrinterError:
            raise
        except Exception as exc:
            raise PrinterError(f"ESC/POS print failed: {exc}") from exc

    def _render(self, printer: object, formatted_body: str, settings: PrinterSettings) -> None:
        printer.set(bold=True)  # type: ignore[attr-defined]
        printer.text("ACARS PRINT BRIDGE\n")  # type: ignore[attr-defined]
        printer.set(bold=False)  # type: ignore[attr-defined]
        body = formatted_body if formatted_body.endswith("\n") else formatted_body + "\n"
        printer.text(body)  # type: ignore[attr-defined]
        if settings.cut_enabled:
            try:
                printer.cut()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _print_via_cups_text(self, printer_name: str, formatted_body: str) -> None:
        """Submit plain text so the CUPS driver (laser/inkjet/MFP) can render it."""
        body = formatted_body if formatted_body.endswith("\n") else formatted_body + "\n"
        # Form-feed helps page printers eject; harmless on most text filters.
        payload = (body + "\f").encode("utf-8")
        self._lp(
            printer_name,
            payload,
            options=["-o", "document-format=text/plain"],
        )

    def _print_via_cups_raw(
        self,
        printer_name: str,
        formatted_body: str,
        settings: PrinterSettings,
        dummy_cls: type,
    ) -> None:
        """Buffer ESC/POS bytes, then hand off to a raw CUPS queue (`lp -o raw`)."""
        dummy = dummy_cls()
        self._render(dummy, formatted_body, settings)
        payload = getattr(dummy, "output", b"")
        if not payload:
            raise PrinterError("CUPS-raw print produced empty output.")
        self._lp(printer_name, payload, options=["-o", "raw"])

    def _lp(self, printer_name: str, payload: bytes, *, options: list[str]) -> None:
        cmd = ["lp", "-d", printer_name, *options, "-t", "ACARS Print Bridge"]
        try:
            completed = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PrinterError(f"CUPS lp failed: {exc}") from exc
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or b"").decode(
                "utf-8", errors="replace"
            ).strip()
            raise PrinterError(err or f"lp exited {completed.returncode}")
        # lp only means "queued". Surface common CUPS/printer faults immediately.
        hint = self._cups_printer_fault(printer_name)
        if hint:
            raise PrinterError(
                f"Job queued on {printer_name}, but CUPS reports: {hint}"
            )

    @staticmethod
    def _cups_printer_fault(printer_name: str) -> str | None:
        try:
            completed = subprocess.run(
                ["lpstat", "-p", printer_name],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        status = (completed.stdout or "") + (completed.stderr or "")
        if not status.strip():
            return None
        lowered = status.lower()
        markers = (
            "job processing failed",
            "no suitable destination host",
            "paused",
            "disabled",
            "waiting for printer to become available",
            "unable to locate printer",
            "access_denied",
            "authentication required",
            "nt_status_",
            "unable to connect to cifs",
            "bad_network_name",
        )
        for line in status.splitlines():
            line_l = line.lower()
            if any(marker in line_l for marker in markers):
                return line.strip()
        if "not ready" in lowered:
            return status.strip().splitlines()[-1].strip()
        return None

    def name(self) -> str:
        return "escpos"
