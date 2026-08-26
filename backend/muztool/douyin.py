from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Any

from .store import get_douyin_cookies, now_iso, set_douyin_cookies

CHAT_URL = "https://www.douyin.com/chat"
SEARCH_INPUT_SELECTOR = 'input.semi-input[placeholder="搜索"]'
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CONVERSATION_ITEM_SELECTOR = '[data-e2e="conversation-item"]'
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_ACTIVE_SELECTOR = ".conversationConversationItemcurConversation"
CHAT_EDITOR_SELECTOR = (
    '.messageEditorimChatEditorContainer '
    '[data-slate-editor="true"][contenteditable="true"]'
)

MAX_COOKIE_COUNT = 200
MAX_COOKIE_NAME_LENGTH = 256
MAX_COOKIE_VALUE_LENGTH = 8192
MAX_SPARK_TARGETS = 10
SPARK_SEND_INTERVAL_MS = 10_000
MAX_TARGET_NAME_LENGTH = 80
MAX_MESSAGE_LENGTH = 200


class DouyinAutomationError(ValueError):
    code = "automation_error"
    retryable = False


class DouyinSessionExpired(DouyinAutomationError):
    code = "session_expired"


class DouyinSecurityChallenge(DouyinAutomationError):
    code = "security_challenge"


class DouyinStructureChanged(DouyinAutomationError):
    code = "structure_changed"


class DouyinAmbiguousSend(DouyinAutomationError):
    code = "ambiguous_send"


class DouyinTargetInvalid(DouyinAutomationError):
    code = "target_invalid"


class DouyinBusy(DouyinAutomationError):
    code = "busy"
    retryable = True


class DouyinTransientError(DouyinAutomationError):
    code = "transient"
    retryable = True


_EXECUTION_LOCKS: dict[str, threading.Lock] = {}
_EXECUTION_LOCKS_GUARD = threading.Lock()


@contextmanager
def _execution_guard(user_id: str):
    key = str(user_id or "unknown")
    with _EXECUTION_LOCKS_GUARD:
        lock = _EXECUTION_LOCKS.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        raise DouyinBusy("续火花任务正在执行，请勿重复触发")
    try:
        yield
    finally:
        lock.release()


def target_identity(target: dict[str, Any]) -> str:
    normalized = normalize_target(target)
    return f"id:{normalized['conversation_id']}" if normalized["conversation_id"] else f"{normalized['conversation_type'] or 'unknown'}:{normalized['name']}"


def _detect_page_block(page: Any) -> DouyinAutomationError | None:
    try:
        url = str(page.url or "").casefold()
    except Exception:
        url = ""
    try:
        text = page.locator("body").inner_text(timeout=2_000)[:6000]
    except Exception:
        text = ""
    lowered = text.casefold()
    security_markers = ("安全验证", "验证身份", "扫码验证", "请输入验证码", "captcha", "异常访问")
    if any(marker.casefold() in lowered for marker in security_markers) or any(marker in url for marker in ("captcha", "verify", "security")):
        return DouyinSecurityChallenge("抖音要求安全验证，已停止自动任务，请在网页端人工完成验证后重新绑定 Cookie")
    login_markers = ("登录后即可", "手机号登录", "扫码登录", "密码登录")
    if any(marker in text for marker in login_markers) or any(marker in url for marker in ("passport", "login")):
        return DouyinSessionExpired("抖音登录状态已失效，请重新导入 Cookie")
    return None


def normalize_cookies(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") or text.startswith("["):
            raw = json.loads(text)
        else:
            raw = []
            for part in text.split(";"):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name, value = name.strip(), value.strip()
                if name:
                    raw.append({"name": name, "value": value, "domain": ".douyin.com", "path": "/"})
    if isinstance(raw, dict):
        if "cookies" in raw:
            raw = raw["cookies"]
        else:
            raw = [{"name": key, "value": value, "domain": ".douyin.com", "path": "/"} for key, value in raw.items()]
    if not isinstance(raw, list) or not raw:
        raise ValueError("请提供有效的抖音 Cookie JSON")
    if len(raw) > MAX_COOKIE_COUNT:
        raise ValueError("Cookie 数量过多")
    cookies = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name") or item.get("value") is None:
            continue
        domain = str(item.get("domain") or ".douyin.com").strip()
        if domain == "douyin.com" or domain.endswith(".douyin.com"):
            domain = ".douyin.com"
        else:
            # Cookie exports can include unrelated domains. Do not retain or
            # inject them into the automation browser context.
            continue
        name = str(item["name"])
        value = str(item["value"])
        if len(name) > MAX_COOKIE_NAME_LENGTH or len(value) > MAX_COOKIE_VALUE_LENGTH:
            raise ValueError("Cookie 字段过长")
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": item.get("path") or "/",
            }
        )
    if not cookies:
        raise ValueError("Cookie 列表为空")
    return cookies


