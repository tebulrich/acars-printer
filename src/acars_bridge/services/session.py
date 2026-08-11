from __future__ import annotations

from dataclasses import dataclass, field

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
from acars_bridge.services.sterile import SterileGate, SterileThresholds
from acars_bridge.services.wire_session import WireSessionVault
from acars_bridge.simbrief.client import SimBriefClient
from acars_bridge.simbrief.watcher import SimBriefWatcher, WatcherConfig
from acars_bridge.simconnect.monitor import SimConnectMonitor, create_simconnect_monitor
from acars_bridge.weather.auto_wx import AutoWxService


def _sterile_from_settings(settings: SettingsStore) -> SterileGate:
    return SterileGate(
        thresholds=SterileThresholds(agl_ft=float(settings.sterile_agl_ft())),
        require_powered=settings.print_when_powered(),
    )


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
    sterile: SterileGate = field(default_factory=SterileGate)
    simconnect: SimConnectMonitor = field(default_factory=create_simconnect_monitor)
    simbrief_watcher: SimBriefWatcher | None = None
    auto_wx: AutoWxService | None = None
    wire_session: WireSessionVault = field(default_factory=WireSessionVault)

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
        # Keep sterile flush synchronous with fake printers (unit tests).
        if use_fake_printer:
            self.sterile.set_flush_runner(None)
        else:
            self.sterile.set_flush_runner(self.print_manager.submit)
        self.ingestion = MessageIngestionService(
            self.messages, self.settings, self.print_manager, sterile=self.sterile
        )
        self.outbound = OutboundMessageService(
            self.station, self.messages, self.settings, self.ingestion
        )
        self.outbound.attach_session(self)
        if self.simbrief_watcher is not None:
            self.simbrief_watcher.print_manager = self.print_manager
        if self.auto_wx is not None:
            self.auto_wx.print_manager = self.print_manager

    def ensure_auto_wx(self) -> AutoWxService:
        if self.auto_wx is None:
            self.auto_wx = AutoWxService(
                settings=self.settings,
                print_manager=self.print_manager,
                sterile=self.sterile,
            )
        return self.auto_wx

    def apply_sterile_settings(self) -> None:
        self.sterile.set_thresholds(
            SterileThresholds(agl_ft=float(self.settings.sterile_agl_ft()))
        )
        self.sterile.set_require_powered(self.settings.print_when_powered())

    def ensure_simbrief_watcher(self) -> SimBriefWatcher:
        if self.simbrief_watcher is None:
            cfg = WatcherConfig(
                post_landing_grace_seconds=float(
                    self.settings.simbrief_post_landing_grace_seconds()
                ),
            )
            self.simbrief_watcher = SimBriefWatcher(
                settings=self.settings,
                print_manager=self.print_manager,
                sterile=self.sterile,
                client=SimBriefClient(),
                config=cfg,
            )
        return self.simbrief_watcher

    def close(self) -> None:
        try:
            self.simconnect.stop()
        except Exception:
            pass
        try:
            self.print_manager.shutdown(wait=False)
        except Exception:
            pass
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
    sterile = _sterile_from_settings(settings)
    simconnect = create_simconnect_monitor()

    destination = settings.printer_destination()
    if use_fake_printer:
        printer = FakeMessagePrinter()
    elif is_device_printer_destination(destination):
        printer = EscPosMessagePrinter()
    else:
        printer = ConsoleMessagePrinter()

    settings.set_mode(ClientMode.OBSERVER)
    print_manager = PrintManager(messages, printer)
    if use_fake_printer:
        sterile.set_flush_runner(None)
    else:
        sterile.set_flush_runner(print_manager.submit)
    ingestion = MessageIngestionService(
        messages, settings, print_manager, sterile=sterile
    )
    outbound = OutboundMessageService(station, messages, settings, ingestion)
    session = AppSession(
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
        sterile=sterile,
        simconnect=simconnect,
    )
    outbound.attach_session(session)
    session.ensure_simbrief_watcher()
    return session
