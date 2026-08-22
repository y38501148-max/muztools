from __future__ import annotations

import json
from typing import Any

from .store import now_iso


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
        cookies.append(
            {
                "name": str(item["name"]),
                "value": str(item["value"]),
                "domain": item.get("domain") or ".douyin.com",
                "path": item.get("path") or "/",
            }
        )
    if not cookies:
        raise ValueError("Cookie 列表为空")
    return cookies


def message_for(target: dict[str, Any], default_message: str) -> str:
    custom = (target.get("message") or "").strip()
    return custom or (default_message or "续火花")


def run_spark(user: dict[str, Any]) -> dict[str, Any]:
    cfg = user.get("douyin") or {}
    cookies = cfg.get("cookies") or []
    targets = cfg.get("targets") or []
    if not cookies:
        raise ValueError("尚未登录抖音账号")
    if not targets:
        raise ValueError("请至少配置一个续火花对象")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 playwright，无法执行续火花。请在后端执行: pip install playwright && playwright install chromium") from exc

    default_message = cfg.get("default_message") or "续火花"
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.set_default_timeout(120_000)
        page.goto("https://creator.douyin.com/creator-micro/data/following/chat", wait_until="domcontentloaded")
        friends_tab = 'xpath=//*[@id="sub-app"]/div/div/div[1]/div[2]'
        try:
            page.wait_for_selector(friends_tab, timeout=30_000)
            page.locator(friends_tab).click()
        except Exception:
            pass
        item_selector = 'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]//div[contains(@class, "semi-list-item-body")]'
        chat_input_selector = "xpath=//div[contains(@class, 'chat-input-')]"
        wanted = {str(target.get("name") or "").strip() for target in targets if target.get("name")}
        found: set[str] = set()
        for _ in range(40):
            for element in page.locator(item_selector).all():
                try:
                    name = element.locator('xpath=.//span[contains(@class, "item-header-name-")]').inner_text().strip()
                except Exception:
                    continue
                if not name or name in found or name not in wanted:
                    continue
                found.add(name)
                element.click()
                page.wait_for_selector(chat_input_selector)
                target = next(item for item in targets if item.get("name") == name)
                text = message_for(target, default_message)
                chat_input = page.locator(chat_input_selector)
                chat_input.fill("")
                chat_input.type(text)
                chat_input.press("Enter")
                results.append({"target": name, "message": text, "ok": True})
            if wanted <= found:
                break
            scroller = page.locator('xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]//ul/div')
            if scroller.count():
                handle = scroller.first.element_handle()
                if handle:
                    page.evaluate("(el) => el.scrollTop += 800", handle)
            page.wait_for_timeout(800)
        browser.close()
    missing = sorted(wanted - found)
    for name in missing:
        results.append({"target": name, "message": "", "ok": False, "error": "未找到该好友"})
    user["douyin"]["last_run"] = now_iso()
    return {"success": all(item.get("ok") for item in results) if results else False, "results": results}
