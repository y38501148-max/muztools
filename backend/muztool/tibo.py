from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable, FrozenSet, Iterable

import httpx

from .config import DATA_DIR
from .notify import push_notification
from .signin_core import TZ_BEIJING
from .store import get_tibo_x_cookies, iter_users

TIBO_USERNAME = os.environ.get("MUZTOOLS_TIBO_USERNAME", "thsottiaux").strip() or "thsottiaux"
TIBO_PROXY_URL = os.environ.get("MUZTOOLS_TIBO_PROXY", "http://127.0.0.1:7890").strip()
TIBO_NOTICE = "tibo发布了一条与重置有关的推特，请点击查看"
TIBO_STATE_PATH = DATA_DIR / "tibo_monitor.json"
TIBO_LOOKBACK_HOURS = 168  # one week; survives multi-day X outages without gaps
TWITTER_EPOCH_MS = 1_288_834_974_657
X_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
GRAPHQL_MAX_PAGES = 5
logger = logging.getLogger(__name__)


class XAuthError(Exception):
    """Raised when a stored X login cookie is rejected (HTTP 401/403)."""


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
    """Read X's server-rendered schema.org SocialMediaPosting cards.

    X currently emits the schema.org attributes as camelCase ``itemProp``
    (React style) and no longer renders ``data-tweet-id`` on the article tag,
    so attribute names are matched case-insensitively and the post id is taken
    from the canonical ``/status/<id>`` URL. Authorship is verified through
    the ``alternateName`` meta (profile pages) or a profile anchor link
    (thread pages, which only carry date/url metas and render the text in a
    ``whitespace-pre-wrap`` span) so retweets of other accounts are ignored.
    """

    STATUS_URL_RE = re.compile(rf"/(?P<user>[A-Za-z0-9_]+)/status/(?P<id>\d+)")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.current: dict[str, str] | None = None
        self.posts: list[TiboPost] = []
        self._capture_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {(key or "").lower(): value or "" for key, value in attrs}
        if tag == "article":
            self.article_depth += 1
            if self.article_depth == 1:
                self.current = {"id": "", "text": "", "url": "", "date": "", "author": ""}
            return
        if self.article_depth != 1 or self.current is None:
            return
        if tag == "meta":
            prop = values.get("itemprop", "").casefold()
            content = values.get("content", "")
            if prop == "text" and content and not self.current["text"]:
                self.current["text"] = content
            elif prop == "datepublished" and not self.current["date"]:
                self.current["date"] = content
            elif prop == "alternatename" and not self.current["author"]:
                self.current["author"] = content.strip().casefold()
            elif prop == "url" and not self.current["id"]:
                match = self.STATUS_URL_RE.search(content)
                if match and match.group("user").casefold() == TIBO_USERNAME.casefold():
                    self.current["id"] = match.group("id")
            return
        if tag == "span":
            classes = set(values.get("class", "").split())
            if {"whitespace-pre-wrap", "break-words"}.issubset(classes) and not self.current["text"]:
                self._capture_text = True
            return
        if tag == "a" and values.get("href", "").rstrip("/").casefold() == f"/{TIBO_USERNAME}".casefold():
            # Thread pages have no alternateName meta; the author profile
            # anchor is the only ownership signal. Mentions of Tibo in other
            # accounts' replies cannot pass because their status URL meta
            # points at the reply author, never at Tibo.
            self.current["author"] = self.current["author"] or TIBO_USERNAME.casefold()

    def handle_data(self, data: str) -> None:
        if self._capture_text and self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._capture_text = False
            return
        if tag != "article" or self.article_depth <= 0:
            return
        self.article_depth -= 1
        if self.article_depth != 0 or self.current is None:
            return
        raw = self.current
        self.current = None
        post_id = raw.get("id", "")
        text = raw.get("text", "").strip()
        if not post_id.isdigit() or not text or raw.get("author") != TIBO_USERNAME.casefold():
            return
        date_text = raw.get("date", "")
        try:
            created_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")) if date_text else snowflake_created_at(post_id)
        except ValueError:
            created_at = snowflake_created_at(post_id)
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


