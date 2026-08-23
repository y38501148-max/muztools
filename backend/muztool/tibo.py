from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable, FrozenSet, Iterable

import httpx

from .config import DATA_DIR
from .notify import push_notification
from .signin_core import TZ_BEIJING
from .store import iter_users

TIBO_USERNAME = os.environ.get("MUZTOOLS_TIBO_USERNAME", "thsottiaux").strip() or "thsottiaux"
TIBO_PROXY_URL = os.environ.get("MUZTOOLS_TIBO_PROXY", "http://127.0.0.1:7890").strip()
TIBO_NOTICE = "tibo发布了一条与重置有关的推特，请点击查看"
TIBO_STATE_PATH = DATA_DIR / "tibo_monitor.json"
TWITTER_EPOCH_MS = 1_288_834_974_657
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TiboPost:
    id: str
    created_at: datetime
    text: str
    url: str


@dataclass(frozen=True)
class FetchResult:
    discovered_ids: tuple[str, ...]
    posts: tuple[TiboPost, ...]


@dataclass(frozen=True)
class CheckReport:
    initialized: bool
    discovered: int
    matched: int
    notified_users: int


def snowflake_created_at(post_id: str) -> datetime:
    if not post_id.isdigit():
        raise ValueError("推特 ID 不是数字")
    timestamp_ms = (int(post_id) >> 22) + TWITTER_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def is_reset_post(text: str) -> bool:
    return "reset" in str(text or "").casefold()


