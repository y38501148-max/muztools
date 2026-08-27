from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncio
import threading
import time

from fastapi import Body, Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .fcm import register_token as register_fcm_token, unregister_token as unregister_fcm_token
from .config import CORS_ORIGINS, ensure_dirs
from .douyin import (
    MAX_MESSAGE_LENGTH,
    MAX_SPARK_TARGETS,
    DouyinAutomationError,
    normalize_cookies,
    normalize_target,
    run_spark,
    list_douyin_friends,
    target_identity,
    validate_douyin_cookies,
    validate_spark_targets,
)
from .checkin import CheckinAuthError, CheckinError, get_provider, list_providers
from .invites import consume_invite, invite_stats, issue_invite, release_invite
from .security import decrypt_hybrid_secret, decrypt_transport_payload, public_transport_key, validate_password, validate_username
from .notify import (
    configure_live_notifications,
    list_notifications,
    mark_read,
    subscribe_live_notifications,
    unsubscribe_live_notifications,
)
from .scheduler import start_scheduler
from . import appver, config, sunshine, td, tibo
from .tibo import list_tibo_history
from .signin_core import perform_duaa_login, safe_fetch_schedule
from .store import (
    FEATURE_KEYS,
    authenticate,
    create_session,
    create_user,
    delete_session,
    ensure_approvals,
    find_user_by_username,
    get_douyin_cookies,
    get_douyin_friends_cache,
    get_checkin_token,
    get_student_password,
    now_iso,
    photo_dir,
    public_user,
    save_user,
    clear_tibo_x_cookies,
    set_douyin_cookies,
    set_douyin_friends_cache,
    set_checkin_token,
    set_student_password,
    set_tibo_x_cookies,
    student_runtime,
    user_from_token,
)

app = FastAPI(title="muztools", version="0.1.0")
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-MuzTool-Bridge-Token"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if config.RELAY_ONLY and request.url.path not in {"/api/health", "/api/app/version", "/api/app/apk"}:
        return Response("Not Found", status_code=404, media_type="text/plain")
    content_length = request.headers.get("content-length")
    if request.url.path in {"/api/auth/login", "/api/auth/register", "/api/student/bind", "/api/douyin/session"} and content_length:
        try:
            limit = 512 * 1024 if request.url.path == "/api/douyin/session" else 64 * 1024
            if int(content_length) > limit:
                return Response("请求体过大", status_code=413, media_type="text/plain")
        except ValueError:
            return Response("请求体无效", status_code=400, media_type="text/plain")
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


SESSION_COOKIE = "muz_session"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def _request_is_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _set_session_cookie(response: Response, token: str, keep_login: bool, *, secure: bool = False) -> None:
    if keep_login:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )
    else:
        response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    bearer_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()
    cookie_token = str(session_cookie or "").strip()

    token = bearer_token
    user = user_from_token(token) if token else None
    # A browser can retain an old local token while its newer persistent
    # HttpOnly cookie is still valid. Fall back to that cookie instead of
    # forcing a needless login.
    if not user and cookie_token and cookie_token != bearer_token:
        token = cookie_token
        user = user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    user["_token"] = token
    return user


