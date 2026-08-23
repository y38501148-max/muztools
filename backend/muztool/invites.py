from __future__ import annotations

import fcntl
import hashlib
import json
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DATA_DIR, ensure_dirs
from .security import decrypt_secret, encrypt_secret, new_id
from .store import now_iso

INVITES_FILE = DATA_DIR / "invite_codes.json"
INVITES_LOCK = DATA_DIR / "invite_codes.lock"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@contextmanager
def _exclusive() -> Iterator[None]:
    ensure_dirs()
    INVITES_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with INVITES_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _load() -> dict[str, Any]:
    if not INVITES_FILE.exists():
        return {"version": 1, "codes": []}
    try:
        return json.loads(INVITES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "codes": []}


def _save(data: dict[str, Any]) -> None:
    temp = INVITES_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(INVITES_FILE)


def normalize_code(code: str) -> str:
    candidate = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    if len(candidate) != 16 or any(ch not in ALPHABET for ch in candidate):
        return ""
    return candidate


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("ascii", "ignore")).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return "-".join(raw[index:index + 4] for index in range(0, 16, 4))


def generate_invites(count: int, created_by: str = "muz-admin") -> dict[str, Any]:
    safe_count = max(1, min(int(count), 500))
    with _exclusive():
        data = _load()
        existing = {item.get("code_hash") for item in data.get("codes", [])}
        generated = []
        while len(generated) < safe_count:
            code = _new_code()
            digest = code_hash(code)
            if digest in existing:
                continue
            existing.add(digest)
            data.setdefault("codes", []).append({
                "id": new_id(), "code_hash": digest, "code_encrypted": encrypt_secret(code),
                "status": "available", "created_at": now_iso(), "created_by": created_by,
                "issued_at": "", "issued_to": "", "used_at": "", "used_by": "",
            })
            generated.append(code)
        _save(data)
        return {"generated": safe_count, "available": sum(x.get("status") == "available" for x in data["codes"])}


def issue_invite(issued_to: str) -> dict[str, Any]:
    with _exclusive():
        data = _load()
        available = [item for item in data.get("codes", []) if item.get("status") == "available"]
        if not available:
            raise ValueError("当前没有可用邀请码，请先在后端批量生成")
        item = secrets.choice(available)
        item["status"] = "issued"
        item["issued_at"] = now_iso()
        item["issued_to"] = issued_to
        _save(data)
        return {"code": decrypt_secret(item.get("code_encrypted")), "remaining": len(available) - 1}


def consume_invite(code: str, used_by: str) -> str:
    digest = code_hash(code)
    if not normalize_code(code):
        raise ValueError("邀请码无效或已被使用")
    with _exclusive():
        data = _load()
        item = next((x for x in data.get("codes", []) if x.get("code_hash") == digest), None)
        if not item or item.get("status") not in {"available", "issued"}:
            raise ValueError("邀请码无效或已被使用")
        item["consumed_from"] = item.get("status") or "issued"
        item["status"] = "used"
        item["used_at"] = now_iso()
        item["used_by"] = used_by
        _save(data)
        return str(item.get("id") or "")


def release_invite(invite_id: str, used_by: str) -> bool:
    """Return an invite to issued state if account creation failed after consume."""
    with _exclusive():
        data = _load()
        item = next(
            (x for x in data.get("codes", [])
             if str(x.get("id") or "") == str(invite_id)
             and x.get("status") == "used"
             and x.get("used_by") == used_by),
            None,
        )
        if not item:
            return False
        item["status"] = item.get("consumed_from") or "issued"
        item["used_at"] = ""
        item["used_by"] = ""
        item["released_at"] = now_iso()
        _save(data)
        return True


def invite_stats() -> dict[str, int]:
    with _exclusive():
        data = _load()
        rows = data.get("codes", [])
        return {status: sum(x.get("status") == status for x in rows) for status in ("available", "issued", "used")}
