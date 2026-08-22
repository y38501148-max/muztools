from __future__ import annotations

import base64
import io
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .douyin import normalize_cookies


DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
SSO_SERVICE = "https://www.douyin.com"
ACTIVE = {"pending", "scanned"}


@dataclass
class QrSession:
    login_id: str
    user_id: str
    status: str = "pending"
    qr_png: bytes = b""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    nickname: str = ""
    error: str = ""
    persisted: bool = False
    created_at: float = field(default_factory=time.time)


_SESSIONS: dict[str, QrSession] = {}
_LOCK = threading.Lock()
_TTL = 180


def _purge() -> None:
    now = time.time()
    with _LOCK:
        dead = [key for key, item in _SESSIONS.items() if now - item.created_at > _TTL]
        for key in dead:
            _SESSIONS.pop(key, None)


def get_session(login_id: str) -> QrSession | None:
    _purge()
    with _LOCK:
        item = _SESSIONS.get(login_id)
        if item and time.time() - item.created_at > _TTL and item.status in ACTIVE:
            item.status = "expired"
            item.error = "二维码已过期，请重试"
        return item


def cancel_session(login_id: str, user_id: str) -> None:
    session = get_session(login_id)
    if session and session.user_id == user_id and session.status in ACTIVE:
        session.status = "cancelled"
        session.error = "已取消"


def start_qr_login(user_id: str) -> QrSession:
    login_id = secrets.token_hex(8)
    session = QrSession(login_id=login_id, user_id=user_id)
    with _LOCK:
        _purge()
        _SESSIONS[login_id] = session

    thread = threading.Thread(target=_run_qr_flow, args=(session,), daemon=True)
    thread.start()

    deadline = time.time() + 12
    while time.time() < deadline:
        if session.qr_png or session.status not in ACTIVE:
            break
        time.sleep(0.15)
    return session


def _run_qr_flow(session: QrSession) -> None:
    try:
        if _run_sso_flow(session):
            return
        _run_playwright_flow(session)
    except Exception as exc:
        if session.status in ACTIVE:
            session.status = "failed"
            session.error = str(exc)


def _run_sso_flow(session: QrSession) -> bool:
    try:
        headers = {
            "User-Agent": DESKTOP_UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }
        with httpx.Client(headers=headers, follow_redirects=True, timeout=20) as client:
            client.get("https://www.douyin.com/")
            response = client.get(
                "https://sso.douyin.com/get_qrcode/",
                params={
                    "service": SSO_SERVICE,
                    "need_logo": "false",
                    "need_short_url": "true",
                    "device_platform": "webapp",
                    "aid": "6383",
                    "account_sdk_source": "sso",
                    "sdk_version": "2.2.5",
                    "language": "zh",
                },
            )
            payload = response.json()
            data = payload.get("data") or {}
            token = str(data.get("token") or "")
            qr_png = _decode_qr_image(data)
            if not token or not qr_png:
                return False
            session.qr_png = qr_png
            deadline = time.time() + 150
            while time.time() < deadline and session.status in ACTIVE:
                check = client.get(
                    "https://sso.douyin.com/check_qrcode/",
                    params={
                        "token": token,
                        "service": SSO_SERVICE,
                        "need_logo": "false",
                    },
                )
                check_data = (check.json().get("data") or {}) if check.is_success else {}
                status = str(check_data.get("status") or check_data.get("error_code") or "")
                if status in {"2", "scanned"}:
                    session.status = "scanned"
                    session.error = ""
                redirect = str(check_data.get("redirect_url") or check_data.get("url") or "")
                if status in {"3", "success"} or redirect:
                    if redirect:
                        client.get(redirect)
                    cookies = _cookies_from_client(client)
                    if _logged_in(cookies):
                        session.cookies = normalize_cookies(cookies)
                        session.nickname = str(check_data.get("nickname") or check_data.get("name") or "")
                        session.status = "success"
                        session.error = ""
                        return True
                if status in {"4", "5", "expired", "canceled", "cancelled"}:
                    session.status = "expired"
                    session.error = "二维码已过期，请重试"
                    return True
                time.sleep(2)
            if session.status in ACTIVE:
                session.status = "expired"
                session.error = "二维码已过期，请重试"
            return True
    except Exception:
        return False


