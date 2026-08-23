from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .notify import push_notification, signin_success_message
from .signin_core import TZ_BEIJING, safe_execute_sign_in, safe_fetch_schedule
from .store import iter_users, save_user, student_runtime


scheduler = AsyncIOScheduler(timezone=TZ_BEIJING)
logger = logging.getLogger(__name__)
AUTO_SPARK_RETRY_INTERVAL = timedelta(minutes=10)


def _auto_signin_users() -> list[dict[str, Any]]:
    # Historical name retained for compatibility; approval mode was removed.
    return [user for user in iter_users() if user.get("student", {}).get("auto_signin")]


def _parse_beijing_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ_BEIJING)
    return parsed.astimezone(TZ_BEIJING)


def should_run_douyin_auto(cfg: dict[str, Any], now: datetime | None = None) -> bool:
    """Return whether today's automatic spark task is due.

    Manual runs only update ``last_run`` and intentionally do not affect this
    decision. A missed configured minute is caught up later the same day.
    """
    current = (now or datetime.now(TZ_BEIJING)).astimezone(TZ_BEIJING)
    if not cfg.get("enabled"):
        return False
    try:
        hour = max(0, min(int(cfg.get("hour", 9)), 23))
    except (TypeError, ValueError):
        hour = 9
    scheduled_at = current.replace(hour=hour, minute=0, second=0, microsecond=0)
    if current < scheduled_at:
        return False

    today = current.date()
    last_auto_run = _parse_beijing_iso(cfg.get("last_auto_run"))
    if last_auto_run and last_auto_run.date() == today:
        return False

    last_attempt = _parse_beijing_iso(cfg.get("last_auto_attempt"))
    if last_attempt and last_attempt.date() == today and current - last_attempt < AUTO_SPARK_RETRY_INTERVAL:
        return False
    return True


async def daily_sync() -> None:
    today = datetime.now(TZ_BEIJING).strftime("%Y%m%d")
    for user in _auto_signin_users():
        acc = user["student"]
        runtime = student_runtime(acc)
        try:
            sched, _auth = await safe_fetch_schedule(runtime, today)
            for key in ("uid", "session_id", "cookies"):
                if key in runtime:
                    acc[key] = runtime[key]
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
    for user in _auto_signin_users():
        acc = user["student"]
        runtime = student_runtime(acc)
        if acc.get("schedule_date") != today:
            continue
        changed = False
        for course in acc.get("today_schedule", []):
            trig = course.get("auto_sign_trigger_hm")
            if trig and now_hm >= trig and str(course.get("signStatus")) != "1" and course.get("retries", 0) < 30:
                course["retries"] = course.get("retries", 0) + 1
                changed = True
                try:
                    res, _auth = await safe_execute_sign_in(runtime, course["id"], force_refresh=course["retries"] == 1)
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
            for key in ("uid", "session_id", "cookies"):
                if key in runtime:
                    acc[key] = runtime[key]
            save_user(user)


async def douyin_hourly() -> None:
    """Run due automatic spark jobs.

    The historical function name is kept to avoid breaking imports, while the
    scheduler now invokes it every minute and catches up after the configured
    time if the service was temporarily unavailable.
    """
    from .douyin import run_spark

    for user in iter_users():
        cfg = user.setdefault("douyin", {})
        now = datetime.now(TZ_BEIJING)
        if not should_run_douyin_auto(cfg, now):
            continue

        cfg["last_auto_attempt"] = now.isoformat(timespec="seconds")
        save_user(user)
        try:
            result = await asyncio.to_thread(run_spark, user)
            rows = result.get("results") if isinstance(result, dict) else []
            rows = rows if isinstance(rows, list) else []
            succeeded = sum(1 for item in rows if isinstance(item, dict) and item.get("ok"))
            total = len(rows)
            completed = bool(result.get("success")) or succeeded > 0
            if completed:
                cfg["last_auto_run"] = datetime.now(TZ_BEIJING).isoformat(timespec="seconds")
            save_user(user)

            if result.get("success"):
                body = f"今日自动续火花已完成，共发送 {succeeded} 条。"
            elif succeeded:
                body = f"今日自动续火花已执行，成功 {succeeded} 条、失败 {max(total - succeeded, 0)} 条。"
            else:
                body = "本次自动续火花未成功，将在稍后自动重试。"
            push_notification(user, "抖音续火花", body, "douyin")
        except Exception:
            save_user(user)
            push_notification(user, "抖音续火花", "自动续火花执行失败，将在稍后自动重试。", "douyin")



async def tibo_monitor() -> None:
    from .tibo import check_tibo_updates

    try:
        await check_tibo_updates()
    except Exception:
        # A failed X request must not affect sign-in or spark scheduling. The
        # next hourly run will retry without marking unread posts as seen.
        logger.exception("Tibo X monitor failed")

def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(daily_sync, "cron", hour=7, minute=0, id="signin_daily_sync", replace_existing=True)
    scheduler.add_job(auto_checkin_executor, "cron", minute="*", id="signin_auto", replace_existing=True)
    scheduler.add_job(douyin_hourly, "cron", minute="*", id="douyin_hourly", replace_existing=True)
    scheduler.add_job(
        tibo_monitor,
        "interval",
        hours=1,
        next_run_time=datetime.now(TZ_BEIJING),
        id="tibo_monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
