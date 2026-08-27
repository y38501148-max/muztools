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
AUTO_SPARK_JITTER_MINUTES = 5


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


def ensure_douyin_auto_schedule(
    cfg: dict[str, Any],
    now: datetime | None = None,
    *,
    jitter_offset: int | None = None,
) -> datetime:
    """Return and persist today's stable randomized automatic send time.

    The offset is selected once per Beijing calendar day and base hour. It is
    then reused by every minute-level scheduler check, so the due time cannot
    drift while the process is running or after a service restart.
    """
    current = (now or datetime.now(TZ_BEIJING)).astimezone(TZ_BEIJING)
    try:
        hour = max(0, min(int(cfg.get("hour", 9)), 23))
    except (TypeError, ValueError):
        hour = 9
    today = current.date().isoformat()
    stored = _parse_beijing_iso(cfg.get("auto_scheduled_at"))
    try:
        stored_hour = int(cfg.get("auto_schedule_hour"))
    except (TypeError, ValueError):
        stored_hour = -1
    if cfg.get("auto_schedule_date") == today and stored_hour == hour and stored is not None:
        return stored

    # Avoid crossing a calendar-day boundary because progress and safety-stop
    # state are intentionally keyed by Beijing date.
    minimum = 0 if hour == 0 else -AUTO_SPARK_JITTER_MINUTES
    maximum = 0 if hour == 23 else AUTO_SPARK_JITTER_MINUTES
    if jitter_offset is None:
        offset = random.randint(minimum, maximum)
    else:
        offset = max(minimum, min(int(jitter_offset), maximum))
    scheduled_at = current.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(minutes=offset)
    cfg["auto_schedule_date"] = today
    cfg["auto_schedule_hour"] = hour
    cfg["auto_schedule_offset_minutes"] = offset
    cfg["auto_scheduled_at"] = scheduled_at.isoformat(timespec="seconds")
    return scheduled_at


def should_run_douyin_auto(
    cfg: dict[str, Any],
    now: datetime | None = None,
    *,
    jitter_offset: int | None = None,
) -> bool:
    """Return whether today's automatic spark task is due.

    Manual runs only update ``last_run`` and intentionally do not affect this
    decision. A missed configured minute is caught up later the same day.
    """
    current = (now or datetime.now(TZ_BEIJING)).astimezone(TZ_BEIJING)
    if not cfg.get("enabled"):
        return False
    scheduled_at = ensure_douyin_auto_schedule(cfg, current, jitter_offset=jitter_offset)
    if current < scheduled_at:
        return False

    today = current.date()
    if str(cfg.get("auto_blocked_date") or "") == today.isoformat():
        return False
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
            else:
                push_notification(user, "自动签到", "您今天没有需要签到的课", "signin")
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
    """Run due automatic spark jobs with per-target progress and safety stops."""
    from .douyin import DouyinBusy, target_identity, validate_spark_targets, run_spark

    for user in iter_users():
        cfg = user.setdefault("douyin", {})
        now = datetime.now(TZ_BEIJING)
        schedule_before = (
            cfg.get("auto_schedule_date"),
            cfg.get("auto_schedule_hour"),
            cfg.get("auto_schedule_offset_minutes"),
            cfg.get("auto_scheduled_at"),
        )
        due = should_run_douyin_auto(cfg, now)
        schedule_after = (
            cfg.get("auto_schedule_date"),
            cfg.get("auto_schedule_hour"),
            cfg.get("auto_schedule_offset_minutes"),
            cfg.get("auto_scheduled_at"),
        )
        if schedule_after != schedule_before:
            save_user(user)
        if not due:
            continue

        today = now.date().isoformat()
        if cfg.get("auto_progress_date") != today:
            cfg["auto_progress_date"] = today
            cfg["auto_completed_target_keys"] = []
            cfg.pop("auto_blocked_date", None)
            cfg.pop("auto_blocked_reason", None)

        try:
            configured_targets = validate_spark_targets(
                [item for item in cfg.get("targets") or [] if isinstance(item, dict)],
                require_identity=True,
            )
        except Exception as exc:
            cfg["auto_blocked_date"] = today
            cfg["auto_blocked_reason"] = "target_invalid"
            cfg["last_auto_attempt"] = now.isoformat(timespec="seconds")
            save_user(user)
            push_notification(user, "抖音续火花", f"自动任务已暂停：{exc}", "douyin")
            continue

        completed_keys = {str(value) for value in cfg.get("auto_completed_target_keys") or []}
        remaining = [target for target in configured_targets if target_identity(target) not in completed_keys]
        if not remaining:
            cfg["last_auto_run"] = now.isoformat(timespec="seconds")
            save_user(user)
            continue

        cfg["last_auto_attempt"] = now.isoformat(timespec="seconds")
        save_user(user)
        try:
            result = await asyncio.to_thread(run_spark, user, targets_override=remaining, record_run=False)
        except DouyinBusy:
            # A manual task is still running. Leave progress untouched and retry later.
            continue
        except Exception:
            cfg["auto_blocked_date"] = today
            cfg["auto_blocked_reason"] = "unexpected"
            save_user(user)
            push_notification(user, "抖音续火花", "自动任务出现未分类错误，今日已停止重试。", "douyin")
            continue

        rows = result.get("results") if isinstance(result, dict) else []
        rows = rows if isinstance(rows, list) else []
        succeeded_keys = {str(item.get("target_key") or "") for item in rows if isinstance(item, dict) and item.get("ok")}
        completed_keys.update(key for key in succeeded_keys if key)
        cfg["auto_completed_target_keys"] = sorted(completed_keys)

        all_keys = {target_identity(target) for target in configured_targets}
        succeeded = len(succeeded_keys)
        failed_rows = [item for item in rows if isinstance(item, dict) and not item.get("ok")]
        halt_reason = str(result.get("halt_reason") or "")
        non_retryable = any(not item.get("retryable") for item in failed_rows)

        if all_keys and all_keys.issubset(completed_keys):
            cfg["last_auto_run"] = datetime.now(TZ_BEIJING).isoformat(timespec="seconds")
            cfg.pop("auto_blocked_date", None)
            cfg.pop("auto_blocked_reason", None)
            body = f"今日自动续火花已完成，本次成功 {succeeded} 条。"
        elif halt_reason or non_retryable:
            cfg["auto_blocked_date"] = today
            cfg["auto_blocked_reason"] = halt_reason or str(failed_rows[0].get("status") or "failed")
            body = f"自动任务已安全暂停：本次成功 {succeeded} 条，剩余目标今日不再自动重试。"
        else:
            remaining_count = len(all_keys - completed_keys)
            body = f"本次成功 {succeeded} 条，剩余 {remaining_count} 条将在稍后仅重试失败目标。"
        save_user(user)
        push_notification(user, "抖音续火花", body, "douyin")



