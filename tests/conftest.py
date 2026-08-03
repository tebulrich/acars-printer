from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from acars_bridge.config import AppPaths
from acars_bridge.services.session import build_session

FIXTURES = Path(__file__).parent / "fixtures" / "hoppie"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def fixture_text():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        return FIXTURES / name

    return _path


@pytest.fixture
def app_session(tmp_path: Path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_printer_destination("fake")
    # Keep unit tests fast — production uses the 1s auto-print delay.
    session.ingestion._print_delay_seconds = 0.0
    yield session
    session.close()