def require_student(user: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    student = user.get("student") or {}
    if not student.get("student_id"):
        raise HTTPException(status_code=400, detail="请先绑定统一认证学号")
    if approved and student.get("status") not in {"verified", "approved"}:
        raise HTTPException(status_code=403, detail="请先完成学生认证")
    return student


def require_feature(user: dict[str, Any], feature: str) -> dict[str, Any]:
    if feature not in FEATURE_KEYS:
        raise HTTPException(status_code=400, detail="未知功能")
    if feature in {"signin", "td"}:
        return require_student(user)
    return user.get("student") or {}



def student_payload(user: dict[str, Any]) -> dict[str, Any]:
    payload = public_user(user)
    student = payload["student"]
    approvals = payload.get("approvals", {})
    return {
        "status": student.get("status") or "unbound",
        "student_id": student.get("student_id"),
        "display_name": student.get("real_name") or user.get("display_name"),
        "auto_signin": bool(student.get("auto_signin")),
        "student": student,
        "approvals": approvals,
        "signin_status": approvals.get("signin", "none"),
        "td_status": approvals.get("td", "none"),
        "spark_status": approvals.get("spark", "none"),
    }


def format_schedule(sched: list[dict[str, Any]], enabled: bool, approved: bool, today: str, cached: bool) -> dict[str, Any]:
    schedule = []
    for course in sched:
        begin = str(course.get("classBeginTime") or "")
        end = str(course.get("classEndTime") or "")
        signed = str(course.get("signStatus")) == "1"
        schedule.append(
            {
                "course_name": course.get("courseName") or "课程",
                "classroom": course.get("roomName") or course.get("classroomName") or "",
                "start_time": begin.split(" ")[-1][:5] if begin else "",
                "end_time": end.split(" ")[-1][:5] if end else "",
                "status": "signed" if signed else "pending",
                "scheduled_time": course.get("auto_sign_trigger_hm") or "",
                "course_id": str(course.get("id") or ""),
                **{k: v for k, v in course.items() if k not in {"id"}},
                "id": course.get("id"),
            }
        )
    payload = {
        "date": today,
        "courses": sched,
        "schedule": schedule,
        "enabled": enabled,
        "approved": approved,
        "auto_signin": enabled,
        "cached": cached,
    }
    if not sched:
        payload["message"] = "您今天没有需要签到的课"
    return payload


async def load_schedule(user: dict[str, Any], use_cache: bool) -> dict[str, Any]:
    from datetime import datetime
    from .signin_core import TZ_BEIJING

    student = user.get("student") or {}
    runtime = student_runtime(student)
    today = datetime.now(TZ_BEIJING).strftime("%Y%m%d")
    empty = format_schedule([], bool(student.get("auto_signin")), ensure_approvals(user)["approvals"].get("signin") == "approved", today, True)
    if not student.get("student_id"):
        return empty
    cached_rows = student.get("today_schedule") or []
    if use_cache:
        rows = cached_rows if student.get("schedule_date") == today else []
        return format_schedule(rows, bool(student.get("auto_signin")), ensure_approvals(user)["approvals"].get("signin") == "approved", today, True)
    try:
        sched, _auth = await safe_fetch_schedule(runtime, today)
    except Exception:
        if cached_rows:
            return format_schedule(cached_rows, bool(student.get("auto_signin")), ensure_approvals(user)["approvals"].get("signin") == "approved", today, True)
        raise
    for key in ("uid", "session_id", "cookies"):
        if key in runtime:
            student[key] = runtime[key]
    old = {item.get("id"): item.get("auto_sign_trigger_hm") for item in cached_rows}
    for course in sched:
        course["auto_sign_trigger_hm"] = old.get(course.get("id"), course.get("auto_sign_trigger_hm"))
    student["today_schedule"] = sched
    student["schedule_date"] = today
    save_user(user)
    return format_schedule(sched, bool(student.get("auto_signin")), ensure_approvals(user)["approvals"].get("signin") == "approved", today, False)


async def load_td(user: dict[str, Any]) -> dict[str, Any]:
    student = require_feature(user, "td")
    rows = await td.query_td_counts(student["student_id"], get_student_password(student))
    latest = td.latest_count(rows)
    photos = photo_dir(user["id"])
    campus = user.get("td", {}).get("campus", "xueyuanlu")
    return {
        "latest": latest,
        "rows": rows,
        "machines": td.campus_machines(campus),
        "gap_seconds": user.get("td", {}).get("gap_seconds", 240),
        "has_entrance_photo": (photos / "entrance.jpg").exists(),
        "has_exit_photo": (photos / "exit.jpg").exists(),
        "campus": campus,
        "semester_count": latest.get("count", 0),
        "target_count": 32,
        "status": "ok",
    }


async def load_sunshine(user: dict[str, Any]) -> dict[str, Any]:
    student = require_feature(user, "td")
    data = await sunshine.query_sunshine(student["student_id"], get_student_password(student))
    data["count"] = data.get("term_count", 0)
    data["target_count"] = data.get("term_target", 16)
    return data


def persist_qr_cookies(user: dict[str, Any], session) -> None:
    if session.status != "success" or not session.cookies or session.persisted:
        return
    user.setdefault("douyin", {})
    set_douyin_cookies(user["douyin"], session.cookies)
    if session.nickname:
        user["douyin"]["username"] = session.nickname
    save_user(user)
    session.persisted = True

_AUTH_RATE_LOCK = threading.Lock()
_AUTH_RATE: dict[str, list[float]] = {}


def _rate_limit(request: Request, scope: str, identity: str, limit: int, window_seconds: int) -> None:
    host = request.client.host if request.client else "unknown"
    key = f"{scope}:{host}:{identity.casefold()}"
    now = time.monotonic()
    with _AUTH_RATE_LOCK:
        attempts = [stamp for stamp in _AUTH_RATE.get(key, []) if now - stamp < window_seconds]
        if len(attempts) >= limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        attempts.append(now)
        _AUTH_RATE[key] = attempts
        if len(_AUTH_RATE) > 10000:
            stale_before = now - 3600
            for stale_key in list(_AUTH_RATE):
                if not _AUTH_RATE[stale_key] or _AUTH_RATE[stale_key][-1] < stale_before:
                    _AUTH_RATE.pop(stale_key, None)


def _require_invite_admin(user: dict[str, Any]) -> None:
    if str(user.get("username") or "").casefold() != "muzermat":
        raise HTTPException(status_code=404, detail="功能不存在")


@app.on_event("startup")
async def on_startup() -> None:
    ensure_dirs()
    appver.load_version()
    if config.RELAY_ONLY:
        return
    configure_live_notifications(asyncio.get_running_loop())
    start_scheduler()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/app/version")
async def app_version() -> dict[str, Any]:
    return appver.public_version()


@app.get("/api/app/apk")
async def app_apk():
    from fastapi.responses import FileResponse

    path = appver.apk_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未上传安装包")
    return FileResponse(path, filename=path.name, media_type="application/vnd.android.package-archive")



@app.get("/api/security/public-key")
async def security_public_key() -> dict[str, Any]:
    return public_transport_key()


@app.post("/api/auth/register")
async def register(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        fields = decrypt_transport_payload(payload, ("username", "password", "display_name", "invite_code"))
        username = validate_username(fields["username"])
        password = validate_password(fields["password"])
        display_name = fields["display_name"].strip() or username
        if len(display_name) > 40:
            raise ValueError("显示名过长")
        invite_code = fields["invite_code"].strip()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _rate_limit(request, "register-ip", "*", 20, 3600)
    _rate_limit(request, "register", username, 8, 3600)
    if find_user_by_username(username):
        raise HTTPException(status_code=400, detail="账号无法注册，请检查信息后重试")
    invite_id = ""
    try:
        invite_id = consume_invite(invite_code, username)
        try:
            user = create_user(username, password, display_name)
        except Exception:
            release_invite(invite_id, username)
            raise
    except ValueError as exc:
        message = str(exc)
        if "邀请码" not in message:
            message = "账号无法注册，请检查信息后重试"
        raise HTTPException(status_code=400, detail=message) from exc
    user["registration_invite_id"] = invite_id
    save_user(user)
    token = create_session(user["id"])
    _set_session_cookie(response, token, bool(payload.get("keep_login", True)), secure=_request_is_secure(request))
    return {"token": token, "user": public_user(user)}


@app.post("/api/auth/login")
async def login(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        fields = decrypt_transport_payload(payload, ("username", "password"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    username = fields["username"].strip()
    _rate_limit(request, "login-ip", "*", 120, 600)
    _rate_limit(request, "login", username or "unknown", 30, 600)
    try:
        user = authenticate(username, fields["password"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="用户名或密码错误") from exc
    token = create_session(user["id"])
    _set_session_cookie(response, token, bool(payload.get("keep_login", False)), secure=_request_is_secure(request))
    return {"token": token, "user": public_user(user)}


@app.get("/api/auth/session")
async def auth_session(request: Request, response: Response, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    token = str(user.get("_token") or "")
    # Refresh the persistent cookie from either an existing cookie or a valid
    # local Bearer token. This repairs browser sessions whose cookie was lost
    # while localStorage still retained the persistent token.
    _set_session_cookie(response, token, True, secure=_request_is_secure(request))
    return {"token": token, "user": public_user(user)}


@app.post("/api/auth/logout")
async def logout(response: Response, user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    delete_session(user.get("_token", ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = public_user(user)
    return {**payload, "user": dict(payload)}


@app.post("/api/devices")
async def register_device(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    device_id = str(payload.get("device_id") or "").strip()
    if device_id and device_id not in user.get("devices", []):
        user.setdefault("devices", []).append(device_id)
        save_user(user)
    return {"status": "ok"}


@app.post("/api/devices/fcm")
async def register_fcm_device(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    try:
        register_fcm_token(
            user,
            token,
            device_id=str(payload.get("device_id") or "").strip()[:128],
            app_version=str(payload.get("app_version") or "").strip()[:32],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "provider": "fcm", "configured": bool(config.FCM_CREDENTIALS_FILE)}


@app.delete("/api/devices/fcm")
async def unregister_fcm_device(payload: dict[str, Any] = Body(default={}), user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    unregister_fcm_token(user, str(payload.get("token") or ""))
    return {"status": "ok"}


@app.get("/api/notifications")
async def notifications(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    items = []
    for item in list_notifications(user):
        items.append(
            {
                **item,
                "content": item.get("body") or item.get("content") or "",
                "timestamp": item.get("timestamp") or 0,
            }
        )
    return items


@app.websocket("/api/notifications/ws")
async def notifications_websocket(websocket: WebSocket, token: str = Query(default="")) -> None:
    if config.RELAY_ONLY:
        await websocket.close(code=4404)
        return
    user = user_from_token(str(token or "").strip())
    if not user:
        await websocket.close(code=4401)
        return
    user_id = str(user.get("id") or "")
    queue = subscribe_live_notifications(user_id)
    await websocket.accept()
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json({"type": "notification", "item": {**item, "content": item.get("body") or ""}})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        unsubscribe_live_notifications(user_id, queue)


@app.get("/api/tibo/history")
async def tibo_history(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = list_tibo_history()
    payload["enabled"] = bool(user.get("tibo", {}).get("enabled", False))
    payload["x_connected"] = bool(user.get("tibo", {}).get("x_cookies_encrypted"))
    return payload


@app.post("/api/tibo/x-session")
async def tibo_x_session(request: Request, payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Import the user's own X cookie (douyin-style hybrid envelope)."""
    _rate_limit(request, "tibo-x-session", str(user.get("id") or ""), 5, 3600)
    try:
        cookie_text = decrypt_hybrid_secret(payload, max_plaintext=64 * 1024)
        cookies = tibo.parse_x_cookie_text(cookie_text)
        await tibo.verify_x_cookies(cookies)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"X Cookie 校验失败：{exc}") from exc
    set_tibo_x_cookies(user.setdefault("tibo", {}), cookies)
    save_user(user)
    return {"valid": True, "message": "X Cookie 校验成功并已保存", "user": public_user(user)}


@app.delete("/api/tibo/x-session")
async def delete_tibo_x_session(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    clear_tibo_x_cookies(user.setdefault("tibo", {}))
    save_user(user)
    return {"success": True, "message": "X Cookie 已移除", "user": public_user(user)}


@app.put("/api/tibo/config")
async def update_tibo_config(
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled"))
    user.setdefault("tibo", {})["enabled"] = enabled
    save_user(user)
    return {
        "success": True,
        "enabled": enabled,
        "message": "Tibo 推送已开启" if enabled else "Tibo 推送已关闭",
    }


@app.post("/api/notifications/read")
async def read_notifications(payload: dict[str, Any] = Body(default={}), user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    mark_read(user["id"], payload.get("id"))
    return {"status": "ok"}


@app.post("/api/student/bind")
async def bind_student(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    try:
        fields = decrypt_transport_payload(payload, ("student_id", "password"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    student_id = fields["student_id"].strip()
    password = fields["password"]
    if not student_id or not password:
        raise HTTPException(status_code=400, detail="学号和密码不能为空")
    try:
        uid, sess, real_name, cookies = await perform_duaa_login(student_id, password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"统一认证失败：{exc}") from exc
    user["student"].update(
        {
            "student_id": student_id,
            "real_name": real_name,
            "uid": uid,
            "session_id": sess,
            "cookies": cookies,
            "status": "verified",
        }
    )
    set_student_password(user["student"], password)
    save_user(user)
    return {"success": True, "message": "学生认证成功，相关校园功能已可使用", "user": public_user(user)}


@app.get("/api/student")
async def student_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return student_payload(user)


@app.get("/api/home")
async def home_summary(cached: int = Query(default=1), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    ensure_approvals(user)
    approvals = user.get("approvals") or {}
    try:
        schedule = await load_schedule(user, use_cache=bool(cached))
    except Exception as exc:
        schedule = {
            "schedule": [],
            "enabled": bool((user.get("student") or {}).get("auto_signin")),
            "message": str(exc),
            "cached": True,
        }

    home_cache = user.setdefault("home_cache", {})
    td_payload = home_cache.get("td")
    sunshine_payload = home_cache.get("sunshine")
    can_query_td = bool((user.get("student") or {}).get("student_id"))
    if not cached and can_query_td:
        td_result, sunshine_result = await asyncio.gather(load_td(user), load_sunshine(user), return_exceptions=True)
        if isinstance(td_result, Exception):
            td_payload = {"semester_count": 0, "target_count": 32, "status": "error", "message": str(td_result)}
        else:
            td_payload = td_result
            home_cache["td"] = td_result
        if isinstance(sunshine_result, Exception):
            sunshine_payload = {"count": 0, "target_count": 16, "message": str(sunshine_result)}
        else:
            sunshine_payload = sunshine_result
            home_cache["sunshine"] = sunshine_result
        home_cache["updated_at"] = now_iso()
        save_user(user)

    return {
        "user": public_user(user),
        "student": student_payload(user),
        "schedule": schedule,
        "td": td_payload,
        "sunshine": sunshine_payload,
        "cached": bool(cached),
    }


@app.post("/api/student/request")
async def request_feature(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _ = payload
    ensure_approvals(user)
    return {"success": True, "message": "审批模式已取消，功能默认开放", "user": public_user(user)}


@app.get("/api/invites/stats")
async def get_invite_stats(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _require_invite_admin(user)
    return invite_stats()


@app.post("/api/invites/issue")
async def get_unused_invite(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _require_invite_admin(user)
    try:
        result = issue_invite(str(user.get("username") or "muzermat"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, **result}


@app.get("/api/signin/schedule")
async def signin_schedule(cached: int = Query(default=0), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_student(user)
    try:
        return await load_schedule(user, use_cache=bool(cached))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"课表查询失败：{exc}") from exc


@app.post("/api/signin/auto")
async def toggle_auto(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    student = require_feature(user, "signin")
    enabled = bool(payload.get("enabled"))
    student["auto_signin"] = enabled
    save_user(user)
    return {"success": True, "message": "自动签到已开启" if enabled else "自动签到已关闭", "auto_signin": enabled, "user": public_user(user)}


@app.get("/api/td/status")
async def td_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    try:
        result = await load_td(user)
        user.setdefault("home_cache", {})["td"] = result
        user["home_cache"]["updated_at"] = now_iso()
        save_user(user)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/td/photos")
async def td_photos(
    entrance: UploadFile | None = File(default=None),
    exit: UploadFile | None = File(default=None),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_feature(user, "td")
    folder = photo_dir(user["id"])
    saved = []
    if entrance is not None:
        (folder / "entrance.jpg").write_bytes(await entrance.read())
        saved.append("entrance")
    if exit is not None:
        (folder / "exit.jpg").write_bytes(await exit.read())
        saved.append("exit")
    if not saved:
        raise HTTPException(status_code=400, detail="请选择入口图或出口图")
    return {"success": True, "message": "照片已保存", "saved": saved}


@app.post("/api/td/manual")
async def td_manual(payload: dict[str, Any] = Body(default={}), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    student = require_feature(user, "td")
    campus = str(payload.get("campus") or user.get("td", {}).get("campus") or "xueyuanlu").strip().casefold()
    campus = {"学院路": "xueyuanlu", "沙河": "shahe"}.get(campus, campus)
    if campus not in td.MACHINES:
        raise HTTPException(status_code=400, detail="校区参数无效")
    try:
        entrance_machine_id = int(payload.get("entrance_machine_id") or user.get("td", {}).get("entrance_machine_id") or td.MACHINES[campus]["entrance"][0]["id"])
        exit_machine_id = int(payload.get("exit_machine_id") or user.get("td", {}).get("exit_machine_id") or td.MACHINES[campus]["exit"][0]["id"])
        gap_seconds = int(payload.get("gap_seconds") or user.get("td", {}).get("gap_seconds") or 240)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="TD 打卡参数格式不正确") from exc
    valid_entrances = {item["id"] for item in td.MACHINES[campus]["entrance"]}
    valid_exits = {item["id"] for item in td.MACHINES[campus]["exit"]}
    if entrance_machine_id not in valid_entrances or exit_machine_id not in valid_exits:
        raise HTTPException(status_code=400, detail="所选打卡机不属于当前校区")
    if not 60 <= gap_seconds <= 15 * 60:
        raise HTTPException(status_code=400, detail="入口至出口时间差需为 1～15 分钟")

    photos = photo_dir(user["id"])
    entrance_path = photos / "entrance.jpg"
    exit_path = photos / "exit.jpg"
    if not entrance_path.exists() or not exit_path.exists():
        raise HTTPException(status_code=400, detail="请先保存入口和出口打卡照片")
    try:
        result = await asyncio.to_thread(
            td.manual_td,
            student["student_id"],
            entrance_machine_id,
            exit_machine_id,
            entrance_path.read_bytes(),
            exit_path.read_bytes(),
            gap_seconds,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"TD 打卡失败：{exc}") from exc
    user.setdefault("td", {}).update(
        {
            "campus": campus,
            "entrance_machine_id": entrance_machine_id,
            "exit_machine_id": exit_machine_id,
            "gap_seconds": gap_seconds,
        }
    )
    save_user(user)
    return result


def _checkin_provider(provider_id: Any) -> Any:
    try:
        return get_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/checkin/providers")
async def checkin_providers(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"providers": list_providers()}


@app.get("/api/checkin/{provider}/config")
async def checkin_config(provider: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    module = _checkin_provider(provider)
    cfg = (user.get("checkin") or {}).get(module.PROVIDER_ID) or {}
    try:
        token = get_checkin_token(cfg)
    except ValueError:
        token = ""
    return {
        "provider": module.PROVIDER_ID,
        "connected": bool(token),
        "token_tail": token[-6:] if token else "",
    }


@app.put("/api/checkin/{provider}/config")
async def checkin_save_config(
    request: Request,
    provider: str,
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    module = _checkin_provider(provider)
    _rate_limit(request, "checkin-config", str(user.get("id") or ""), 10, 3600)
    try:
        token = module.validate_token(decrypt_transport_payload(payload, ("token",))["token"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not await module.check_token(token):
        raise HTTPException(status_code=400, detail="签到 token 无效或已过期，请重新从小程序获取")
    user.setdefault("checkin", {}).setdefault(module.PROVIDER_ID, {})
    set_checkin_token(user["checkin"][module.PROVIDER_ID], token)
    save_user(user)
    return {
        "provider": module.PROVIDER_ID,
        "connected": True,
        "token_tail": token[-6:],
        "message": "签到 token 已保存并验证有效",
    }


def _checkin_token(user: dict[str, Any], module: Any) -> str:
    cfg = (user.get("checkin") or {}).get(module.PROVIDER_ID) or {}
    try:
        token = get_checkin_token(cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not token:
        raise HTTPException(status_code=400, detail="请先配置签到 token")
    return token


@app.post("/api/checkin/{provider}/preview")
async def checkin_preview(
    request: Request,
    provider: str,
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    module = _checkin_provider(provider)
    _rate_limit(request, "checkin-preview", str(user.get("id") or ""), 40, 600)
    token = _checkin_token(user, module)
    try:
        activity = await module.fetch_activity(token, payload.get("code"))
    except CheckinAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CheckinError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"activity": activity}


@app.post("/api/checkin/{provider}/sign")
async def checkin_sign(
    request: Request,
    provider: str,
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    module = _checkin_provider(provider)
    _rate_limit(request, "checkin-sign", str(user.get("id") or ""), 15, 3600)
    token = _checkin_token(user, module)
    try:
        result = await module.submit_sign(
            token,
            payload.get("code"),
            payload.get("values"),
            payload.get("options") or {},
        )
    except CheckinAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CheckinError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.get("/api/sunshine/status")
async def sunshine_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    try:
        result = await load_sunshine(user)
        user.setdefault("home_cache", {})["sunshine"] = result
        user["home_cache"]["updated_at"] = now_iso()
        save_user(user)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/douyin/qr/start")
async def douyin_qr_start(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="抖音扫码登录已停用，请使用 Cookie 导入完成账号绑定",
    )


@app.get("/api/douyin/qr/status")
async def douyin_qr_status(login_id: str = Query(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _ = login_id
    raise HTTPException(
        status_code=410,
        detail="抖音扫码登录已停用，请使用 Cookie 导入完成账号绑定",
    )


@app.post("/api/douyin/qr/cancel")
async def douyin_qr_cancel(payload: dict[str, Any] = Body(default={}), user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    _ = payload
    return {"status": "ok"}


@app.post("/api/douyin/session")
async def douyin_session(request: Request, payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _rate_limit(request, "douyin-session", str(user.get("id") or ""), 5, 3600)
    try:
        cookie_text = decrypt_hybrid_secret(payload, max_plaintext=256 * 1024)
        cookies = normalize_cookies(cookie_text)
        cookies, detected_name = await asyncio.to_thread(validate_douyin_cookies, cookies)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.setdefault("douyin", {})
    set_douyin_cookies(user["douyin"], cookies)
    set_douyin_friends_cache(user["douyin"], [])
    user["douyin"]["friends_cache_initialized"] = False
    user["douyin"].pop("friends_cached_at", None)
    # A Cookie import may represent a different Douyin account. Reusing the
    # previous account's conversation ids could send to an unintended target.
    user["douyin"]["enabled"] = False
    user["douyin"]["targets"] = []
    user["douyin"]["target_status"] = {}
    user["douyin"].pop("auto_progress_date", None)
    user["douyin"].pop("auto_completed_target_keys", None)
    user["douyin"].pop("auto_blocked_date", None)
    user["douyin"].pop("auto_blocked_reason", None)
    user["douyin"]["username"] = str(
        payload.get("username")
        or detected_name
        or user["douyin"].get("username")
        or user.get("display_name")
        or "抖音用户"
    )
    save_user(user)
    return {
        "valid": True,
        "nickname": user["douyin"]["username"],
        "message": "抖音 Cookie 校验成功并已保存",
        "user": public_user(user),
    }


@app.get("/api/douyin/session")
async def get_douyin_session(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    dy = public_user(user)["douyin"]
    return {
        "valid": bool(dy.get("connected")),
        "nickname": dy.get("username") or None,
        "douyin": dy,
        "enabled": dy.get("enabled"),
        "default_message": dy.get("default_message"),
        "targets": dy.get("targets"),
        "hour": dy.get("hour"),
    }


def _normalize_friend_cache(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    friends: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        conversation_id = str(item.get("conversation_id") or "").strip()
        raw_type = str(item.get("conversation_type") or "").strip().lower()
        conversation_type = raw_type if raw_type in {"direct", "group"} else ""
        if not name:
            continue
        key = f"id:{conversation_id}" if conversation_id else f"{conversation_type or 'unknown'}:{name}"
        if key in seen:
            continue
        seen.add(key)
        friends.append(
            {
                "name": name,
                "avatar_url": str(item.get("avatar_url") or ""),
                "conversation_id": conversation_id,
                "conversation_short_id": str(item.get("conversation_short_id") or "").strip(),
                "conversation_type": conversation_type,
            }
        )
    return friends


def _enrich_spark_targets(cfg: dict[str, Any], friends: list[dict[str, str]]) -> bool:
    changed = False
    by_name: dict[str, list[dict[str, str]]] = {}
    for friend in friends:
        by_name.setdefault(friend["name"], []).append(friend)
    enriched: list[dict[str, str]] = []
    for raw in cfg.get("targets") or []:
        if not isinstance(raw, dict):
            continue
        target = normalize_target(raw)
        matches = by_name.get(target["name"], [])
        if not target["conversation_id"] and len(matches) == 1 and matches[0].get("conversation_id"):
            friend = matches[0]
            target["conversation_id"] = friend["conversation_id"]
            target["conversation_short_id"] = friend.get("conversation_short_id", "")
            target["conversation_type"] = friend.get("conversation_type", "")
            changed = True
        enriched.append(target)
    if enriched != (cfg.get("targets") or []):
        cfg["targets"] = enriched
        changed = True
    return changed


@app.get("/api/douyin/friends")
async def douyin_friends(
    request: Request,
    query: str = Query("", max_length=64),
    refresh: bool = Query(False),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    cfg = user.setdefault("douyin", {})
    cookies = get_douyin_cookies(cfg)
    if not cookies:
        raise HTTPException(status_code=400, detail="请先导入有效的抖音 Cookie")

    cache_exists = bool(cfg.get("friends_cache_initialized"))
    refreshed = bool(refresh or not cache_exists)
    if refreshed:
        if refresh:
            _rate_limit(request, "douyin-friends-refresh", str(user.get("id") or ""), 4, 3600)
        try:
            friends = await asyncio.to_thread(list_douyin_friends, cookies)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        friends = _normalize_friend_cache(friends)
        set_douyin_friends_cache(cfg, friends)
        cfg["friends_cached_at"] = now_iso()
        _enrich_spark_targets(cfg, friends)
        save_user(user)
    else:
        friends = _normalize_friend_cache(get_douyin_friends_cache(cfg))
        if _enrich_spark_targets(cfg, friends):
            save_user(user)

    total = len(friends)
    needle = query.strip().casefold()
    if needle:
        friends = [friend for friend in friends if needle in friend["name"].casefold()]
    return {
        "query": query.strip(),
        "count": len(friends),
        "total": total,
        "friends": friends,
        "cached": not refreshed,
        "cached_at": str(cfg.get("friends_cached_at") or ""),
    }


@app.put("/api/douyin/config")
async def douyin_config(request: Request, payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _rate_limit(request, "douyin-config", str(user.get("id") or ""), 30, 60)
    cfg = user.setdefault("douyin", {})
    try:
        previous_hour = max(0, min(int(cfg.get("hour", 9)), 23))
    except (TypeError, ValueError):
        previous_hour = 9
    if "enabled" in payload:
        cfg["enabled"] = bool(payload.get("enabled"))
    if "default_message" in payload:
        default_message = str(payload.get("default_message") or "续火花").strip()
        if len(default_message) > MAX_MESSAGE_LENGTH:
            raise HTTPException(status_code=400, detail=f"默认文案不能超过 {MAX_MESSAGE_LENGTH} 个字符")
        cfg["default_message"] = default_message
    if "hour" in payload:
        try:
            raw_hour = payload.get("hour")
            cfg["hour"] = max(0, min(int(9 if raw_hour in (None, "") else raw_hour), 23))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="自动发送时间必须是 0 到 23 的整数") from exc
        if cfg["hour"] != previous_hour:
            for key in (
                "auto_schedule_date",
                "auto_schedule_hour",
                "auto_schedule_offset_minutes",
                "auto_scheduled_at",
            ):
                cfg.pop(key, None)
    if "targets" in payload:
        raw_targets = [item for item in (payload.get("targets") or []) if isinstance(item, dict)]
        if len(raw_targets) > MAX_SPARK_TARGETS:
            raise HTTPException(status_code=400, detail=f"续火花目标不能超过 {MAX_SPARK_TARGETS} 个")
        try:
            targets = validate_spark_targets(raw_targets, require_identity=bool(payload.get("enabled", cfg.get("enabled")))) if raw_targets else []
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        cfg["targets"] = targets
    if cfg.get("enabled"):
        try:
            validate_spark_targets([item for item in cfg.get("targets") or [] if isinstance(item, dict)], require_identity=True)
        except ValueError as exc:
            cfg["enabled"] = False
            save_user(user)
            raise HTTPException(status_code=400, detail=f"无法开启自动续火花：{exc}") from exc
        if cfg.get("auto_blocked_reason") == "target_invalid":
            cfg.pop("auto_blocked_date", None)
            cfg.pop("auto_blocked_reason", None)
    save_user(user)
    return {"success": True, "message": "火花配置已保存", "user": public_user(user)}


@app.post("/api/douyin/run")
async def douyin_run(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    _rate_limit(request, "douyin-run", str(user.get("id") or ""), 3, 3600)
    try:
        result = await asyncio.to_thread(run_spark, user)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_user(user)
    result["success"] = bool(result.get("success"))
    result["message"] = "续火花完成" if result.get("success") else "续火花未全部成功"
    return result


@app.post("/api/douyin/run-target")
async def douyin_run_target(
    request: Request,
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Send one real test message to one already-configured stable conversation."""
    # Share the same budget with the full manual run so the single-target
    # helper cannot be used to bypass the manual automation rate limit.
    _rate_limit(request, "douyin-run", str(user.get("id") or ""), 3, 3600)
    target_key = str(payload.get("target_key") or "").strip()
    if not target_key or len(target_key) > 300:
        raise HTTPException(status_code=400, detail="请选择一个有效的续火花目标")

    cfg = user.setdefault("douyin", {})
    try:
        configured = validate_spark_targets(
            [item for item in cfg.get("targets") or [] if isinstance(item, dict)],
            require_identity=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target = next((item for item in configured if target_identity(item) == target_key), None)
    if target is None:
        raise HTTPException(status_code=404, detail="该续火花目标不存在，请刷新页面后重试")

    try:
        result = await asyncio.to_thread(run_spark, user, targets_override=[target])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_user(user)
    result["success"] = bool(result.get("success"))
    result["single_target"] = True
    result["target"] = target["name"]
    result["message"] = (
        f"已向“{target['name']}”发送测试续火花消息"
        if result.get("success")
        else f"向“{target['name']}”发送测试消息失败"
    )
    return result



WEB_DIR = Path(__file__).resolve().parent / "web"


@app.get("/")
async def web_root():
    index = WEB_DIR / "index.html"
    if not index.exists():
        return {"name": "muztools"}
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/index.html")
async def web_index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/assets/aes-gcm.min.js")
async def web_aes_gcm():
    return FileResponse(
        WEB_DIR / "aes-gcm.min.js",
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/downloads/muz-checkin-token-macos.zip")
async def download_checkin_token_macos():
    return FileResponse(
        WEB_DIR / "MuzTool-Checkin-Token-macOS.zip",
        filename="MuzTool-Checkin-Token-macOS.zip",
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
