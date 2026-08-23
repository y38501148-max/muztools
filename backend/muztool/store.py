from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import fcntl

from .config import DATA_DIR, ensure_dirs
from .security import decrypt_secret, encrypt_secret, hash_password, new_id, new_token, validate_password, validate_username, verify_password

TZ_BEIJING = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ_BEIJING).isoformat(timespec="seconds")


def _locked_read(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return deepcopy(default)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _locked_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)


FEATURE_KEYS = ("signin", "td", "spark")
DOUYIN_ALLOWED_USERNAME = "muzermat"


def user_path(user_id: str) -> Path:
    return DATA_DIR / "users" / f"{user_id}.json"


def ensure_approvals(user: dict[str, Any]) -> dict[str, Any]:
    """Compatibility projection after approval mode was removed in v1.3.0."""
    user["approvals"] = {key: "approved" for key in FEATURE_KEYS}
    return user

def set_feature_approval(user: dict[str, Any], feature: str, status: str) -> dict[str, Any]:
    if feature not in FEATURE_KEYS:
        raise ValueError(f"未知功能：{feature}")
    ensure_approvals(user)
    user["approvals"][feature] = status
    if feature == "signin" and status != "approved":
        user.setdefault("student", {})["auto_signin"] = False
    return user


def empty_user(username: str, password: str, display_name: str) -> dict[str, Any]:
    return {
        "id": new_id(),
        "username": username.strip(),
        "password_hash": hash_password(password),
        "display_name": display_name.strip() or username.strip(),
        "created_at": now_iso(),
        "student": {
            "student_id": "",
            "password_encrypted": "",
            "real_name": "",
            "uid": "",
            "session_id": "",
            "cookies": {},
            "status": "unbound",
            "auto_signin": False,
            "today_schedule": [],
            "schedule_date": "",
        },
        "approvals": {"signin": "approved", "td": "approved", "spark": "approved"},
        "td": {
            "campus": "xueyuanlu",
            "gap_seconds": 240,
            "entrance_machine_id": 2,
            "exit_machine_id": 6,
        },
        "douyin": {
            "cookies_encrypted": "",
            "unique_id": "",
            "username": "",
            "enabled": False,
            "default_message": "续火花",
            "targets": [],
            "friends_cache_encrypted": "",
            "friends_cache_initialized": False,
            "friends_cached_at": "",
            "hour": 9,
            "last_run": "",
            "last_auto_run": "",
            "last_auto_attempt": "",
        },
        "tibo": {"enabled": False},
        "devices": [],
        "notifications": [],
    }



def can_use_douyin(user: dict[str, Any]) -> bool:
    return str(user.get("username") or "").casefold() == DOUYIN_ALLOWED_USERNAME


def set_douyin_cookies(douyin: dict[str, Any], cookies: list[dict[str, Any]]) -> None:
    payload = json.dumps(cookies or [], ensure_ascii=False, separators=(",", ":"))
    douyin["cookies_encrypted"] = encrypt_secret(payload) if cookies else ""
    douyin.pop("cookies", None)


def get_douyin_cookies(douyin: dict[str, Any]) -> list[dict[str, Any]]:
    encrypted = douyin.get("cookies_encrypted")
    if encrypted:
        try:
            value = json.loads(decrypt_secret(encrypted))
        except Exception as exc:
            raise ValueError("服务器保存的抖音 Cookie 无法解密，请重新绑定") from exc
        return value if isinstance(value, list) else []
    legacy = douyin.get("cookies")
    return legacy if isinstance(legacy, list) else []


def set_douyin_friends_cache(douyin: dict[str, Any], friends: list[dict[str, Any]]) -> None:
    payload = json.dumps(friends or [], ensure_ascii=False, separators=(",", ":"))
    douyin["friends_cache_encrypted"] = encrypt_secret(payload) if friends else ""
    douyin["friends_cache_initialized"] = True
    douyin.pop("friends_cache", None)


def get_douyin_friends_cache(douyin: dict[str, Any]) -> list[dict[str, Any]]:
    encrypted = douyin.get("friends_cache_encrypted")
    if encrypted:
        try:
            value = json.loads(decrypt_secret(encrypted))
        except Exception as exc:
            raise ValueError("服务器保存的好友缓存无法解密，请主动刷新") from exc
        return value if isinstance(value, list) else []
    legacy = douyin.get("friends_cache")
    return legacy if isinstance(legacy, list) else []

def set_student_password(student: dict[str, Any], password: str) -> None:
    student["password_encrypted"] = encrypt_secret(password) if password else ""
    student.pop("password", None)


def get_student_password(student: dict[str, Any]) -> str:
    encrypted = student.get("password_encrypted")
    if encrypted:
        return decrypt_secret(encrypted)
    return str(student.get("password") or "")


def student_runtime(student: dict[str, Any]) -> dict[str, Any]:
    runtime = deepcopy(student)
    runtime["password"] = get_student_password(student)
    return runtime


