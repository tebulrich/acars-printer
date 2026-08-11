from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterError, PrinterSettings


class EscPosMessagePrinter:
    def feed(self, settings: PrinterSettings, lines: int | None = None) -> None:
        """Advance paper without printing a message (cockpit FEED)."""
        count = settings.tear_feed_lines if lines is None else max(1, int(lines))
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
                printer = Network(parsed.hostname, port=parsed.port or 9100, timeout=5)
                self._feed_lines(printer, count)
                printer.close()
            elif destination.startswith("file://"):
                path = Path(destination.removeprefix("file://"))
                path.parent.mkdir(parents=True, exist_ok=True)
                printer = File(str(path))
                self._feed_lines(printer, count)
                printer.close()
            elif destination.startswith("win32://"):
                printer_name = destination.removeprefix("win32://")
                try:
                    from escpos.printer import Win32Raw
                except Exception as exc:  # pragma: no cover
                    raise PrinterError("Win32Raw printer unavailable on this platform") from exc
                printer = Win32Raw(printer_name)
                printer.open()
                self._feed_lines(printer, count)
                printer.close()
            elif destination.startswith("cups-raw://"):
                printer_name = destination.removeprefix("cups-raw://")
                if not printer_name:
                    raise PrinterError("Invalid CUPS-raw printer destination.")
                dummy = Dummy()
                self._feed_lines(dummy, count)
                payload = getattr(dummy, "output", b"") or b""
                self._lp(printer_name, payload, options=["-o", "raw"])
            else:
                raise PrinterError(
                    "Feed unsupported for this destination "
                    "(use tcp://, file://, win32://, or cups-raw://)."
                )
        except PrinterError:
            raise
        except Exception as exc:
            raise PrinterError(f"ESC/POS feed failed: {exc}") from exc

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
        self._prepare_page(printer, settings)
        # After a cut/tear the head sits on the paper edge — without a short
        # lead-in the first line loses a few pixels at the top.
        self._feed_lines(printer, settings.lead_in_lines)
        body = formatted_body if formatted_body.endswith("\n") else formatted_body + "\n"
        if settings.render_mode == "bitmap":
            self._render_bitmap(printer, body, settings)
        else:
            printer.text(body)  # type: ignore[attr-defined]
        if settings.cut_enabled:
            self._tear_or_cut(printer, settings)

    @staticmethod
    def _render_bitmap(printer: object, body: str, settings: PrinterSettings) -> None:
        from acars_bridge.printing.bitmap_render import render_receipt_bitmap

        img = render_receipt_bitmap(
            body,
            paper_width=settings.paper_width,
            glyph_px=settings.glyph_px,
            line_gap_px=settings.line_gap_px,
            bold=settings.bold,
        )
        # python-escpos prints a stdout warning when media.width.pixels is
        # "Unknown" (even with center=False). That breaks the Tauri NDJSON bridge.
        EscPosMessagePrinter._ensure_media_width_pixels(printer, settings.paper_width)
        try:
            printer.image(img, center=False)  # type: ignore[attr-defined]
        except TypeError:
            # Older python-escpos: path-only — write temp PNG.
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "strip.png"
                img.save(path)
                try:
                    printer.image(str(path), center=False)  # type: ignore[attr-defined]
                except TypeError:
                    printer.image(str(path))  # type: ignore[attr-defined]

    @staticmethod
    def _ensure_media_width_pixels(printer: object, paper_width: str) -> None:
        """Set escpos profile pixel width so image() stays quiet on stdout."""
        from acars_bridge.printing.bitmap_render import paper_dot_width

        dots = int(paper_dot_width(paper_width))
        profile = getattr(printer, "profile", None)
        if profile is None:
            return
        data = getattr(profile, "profile_data", None)
        if not isinstance(data, dict):
            return
        media = data.setdefault("media", {})
        if not isinstance(media, dict):
            return
        width = media.setdefault("width", {})
        if not isinstance(width, dict):
            return
        current = width.get("pixels")
        if current in (None, "", "Unknown") or not str(current).isdigit():
            width["pixels"] = dots

    @staticmethod
    def _feed_lines(printer: object, lines: int) -> None:
        if lines <= 0:
            return
        try:
            printer.print_and_feed(lines)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        try:
            printer.text("\n" * lines)  # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _prepare_page(printer: object, settings: PrinterSettings) -> None:
        """Apply Settings print style (font / size / bold / spacing)."""
        if settings.render_mode == "bitmap":
            # Image path — still reset alignment / margins.
            try:
                printer.set(align="left", density=8)  # type: ignore[attr-defined]
            except Exception:
                pass
        else:
            font = "b" if settings.font == "b" else "a"
            width = max(1, min(8, int(settings.char_width)))
            height = max(1, min(8, int(settings.char_height)))
            try:
                printer.set(  # type: ignore[attr-defined]
                    align="left",
                    font=font,
                    bold=settings.bold,
                    custom_size=True,
                    width=width,
                    height=height,
                    density=8,
                )
            except Exception:
                try:
                    printer.set(  # type: ignore[attr-defined]
                        align="left",
                        font=font,
                        bold=settings.bold,
                        double_width=width >= 2,
                        double_height=height >= 2,
                        normal_textsize=width == 1 and height == 1,
                    )
                except Exception:
                    pass

            dots = settings.line_spacing_dots
            spacing_fn = getattr(printer, "line_spacing", None)
            if callable(spacing_fn):
                try:
                    if dots is None:
                        spacing_fn()
                    else:
                        spacing_fn(dots)
                except Exception:
                    pass

        for attr, args in (
            ("set_left_margin", (0,)),
            ("left_margin", (0,)),
        ):
            fn = getattr(printer, attr, None)
            if callable(fn):
                try:
                    fn(*args)
                    break
                except Exception:
                    continue

    def _tear_or_cut(self, printer: object, settings: PrinterSettings) -> None:
        """Advance to the tear bar, then partial-cut when the mechanism exists.

        Cheap POS-80 units often have only a serrated tear edge (or a partial
        cutter). A full cut can jam them; skipping feed leaves the last lines
        under the head so ripping tears the receipt crooked — Fenix avoids that
        by feeding before cut/tear.
        """
        try:
            printer.cut(mode="PART")  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        self._feed_lines(printer, settings.tear_feed_lines)

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
