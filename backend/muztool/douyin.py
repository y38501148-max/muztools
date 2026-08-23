from __future__ import annotations

import json
from typing import Any

from .store import now_iso

CHAT_URL = "https://www.douyin.com/chat"
SEARCH_INPUT_SELECTOR = 'input.semi-input[placeholder="搜索"]'
SEARCH_RESULT_SELECTOR = ".SearchPanelitembox"
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CONVERSATION_ITEM_SELECTOR = '[data-e2e="conversation-item"]'
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_ACTIVE_SELECTOR = ".conversationConversationItemcurConversation"
CHAT_EDITOR_SELECTOR = (
    '.messageEditorimChatEditorContainer '
    '[data-slate-editor="true"][contenteditable="true"]'
)


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
    cookies = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name") or item.get("value") is None:
            continue
        domain = str(item.get("domain") or ".douyin.com").strip()
        if domain == "douyin.com" or domain.endswith(".douyin.com"):
            domain = ".douyin.com"
        cookies.append(
            {
                "name": str(item["name"]),
                "value": str(item["value"]),
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
    page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45_000)
    search_input = page.locator(SEARCH_INPUT_SELECTOR).first
    try:
        search_input.wait_for(state="visible", timeout=30_000)
    except Exception as exc:
        context.close()
        raise ValueError(
            "Cookie 校验失败：抖音聊天页面未进入登录状态，请重新导出最新的完整 Cookie JSON"
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


def _result_name(item: Any) -> str:
    try:
        lines = [line.strip() for line in item.inner_text().splitlines() if line.strip()]
    except Exception:
        return ""
    ignored = {"发消息", "发私信", "关注", "已关注", "用户", "好友"}
    return next((line for line in lines if line not in ignored and not line.startswith("抖音号：")), "")


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
    return {
        "name": name,
        "mode": mode,
        "message": message if mode == "custom" else "",
        "conversation_id": str(item.get("conversation_id") or "").strip(),
        "conversation_short_id": str(item.get("conversation_short_id") or "").strip(),
        "conversation_type": conversation_type,
    }


def message_for(target: dict[str, Any], default_message: str) -> str:
    normalized = normalize_target(target)
    if normalized["mode"] == "custom" and normalized["message"]:
        return normalized["message"]
    return default_message or "续火花"


def _target_matches(target: dict[str, Any], conversation: dict[str, Any]) -> bool:
    normalized = normalize_target(target)
    conversation_id = str(conversation.get("conversation_id") or "").strip()
    if normalized["conversation_id"]:
        return conversation_id == normalized["conversation_id"]
    if str(conversation.get("name") or "").strip() != normalized["name"]:
        return False
    if normalized["conversation_type"]:
        return str(conversation.get("conversation_type") or "") == normalized["conversation_type"]
    return True


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
    legacy_matches: list[dict[str, str]] = []

    for _round in range(80):
        for item in panel.locator(CONVERSATION_ITEM_SELECTOR).all():
            conversation = _conversation_friend(item)
            if not conversation or not _target_matches(target, conversation):
                continue
            if target.get("conversation_id") or target.get("conversation_type"):
                return item, conversation
            if all(_conversation_key(existing) != _conversation_key(conversation) for existing in legacy_matches):
                legacy_matches.append(conversation)
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

    if len(legacy_matches) > 1:
        raise ValueError(f"会话名称“{target.get('name', '')}”不唯一，请刷新好友列表后重新添加")
    if not legacy_matches:
        return None, None
    discovered = legacy_matches[0]
    enriched = {**normalize_target(target), **discovered}
    return _find_conversation_in_list(page, enriched)


def _find_search_result(page: Any, search_input: Any, name: str) -> Any | None:
    result = page.locator(SEARCH_RESULT_SELECTOR).filter(has=page.get_by_text(name, exact=True)).first
    for _attempt in range(3):
        search_input.fill("")
        try:
            page.locator(SEARCH_RESULT_SELECTOR).first.wait_for(state="hidden", timeout=3_000)
        except Exception:
            pass
        page.wait_for_timeout(300)
        search_input.fill(name)
        try:
            result.wait_for(state="visible", timeout=5_000)
            return result
        except Exception:
            page.wait_for_timeout(1_000)
    return None


def _open_target_conversation(
    page: Any,
    search_input: Any,
    target: dict[str, Any],
    *,
    group_only: bool = False,
) -> tuple[Any, dict[str, str]]:
    item, conversation = _find_conversation_in_list(page, target)
    if item is not None and conversation is not None:
        if group_only and conversation.get("conversation_type") != "group":
            raise ValueError("安全保护已中止：目标不是群聊")
        item.click(timeout=5_000)
    else:
        if group_only or target.get("conversation_type") == "group":
            raise ValueError("未在聊天会话列表中找到指定群聊")
        result = _find_search_result(page, search_input, target["name"])
        if result is None:
            raise ValueError("未找到该会话")
        send_button = result.get_by_text("发消息", exact=True)
        if send_button.count() == 0:
            send_button = result.get_by_text("发私信", exact=True)
        if send_button.count():
            send_button.first.click(timeout=5_000)
        else:
            result.click(timeout=5_000)
        conversation = {
            "name": target["name"],
            "avatar_url": "",
            "conversation_id": "",
            "conversation_short_id": "",
            "conversation_type": "direct",
        }

    editor = page.locator(CHAT_EDITOR_SELECTOR).first
    editor.wait_for(state="visible", timeout=10_000)
    return editor, conversation


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


def run_spark(
    user: dict[str, Any],
    *,
    targets_override: list[dict[str, Any]] | None = None,
    group_only: bool = False,
    record_run: bool = True,
) -> dict[str, Any]:
    cfg = user.get("douyin") or {}
    cookies = cfg.get("cookies") or []
    source_targets = targets_override if targets_override is not None else (cfg.get("targets") or [])
    targets = [normalize_target(item) for item in source_targets if isinstance(item, dict) and item.get("name")]
    if not cookies:
        raise ValueError("尚未登录抖音账号")
    if not targets:
        raise ValueError("请至少配置一个续火花对象")
    if group_only:
        if len(targets) != 1:
            raise ValueError("安全保护已中止：群聊测试必须且只能包含一个目标")
        if targets[0].get("conversation_type") != "group" or not targets[0].get("conversation_id"):
            raise ValueError("安全保护已中止：目标缺少明确的群聊标识")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，无法执行续火花") from exc

    default_message = cfg.get("default_message") or "续火花"
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = None
        try:
            context, page, search_input = _open_chat(browser, cookies)
            for target in targets:
                name = target["name"]
                try:
                    editor, discovered = _open_target_conversation(
                        page, search_input, target, group_only=group_only
                    )
                    if group_only and discovered.get("conversation_type") != "group":
                        raise ValueError("安全保护已中止：打开后的会话不是群聊")
                    _merge_discovered_target(cfg, target, discovered)
                    editor.click()
                    text = message_for(target, default_message)
                    page.keyboard.insert_text(text)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1_000)
                    remaining = "".join(editor.inner_text().split()).replace("\u200b", "")
                    if remaining:
                        raise ValueError("发送键未生效，消息仍停留在输入框")
                    results.append({
                        "target": name,
                        "target_type": discovered.get("conversation_type") or target.get("conversation_type") or "direct",
                        "message": text,
                        "ok": True,
                    })
                except Exception as exc:
                    results.append({"target": name, "message": "", "ok": False, "error": str(exc)})
        finally:
            if context:
                context.close()
            browser.close()
    if record_run:
        user.setdefault("douyin", {})["last_run"] = now_iso()
    return {"success": all(item.get("ok") for item in results) if results else False, "results": results}
