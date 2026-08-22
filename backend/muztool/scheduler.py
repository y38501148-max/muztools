from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .notify import push_notification, signin_success_message
from .signin_core import TZ_BEIJING, safe_execute_sign_in, safe_fetch_schedule
from .store import iter_users, save_user


scheduler = AsyncIOScheduler(timezone=TZ_BEIJING)


def _approved_auto_users() -> list[dict[str, Any]]:
    return [
        user
        for user in iter_users()
        if user.get("student", {}).get("status") == "approved" and user.get("student", {}).get("auto_signin")
    ]


async def daily_sync() -> None:
    today = datetime.now(TZ_BEIJING).strftime("%Y%m%d")
    for user in _approved_auto_users():
        acc = user["student"]
        try:
            sched, _auth = await safe_fetch_schedule(acc, today)
            for course in sched:
                begin = course.get("classBeginTime", "")
                if begin:
                    dt = datetime.strptime(begin.split(" ")[-1][:5], "%H:%M")
                    course["auto_sign_trigger_hm"] = (dt - timedelta(minutes=random.randint(3, 9))).strftime("%H:%M")
                    course["retries"] = 0
            acc["today_schedule"] = sched
            acc["schedule_date"] = today
            save_user(user)
            if sched:
                push_notification(
                    user,
                    "自动签到",
                    f"今日检测到 {len(sched)} 节课，已安排自动签到。",
                    "signin",
                )
        except Exception as exc:
            push_notification(user, "自动签到", f"今日课表同步失败：{exc}", "signin")


async def auto_checkin_executor() -> None:
    now_hm = datetime.now(TZ_BEIJING).strftime("%H:%M")
    today = datetime.now(TZ_BEIJING).strftime("%Y%m%d")
    for user in _approved_auto_users():
        acc = user["student"]
        if acc.get("schedule_date") != today:
            continue
        changed = False
        for course in acc.get("today_schedule", []):
            trig = course.get("auto_sign_trigger_hm")
            if trig and now_hm >= trig and str(course.get("signStatus")) != "1" and course.get("retries", 0) < 30:
                course["retries"] = course.get("retries", 0) + 1
                changed = True
                try:
                    res, _auth = await safe_execute_sign_in(acc, course["id"], force_refresh=course["retries"] == 1)
                    ok = str(res.get("STATUS")) == "0" and str(res.get("result", {}).get("stuSignStatus")) == "1"
                    err = res.get("ERRMSG", "")
                    if ok or "已签到" in err:
                        course["signStatus"] = "1"
                        body = signin_success_message(acc.get("real_name") or user.get("display_name"), course.get("courseName") or "课程", now_hm)
                        push_notification(user, "签到提示", body, "signin")
                    elif "结束" in err or ("课程" in err and "不存在" in err):
                        course["retries"] = 99
                except Exception:
                    pass
        if changed:
            save_user(user)


async def douyin_hourly() -> None:
    hour = datetime.now(TZ_BEIJING).hour
    from .douyin import run_spark

    for user in iter_users():
        cfg = user.get("douyin") or {}
        if not cfg.get("enabled") or int(cfg.get("hour") or 9) != hour:
            continue
        today = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")
        if str(cfg.get("last_run") or "").startswith(today):
            continue
        try:
            result = run_spark(user)
            save_user(user)
            ok = result.get("success")
            push_notification(user, "抖音续火花", "今日续火花已完成" if ok else f"续火花部分失败：{result}", "douyin")
        except Exception as exc:
            push_notification(user, "抖音续火花", f"续火花失败：{exc}", "douyin")


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(daily_sync, "cron", hour=7, minute=0, id="signin_daily_sync", replace_existing=True)
    scheduler.add_job(auto_checkin_executor, "cron", minute="*", id="signin_auto", replace_existing=True)
    scheduler.add_job(douyin_hourly, "cron", minute=5, id="douyin_hourly", replace_existing=True)
    scheduler.start()
