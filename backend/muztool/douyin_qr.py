from __future__ import annotations

import base64
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .douyin import normalize_cookies


DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
LOGIN_URL = "https://www.douyin.com/"
CHECK_QR_URL = "https://sso.douyin.com/check_qrconnect/"
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
    workdir: str = ""
    proc: subprocess.Popen[bytes] | None = field(default=None, repr=False)


_SESSIONS: dict[str, QrSession] = {}
_LOCK = threading.Lock()
_TTL = 300


def _purge_locked() -> None:
    now = time.time()
    dead = [key for key, item in _SESSIONS.items() if now - item.created_at > _TTL]
    for key in dead:
        session = _SESSIONS.pop(key, None)
        if session:
            _stop_worker(session)


def _purge() -> None:
    with _LOCK:
        _purge_locked()


def get_session(login_id: str) -> QrSession | None:
    _purge()
    with _LOCK:
        item = _SESSIONS.get(login_id)
        if item and time.time() - item.created_at > _TTL and item.status in ACTIVE:
            item.status = "expired"
            item.error = "二维码已过期，请重试"
            _stop_worker(item)
        return item


def cancel_session(login_id: str, user_id: str) -> None:
    session = get_session(login_id)
    if session and session.user_id == user_id and session.status in ACTIVE:
        session.status = "cancelled"
        session.error = "已取消"
        _stop_worker(session)


def start_qr_login(user_id: str) -> QrSession:
    login_id = secrets.token_hex(8)
    session = QrSession(login_id=login_id, user_id=user_id)
    with _LOCK:
        _purge_locked()
        _SESSIONS[login_id] = session

    thread = threading.Thread(target=_watch_worker, args=(session,), daemon=True)
    thread.start()

    deadline = time.time() + 25
    while time.time() < deadline:
        if session.qr_png or session.status not in ACTIVE:
            break
        time.sleep(0.15)
    return session


def _watch_worker(session: QrSession) -> None:
    workdir = Path(tempfile.mkdtemp(prefix=f"muz-qr-{session.login_id}-"))
    session.workdir = str(workdir)
    events = workdir / "events.jsonl"
    events.touch()
    try:
        stderr_file = (workdir / "worker.stderr.log").open("ab")
        try:
            session.proc = subprocess.Popen(
                [sys.executable, "-m", "muztool.douyin_qr", str(workdir)],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )
        finally:
            stderr_file.close()
    except Exception as exc:
        session.status = "failed"
        session.error = f"无法启动扫码进程: {exc}"
        return

    offset = 0
    deadline = time.time() + 280
    while time.time() < deadline and session.status in ACTIVE:
        offset = _read_events(session, events, offset)
        if session.proc.poll() is not None and not _has_pending_events(events, offset):
            if session.status in ACTIVE and not session.qr_png:
                err = _worker_stderr(session)
                session.status = "failed"
                session.error = err or "页面上没有找到登录二维码"
            break
        time.sleep(0.2)
    if session.status in ACTIVE:
        session.status = "expired"
        session.error = "二维码已过期，请重试"
    _stop_worker(session)


def _read_events(session: QrSession, events: Path, offset: int) -> int:
    try:
        data = events.read_bytes()
    except OSError:
        return offset
    if len(data) <= offset:
        return offset
    chunk = data[offset:]
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        keep = text.rfind("\n") + 1
        if keep <= 0:
            return offset
        text = text[:keep]
    offset += len(text.encode("utf-8"))
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        _apply_event(session, event)
    return offset


def _has_pending_events(events: Path, offset: int) -> bool:
    try:
        return events.stat().st_size > offset
    except OSError:
        return False


