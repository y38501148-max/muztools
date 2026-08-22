from __future__ import annotations

from datetime import datetime
from typing import Any

from .store import TZ_BEIJING, load_user, now_iso, save_user


def push_notification(user: dict[str, Any], title: str, body: str, category: str = "general") -> dict[str, Any]:
    item = {
        "id": f"{int(datetime.now(TZ_BEIJING).timestamp() * 1000)}",
        "title": title,
        "body": body,
        "category": category,
        "created_at": now_iso(),
        "read": False,
    }
    user.setdefault("notifications", []).insert(0, item)
    user["notifications"] = user["notifications"][:200]
    save_user(user)
    return item


def signin_success_message(real_name: str, course_name: str, signed_at: str | None = None) -> str:
    hhmm = signed_at or datetime.now(TZ_BEIJING).strftime("%H:%M")
    name = real_name or "同学"
    return f"[签到提示]{name}您好，您的课程{course_name}已在{hhmm}完成签到"


def list_notifications(user: dict[str, Any], unread_only: bool = False) -> list[dict[str, Any]]:
    items = user.get("notifications", [])
    if unread_only:
        return [item for item in items if not item.get("read")]
    return items


def mark_read(user_id: str, notification_id: str | None = None) -> dict[str, Any] | None:
    user = load_user(user_id)
    if not user:
        return None
    changed = False
    for item in user.get("notifications", []):
        if notification_id is None or item.get("id") == notification_id:
            if not item.get("read"):
                item["read"] = True
                changed = True
    if changed:
        save_user(user)
    return user
