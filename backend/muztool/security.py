from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

from .config import SECRET_FILE, ensure_dirs


def _secret() -> bytes:
    ensure_dirs()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_bytes(secrets.token_bytes(32))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_bytes()


def hash_password(password: str, salt: str | None = None) -> str:
    raw_salt = salt.encode("utf-8") if salt else secrets.token_hex(16).encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw_salt, 200_000)
    return f"{raw_salt.decode('utf-8') if salt else raw_salt.decode('utf-8')}${digest.hex()}" if salt else f"{raw_salt.decode('utf-8')}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, f"{salt}${digest}")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_id() -> str:
    return secrets.token_hex(8)