def parse_x_cookie_text(text: str) -> dict[str, str]:
    """Extract auth_token/ct0 from a cookie header or a browser cookie export."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("请输入 X Cookie 内容")
    jar: dict[str, str] = {}
    string_chunks: list[str] = []
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("X Cookie JSON 格式无效") from exc
        if isinstance(data, dict):
            for key, value in data.items():
                jar[str(key).strip()] = str(value or "")
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name"):
                    jar[str(item["name"]).strip()] = str(item.get("value") or "")
                elif isinstance(item, str):
                    string_chunks.append(item)
        else:
            raise ValueError("X Cookie JSON 格式无效")
    else:
        string_chunks.append(raw)
    for chunk in string_chunks:
        for part in chunk.replace("\n", ";").split(";"):
            name, sep, value = part.partition("=")
            if sep and name.strip():
                jar[name.strip()] = value.strip()
    auth_token = jar.get("auth_token") or ""
    ct0 = jar.get("ct0") or ""
    if not auth_token or not ct0:
        raise ValueError("Cookie 中缺少 auth_token 或 ct0，请导出登录 x.com 后的完整 Cookie")
    return {"auth_token": auth_token, "ct0": ct0}


_GRAPHQL_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": False,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_x_endpoint_cache: dict[str, str] = {}

_X_SCRIPT_RE = re.compile(r"(?:https://abs\.twimg\.com|/)[^\"'\s<>\\]+\.js(?![A-Za-z0-9])(?:\?[^\"'\s<>\\]*)?")
_X_IMPORT_RE = re.compile(r"[\"']([^\"']+\.js(?:\?[^\"']*)?)[\"']")
_X_BEARER_RE = re.compile(r"Bearer\s+((?:A{9,})[A-Za-z0-9%_-]{30,})|((?:A{9,})[A-Za-z0-9%_-]{30,})")


def _operation_query_id(script: str, operation_names: Iterable[str]) -> str | None:
    """Extract a Relay operation id from old or current X bundles.

    X has used both ``queryId: \"...\",operationName: \"...\"`` and
    compiled Relay artifacts such as ``params:{id:`...`,name:`...`}`.  Keep
    this parser deliberately local to the operation metadata instead of
    relying on a particular minifier's whitespace or quote style.
    """
    for operation_name in operation_names:
        escaped = re.escape(operation_name)
        patterns = (
            rf"queryId\s*[:=]\s*[\"']([A-Za-z0-9_-]+)[\"']\s*,\s*operationName\s*[:=]\s*[\"']{escaped}[\"']",
            rf"operationName\s*[:=]\s*[\"']{escaped}[\"']\s*,\s*queryId\s*[:=]\s*[\"']([A-Za-z0-9_-]+)[\"']",
            rf"params:\{{id:\s*`([A-Za-z0-9_-]+)`.{{0,600}}?name:`{escaped}`",
            rf"params:\{{id:\s*[\"']([A-Za-z0-9_-]+)[\"'].{{0,600}}?name:[\"']{escaped}[\"']",
        )
        for pattern in patterns:
            match = re.search(pattern, script)
            if match:
                return match.group(1)
    return None


def _x_script_urls(page_url: str, page_text: str) -> list[str]:
    """Return JavaScript URLs advertised by an X document."""
    from urllib.parse import urljoin

    urls: list[str] = []
    for match in _X_SCRIPT_RE.finditer(page_text):
        url = urljoin(page_url, match.group(0))
        if url.endswith(".js") or ".js?" in url:
            if url not in urls:
                urls.append(url)
    return urls


def _x_import_urls(base_url: str, script: str) -> list[str]:
    from urllib.parse import urljoin

    urls: list[str] = []
    for relative in _X_IMPORT_RE.findall(script):
        url = urljoin(base_url, relative)
        if url.startswith("https://abs.twimg.com/") and (url.endswith(".js") or ".js?" in url) and url not in urls:
            urls.append(url)
    return urls


def _graphql_headers(cookies: dict[str, str], bearer: str) -> dict[str, str]:
    return {
        "User-Agent": X_UA,
        "authorization": "Bearer " + bearer,
        "x-csrf-token": cookies["ct0"],
        "x-twitter-auth-type": "OAuth2Session",
    }


async def _resolve_x_endpoint(client: httpx.AsyncClient, cookies: dict[str, str] | None = None) -> dict[str, str]:
    """Discover GraphQL credentials and query ids from the live X bundles.

    Since X's migration to the Vite/Rolldown web app, the old single
    ``responsive-web/client-web/main.<hash>.js`` bundle is gone.  The page
    now advertises an entry module which imports many hashed chunks, and an
    authenticated page is needed to load the timeline operations.  Walk the
    advertised module graph (bounded for safety), accepting both legacy and
    Relay metadata formats.
    """
    if _x_endpoint_cache.get("bearer") and _x_endpoint_cache.get("user_by_screen_name"):
        return _x_endpoint_cache
    request_kwargs: dict[str, Any] = {}
    if cookies:
        request_kwargs["cookies"] = cookies
    page = await client.get(f"https://x.com/{TIBO_USERNAME}", **request_kwargs)
    page.raise_for_status()
    scripts = _x_script_urls(str(page.url), page.text)
    if not scripts:
        raise ConnectionError("无法在 X 页面中定位客户端脚本")

    queue = list(scripts)
    visited: set[str] = set()
    downloaded = 0
    while queue and downloaded < 120:
        script_url = queue.pop(0)
        if script_url in visited:
            continue
        visited.add(script_url)
        try:
            response = await client.get(script_url)
            response.raise_for_status()
        except httpx.HTTPError:
            logger.debug("Could not fetch X client chunk %s", script_url)
            continue
        downloaded += 1
        script = response.text
        bearer = _X_BEARER_RE.search(script)
        if bearer and not _x_endpoint_cache.get("bearer"):
            _x_endpoint_cache["bearer"] = bearer.group(1) or bearer.group(2)
        for operation_name in ("UserTweets", "UserTweetsAndReplies"):
            user_tweets = _operation_query_id(script, (operation_name,))
            if user_tweets and not _x_endpoint_cache.get("user_tweets"):
                _x_endpoint_cache["user_tweets"] = user_tweets
                _x_endpoint_cache["user_tweets_operation"] = operation_name
                break
        for operation_name in ("UserByScreenName", "UserByScreenNameQuery", "intentFollowUserByScreenNameQuery"):
            user_by_name = _operation_query_id(script, (operation_name,))
            if user_by_name and not _x_endpoint_cache.get("user_by_screen_name"):
                _x_endpoint_cache["user_by_screen_name"] = user_by_name
                _x_endpoint_cache["user_by_screen_name_operation"] = operation_name
                break
        if _x_endpoint_cache.get("bearer") and _x_endpoint_cache.get("user_by_screen_name") and _x_endpoint_cache.get("user_tweets"):
            break
        queue.extend(url for url in _x_import_urls(script_url, script) if url not in visited and url not in queue)

    if not (_x_endpoint_cache.get("bearer") and _x_endpoint_cache.get("user_by_screen_name")):
        raise ConnectionError("无法解析 X 用户查询接口")
    return _x_endpoint_cache


async def _x_user_id(client: httpx.AsyncClient, cookies: dict[str, str]) -> str:
    """Resolve (and cache) Tibo's numeric user id with an authenticated call."""
    if _x_endpoint_cache.get("user_id"):
        return _x_endpoint_cache["user_id"]
    endpoint = await _resolve_x_endpoint(client, cookies)
    query_id = endpoint.get("user_by_screen_name")
    if not query_id:
        raise ConnectionError("无法解析 X 用户查询接口")
    operation_name = endpoint.get("user_by_screen_name_operation") or "UserByScreenName"
    response = await client.get(
        f"https://x.com/i/api/graphql/{query_id}/{operation_name}",
        params={
            "variables": json.dumps({"screenName": TIBO_USERNAME, "screen_name": TIBO_USERNAME}),
            "features": json.dumps(_GRAPHQL_FEATURES),
        },
        headers=_graphql_headers(cookies, endpoint["bearer"]),
        cookies=cookies,
    )
    _raise_for_x_auth(response)
    if response.status_code != 200:
        raise ConnectionError(f"X 用户查询失败（{response.status_code}）")
    payload = response.json()
    result = ((payload.get("data") or {}).get("user") or {}).get("result") or {}
    if not result:
        result = ((payload.get("data") or {}).get("user_result_by_screen_name") or {}).get("result") or {}
    user_id = str(result.get("rest_id") or "")
    if not user_id.isdigit():
        raise ConnectionError("X 用户查询返回异常")
    _x_endpoint_cache["user_id"] = user_id
    return user_id



def _raise_for_x_auth(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise XAuthError("X Cookie 无效或已过期")


def _parse_graphql_tweets(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Flatten a UserTweets GraphQL response into tweet dicts plus the cursor."""
    tweets: list[dict[str, Any]] = []
    cursor: str | None = None
    timeline = ((data.get("data") or {}).get("user") or {}).get("result", {}).get("timeline", {}).get("timeline", {})
    for instruction in timeline.get("instructions") or []:
        for entry in instruction.get("entries") or []:
            content = entry.get("content") or {}
            if content.get("entryType") == "TimelineTimelineCursor":
                if content.get("cursorType") == "Bottom":
                    cursor = (content.get("content") or {}).get("value") or content.get("value")
                continue
            tweet = (content.get("itemContent") or {}).get("tweet_results", {}).get("result") or {}
            if tweet.get("__typename") == "TweetWithVisibilityResults":
                tweet = tweet.get("tweet") or {}
            if tweet.get("__typename") != "Tweet":
                continue
            legacy = tweet.get("legacy") or {}
            user = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
            tweets.append(
                {
                    "id": str(legacy.get("id_str") or tweet.get("rest_id") or ""),
                    "created_at": str(legacy.get("created_at") or ""),
                    "text": str(legacy.get("full_text") or ""),
                    "screen": str((user.get("legacy") or {}).get("screen_name") or "").casefold(),
                }
            )
    return tweets, cursor


def _build_fetch_result(by_id: dict[str, TiboPost], now: datetime, lookback_hours: int) -> FetchResult:
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


async def _scan_threads(
    client: httpx.AsyncClient, posts: Iterable[TiboPost]
) -> dict[str, TiboPost]:
    """Fetch each conversation page and merge Tibo's self-replies by tweet ID."""

    async def fetch_thread(post: TiboPost) -> tuple[TiboPost, ...]:
        try:
            thread_response = await client.get(post.url)
            thread_response.raise_for_status()
            return parse_profile_html(thread_response.text)
        except Exception:
            logger.warning("Could not fetch Tibo thread %s", post.id, exc_info=True)
            return ()

    top = sorted(posts, key=lambda item: int(item.id), reverse=True)[:8]
    thread_results = await asyncio.gather(*(fetch_thread(post) for post in top))
    merged: dict[str, TiboPost] = {}
    for thread_posts in thread_results:
        for post in thread_posts:
            merged[post.id] = post
    return merged


async def fetch_recent_tibo_posts(
    seen_ids: FrozenSet[str],
    now: datetime,
    lookback_hours: int = TIBO_LOOKBACK_HOURS,
) -> FetchResult:
    """Fetch Tibo's recent posts and self-replies from public X HTML.

    The anonymous profile HTML only exposes a handful of recent top-level
    posts. Reset timing is sometimes published as a self-reply, so recent
    conversation pages are also scanned and merged by tweet ID.
    """
    del seen_ids  # State filtering happens after all profile/thread posts merge.
    proxy = TIBO_PROXY_URL or None
    headers = {
        "User-Agent": X_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, timeout=30, headers=headers) as client:
        response = await client.get(f"https://x.com/{TIBO_USERNAME}")
        response.raise_for_status()
        profile_posts = parse_profile_html(response.text)
        thread_posts = await _scan_threads(client, profile_posts)

    by_id = {post.id: post for post in profile_posts}
    by_id.update(thread_posts)
    return _build_fetch_result(by_id, now, lookback_hours)


async def fetch_tibo_posts_authenticated(
    cookies: dict[str, str],
    now: datetime,
    lookback_hours: int = TIBO_LOOKBACK_HOURS,
) -> FetchResult:
    """Full-timeline fetch using a user-imported X login cookie.

    Unlike the anonymous HTML page, the GraphQL UserTweets endpoint paginates
    the whole week, so posts can no longer scroll out of view between checks.
    """
    proxy = TIBO_PROXY_URL or None
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, timeout=30, headers={"User-Agent": X_UA}) as client:
        user_id = await _x_user_id(client, cookies)
        endpoint = await _resolve_x_endpoint(client, cookies)
        if not endpoint.get("user_tweets"):
            raise ConnectionError("无法解析 X 推文查询接口")
        headers = _graphql_headers(cookies, endpoint["bearer"])
        cutoff = now.astimezone(timezone.utc) - timedelta(hours=lookback_hours)
        by_id: dict[str, TiboPost] = {}
        cursor: str | None = None
        for _page in range(GRAPHQL_MAX_PAGES):
            variables: dict[str, Any] = {
                "userId": user_id,
                "count": 20,
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
            }
            if cursor:
                variables["cursor"] = cursor
            response = await client.get(
                f"https://x.com/i/api/graphql/{endpoint['user_tweets']}/{endpoint.get('user_tweets_operation') or 'UserTweets'}",
                params={"variables": json.dumps(variables), "features": json.dumps(_GRAPHQL_FEATURES)},
                headers=headers,
                cookies=cookies,
            )
            _raise_for_x_auth(response)
            response.raise_for_status()
            tweets, cursor = _parse_graphql_tweets(response.json())
            oldest: datetime | None = None
            for tweet in tweets:
                if not tweet["id"].isdigit() or tweet["screen"] != TIBO_USERNAME.casefold():
                    continue
                try:
                    created_at = datetime.strptime(tweet["created_at"], "%a %b %d %H:%M:%S %z %Y")
                except ValueError:
                    created_at = snowflake_created_at(tweet["id"])
                by_id[tweet["id"]] = TiboPost(
                    tweet["id"],
                    created_at.astimezone(timezone.utc),
                    tweet["text"].strip(),
                    f"https://x.com/{TIBO_USERNAME}/status/{tweet['id']}",
                )
                if oldest is None or created_at < oldest:
                    oldest = created_at
            if not cursor or not tweets or (oldest is not None and oldest.astimezone(timezone.utc) < cutoff):
                break
        thread_posts = await _scan_threads(client, by_id.values())
    by_id.update(thread_posts)
    return _build_fetch_result(by_id, now, lookback_hours)


async def verify_x_cookies(cookies: dict[str, str]) -> None:
    """Validate imported X cookies with a lightweight authenticated call."""
    proxy = TIBO_PROXY_URL or None
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, timeout=30, headers={"User-Agent": X_UA}) as client:
        await _x_user_id(client, cookies)


def iter_x_cookie_users() -> list[dict[str, Any]]:
    """Users whose own X cookie can power the monitoring fetch."""
    result = []
    for user in iter_users():
        if not bool(user.get("tibo", {}).get("enabled", False)):
            continue
        if not user.get("tibo", {}).get("x_cookies_encrypted"):
            continue
        result.append(user)
    return result


def get_user_x_cookies(user: dict[str, Any]) -> dict[str, str]:
    try:
        return get_tibo_x_cookies(user.get("tibo") or {})
    except ValueError:
        logger.warning("Stored X cookies for user %s cannot be decrypted", user.get("id"))
        return {}


def notify_x_cookie_expired(user: dict[str, Any], now: datetime) -> None:
    """Remind the cookie owner at most once per day to re-import."""
    tibo_cfg = user.setdefault("tibo", {})
    today = now.astimezone(TZ_BEIJING).date().isoformat()
    if tibo_cfg.get("x_auth_notified_date") == today:
        return
    tibo_cfg["x_auth_notified_date"] = today
    push_notification(
        user,
        "Tibo 监测",
        "你导入的 X Cookie 已失效，请重新导出登录 x.com 后的 Cookie，否则只能匿名监测最近几条推特。",
        "tibo",
        source_id="tibo:x-cookie-expired",
    )



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


STALL_ALERT_CHECKS = 6  # ~6 hourly checks discovering nothing means parsing broke


def _notify_monitor_stall(streak: int, last_checked: str) -> None:
    """Alert the admin account when X page changes silently break parsing."""
    for user in iter_users():
        if str(user.get("username") or "").casefold() != "muzermat":
            continue
        push_notification(
            user,
            "Tibo 监测异常",
            f"Tibo 监测已连续 {streak} 次检查未解析到任何帖子，页面结构可能已变化，请检查服务器。上次检查：{last_checked or '未知'}",
            "tibo",
            source_id="tibo:monitor-stalled",
        )


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
    result = await fetcher(seen, current, TIBO_LOOKBACK_HOURS)
    matched = tuple(post for post in result.posts if is_reset_post(post.text))
    new_matched = tuple(post for post in matched if post.id not in seen)

    # Canary: the profile page always lists several posts, so a successful
    # fetch that parses to zero posts means X changed its HTML again.
    streak = int(state.get("empty_check_streak") or 0)
    stall_alerted = bool(state.get("stall_alerted"))
    if result.discovered_ids:
        streak = 0
        stall_alerted = False
    else:
        streak += 1
        if streak >= STALL_ALERT_CHECKS and not stall_alerted:
            logger.warning("Tibo monitor parsed 0 posts for %d consecutive checks", streak)
            _notify_monitor_stall(streak, str(state.get("last_checked") or ""))
            stall_alerted = True

    # The first successful check establishes a baseline instead of sending an
    # old backlog to every MuzTool account.
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
            "empty_check_streak": streak,
            "stall_alerted": stall_alerted,
        },
        state_path,
    )
    return CheckReport(
        initialized=not was_initialized,
        discovered=len(result.discovered_ids),
        matched=len(new_matched),
        notified_users=notified,
    )
