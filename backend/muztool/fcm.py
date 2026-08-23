"""Firebase Cloud Messaging HTTP v1 integration.

The implementation uses the service-account JWT flow directly so the production
server does not need the Firebase Admin SDK package or outbound package installs.
It remains optional until ``MUZTOOLS_FCM_CREDENTIALS`` points at a valid service
account JSON file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15

from . import config
from .security import decrypt_secret, encrypt_secret
from .store import load_user, now_iso, save_user

logger = logging.getLogger(__name__)
_credentials_lock = threading.Lock()
_credentials_cache: dict[str, Any] | None = None
_access_token: tuple[str, float] | None = None


def _credential_path() -> Path | None:
    value = str(config.FCM_CREDENTIALS_FILE or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() and path.is_file() else None


def _load_credentials() -> dict[str, Any] | None:
    global _credentials_cache
    path = _credential_path()
    if path is None:
        return None
    with _credentials_lock:
        if _credentials_cache is not None and _credentials_cache.get("_path") == str(path):
            return _credentials_cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("client_email") or not data.get("private_key"):
                raise ValueError("service account fields are incomplete")
            data["_path"] = str(path)
            _credentials_cache = data
            return data
        except Exception:
            logger.exception("FCM credentials could not be loaded")
            return None


def enabled() -> bool:
    return _load_credentials() is not None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _post(url: str, **kwargs: Any) -> httpx.Response:
    """POST through the dedicated FCM proxy when one is configured."""
    client_kwargs: dict[str, Any] = {"timeout": kwargs.pop("timeout", 15)}
    if config.FCM_PROXY:
        client_kwargs["proxy"] = config.FCM_PROXY
    with httpx.Client(**client_kwargs) as client:
        return client.post(url, **kwargs)


def _access_token_for(credentials: dict[str, Any]) -> str | None:
    global _access_token
    now = int(time.time())
    if _access_token and _access_token[1] > now + 60:
        return _access_token[0]
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(json.dumps({
        "iss": credentials["client_email"],
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }, separators=(",", ":")).encode())
    unsigned = f"{header}.{claims}".encode("ascii")
    key = RSA.import_key(credentials["private_key"])
    signature = pkcs1_15.new(key).sign(SHA256.new(unsigned))
    assertion = f"{header}.{claims}.{_b64url(signature)}"
    try:
        response = _post(
            "https://oauth2.googleapis.com/token",
            content=urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            return None
        _access_token = (token, now + int(payload.get("expires_in", 3600)))
        return token
    except Exception:
        logger.exception("FCM OAuth token request failed")
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_token(user: dict[str, Any], token: str, device_id: str = "", app_version: str = "") -> None:
    token = str(token or "").strip()
    if not token or len(token) > 4096:
        raise ValueError("FCM token 格式无效")
    digest = _token_hash(token)
    devices = user.setdefault("devices", [])
    for item in devices:
        if isinstance(item, dict) and item.get("token_hash") == digest:
            item.update({"device_id": device_id, "app_version": app_version})
            save_user(user)
            return
    devices.append({
        "kind": "fcm",
        "token_hash": digest,
        "token_encrypted": encrypt_secret(token),
        "device_id": device_id,
        "app_version": app_version,
        "created_at": now_iso(),
    })
    fcm_devices = [item for item in devices if isinstance(item, dict) and item.get("kind") == "fcm"]
    if len(fcm_devices) > 8:
        keep = {id(item) for item in fcm_devices[-8:]}
        user["devices"] = [
            item for item in devices
            if not (isinstance(item, dict) and item.get("kind") == "fcm") or id(item) in keep
        ]
    save_user(user)


def unregister_token(user: dict[str, Any], token: str) -> None:
    digest = _token_hash(str(token or "").strip())
    user["devices"] = [
        item for item in user.get("devices", [])
        if not (isinstance(item, dict) and item.get("kind") == "fcm" and item.get("token_hash") == digest)
    ]
    save_user(user)


def _send_one(credentials: dict[str, Any], token: str, data: dict[str, str]) -> tuple[bool, bool]:
    access_token = _access_token_for(credentials)
    if not access_token:
        return False, False
    project_id = config.FCM_PROJECT_ID or str(credentials.get("project_id") or "")
    if not project_id:
        logger.error("FCM project ID is missing")
        return False, False
    payload = {
        "message": {
            "token": token,
            "data": data,
            "android": {"priority": "HIGH"},
        }
    }
    try:
        response = _post(
            f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if response.is_success:
            return True, False
        text = response.text.lower()
        invalid = response.status_code in {400, 404} and any(
            marker in text for marker in ("unregistered", "registration-token-not-registered", "invalid argument")
        )
        logger.warning("FCM message failed with HTTP %s", response.status_code)
        return False, invalid
    except Exception:
        logger.exception("FCM message request failed")
        return False, False


def send_notification(user: dict[str, Any], item: dict[str, Any]) -> None:
    credentials = _load_credentials()
    if credentials is None:
        return
    tokens: list[tuple[str, dict[str, Any]]] = []
    for device in user.get("devices", []):
        if not isinstance(device, dict) or device.get("kind") != "fcm":
            continue
        try:
            token = decrypt_secret(device.get("token_encrypted"))
        except Exception:
            logger.warning("Ignoring an unreadable FCM token for user %s", user.get("id"))
            continue
        if token:
            tokens.append((token, device))
    if not tokens:
        return
    data = {
        "notification_id": str(item.get("id") or ""),
        "title": str(item.get("title") or "系统通知")[:100],
        "body": str(item.get("body") or item.get("content") or "")[:2000],
        "category": str(item.get("category") or "general")[:40],
        "url": str(item.get("url") or "")[:2000],
    }
    invalid_hashes: set[str] = set()
    for token, device in tokens:
        _, invalid = _send_one(credentials, token, data)
        if invalid:
            invalid_hashes.add(str(device.get("token_hash") or _token_hash(token)))
    if invalid_hashes:
        refreshed = load_user(str(user.get("id") or ""))
        if refreshed:
            refreshed["devices"] = [
                device for device in refreshed.get("devices", [])
                if not (isinstance(device, dict) and device.get("kind") == "fcm" and device.get("token_hash") in invalid_hashes)
            ]
            save_user(refreshed)


def dispatch_notification(user: dict[str, Any], item: dict[str, Any]) -> None:
    """Schedule a non-blocking FCM send from the notification hot path."""
    if not config.FCM_CREDENTIALS_FILE:
        return
    threading.Thread(target=send_notification, args=(dict(user), dict(item)), daemon=True, name="muztool-fcm").start()