def _run_playwright_flow(session: QrSession) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        session.status = "failed"
        session.error = "服务器未安装 Playwright。请执行: pip install playwright && playwright install chromium"
        raise exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 860},
            user_agent=DESKTOP_UA,
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        qr = b""
        for url in (
            "https://www.douyin.com/",
            "https://creator.douyin.com/",
            "https://creator.douyin.com/login",
        ):
            if session.status not in ACTIVE:
                browser.close()
                return
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1800)
                _try_open_login(page)
                qr = _capture_qr(page)
                if qr:
                    break
            except Exception:
                continue
        if not qr:
            session.status = "failed"
            session.error = "页面上没有找到登录二维码"
            browser.close()
            return
        session.qr_png = qr
        deadline = time.time() + 150
        while time.time() < deadline and session.status in ACTIVE:
            cookies = context.cookies()
            if _logged_in(cookies):
                session.cookies = normalize_cookies(cookies)
                session.nickname = _guess_name(page)
                session.status = "success"
                session.error = ""
                break
            time.sleep(2)
            try:
                refreshed = _capture_qr(page)
                if refreshed:
                    session.qr_png = refreshed
            except Exception:
                pass
        if session.status in ACTIVE:
            session.status = "expired"
            session.error = "二维码已过期，请重试"
        browser.close()


def _try_open_login(page: Any) -> None:
    for selector in (
        "text=登录",
        "text=登录 / 注册",
        "button:has-text('登录')",
        "[class*='login']",
    ):
        try:
            locator = page.locator(selector).first
            if locator.count():
                locator.click(timeout=2000)
                page.wait_for_timeout(800)
                break
        except Exception:
            continue


def _capture_qr(page: Any) -> bytes:
    selectors = [
        "img[src*='qr']",
        "img[alt*='二维码']",
        "#animate_qrcode_container img",
        "[class*='qrcode'] img",
        "[class*='qr-code'] img",
        "[class*='QrCode'] img",
        "canvas",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.wait_for(state="visible", timeout=4000)
            return locator.screenshot(type="png")
        except Exception:
            continue
    return b""


def _decode_qr_image(data: dict[str, Any]) -> bytes:
    raw = data.get("qrcode") or data.get("qr_code") or data.get("image") or ""
    if isinstance(raw, str) and raw:
        text = raw.split(",", 1)[-1] if raw.startswith("data:image") else raw
        try:
            decoded = base64.b64decode(text)
            if decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8"):
                return decoded
        except Exception:
            pass
        if raw.startswith("http"):
            try:
                response = httpx.get(raw, timeout=15, headers={"User-Agent": DESKTOP_UA})
                if response.is_success and response.content:
                    return response.content
            except Exception:
                pass
    url = str(data.get("qrcode_index_url") or data.get("url") or "")
    if url:
        png = _render_qr(url)
        if png:
            return png
    return b""


def _render_qr(content: str) -> bytes:
    try:
        import qrcode
    except ImportError:
        return b""
    image = qrcode.make(content)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _cookies_from_client(client: httpx.Client) -> list[dict[str, Any]]:
    cookies = []
    for cookie in client.cookies.jar:
        domain = cookie.domain or ".douyin.com"
        if "douyin" not in domain:
            domain = ".douyin.com"
        elif not domain.startswith("."):
            domain = "." + domain.lstrip(".")
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
            }
        )
    return cookies


def _logged_in(cookies: list[dict[str, Any]]) -> bool:
    names = {str(item.get("name") or "").lower() for item in cookies}
    return "sessionid" in names or "sessionid_ss" in names


def _guess_name(page: Any) -> str:
    try:
        title = page.title()
        return title.replace("抖音", "").replace("-", "").strip()[:32]
    except Exception:
        return ""


def public_qr(session: QrSession) -> dict[str, Any]:
    qr_b64 = base64.b64encode(session.qr_png).decode("ascii") if session.qr_png else ""
    return {
        "login_id": session.login_id,
        "status": session.status,
        "qr_image": qr_b64,
        "nickname": session.nickname,
        "error": session.error,
        "valid": session.status == "success",
    }
