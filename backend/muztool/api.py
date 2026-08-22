from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import appver, sunshine, td
from .config import ensure_dirs
from .douyin import normalize_cookies, run_spark
from .notify import list_notifications, mark_read
from .scheduler import start_scheduler
from .signin_core import perform_duaa_login, safe_fetch_schedule
from .store import (
    FEATURE_KEYS,
    authenticate,
    create_session,
    create_user,
    delete_session,
    ensure_approvals,
    photo_dir,
    public_user,
    save_user,
    set_feature_approval,
    user_from_token,
)

app = FastAPI(title="muztools", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
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
    student = require_student(user)
    ensure_approvals(user)
    if user.get("approvals", {}).get(feature) != "approved":
        names = {"signin": "自动签到", "td": "TD", "spark": "抖音续火花"}
        raise HTTPException(status_code=403, detail=f"{names.get(feature, feature)}尚未通过审批")
    return student


@app.on_event("startup")
async def on_startup() -> None:
    ensure_dirs()
    appver.load_version()
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



@app.post("/api/auth/register")
async def register(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    display_name = str(payload.get("display_name") or username).strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    try:
        user = create_user(username, password, display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = create_session(user["id"])
    return {"token": token, "user": public_user(user)}


@app.post("/api/auth/login")
async def login(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        user = authenticate(str(payload.get("username") or ""), str(payload.get("password") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = create_session(user["id"])
    return {"token": token, "user": public_user(user)}


@app.post("/api/auth/logout")
async def logout(user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    delete_session(user.get("_token", ""))
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


@app.post("/api/notifications/read")
async def read_notifications(payload: dict[str, Any] = Body(default={}), user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    mark_read(user["id"], payload.get("id"))
    return {"status": "ok"}


@app.post("/api/student/bind")
async def bind_student(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    student_id = str(payload.get("student_id") or "").strip()
    password = str(payload.get("password") or "")
    if not student_id or not password:
        raise HTTPException(status_code=400, detail="学号和密码不能为空")
    try:
        uid, sess, real_name, cookies = await perform_duaa_login(student_id, password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"统一认证失败：{exc}") from exc
    user["student"].update(
        {
            "student_id": student_id,
            "password": password,
            "real_name": real_name,
            "uid": uid,
            "session_id": sess,
            "cookies": cookies,
            "status": "verified",
        }
    )
    ensure_approvals(user)
    save_user(user)
    return {"success": True, "message": "学生认证成功，请分别申请自动签到 / TD / 续火花", "user": public_user(user)}


@app.get("/api/student")
async def student_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = public_user(user)
    student = payload["student"]
    approvals = payload.get("approvals", {})
    return {
        "status": student.get("status") or "unbound",
        "student_id": student.get("student_id"),
        "display_name": student.get("real_name") or user.get("display_name"),
        "student": student,
        "approvals": approvals,
        "signin_status": approvals.get("signin", "none"),
        "td_status": approvals.get("td", "none"),
        "spark_status": approvals.get("spark", "none"),
    }


@app.post("/api/student/request")
async def request_feature(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_student(user)
    feature = str(payload.get("feature") or "").strip()
    if feature not in FEATURE_KEYS:
        raise HTTPException(status_code=400, detail="功能须为 signin / td / spark")
    current = ensure_approvals(user)["approvals"].get(feature)
    if current == "approved":
        return {"success": True, "message": "该功能已通过审批", "user": public_user(user)}
    set_feature_approval(user, feature, "pending")
    save_user(user)
    return {"success": True, "message": "已提交审批申请", "user": public_user(user)}


@app.get("/api/signin/schedule")
async def signin_schedule(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    from datetime import datetime
    from .signin_core import TZ_BEIJING

    student = require_student(user)
    today = datetime.now(TZ_BEIJING).strftime("%Y%m%d")
    try:
        sched, _auth = await safe_fetch_schedule(student, today)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"课表查询失败：{exc}") from exc
    old = {item.get("id"): item.get("auto_sign_trigger_hm") for item in student.get("today_schedule", [])}
    for course in sched:
        course["auto_sign_trigger_hm"] = old.get(course.get("id"), course.get("auto_sign_trigger_hm"))
    student["today_schedule"] = sched
    student["schedule_date"] = today
    save_user(user)
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
    return {
        "date": today,
        "courses": sched,
        "schedule": schedule,
        "enabled": bool(student.get("auto_signin")),
        "approved": ensure_approvals(user)["approvals"].get("signin") == "approved",
        "auto_signin": bool(student.get("auto_signin")),
    }


@app.post("/api/signin/auto")
async def toggle_auto(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    student = require_feature(user, "signin")
    enabled = bool(payload.get("enabled"))
    student["auto_signin"] = enabled
    save_user(user)
    return {"success": True, "message": "自动签到已开启" if enabled else "自动签到已关闭", "auto_signin": enabled, "user": public_user(user)}


@app.get("/api/td/status")
async def td_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    student = require_feature(user, "td")
    try:
        rows = await td.query_td_counts(student["student_id"], student["password"])
        latest = td.latest_count(rows)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    _ = (payload, user)
    raise HTTPException(status_code=400, detail="手动 TD 需在校园网由手机端直接向 TD 服务器发起，后端不再代发")


@app.get("/api/sunshine/status")
async def sunshine_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    try:
        data = await sunshine.query_sunshine(student["student_id"], student["password"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data["count"] = data.get("term_count", 0)
    data["target_count"] = data.get("term_target", 16)
    return data


@app.post("/api/douyin/session")
async def douyin_session(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_feature(user, "spark")
    try:
        cookies = normalize_cookies(payload.get("cookies"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user["douyin"]["cookies"] = cookies
    user["douyin"]["username"] = str(payload.get("username") or user["douyin"].get("username") or "")
    save_user(user)
    return {"valid": True, "nickname": user["douyin"].get("username") or user.get("display_name"), "user": public_user(user)}


@app.get("/api/douyin/session")
async def get_douyin_session(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_feature(user, "spark")
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


@app.put("/api/douyin/config")
async def douyin_config(payload: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_feature(user, "spark")
    cfg = user.setdefault("douyin", {})
    if "enabled" in payload:
        cfg["enabled"] = bool(payload.get("enabled"))
    if "default_message" in payload:
        cfg["default_message"] = str(payload.get("default_message") or "续火花")
    if "hour" in payload:
        cfg["hour"] = max(0, min(int(payload.get("hour") or 9), 23))
    if "targets" in payload:
        targets = []
        for item in payload.get("targets") or []:
            name = str(item.get("name") or "").strip()
            if name:
                targets.append({"name": name, "message": str(item.get("message") or "")})
        cfg["targets"] = targets
    save_user(user)
    return {"success": True, "message": "火花配置已保存", "user": public_user(user)}


@app.post("/api/douyin/run")
async def douyin_run(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_feature(user, "spark")
    try:
        result = run_spark(user)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_user(user)
    result["success"] = bool(result.get("success"))
    result["message"] = "续火花完成" if result.get("success") else "续火花未全部成功"
    return result