class _ProfileHtmlParser(HTMLParser):
    """Read X's server-rendered schema.org SocialMediaPosting cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.current: dict[str, str] | None = None
        self.posts: list[TiboPost] = []
        self._capture_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "article":
            if self.article_depth == 0:
                post_id = values.get("data-tweet-id", "")
                self.current = {"id": post_id, "text": "", "url": "", "date": "", "author_match": ""}
            self.article_depth += 1
            return
        if self.article_depth != 1 or self.current is None:
            return
        if tag == "a" and values.get("href", "").rstrip("/").casefold() == f"/{TIBO_USERNAME}".casefold():
            self.current["author_match"] = "1"
            return
        if tag == "span":
            classes = set(values.get("class", "").split())
            if {"whitespace-pre-wrap", "break-words", "text-inherit", "font-inherit"}.issubset(classes):
                self._capture_text = True
            return
        if tag != "meta":
            return
        prop = values.get("itemprop", "")
        content = values.get("content", "")
        if prop == "text":
            self.current["text"] = content
        elif prop == "url" and f"/{TIBO_USERNAME}/status/" in content.casefold():
            self.current["url"] = content
            self.current["author_match"] = "1"
        elif prop == "datePublished":
            self.current["date"] = content

    def handle_data(self, data: str) -> None:
        if self._capture_text and self.article_depth == 1 and self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture_text:
            self._capture_text = False
        if tag != "article" or self.article_depth <= 0:
            return
        self.article_depth -= 1
        if self.article_depth != 0 or self.current is None:
            return
        raw = self.current
        self.current = None
        self._capture_text = False
        post_id = raw.get("id", "")
        text = raw.get("text", "").strip()
        if not post_id.isdigit() or not text or not raw.get("author_match"):
            return
        date_text = raw.get("date", "")
        try:
            created_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")) if date_text else snowflake_created_at(post_id)
        except ValueError:
            created_at = snowflake_created_at(post_id)
        # Profile cards may expose engagement URLs such as /retweets as the
        # last itemprop=url. Always use the canonical status URL for thread
        # expansion and user-facing links.
        url = f"https://x.com/{TIBO_USERNAME}/status/{post_id}"
        self.posts.append(TiboPost(post_id, created_at.astimezone(timezone.utc), text, url))


def parse_profile_html(html: str) -> tuple[TiboPost, ...]:
    parser = _ProfileHtmlParser()
    parser.feed(html)
    seen: set[str] = set()
    posts: list[TiboPost] = []
    for post in parser.posts:
        if post.id in seen:
            continue
        seen.add(post.id)
        posts.append(post)
    return tuple(posts)


def _read_state(path: Path = TIBO_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"initialized": False, "seen_ids": [], "last_checked": "", "history": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"initialized": False, "seen_ids": [], "last_checked": "", "history": []}
    if not isinstance(raw, dict):
        return {"initialized": False, "seen_ids": [], "last_checked": "", "history": []}
    seen_ids = raw.get("seen_ids")
    raw["seen_ids"] = [str(item) for item in seen_ids if str(item).isdigit()] if isinstance(seen_ids, list) else []
    history = raw.get("history")
    raw["history"] = [item for item in history if isinstance(item, dict) and str(item.get("id") or "").isdigit()][:100] if isinstance(history, list) else []
    raw["initialized"] = bool(raw.get("initialized"))
    return raw


def _write_state(state: dict[str, Any], path: Path = TIBO_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


async def fetch_recent_tibo_posts(
    seen_ids: FrozenSet[str],
    now: datetime,
    lookback_hours: int = 24,
) -> FetchResult:
    """Fetch Tibo's recent posts and self-replies from public X HTML.

    The anonymous profile HTML only exposes top-level posts. Reset timing is
    sometimes published as a self-reply, so recent conversation pages are also
    scanned and merged by tweet ID.
    """
    del seen_ids  # State filtering happens after all profile/thread posts merge.
    proxy = TIBO_PROXY_URL or None
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/136 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, timeout=30, headers=headers) as client:
        response = await client.get(f"https://x.com/{TIBO_USERNAME}")
        response.raise_for_status()
        profile_posts = parse_profile_html(response.text)

        async def fetch_thread(post: TiboPost) -> tuple[TiboPost, ...]:
            try:
                thread_response = await client.get(post.url)
                thread_response.raise_for_status()
                return parse_profile_html(thread_response.text)
            except Exception:
                logger.warning("Could not fetch Tibo thread %s", post.id, exc_info=True)
                return ()

        # X's anonymous profile currently returns only a small page. Scanning
        # each returned conversation catches recent Tibo self-replies without
        # accepting replies authored by other accounts.
        thread_results = await asyncio.gather(*(fetch_thread(post) for post in profile_posts[:8]))

    by_id = {post.id: post for post in profile_posts}
    for thread_posts in thread_results:
        for post in thread_posts:
            by_id[post.id] = post

    current_utc = now.astimezone(timezone.utc)
    cutoff = current_utc - timedelta(hours=lookback_hours)
    discovered: list[str] = []
    posts: list[TiboPost] = []
    for post in sorted(by_id.values(), key=lambda item: int(item.id), reverse=True):
        if post.created_at > current_utc + timedelta(minutes=5):
            continue
        discovered.append(post.id)
        if post.created_at < cutoff or not is_reset_post(post.text):
            continue
        posts.append(post)
    return FetchResult(tuple(discovered), tuple(posts))



def _post_payload(post: TiboPost) -> dict[str, str]:
    return {
        "id": post.id,
        "created_at": post.created_at.astimezone(TZ_BEIJING).isoformat(timespec="seconds"),
        "text": post.text,
        "url": post.url,
    }


def list_tibo_history(path: Path = TIBO_STATE_PATH) -> dict[str, Any]:
    state = _read_state(path)
    return {
        "items": list(state.get("history") or [])[:100],
        "count": len(state.get("history") or []),
        "last_checked": str(state.get("last_checked") or ""),
    }

def _already_notified(user: dict[str, Any], post_id: str) -> bool:
    source_id = f"tibo:{post_id}"
    return any(item.get("source_id") == source_id for item in user.get("notifications", []))


def _notify_users(posts: Iterable[TiboPost]) -> int:
    notified = 0
    users = list(iter_users())
    for post in posts:
        source_id = f"tibo:{post.id}"
        for user in users:
            if not bool(user.get("tibo", {}).get("enabled", False)):
                continue
            if _already_notified(user, post.id):
                continue
            push_notification(
                user,
                "Tibo 推特提醒",
                TIBO_NOTICE,
                "tibo",
                url=post.url,
                source_id=source_id,
            )
            notified += 1
    return notified


async def check_tibo_updates(
    *,
    fetcher: Callable[[FrozenSet[str], datetime, int], Awaitable[FetchResult]] = fetch_recent_tibo_posts,
    now: datetime | None = None,
    state_path: Path = TIBO_STATE_PATH,
) -> CheckReport:
    current = (now or datetime.now(TZ_BEIJING)).astimezone(TZ_BEIJING)
    state = _read_state(state_path)
    was_initialized = bool(state.get("initialized"))
    seen = frozenset(str(item) for item in state.get("seen_ids", []) if str(item).isdigit())
    result = await fetcher(seen, current, 24)
    matched = tuple(post for post in result.posts if is_reset_post(post.text))
    new_matched = tuple(post for post in matched if post.id not in seen)

    # The first successful check establishes a baseline instead of sending an
    # old 24-hour backlog to every MuzTool account.
    notified = _notify_users(new_matched) if was_initialized else 0
    combined = sorted(seen.union(result.discovered_ids), key=int, reverse=True)[:500]
    history_by_id = {str(item.get("id")): item for item in state.get("history", []) if isinstance(item, dict)}
    for post in matched:
        history_by_id[post.id] = _post_payload(post)
    history = sorted(history_by_id.values(), key=lambda item: int(str(item.get("id") or "0")), reverse=True)[:100]
    _write_state(
        {
            "initialized": True,
            "seen_ids": combined,
            "last_checked": current.isoformat(timespec="seconds"),
            "history": history,
        },
        state_path,
    )
    return CheckReport(
        initialized=not was_initialized,
        discovered=len(result.discovered_ids),
        matched=len(new_matched),
        notified_users=notified,
    )