def _open_chat(browser: Any, cookies: list[dict[str, Any]]) -> tuple[Any, Any, Any]:
    context = browser.new_context(locale="zh-CN")
    context.add_cookies(cookies)
    page = context.new_page()
    try:
        page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        context.close()
        raise DouyinTransientError("暂时无法连接抖音聊天页面，请稍后重试") from exc
    search_input = page.locator(SEARCH_INPUT_SELECTOR).first
    try:
        search_input.wait_for(state="visible", timeout=30_000)
    except Exception as exc:
        blocked = _detect_page_block(page)
        context.close()
        if blocked:
            raise blocked from exc
        raise DouyinStructureChanged(
            "抖音聊天页面结构发生变化，已停止自动操作，请等待工具更新"
        ) from exc
    try:
        page.locator('[class*="conversation"], [class*="Conversation"]').first.wait_for(
            state="visible", timeout=12_000
        )
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    return context, page, search_input


def validate_douyin_cookies(cookies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Validate imported cookies against Douyin's chat page before persisting them."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，暂时无法校验抖音 Cookie") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = None
        try:
            context, page, _search_input = _open_chat(browser, cookies)
            refreshed = normalize_cookies(context.cookies())
            title = page.title().replace("抖音", "").replace("-", "").strip()
            return refreshed, title[:32]
        finally:
            if context:
                context.close()
            browser.close()


def _conversation_metadata(item: Any) -> dict[str, str]:
    """Read the stable IM conversation identity from Douyin's React row props.

    The visible DOM does not expose a conversation id. Douyin keeps the IM
    conversation model on the row's React props, where type=1 is a direct chat
    and type=2 is a group chat. Return an empty identity if the internal model
    changes instead of guessing a group from its avatar shape.
    """
    try:
        raw = item.evaluate(
            """el => {
              const roots = Object.getOwnPropertyNames(el)
                .filter(key => key.startsWith('__react'))
                .map(key => el[key]);
              const visited = new WeakSet();
              let conversation = null;
              function walk(value, depth) {
                if (conversation || !value || depth > 8) return;
                if (typeof value !== 'object' && typeof value !== 'function') return;
                if (visited.has(value)) return;
                visited.add(value);
                let keys = [];
                try { keys = Reflect.ownKeys(value); } catch (_) { return; }
                for (const key of keys) {
                  let child;
                  try { child = value[key]; } catch (_) { continue; }
                  if (key === 'conversation' && child && typeof child === 'object') {
                    conversation = child;
                    return;
                  }
                  if (typeof child === 'object' || typeof child === 'function') {
                    walk(child, depth + 1);
                  }
                  if (conversation) return;
                }
              }
              roots.forEach(root => walk(root, 0));
              if (!conversation) return {};
              let id = '', shortId = '', type = 0;
              try { id = String(conversation.id || ''); } catch (_) {}
              try { shortId = String(conversation.shortId || ''); } catch (_) {}
              try { type = Number(conversation.type || 0); } catch (_) {}
              return {id, shortId, type};
            }"""
        ) or {}
    except Exception:
        raw = {}
    raw_type = int(raw.get("type") or 0)
    conversation_type = "group" if raw_type == 2 else ("direct" if raw_type == 1 else "")
    return {
        "conversation_id": str(raw.get("id") or raw.get("shortId") or ""),
        "conversation_short_id": str(raw.get("shortId") or ""),
        "conversation_type": conversation_type,
    }


def _conversation_friend(item: Any) -> dict[str, str] | None:
    try:
        name = item.locator(CONVERSATION_TITLE_SELECTOR).first.inner_text().strip()
    except Exception:
        name = ""
    if not name:
        return None
    avatar = ""
    try:
        avatar = str(item.locator("img").first.get_attribute("src") or "")
    except Exception:
        pass
    return {"name": name, "avatar_url": avatar, **_conversation_metadata(item)}


def _conversation_key(conversation: dict[str, Any]) -> str:
    conversation_id = str(conversation.get("conversation_id") or "").strip()
    if conversation_id:
        return f"id:{conversation_id}"
    return f"{str(conversation.get('conversation_type') or 'unknown')}:{str(conversation.get('name') or '').strip()}"


def _scroll_conversation_panel(panel: Any) -> dict[str, Any]:
    return panel.evaluate(
        """el => {
          const before = el.scrollTop;
          const max = Math.max(0, el.scrollHeight - el.clientHeight);
          const step = Math.max(260, Math.floor(el.clientHeight * 0.8));
          el.scrollTop = Math.min(max, before + step);
          el.dispatchEvent(new Event('scroll', {bubbles: true}));
          return {before, after: el.scrollTop, max};
        }"""
    )


def _rewind_conversation_panel(panel: Any) -> None:
    panel.evaluate("el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll', {bubbles: true})); }")


def list_douyin_friends(cookies: list[dict[str, Any]], limit: int = 200) -> list[dict[str, str]]:
    """Read direct and group conversations with their stable IM identities."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，暂时无法读取抖音好友列表") from exc

    safe_limit = max(1, min(int(limit or 200), 500))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = None
        try:
            context, page, _search_input = _open_chat(browser, cookies)
            conversation_list = page.locator(CONVERSATION_LIST_SELECTOR).first
            try:
                conversation_list.wait_for(state="visible", timeout=12_000)
            except Exception:
                return []

            friends: list[dict[str, str]] = []
            seen: set[str] = set()
            unchanged_rounds = 0
            previous_scroll_top = -1
            _rewind_conversation_panel(conversation_list)
            page.wait_for_timeout(250)

            for _round in range(80):
                before_count = len(friends)
                items = conversation_list.locator(CONVERSATION_ITEM_SELECTOR)
                for item in items.all():
                    friend = _conversation_friend(item)
                    if not friend:
                        continue
                    key = _conversation_key(friend)
                    if key in seen:
                        continue
                    seen.add(key)
                    friends.append(friend)
                    if len(friends) >= safe_limit:
                        return friends

                scroll_state = _scroll_conversation_panel(conversation_list)
                current_scroll_top = int(scroll_state.get("after") or 0)
                at_end = current_scroll_top >= int(scroll_state.get("max") or 0)
                moved = current_scroll_top != int(scroll_state.get("before") or 0)
                found_new = len(friends) > before_count

                if found_new or current_scroll_top != previous_scroll_top:
                    unchanged_rounds = 0
                else:
                    unchanged_rounds += 1
                previous_scroll_top = current_scroll_top

                if at_end and not moved:
                    unchanged_rounds += 1
                if unchanged_rounds >= 2:
                    break
                page.wait_for_timeout(450)

            return friends
        finally:
            if context:
                context.close()
            browser.close()

def search_douyin_friends(cookies: list[dict[str, Any]], query: str = "", limit: int = 200) -> list[dict[str, str]]:
    """Compatibility wrapper: crawl the list first, then optionally filter it."""
    friends = list_douyin_friends(cookies, limit=limit)
    needle = query.strip().casefold()
    if not needle:
        return friends
    return [friend for friend in friends if needle in friend["name"].casefold()]


def normalize_target(item: dict[str, Any]) -> dict[str, str]:
    name = str(item.get("name") or "").strip()
    message = str(item.get("message") or "").strip()
    raw_mode = str(item.get("mode") or "").strip().lower()
    mode = raw_mode if raw_mode in {"standard", "custom"} else ("custom" if message else "standard")
    raw_type = str(item.get("conversation_type") or "").strip().lower()
    conversation_type = raw_type if raw_type in {"direct", "group"} else ""
    conversation_id = str(item.get("conversation_id") or "").strip()
    conversation_short_id = str(item.get("conversation_short_id") or "").strip()
    if len(name) > MAX_TARGET_NAME_LENGTH:
        raise ValueError("会话名称过长")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"发送内容不能超过 {MAX_MESSAGE_LENGTH} 个字符")
    if len(conversation_id) > 256 or len(conversation_short_id) > 256:
        raise ValueError("会话标识过长")
    return {
        "name": name,
        "mode": mode,
        "message": message if mode == "custom" else "",
        "conversation_id": conversation_id,
        "conversation_short_id": conversation_short_id,
        "conversation_type": conversation_type,
    }


def validate_spark_targets(raw_targets: list[dict[str, Any]], *, require_identity: bool = True) -> list[dict[str, str]]:
    if len(raw_targets) > MAX_SPARK_TARGETS:
        raise ValueError(f"续火花目标不能超过 {MAX_SPARK_TARGETS} 个")
    targets = [normalize_target(item) for item in raw_targets if isinstance(item, dict) and item.get("name")]
    if not targets:
        raise ValueError("请至少配置一个续火花对象")
    seen: set[str] = set()
    for target in targets:
        if require_identity and (not target["conversation_id"] or target["conversation_type"] not in {"direct", "group"}):
            raise DouyinTargetInvalid(f"会话“{target['name']}”缺少稳定标识，请刷新好友列表后重新添加")
        key = target_identity(target)
        if key in seen:
            raise ValueError("续火花列表中存在重复会话")
        seen.add(key)
    return targets


def message_for(target: dict[str, Any], default_message: str) -> str:
    normalized = normalize_target(target)
    text = normalized["message"] if normalized["mode"] == "custom" and normalized["message"] else (default_message or "续火花")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"发送内容不能超过 {MAX_MESSAGE_LENGTH} 个字符")
    return text


def _target_matches(target: dict[str, Any], conversation: dict[str, Any]) -> bool:
    normalized = normalize_target(target)
    if not normalized["conversation_id"] or normalized["conversation_type"] not in {"direct", "group"}:
        return False
    conversation_id = str(conversation.get("conversation_id") or "").strip()
    return (
        conversation_id == normalized["conversation_id"]
        and str(conversation.get("conversation_type") or "") == normalized["conversation_type"]
    )


def _find_conversation_in_list(page: Any, target: dict[str, Any]) -> tuple[Any | None, dict[str, str] | None]:
    panel = page.locator(CONVERSATION_LIST_SELECTOR).first
    try:
        panel.wait_for(state="visible", timeout=10_000)
    except Exception:
        return None, None
    _rewind_conversation_panel(panel)
    page.wait_for_timeout(250)
    previous_scroll_top = -1
    unchanged_rounds = 0
    for _round in range(80):
        for item in panel.locator(CONVERSATION_ITEM_SELECTOR).all():
            conversation = _conversation_friend(item)
            if not conversation or not _target_matches(target, conversation):
                continue
            return item, conversation
        scroll_state = _scroll_conversation_panel(panel)
        current_scroll_top = int(scroll_state.get("after") or 0)
        moved = current_scroll_top != int(scroll_state.get("before") or 0)
        if current_scroll_top != previous_scroll_top:
            unchanged_rounds = 0
        else:
            unchanged_rounds += 1
        previous_scroll_top = current_scroll_top
        if current_scroll_top >= int(scroll_state.get("max") or 0) and not moved:
            unchanged_rounds += 1
        if unchanged_rounds >= 2:
            break
        page.wait_for_timeout(350)

    return None, None


def _verify_active_conversation(page: Any, target: dict[str, Any]) -> dict[str, str]:
    active = page.locator(CONVERSATION_ACTIVE_SELECTOR).first
    try:
        active.wait_for(state="visible", timeout=8_000)
        conversation = _conversation_friend(active)
    except Exception as exc:
        blocked = _detect_page_block(page)
        if blocked:
            raise blocked from exc
        raise DouyinAmbiguousSend("无法确认当前活动会话，已停止发送") from exc
    if not conversation or conversation.get("name") != target.get("name"):
        raise DouyinAmbiguousSend("当前活动会话与目标不一致，已停止发送")
    active_id = str(conversation.get("conversation_id") or "")
    active_type = str(conversation.get("conversation_type") or "")
    if not active_id or active_type not in {"direct", "group"}:
        raise DouyinStructureChanged("无法读取当前活动会话的稳定标识，已停止发送")
    if active_id != target.get("conversation_id"):
        raise DouyinAmbiguousSend("当前活动会话标识与目标不一致，已停止发送")
    if active_type != target.get("conversation_type"):
        raise DouyinAmbiguousSend("当前活动会话类型与目标不一致，已停止发送")
    return conversation


def _open_target_conversation(page: Any, target: dict[str, Any]) -> tuple[Any, dict[str, str]]:
    if not target.get("conversation_id") or target.get("conversation_type") not in {"direct", "group"}:
        raise DouyinTargetInvalid("目标缺少稳定会话标识，请刷新好友列表后重新添加")
    item, conversation = _find_conversation_in_list(page, target)
    if item is None or conversation is None:
        raise DouyinTargetInvalid(f"未在聊天列表中找到会话“{target.get('name', '')}”，请刷新好友列表后重新添加")
    try:
        item.click(timeout=5_000)
    except Exception as exc:
        raise DouyinTransientError("暂时无法打开目标会话") from exc
    active = _verify_active_conversation(page, target)
    editor = page.locator(CHAT_EDITOR_SELECTOR).first
    try:
        editor.wait_for(state="visible", timeout=10_000)
    except Exception as exc:
        blocked = _detect_page_block(page)
        if blocked:
            raise blocked from exc
        raise DouyinStructureChanged("消息编辑器不可用，抖音页面结构可能已经变化") from exc
    return editor, {**conversation, **{k: v for k, v in active.items() if v}}


def _send_and_confirm(page: Any, editor: Any, text: str) -> None:
    exact = page.get_by_text(text, exact=True)
    before_count = exact.count()
    editor.click()
    page.keyboard.insert_text(text)
    page.keyboard.press("Enter")
    for _ in range(20):
        page.wait_for_timeout(250)
        remaining = "".join(editor.inner_text().split()).replace("\u200b", "")
        if not remaining:
            break
    else:
        raise DouyinAmbiguousSend("发送键未确认生效，消息仍停留在输入框")
    for _ in range(32):
        page.wait_for_timeout(250)
        if exact.count() > before_count:
            return
    blocked = _detect_page_block(page)
    if blocked:
        raise blocked
    raise DouyinAmbiguousSend("无法确认消息已经出现在聊天记录中，为避免重复发送已停止自动重试")


def _merge_discovered_target(cfg: dict[str, Any], original: dict[str, Any], discovered: dict[str, Any]) -> None:
    if not discovered.get("conversation_id"):
        return
    for index, raw in enumerate(cfg.get("targets") or []):
        if not isinstance(raw, dict):
            continue
        normalized = normalize_target(raw)
        same = normalized["conversation_id"] == original.get("conversation_id") if original.get("conversation_id") else (
            normalized["name"] == original.get("name")
        )
        if same:
            cfg["targets"][index] = {
                **normalized,
                "conversation_id": str(discovered.get("conversation_id") or ""),
                "conversation_short_id": str(discovered.get("conversation_short_id") or ""),
                "conversation_type": str(discovered.get("conversation_type") or ""),
            }
            return


def _result_from_error(target: dict[str, Any], exc: Exception) -> dict[str, Any]:
    if isinstance(exc, DouyinAutomationError):
        code = exc.code
        retryable = exc.retryable
    else:
        code = "unexpected"
        retryable = False
        exc = ValueError("自动任务出现未分类错误，已停止重试")
    return {
        "target": target.get("name", ""),
        "target_key": target_identity(target),
        "target_type": target.get("conversation_type") or "",
        "message": "",
        "ok": False,
        "status": code,
        "retryable": retryable,
        "error": str(exc),
    }


def _record_target_status(cfg: dict[str, Any], item: dict[str, Any], attempted_at: str) -> None:
    statuses = cfg.setdefault("target_status", {})
    key = str(item.get("target_key") or "")
    previous = statuses.get(key) if isinstance(statuses.get(key), dict) else {}
    record = {
        "name": str(item.get("target") or ""),
        "status": str(item.get("status") or ("success" if item.get("ok") else "failed")),
        "error": str(item.get("error") or "")[:500],
        "last_attempt": attempted_at,
        "last_success": previous.get("last_success", ""),
    }
    if item.get("ok"):
        record["last_success"] = attempted_at
    statuses[key] = record


def run_spark(
    user: dict[str, Any],
    *,
    targets_override: list[dict[str, Any]] | None = None,
    group_only: bool = False,
    record_run: bool = True,
) -> dict[str, Any]:
    cfg = user.setdefault("douyin", {})
    cookies = get_douyin_cookies(cfg)
    source_targets = targets_override if targets_override is not None else (cfg.get("targets") or [])
    targets = validate_spark_targets([item for item in source_targets if isinstance(item, dict)], require_identity=True)
    if not cookies:
        raise DouyinSessionExpired("尚未登录抖音账号")
    if group_only:
        if len(targets) != 1:
            raise ValueError("安全保护已中止：群聊测试必须且只能包含一个目标")
        if targets[0].get("conversation_type") != "group":
            raise ValueError("安全保护已中止：目标必须是明确的群聊")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，无法执行续火花") from exc

    default_message = str(cfg.get("default_message") or "续火花").strip()
    if len(default_message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"默认文案不能超过 {MAX_MESSAGE_LENGTH} 个字符")
    results: list[dict[str, Any]] = []
    attempted_at = now_iso()
    halt_reason = ""
    refreshed_cookies: list[dict[str, Any]] | None = None

    with _execution_guard(str(user.get("id") or user.get("username") or "unknown")):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = None
            try:
                context, page, _search_input = _open_chat(browser, cookies)
                for index, target in enumerate(targets):
                    try:
                        editor, discovered = _open_target_conversation(page, target)
                        _merge_discovered_target(cfg, target, discovered)
                        text = message_for(target, default_message)
                        _send_and_confirm(page, editor, text)
                        item = {
                            "target": target["name"],
                            "target_key": target_identity(target),
                            "target_type": discovered.get("conversation_type") or target.get("conversation_type") or "",
                            "message": text,
                            "ok": True,
                            "status": "success",
                            "retryable": False,
                            "error": "",
                        }
                    except Exception as exc:
                        item = _result_from_error(target, exc)
                        if not item["retryable"]:
                            halt_reason = item["status"]
                    results.append(item)
                    _record_target_status(cfg, item, attempted_at)
                    if halt_reason in {"security_challenge", "session_expired", "structure_changed", "ambiguous_send"}:
                        break
                    if index + 1 < len(targets):
                        # Send configured targets strictly in list order and
                        # leave a fixed ten-second interval between targets.
                        page.wait_for_timeout(SPARK_SEND_INTERVAL_MS)
            except Exception as exc:
                if isinstance(exc, DouyinAutomationError):
                    halt_reason = exc.code
                    results.append({
                        "target": "", "target_key": "", "target_type": "", "message": "",
                        "ok": False, "status": exc.code, "retryable": exc.retryable, "error": str(exc),
                    })
                else:
                    halt_reason = "unexpected"
                    results.append({
                        "target": "", "target_key": "", "target_type": "", "message": "",
                        "ok": False, "status": "unexpected", "retryable": False, "error": "自动任务出现未分类错误，已停止重试",
                    })
            finally:
                if context:
                    try:
                        refreshed_cookies = normalize_cookies(context.cookies())
                    except Exception:
                        refreshed_cookies = None
                    context.close()
                browser.close()

    if refreshed_cookies:
        set_douyin_cookies(cfg, refreshed_cookies)
    if record_run:
        cfg["last_run"] = attempted_at
    succeeded = sum(1 for item in results if item.get("ok"))
    failed = sum(1 for item in results if not item.get("ok"))
    ambiguous = sum(1 for item in results if item.get("status") in {"ambiguous_send", "unexpected"})
    cfg["last_result"] = {
        "attempted_at": attempted_at,
        "success_count": succeeded,
        "failure_count": failed,
        "ambiguous_count": ambiguous,
        "halt_reason": halt_reason,
        "items": [
            {k: item.get(k) for k in ("target", "target_key", "target_type", "ok", "status", "retryable", "error")}
            for item in results
        ],
    }
    success = bool(results) and succeeded == len(targets) and failed == 0
    failed_results = [item for item in results if not item.get("ok")]
    return {
        "success": success,
        "results": results,
        "halt_reason": halt_reason,
        "retryable": bool(failed_results) and not halt_reason and all(item.get("retryable") for item in failed_results),
    }
