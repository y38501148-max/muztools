from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DATA_DIR, ensure_dirs
from .store import _locked_read, _locked_write, now_iso

VERSION_FILE = DATA_DIR / "app_version.json"
RELEASE_DIR = DATA_DIR / "releases"


def default_version() -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "version_code": 1,
        "min_version_code": 1,
        "force": False,
        "title": "盐的工具箱",
        "message": "当前已是最新版本。",
        "apk_name": "",
        "updated_at": "",
    }


def load_version() -> dict[str, Any]:
    ensure_dirs()
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    data = _locked_read(VERSION_FILE, default_version())
    merged = default_version()
    merged.update(data or {})
    return merged


def save_version(data: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    current = load_version()
    current.update(data)
    current["updated_at"] = now_iso()
    _locked_write(VERSION_FILE, current)
    return current


def apk_path(name: str | None = None) -> Path:
    meta = load_version()
    filename = name or meta.get("apk_name") or "muztools.apk"
    return RELEASE_DIR / filename


def public_version(download_path: str = "/api/app/apk") -> dict[str, Any]:
    meta = load_version()
    return {
        "version": meta.get("version") or "1.0.0",
        "version_code": int(meta.get("version_code") or 1),
        "min_version_code": int(meta.get("min_version_code") or 1),
        "force": bool(meta.get("force")),
        "title": meta.get("title") or "发现新版本",
        "message": meta.get("message") or "",
        "apk_url": download_path if meta.get("apk_name") else "",
        "updated_at": meta.get("updated_at") or "",
    }