def migrate_user_secrets(user: dict[str, Any]) -> bool:
    changed = False
    student = user.setdefault("student", {})
    legacy = str(student.get("password") or "")
    if legacy:
        set_student_password(student, legacy)
        changed = True
    elif "password" in student:
        student.pop("password", None)
        student.setdefault("password_encrypted", "")
        changed = True
    elif "password_encrypted" not in student:
        student["password_encrypted"] = ""
        changed = True

    douyin = user.setdefault("douyin", {})
    if "cookies" in douyin:
        legacy_cookies = douyin.get("cookies")
        set_douyin_cookies(douyin, legacy_cookies if isinstance(legacy_cookies, list) else [])
        changed = True
    elif "cookies_encrypted" not in douyin:
        douyin["cookies_encrypted"] = ""
        changed = True
    if "friends_cache" in douyin:
        legacy_friends = douyin.get("friends_cache")
        set_douyin_friends_cache(douyin, legacy_friends if isinstance(legacy_friends, list) else [])
        changed = True
    elif "friends_cache_encrypted" not in douyin:
        douyin["friends_cache_encrypted"] = ""
        douyin["friends_cache_initialized"] = False
        changed = True
    if not can_use_douyin(user) and douyin.get("enabled"):
        douyin["enabled"] = False
        douyin["disabled_reason"] = "temporary_admin_only"
        changed = True

    before = dict(user.get("approvals") or {})
    ensure_approvals(user)
    if before != user.get("approvals"):
        changed = True
    return changed


def load_user(user_id: str) -> dict[str, Any] | None:
    path = user_path(user_id)
    if not path.exists():
        return None
    data = _locked_read(path, {})
    if data and migrate_user_secrets(data):
        _locked_write(path, data)
    return data


def save_user(user: dict[str, Any]) -> None:
    ensure_dirs()
    migrate_user_secrets(user)
    _locked_write(user_path(user["id"]), user)


def iter_users() -> list[dict[str, Any]]:
    ensure_dirs()
    users: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "users").glob("*.json")):
        data = _locked_read(path, {})
        if data.get("id"):
            if migrate_user_secrets(data):
                _locked_write(path, data)
            users.append(data)
    return users


def find_user_by_username(username: str) -> dict[str, Any] | None:
    target = username.strip().lower()
    for user in iter_users():
        if user.get("username", "").lower() == target:
            return user
    return None


def find_user_by_student_id(student_id: str) -> dict[str, Any] | None:
    target = student_id.strip()
    for user in iter_users():
        if user.get("student", {}).get("student_id") == target:
            return user
    return None


def resolve_user(key: str) -> dict[str, Any] | None:
    key = key.strip()
    direct = load_user(key)
    if direct:
        return direct
    by_name = find_user_by_username(key)
    if by_name:
        return by_name
    return find_user_by_student_id(key)


def create_user(username: str, password: str, display_name: str) -> dict[str, Any]:
    username = validate_username(username)
    password = validate_password(password)
    if find_user_by_username(username):
        raise ValueError("用户名已存在")
    user = empty_user(username, password, display_name)
    save_user(user)
    return user


def authenticate(username: str, password: str) -> dict[str, Any]:
    user = find_user_by_username(username)
    if not user or not verify_password(password, user.get("password_hash", "")):
        raise ValueError("用户名或密码错误")
    return user


def session_path(token: str) -> Path:
    return DATA_DIR / "sessions" / f"{token}.json"


def create_session(user_id: str) -> str:
    ensure_dirs()
    token = new_token()
    _locked_write(session_path(token), {"token": token, "user_id": user_id, "created_at": now_iso()})
    return token


def user_from_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    data = _locked_read(session_path(token), {})
    user_id = data.get("user_id")
    return load_user(user_id) if user_id else None


def delete_session(token: str) -> None:
    path = session_path(token)
    if path.exists():
        path.unlink()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    student = user.get("student", {})
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "role": "admin" if str(user.get("username") or "").lower() == "muzermat" else "user",
        "can_manage_invites": str(user.get("username") or "").lower() == "muzermat",
        "can_use_douyin": can_use_douyin(user),
        "created_at": user.get("created_at"),
        "student": {
            "student_id": student.get("student_id", ""),
            "real_name": student.get("real_name", ""),
            "status": student.get("status", "unbound"),
            "auto_signin": bool(student.get("auto_signin")),
            "schedule_date": student.get("schedule_date", ""),
        },
        "approvals": ensure_approvals(user).get("approvals", {}),
        "td": user.get("td", {}),
        "tibo": {"enabled": bool(user.get("tibo", {}).get("enabled", False))},
        "douyin": {
            "connected": bool(user.get("douyin", {}).get("cookies_encrypted") or user.get("douyin", {}).get("cookies")),
            "username": user.get("douyin", {}).get("username", ""),
            "enabled": bool(user.get("douyin", {}).get("enabled")),
            "default_message": user.get("douyin", {}).get("default_message", "续火花"),
            "targets": user.get("douyin", {}).get("targets", []),
            "hour": user.get("douyin", {}).get("hour", 9),
            "last_run": user.get("douyin", {}).get("last_run", ""),
            "last_auto_run": user.get("douyin", {}).get("last_auto_run", ""),
            "last_auto_attempt": user.get("douyin", {}).get("last_auto_attempt", ""),
            "auto_scheduled_at": user.get("douyin", {}).get("auto_scheduled_at", ""),
            "auto_schedule_offset_minutes": user.get("douyin", {}).get("auto_schedule_offset_minutes", 0),
            "auto_blocked_date": user.get("douyin", {}).get("auto_blocked_date", ""),
            "auto_blocked_reason": user.get("douyin", {}).get("auto_blocked_reason", ""),
            "last_result": user.get("douyin", {}).get("last_result", {}),
            "target_status": user.get("douyin", {}).get("target_status", {}),
            "disabled_reason": user.get("douyin", {}).get("disabled_reason", ""),
        },
    }


def photo_dir(user_id: str) -> Path:
    path = DATA_DIR / "photos" / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path
