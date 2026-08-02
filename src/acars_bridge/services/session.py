from __future__ import annotations

from dataclasses import dataclass

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.observer import ObserverTransport
from acars_bridge.hoppie.station import StationTransport
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.models.db import Database
from acars_bridge.models.messages import MessageRepository
from acars_bridge.models.settings import SettingsStore
from acars_bridge.printing.console_printer import ConsoleMessagePrinter
from acars_bridge.printing.discovery import is_device_printer_destination
from acars_bridge.printing.escpos_printer import EscPosMessagePrinter
from acars_bridge.printing.fake_printer import FakeMessagePrinter
from acars_bridge.services.ingestion import MessageIngestionService
from acars_bridge.services.outbound import OutboundMessageService
from acars_bridge.services.print_manager import PrintManager


@dataclass(slots=True)
class AppSession:
    paths: AppPaths
    db: Database
    settings: SettingsStore
    messages: MessageRepository
    client: HoppieClient
    station: StationTransport
    observer: ObserverTransport
    ingestion: MessageIngestionService
    outbound: OutboundMessageService
    print_manager: PrintManager

    def transport(self):
        return self.observer

    def rebuild_printer(self, *, use_fake_printer: bool = False) -> None:
        """Recreate print stack after printer settings change."""
        destination = self.settings.printer_destination()
        if use_fake_printer:
            printer = FakeMessagePrinter()
        elif is_device_printer_destination(destination):
            printer = EscPosMessagePrinter()
        else:
            printer = ConsoleMessagePrinter()
        self.print_manager = PrintManager(self.messages, printer)
        self.ingestion = MessageIngestionService(self.messages, self.settings, self.print_manager)
        self.outbound = OutboundMessageService(
            self.station, self.messages, self.settings, self.ingestion
        )

    def close(self) -> None:
        self.db.close()


def build_session(
    paths: AppPaths | None = None,
    *,
    client: HoppieClient | None = None,
    use_fake_printer: bool = False,
) -> AppSession:
    paths = paths or AppPaths.default()
    db = Database(paths.db)
    settings = SettingsStore(db, paths.key)
    messages = MessageRepository(db)
    hoppie = client or HoppieClient(base_url=settings.hoppie_url())
    station = StationTransport(hoppie)
    observer = ObserverTransport(hoppie)

    destination = settings.printer_destination()
    if use_fake_printer:
        printer = FakeMessagePrinter()
    elif is_device_printer_destination(destination):
        printer = EscPosMessagePrinter()
    else:
        printer = ConsoleMessagePrinter()

    settings.set_mode(ClientMode.OBSERVER)
    print_manager = PrintManager(messages, printer)
    ingestion = MessageIngestionService(messages, settings, print_manager)
    outbound = OutboundMessageService(station, messages, settings, ingestion)
    return AppSession(
        paths=paths,
        db=db,
        settings=settings,
        messages=messages,
        client=hoppie,
        station=station,
        observer=observer,
        ingestion=ingestion,
        outbound=outbound,
        print_manager=print_manager,
    )