async def tibo_monitor() -> None:
    from .tibo import (
        XAuthError,
        check_tibo_updates,
        fetch_tibo_posts_authenticated,
        get_user_x_cookies,
        iter_x_cookie_users,
        notify_x_cookie_expired,
    )

    def cookie_fetcher(cookies: dict[str, str]):
        async def fetch(_seen, now, _lookback):
            return await fetch_tibo_posts_authenticated(cookies, now)

        return fetch

    try:
        users = iter_x_cookie_users()
        if users:
            # Rotate the starting credential hourly so one account does not
            # carry the whole monitoring load.
            start = datetime.now(TZ_BEIJING).hour % len(users)
            for user in users[start:] + users[:start]:
                cookies = get_user_x_cookies(user)
                if not cookies:
                    continue
                try:
                    await check_tibo_updates(fetcher=cookie_fetcher(cookies))
                    return
                except XAuthError:
                    notify_x_cookie_expired(user, datetime.now(TZ_BEIJING))
                except Exception:
                    logger.warning("Tibo authenticated check failed, trying next credential", exc_info=True)
        await check_tibo_updates()
    except Exception:
        # A failed X request must not affect sign-in or spark scheduling. The
        # next hourly run will retry without marking unread posts as seen.
        logger.exception("Tibo X monitor failed")


async def notification_event_drain() -> None:
    from .notify import drain_live_notification_events

    try:
        drain_live_notification_events()
    except Exception:
        logger.exception("Notification event spool drain failed")

def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(daily_sync, "cron", hour=7, minute=0, id="signin_daily_sync", replace_existing=True)
    scheduler.add_job(auto_checkin_executor, "cron", minute="*", id="signin_auto", replace_existing=True)
    scheduler.add_job(douyin_hourly, "cron", minute="*", id="douyin_hourly", replace_existing=True)
    scheduler.add_job(
        notification_event_drain,
        "interval",
        seconds=2,
        next_run_time=datetime.now(TZ_BEIJING),
        id="notification_event_drain",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
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
