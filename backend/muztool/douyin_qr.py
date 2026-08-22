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

from .douyin import normalize_cookies


DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
LOGIN_URL = "https://creator.douyin.com/login"
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
_TTL = 180


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
        session.proc = subprocess.Popen(
            [sys.executable, "-m", "muztool.douyin_qr", str(workdir)],
            cwd=str(Path(__file__).resolve().parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        session.status = "failed"
        session.error = f"无法启动扫码进程: {exc}"
        return

    offset = 0
    deadline = time.time() + 160
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
        png = _b64_to_png(str(event.get("png") or ""))
        if png:
            session.qr_png = png
    elif kind == "status":
        status = str(event.get("status") or "")
        if status == "scanned" and session.status in ACTIVE:
            session.status = "scanned"
            session.error = ""
        elif status in {"expired", "cancelled", "failed"} and session.status in ACTIVE:
            session.status = status
            session.error = str(event.get("error") or session.error)
    elif kind == "success":
        cookies = event.get("cookies") or []
        try:
            session.cookies = normalize_cookies(cookies)
        except Exception:
            session.cookies = cookies if isinstance(cookies, list) else []
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
    proc = session.proc
    if not proc or not proc.stderr:
        return ""
    try:
        text = proc.stderr.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    return text[-300:]


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


def decode_qr_image(data: dict[str, Any]) -> bytes:
    raw = data.get("qrcode") or data.get("qr_code") or data.get("image") or ""
    if isinstance(raw, str) and raw:
        text = raw.split(",", 1)[-1] if raw.startswith("data:image") else raw
        png = _b64_to_png(text)
        if png:
            return png
        if raw.startswith("http"):
            try:
                import httpx
                response = httpx.get(raw, timeout=15, headers={"User-Agent": DESKTOP_UA})
                if response.is_success and response.content:
                    return response.content
            except Exception:
                pass
    url = str(data.get("qrcode_index_url") or data.get("url") or "")
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
        "valid": session.status == "success",
    }


def _emit(events: Path, payload: dict[str, Any]) -> None:
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _logged_in(cookies: list[dict[str, Any]]) -> bool:
    names = {str(item.get("name") or "").lower() for item in cookies}
    return "sessionid" in names or "sessionid_ss" in names


def _guess_name(page: Any) -> str:
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


def _worker_main(workdir: Path) -> int:
    events = workdir / "events.jsonl"

    def emit_qr(png: bytes) -> None:
        if png:
            _emit(events, {"event": "qr", "png": base64.b64encode(png).decode("ascii")})

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
                if "get_qrcode" not in url and "check_qrconnect" not in url:
                    return
                try:
                    payload = response.json()
                except Exception:
                    return
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    return
                png = decode_qr_image(data)
                if png:
                    emit_qr(png)
                status = str(data.get("status") or "")
                if status in {"2", "scanned"}:
                    _emit(events, {"event": "status", "status": "scanned"})
                elif status in {"4", "expired", "canceled", "cancelled"}:
                    _emit(events, {"event": "status", "status": "expired", "error": "二维码已过期，请重试"})

            page.on("response", on_response)
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            page.wait_for_timeout(1800)
            _try_open_login(page)

            found = False
            deadline = time.time() + 22
            while time.time() < deadline:
                captured = _capture_qr(page)
                if captured:
                    emit_qr(captured)
                    found = True
                    break
                if (workdir / "qr.flag").exists():
                    found = True
                    break
                page.wait_for_timeout(400)

            # The intercept may have already written a QR without the flag.
            if not found:
                # Give intercept a little more time after click.
                page.wait_for_timeout(2500)
                captured = _capture_qr(page)
                if captured:
                    emit_qr(captured)
                    found = True

            if not found and not any(events.read_text(encoding="utf-8").find('"event": "qr"') >= 0 for _ in [0]):
                _emit(events, {"event": "failed", "error": "页面上没有找到登录二维码"})
                browser.close()
                return 1

            deadline = time.time() + 150
            while time.time() < deadline:
                cookies = context.cookies()
                if _logged_in(cookies):
                    _emit(
                        events,
                        {
                            "event": "success",
                            "cookies": cookies,
                            "nickname": _guess_name(page),
                        },
                    )
                    browser.close()
                    return 0
                page.wait_for_timeout(1500)
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
