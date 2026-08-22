from __future__ import annotations

import hashlib
import hmac
import re
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


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{6,18}$")


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not USERNAME_RE.fullmatch(name):
        raise ValueError("账号须为 6～18 位字母、数字或下划线")
    return name


def validate_password(password: str) -> str:
    if not 6 <= len(password or "") <= 18:
        raise ValueError("密码须为 6～18 位")
    if not re.search(r"[0-9]", password):
        raise ValueError("密码必须包含数字")
    if not re.search(r"[a-z]", password):
        raise ValueError("密码必须包含小写字母")
    if not re.search(r"[A-Z]", password):
        raise ValueError("密码必须包含大写字母")
    return password
