from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from .store import TZ_BEIJING, load_user, now_iso, save_user
from .fcm import dispatch_notification


_live_loop: asyncio.AbstractEventLoop | None = None
_live_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}


def configure_live_notifications(loop: asyncio.AbstractEventLoop) -> None:
    global _live_loop
    _live_loop = loop


def subscribe_live_notifications(user_id: str) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
    _live_subscribers.setdefault(user_id, set()).add(queue)
    return queue


def unsubscribe_live_notifications(user_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    queues = _live_subscribers.get(user_id)
    if not queues:
        return
    queues.discard(queue)
    if not queues:
        _live_subscribers.pop(user_id, None)


def _deliver_live_notification(user_id: str, item: dict[str, Any]) -> None:
    for queue in tuple(_live_subscribers.get(user_id, ())):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(dict(item))
        except asyncio.QueueFull:
            pass


def publish_live_notification(user_id: str, item: dict[str, Any]) -> None:
    loop = _live_loop
    if not loop or loop.is_closed():
        return
    loop.call_soon_threadsafe(_deliver_live_notification, user_id, dict(item))


def push_notification(
    user: dict[str, Any],
    title: str,
    body: str,
    category: str = "general",
    *,
    url: str = "",
    source_id: str = "",
) -> dict[str, Any]:
    item = {
        "id": f"{int(datetime.now(TZ_BEIJING).timestamp() * 1000)}",
        "title": title,
        "body": body,
        "category": category,
        "created_at": now_iso(),
        "read": False,
        "url": url,
        "source_id": source_id,
    }
    user.setdefault("notifications", []).insert(0, item)
    user["notifications"] = user["notifications"][:200]
    save_user(user)
    publish_live_notification(str(user.get("id") or ""), item)
    dispatch_notification(user, item)
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