def _apply_event(session: QrSession, event: dict[str, Any]) -> None:
    kind = event.get("event")
    if kind == "qr":
        if session.status in {"scanned", "success", "failed", "expired", "cancelled"}:
            return
        png = _b64_to_png(str(event.get("png") or ""))
        if png:
            session.qr_png = png
    elif kind == "status":
        status = str(event.get("status") or "")
        if status == "scanned" and session.status in ACTIVE:
            guidance = str(event.get("error") or "")
            if guidance or session.status != "scanned":
                session.error = guidance
            session.status = "scanned"
        elif status in {"expired", "cancelled", "failed"} and session.status in ACTIVE:
            session.status = status
            session.error = str(event.get("error") or session.error)
    elif kind == "success":
        cookies = event.get("cookies") or []
        try:
            session.cookies = normalize_cookies(cookies)
        except Exception:
            session.cookies = cookies if isinstance(cookies, list) else []
        if not session.cookies:
            if session.status in ACTIVE:
                session.status = "failed"
                session.error = "扫码已完成，但未获取到抖音登录 Cookie"
            return
        session.nickname = str(event.get("nickname") or "")
        session.status = "success"
        session.error = ""
    elif kind == "failed":
        if session.status in ACTIVE:
            session.status = "failed"
            session.error = str(event.get("error") or "生成二维码失败")


def _b64_to_png(raw: str) -> bytes:
    if not raw:
        return b""
    try:
        decoded = base64.b64decode(raw)
    except Exception:
        return b""
    if decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8"):
        return decoded
    return b""


def _worker_stderr(session: QrSession) -> str:
    if not session.workdir:
        return ""
    try:
        text = (Path(session.workdir) / "worker.stderr.log").read_text(
            encoding="utf-8", errors="replace"
        ).strip()
    except OSError:
        return ""
    return text[-1000:]


def _stop_worker(session: QrSession) -> None:
    proc = session.proc
    session.proc = None
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    if session.workdir:
        try:
            for item in Path(session.workdir).glob("*"):
                item.unlink(missing_ok=True)
            Path(session.workdir).rmdir()
        except OSError:
            pass


def _looks_like_html(value: str) -> bool:
    sample = value.lstrip().lower()[:240]
    return (
        sample.startswith("<!doctype")
        or sample.startswith("<html")
        or "<head" in sample
        or "<body" in sample
        or "<script" in sample
    )


def _scan_payload_url(data: dict[str, Any]) -> str:
    url = str(data.get("qrcode_index_url") or "")
    if not url.startswith(("http://", "https://")):
        return ""
    if len(url) > 2048 or _looks_like_html(url):
        return ""
    return url


def decode_qr_image(data: dict[str, Any]) -> bytes:
    raw = data.get("qrcode") or data.get("qr_code") or data.get("image") or ""
    if isinstance(raw, str) and raw and not _looks_like_html(raw):
        text = raw.split(",", 1)[-1] if raw.startswith("data:image") else raw
        png = _b64_to_png(text)
        if png:
            return png
        if raw.startswith(("http://", "https://")) and len(raw) < 2048:
            try:
                import httpx
                response = httpx.get(raw, timeout=15, headers={"User-Agent": DESKTOP_UA})
                content = response.content if response.is_success else b""
                if content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8"):
                    return content
            except Exception:
                pass
    url = _scan_payload_url(data)
    if url:
        png = render_qr(url)
        if png:
            return png
    return b""


def render_qr(content: str) -> bytes:
    try:
        import qrcode
    except ImportError:
        return b""
    image = qrcode.make(content)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def public_qr(session: QrSession) -> dict[str, Any]:
    qr_b64 = base64.b64encode(session.qr_png).decode("ascii") if session.qr_png else ""
    return {
        "login_id": session.login_id,
        "status": session.status,
        "qr_image": qr_b64,
        "nickname": session.nickname,
        "error": session.error,
        "valid": session.status == "success" and bool(session.cookies),
    }


def _emit(events: Path, payload: dict[str, Any]) -> None:
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


AUTH_COOKIE_EXACT = {
    "sessionid",
    "sessionid_ss",
    "sessionid_ads",
    "sessionid_creator",
    "sid_tt",
    "sid_tt_ss",
    "sid_guard",
    "uid_tt",
    "uid_tt_ss",
}


