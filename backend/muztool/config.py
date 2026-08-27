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
TD_SERVER_HOST = os.environ.get("MUZTOOLS_TD_HOST", "").strip()
CORS_ORIGINS = [item.strip() for item in os.environ.get("MUZTOOLS_CORS_ORIGINS", "").split(",") if item.strip()]
SECRET_FILE = DATA_DIR / "secret.key"
VAULT_KEY_FILE = DATA_DIR / "vault.key"
RSA_PRIVATE_KEY_FILE = DATA_DIR / "transport_rsa.pem"
FCM_CREDENTIALS_FILE = os.environ.get("MUZTOOLS_FCM_CREDENTIALS", "").strip()
FCM_PROJECT_ID = os.environ.get("MUZTOOLS_FCM_PROJECT_ID", "").strip()
FCM_PROXY = os.environ.get("MUZTOOLS_FCM_PROXY", "").strip()
RELAY_ONLY = os.environ.get("MUZTOOLS_RELAY_ONLY", "").strip().lower() in {"1", "true", "yes"}
# Forwarded client/protocol headers are trusted only from a loopback peer and
# only when explicitly enabled for a local reverse proxy or Cloudflare Tunnel.
TRUST_PROXY_HEADERS = os.environ.get("MUZTOOLS_TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes"}


def ensure_dirs() -> None:
    for name in ("users", "sessions", "photos", "notifications", "notification_events", "tmp"):
        path = DATA_DIR / name
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
