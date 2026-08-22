from __future__ import annotations

import os
from pathlib import Path


def _default_data_dir() -> Path:
    env = os.environ.get("MUZTOOLS_DATA")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data"


DATA_DIR = _default_data_dir()
HOST = os.environ.get("MUZTOOLS_HOST", "0.0.0.0")
PORT = int(os.environ.get("MUZTOOLS_PORT", "18787"))
TD_SOCKS = os.environ.get("MUZTOOLS_TD_SOCKS", "").strip()
SECRET_FILE = DATA_DIR / "secret.key"


def ensure_dirs() -> None:
    for name in ("users", "sessions", "photos", "notifications", "tmp"):
        (DATA_DIR / name).mkdir(parents=True, exist_ok=True)