def _logged_in(cookies: list[dict[str, Any]]) -> bool:
    for item in cookies:
        name = str(item.get("name") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        if name in AUTH_COOKIE_EXACT:
            return True
        if "sessionid" in name or name.startswith("sid_") or name.startswith("uid_tt"):
            return True
    return False


def _merge_cookies(*cookie_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for cookies in cookie_sets:
        for item in cookies or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = item.get("value")
            if not name or value is None:
                continue
            domain = str(item.get("domain") or ".douyin.com")
            path = str(item.get("path") or "/")
            merged[(name, domain, path)] = {
                "name": name,
                "value": str(value),
                "domain": domain,
                "path": path,
            }
    return list(merged.values())


def _payload_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _extract_payload_cookies(payload: Any) -> list[dict[str, Any]]:
    data = _payload_data(payload)
    raw = data.get("cookies") or data.get("cookie") or data.get("set_cookies")
    if not raw:
        return []
    try:
        return normalize_cookies(raw)
    except Exception:
        return []


def _guess_name(page: Any, state: dict[str, Any] | None = None) -> str:
    if state:
        name = str(state.get("nickname") or "").strip()
        if name:
            return name[:32]
    try:
        title = page.title()
        return title.replace("抖音", "").replace("-", "").replace("创作者中心", "").strip()[:32]
    except Exception:
        return ""


def _try_open_login(page: Any) -> None:
    try:
        page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll('button, span, div, a, p'));
                const hit = nodes.find((node) => {
                    const text = (node.textContent || '').replace(/\\s+/g, '');
                    return text === '登录' || text === '登录/注册' || text.includes('扫码登录');
                });
                if (hit) hit.click();
            }"""
        )
        page.wait_for_timeout(800)
    except Exception:
        pass


def _capture_qr(page: Any) -> bytes:
    selectors = [
        "#animate_qrcode_container img",
        "img[alt*='二维码']",
        "img[src*='qr']",
        "[class*='qrcode'] img",
        "[class*='qr-code'] img",
        "[class*='QrCode'] img",
    ]
    frames = [page]
    try:
        frames.extend(page.frames)
    except Exception:
        pass
    for frame in frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                if locator.count() == 0:
                    continue
                locator.wait_for(state="visible", timeout=1200)
                return locator.screenshot(type="png")
            except Exception:
                continue
    return b""


def _cookie_snapshot(cookies: list[dict[str, Any]]) -> list[str]:
    return sorted({str(item.get("name") or "") for item in cookies if item.get("name")})


def _page_left_login(page: Any) -> bool:
    try:
        url = str(page.url or "")
    except Exception:
        return False
    return "douyin.com" in url and "/login" not in url and "sso.douyin.com" not in url


def _page_has_login_artifacts(page: Any) -> bool:
    """Douyin's web login writes these security keys after the callback completes."""
    keys = (
        "security-sdk/s_sdk_crypt_sdk",
        "security-sdk/s_sdk_sign_data_key/web_protect",
    )
    try:
        values = page.evaluate(
            "keys => keys.map(key => window.localStorage.getItem(key) || '')",
            list(keys),
        )
        return isinstance(values, list) and all(str(value).strip() for value in values)
    except Exception:
        return False


