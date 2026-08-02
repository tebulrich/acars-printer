from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "acars-bridge"
APP_AUTHOR = "acars-bridge"

HOPPIE_DEFAULT_URL = "https://www.hoppie.nl/acars/system/connect.html"
HOPPIE_TIMEOUT_SECONDS = 15
MIN_POLL_INTERVAL_SECONDS = 45
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_OBSERVER_INTERVAL_SECONDS = 60
FAST_POLL_SECONDS = 20
JITTER_SECONDS = 5
MAX_BACKOFF_SECONDS = 900


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    return data_dir() / "acars.sqlite3"


def default_key_path() -> Path:
    return data_dir() / "secret.key"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    db: Path
    key: Path

    @classmethod
    def default(cls) -> AppPaths:
        root = data_dir()
        return cls(root=root, db=root / "acars.sqlite3", key=root / "secret.key")

    @classmethod
    def for_testing(cls, root: Path) -> AppPaths:
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root, db=root / "acars.sqlite3", key=root / "secret.key")
