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
CORS_ORIGINS = [item.strip() for item in os.environ.get("MUZTOOLS_CORS_ORIGINS", "").split(",") if item.strip()]
SECRET_FILE = DATA_DIR / "secret.key"
VAULT_KEY_FILE = DATA_DIR / "vault.key"
RSA_PRIVATE_KEY_FILE = DATA_DIR / "transport_rsa.pem"
FCM_CREDENTIALS_FILE = os.environ.get("MUZTOOLS_FCM_CREDENTIALS", "").strip()
FCM_PROJECT_ID = os.environ.get("MUZTOOLS_FCM_PROJECT_ID", "").strip()


def ensure_dirs() -> None:
    for name in ("users", "sessions", "photos", "notifications", "tmp"):
        (DATA_DIR / name).mkdir(parents=True, exist_ok=True)