def _is_login_redirect(value: str) -> bool:
    """Accept only a real Douyin passport callback, never an MFA/static asset URL."""
    try:
        parsed = urlparse(value.strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = (parsed.path or "/").lower()
    if not host or path.endswith((".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".svg", ".ico")):
        return False
    if host == "auth.zijieapi.com" or "second_verification" in path:
        return False
    if host == "sso.douyin.com":
        return "callback" in path or "/passport/" in path
    if host == "douyin.com" or host.endswith(".douyin.com"):
        return "/passport/" in path and ("callback" in path or "/sso/" in path)
    return False


def _handle_check_payload(data: dict[str, Any], state: dict[str, Any], events: Path) -> None:
    data = _payload_data(data)
    status = str(data.get("status") or data.get("error_code") or data.get("status_code") or "")
    redirect_candidates = (
        data.get("redirect_url"),
        data.get("redirect"),
        data.get("redirect_uri"),
        data.get("next_url"),
        data.get("url"),
        data.get("url_path"),
    )
    redirect = next(
        (str(candidate) for candidate in redirect_candidates if candidate and _is_login_redirect(str(candidate))),
        "",
    )
    if data.get("nickname") or data.get("username"):
        state["nickname"] = str(data.get("nickname") or data.get("username") or "")
    _emit(
        events,
        {
            "event": "debug",
            "phase": "check",
            "status": status,
            "keys": list(data.keys())[:20],
            "has_redirect": bool(redirect),
        },
    )
    if status == "2046":
        first_notice = not state.get("verification_required")
        state["verification_required"] = True
        state["confirmed"] = False
        state["redirect"] = ""
        if first_notice:
            _emit(
                events,
                {
                    "event": "status",
                    "status": "scanned",
                    "error": "抖音要求后端网页登录进行二次安全验证；当前扫码流程尚未提供验证码或密码输入入口",
                },
            )
        return
    if status in {"2", "scanned"}:
        _emit(events, {"event": "status", "status": "scanned"})
        return
    if status in {"3", "success", "confirmed", "confirm"} or bool(redirect):
        state["verification_required"] = False
        state["confirmed"] = True
        if redirect:
            state["redirect"] = redirect
        _emit(events, {"event": "status", "status": "scanned"})
        return
    if status in {"4", "5", "expired", "canceled", "cancelled"}:
        _emit(events, {"event": "status", "status": "expired", "error": "二维码已过期，请重试"})
        state["done"] = True


def _worker_main(workdir: Path) -> int:
    events = workdir / "events.jsonl"
    state = {
        "redirect": "",
        "done": False,
        "token": "",
        "confirmed": False,
        "verification_required": False,
        "cookies": [],
        "nickname": "",
        "finalized": False,
    }

    def emit_qr(png: bytes) -> None:
        if png:
            _emit(events, {"event": "qr", "png": base64.b64encode(png).decode("ascii")})

    def authenticated_cookies(context: Any) -> list[dict[str, Any]]:
        try:
            browser_cookies = context.cookies()
        except Exception:
            browser_cookies = []
        return _merge_cookies(browser_cookies, state.get("cookies") or [])

    def emit_success_if_ready(context: Any, page: Any) -> bool:
        cookies = authenticated_cookies(context)
        if not cookies:
            return False
        if not (_logged_in(cookies) or _page_has_login_artifacts(page)):
            return False
        _emit(
            events,
            {
                "event": "success",
                "cookies": cookies,
                "nickname": _guess_name(page, state),
            },
        )
        return True

    def finalize_confirmed_login(page: Any, context: Any) -> None:
        """Visit a normal creator endpoint after confirmation so Set-Cookie is committed."""
        if state.get("finalized"):
            return
        state["finalized"] = True
        urls = [
            "https://www.douyin.com/",
            "https://creator.douyin.com/creator-micro/data/following/chat",
        ]
        for url in urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1200)
            except Exception:
                pass
            try:
                info = page.request.get("https://creator.douyin.com/web/api/media/user/info/", timeout=12000)
                payload = info.json()
                data = _payload_data(payload)
                state["cookies"] = _merge_cookies(state.get("cookies") or [], _extract_payload_cookies(payload))
                nickname = data.get("nickname") or data.get("unique_id") or data.get("name")
                if nickname:
                    state["nickname"] = str(nickname)
            except Exception:
                pass
            if emit_success_if_ready(context, page):
                return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _emit(events, {"event": "failed", "error": "服务器未安装 Playwright。请执行: pip install playwright && playwright install chromium"})
        return 1

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 860},
                user_agent=DESKTOP_UA,
                locale="zh-CN",
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            def on_response(response: Any) -> None:
                url = getattr(response, "url", "") or ""
                interesting = any(
                    key in url
                    for key in (
                        "get_qrcode",
                        "check_qrconnect",
                        "check_login",
                        "login/callback",
                        "/web/api/media/user/info/",
                    )
                )
                if not interesting:
                    return
                try:
                    payload = response.json()
                except Exception:
                    payload = None
                data = _payload_data(payload)
                state["cookies"] = _merge_cookies(state.get("cookies") or [], _extract_payload_cookies(payload))
                nickname = data.get("nickname") or data.get("unique_id") or data.get("name")
                if nickname:
                    state["nickname"] = str(nickname)
                if "get_qrcode" in url and isinstance(data, dict):
                    token = str(data.get("token") or data.get("qrcode_token") or "")
                    if token:
                        state["token"] = token
                    png = decode_qr_image(data)
                    if png:
                        emit_qr(png)
                    return
                if isinstance(data, dict) and ("check_qrconnect" in url or "check_login" in url):
                    _handle_check_payload(data, state, events)

            page.on("response", on_response)
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            page.wait_for_timeout(1800)
            _try_open_login(page)

            deadline = time.time() + 22
            while time.time() < deadline:
                if '"event": "qr"' in events.read_text(encoding="utf-8"):
                    break
                captured = _capture_qr(page)
                if captured:
                    emit_qr(captured)
                    break
                page.wait_for_timeout(400)
            else:
                captured = _capture_qr(page)
                if captured:
                    emit_qr(captured)

            if '"event": "qr"' not in events.read_text(encoding="utf-8"):
                _emit(events, {"event": "failed", "error": "页面上没有找到登录二维码"})
                browser.close()
                return 1

            followed: set[str] = set()
            deadline = time.time() + 260
            while time.time() < deadline and not state["done"]:
                if state["token"] and not state["confirmed"]:
                    try:
                        check = page.request.get(
                            CHECK_QR_URL,
                            params={
                                "token": state["token"],
                                "service": "https://www.douyin.com",
                                "need_logo": "false",
                                "is_frontier": "false",
                                "need_short_url": "false",
                                "passport_jssdk_version": "1.0.26",
                                "passport_jssdk_type": "pro",
                                "aid": "6383",
                                "language": "zh",
                                "account_sdk_source": "sso",
                                "device_platform": "web_app",
                            },
                        )
                        payload = check.json()
                        data = _payload_data(payload)
                        state["cookies"] = _merge_cookies(state.get("cookies") or [], _extract_payload_cookies(payload))
                        if isinstance(data, dict):
                            _handle_check_payload(data, state, events)
                    except Exception:
                        pass

                if emit_success_if_ready(context, page):
                    browser.close()
                    return 0

                if state["confirmed"]:
                    redirect = state["redirect"]
                    if redirect and redirect not in followed:
                        followed.add(redirect)
                        try:
                            page.goto(redirect, wait_until="domcontentloaded", timeout=20000)
                        except Exception:
                            pass
                        page.wait_for_timeout(1500)
                        cookies = authenticated_cookies(context)
                        _emit(
                            events,
                            {
                                "event": "debug",
                                "phase": "after_redirect",
                                "url": getattr(page, "url", ""),
                                "cookies": _cookie_snapshot(cookies),
                            },
                        )
                        if emit_success_if_ready(context, page):
                            browser.close()
                            return 0
                        finalize_confirmed_login(page, context)
                        if emit_success_if_ready(context, page):
                            browser.close()
                            return 0
                    elif not redirect:
                        page.wait_for_timeout(2000)
                        cookies = authenticated_cookies(context)
                        _emit(
                            events,
                            {
                                "event": "debug",
                                "phase": "confirmed_no_redirect",
                                "url": getattr(page, "url", ""),
                                "cookies": _cookie_snapshot(cookies),
                            },
                        )
                        if emit_success_if_ready(context, page):
                            browser.close()
                            return 0
                        if _page_left_login(page):
                            state["redirect"] = str(getattr(page, "url", "") or "")
                        finalize_confirmed_login(page, context)
                        if emit_success_if_ready(context, page):
                            browser.close()
                            return 0
                page.wait_for_timeout(1000)
            if emit_success_if_ready(context, page):
                browser.close()
                return 0
            if state["confirmed"]:
                _emit(events, {"event": "failed", "error": "扫码已确认，但服务器未获取到有效抖音登录 Cookie，请重新扫码或改用 Cookie 导入"})
            else:
                _emit(events, {"event": "status", "status": "expired", "error": "二维码已过期，请重试"})
            browser.close()
            return 1
    except Exception as exc:
        _emit(events, {"event": "failed", "error": f"生成二维码失败: {exc}"})
        return 1



if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    if not target:
        raise SystemExit("usage: python -m muztool.douyin_qr WORKDIR")
    raise SystemExit(_worker_main(target))
