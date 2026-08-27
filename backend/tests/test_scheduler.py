import asyncio
from datetime import datetime, timedelta

from muztool import scheduler as scheduler_module
from muztool.signin_core import TZ_BEIJING


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 23, hour, minute, tzinfo=TZ_BEIJING)


def test_manual_run_does_not_block_automatic_run():
    cfg = {
        "enabled": True,
        "hour": 6,
        "last_run": dt(0, 19).isoformat(),
        "last_auto_run": "",
        "last_auto_attempt": "",
    }
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 0), jitter_offset=0) is True


def test_successful_auto_run_blocks_duplicate_for_the_day():
    cfg = {"enabled": True, "hour": 6, "last_auto_run": dt(6, 2).isoformat()}
    assert scheduler_module.should_run_douyin_auto(cfg, dt(20, 0), jitter_offset=0) is False


def test_missed_exact_minute_is_caught_up_later():
    cfg = {"enabled": True, "hour": 6, "last_auto_run": "", "last_auto_attempt": ""}
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 37), jitter_offset=0) is True


def test_failed_attempt_waits_before_retry():
    cfg = {
        "enabled": True,
        "hour": 6,
        "last_auto_run": "",
        "last_auto_attempt": dt(6, 5).isoformat(),
    }
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 14), jitter_offset=0) is False
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 15), jitter_offset=0) is True


def test_auto_spark_uses_stable_daily_random_offset():
    cfg = {"enabled": True, "hour": 6, "last_auto_run": "", "last_auto_attempt": ""}
    scheduled = scheduler_module.ensure_douyin_auto_schedule(cfg, dt(5, 50), jitter_offset=4)
    assert scheduled == dt(6, 4)
    assert cfg["auto_schedule_offset_minutes"] == 4
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 3), jitter_offset=-5) is False
    # A later scheduler tick must reuse +4 rather than redraw -5.
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 4), jitter_offset=-5) is True
    assert cfg["auto_schedule_offset_minutes"] == 4


def test_auto_spark_draws_new_offset_on_next_day_or_hour_change():
    cfg = {"enabled": True, "hour": 6}
    first = scheduler_module.ensure_douyin_auto_schedule(cfg, dt(5), jitter_offset=-3)
    assert first == dt(5, 57)
    next_day = datetime(2026, 8, 24, 5, 0, tzinfo=TZ_BEIJING)
    second = scheduler_module.ensure_douyin_auto_schedule(cfg, next_day, jitter_offset=5)
    assert second == datetime(2026, 8, 24, 6, 5, tzinfo=TZ_BEIJING)
    cfg["hour"] = 7
    third = scheduler_module.ensure_douyin_auto_schedule(cfg, next_day, jitter_offset=-2)
    assert third == datetime(2026, 8, 24, 6, 58, tzinfo=TZ_BEIJING)


def test_auto_spark_jitter_does_not_cross_calendar_boundary():
    midnight = {"enabled": True, "hour": 0}
    end_of_day = {"enabled": True, "hour": 23}
    assert scheduler_module.ensure_douyin_auto_schedule(midnight, dt(0), jitter_offset=-5) == dt(0)
    assert scheduler_module.ensure_douyin_auto_schedule(end_of_day, dt(22), jitter_offset=5) == dt(23)


def test_scheduler_runs_playwright_worker_off_asyncio_loop(monkeypatch):
    user = {
        "id": "u1",
        "username": "muzermat",
        "approvals": {"spark": "approved"},
        "douyin": {
            "enabled": True,
            "hour": 0,
            "last_auto_run": "",
            "last_auto_attempt": "",
            "targets": [{"name": "目标", "conversation_id": "d1", "conversation_type": "direct"}],
        },
    }
    saved = []

    def fake_run_spark(target_user, **_kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise AssertionError("sync Playwright worker ran in asyncio event loop")
        target_user["douyin"]["last_run"] = dt(6).isoformat()
        return {"success": True, "results": [{"ok": True, "target_key": "id:d1"}]}

    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda value: saved.append(value.copy()))
    monkeypatch.setattr(scheduler_module, "push_notification", lambda *args, **kwargs: None)
    import muztool.douyin as douyin_module
    monkeypatch.setattr(douyin_module, "run_spark", fake_run_spark)

    asyncio.run(scheduler_module.douyin_hourly())
    assert user["douyin"]["last_auto_run"]
    assert saved


def test_partial_success_retries_only_remaining_targets(monkeypatch):
    now = datetime.now(TZ_BEIJING)
    user = {
        "id": "u-partial",
        "username": "muzermat",
        "douyin": {
            "enabled": True,
            "hour": 0,
            "last_auto_run": "",
            "last_auto_attempt": "",
            "targets": [
                {"name": "目标一", "conversation_id": "d1", "conversation_type": "direct"},
                {"name": "目标二", "conversation_id": "d2", "conversation_type": "direct"},
            ],
        },
    }
    calls = []

    def fake_run_spark(_user, *, targets_override, **_kwargs):
        calls.append([target["conversation_id"] for target in targets_override])
        if len(calls) == 1:
            return {
                "success": False,
                "halt_reason": "",
                "results": [
                    {"ok": True, "target_key": "id:d1", "retryable": False, "status": "success"},
                    {"ok": False, "target_key": "id:d2", "retryable": True, "status": "transient"},
                ],
            }
        return {
            "success": True,
            "halt_reason": "",
            "results": [{"ok": True, "target_key": "id:d2", "retryable": False, "status": "success"}],
        }

    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda _user: None)
    monkeypatch.setattr(scheduler_module, "push_notification", lambda *_args, **_kwargs: None)
    import muztool.douyin as douyin_module
    monkeypatch.setattr(douyin_module, "run_spark", fake_run_spark)

    asyncio.run(scheduler_module.douyin_hourly())
    assert calls == [["d1", "d2"]]
    assert user["douyin"]["auto_completed_target_keys"] == ["id:d1"]
    assert not user["douyin"].get("last_auto_run")
    assert not user["douyin"].get("auto_blocked_date")

    user["douyin"]["last_auto_attempt"] = (now - timedelta(hours=1)).isoformat()
    asyncio.run(scheduler_module.douyin_hourly())
    assert calls == [["d1", "d2"], ["d2"]]
    assert user["douyin"]["last_auto_run"]
    assert set(user["douyin"]["auto_completed_target_keys"]) == {"id:d1", "id:d2"}


def test_security_challenge_blocks_automatic_retry_for_today(monkeypatch):
    user = {
        "id": "u-blocked",
        "username": "muzermat",
        "douyin": {
            "enabled": True,
            "hour": 0,
            "last_auto_run": "",
            "last_auto_attempt": "",
            "targets": [{"name": "目标", "conversation_id": "d1", "conversation_type": "direct"}],
        },
    }

    def fake_run_spark(_user, **_kwargs):
        return {
            "success": False,
            "halt_reason": "security_challenge",
            "results": [
                {"ok": False, "target_key": "id:d1", "retryable": False, "status": "security_challenge"}
            ],
        }

    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda _user: None)
    monkeypatch.setattr(scheduler_module, "push_notification", lambda *_args, **_kwargs: None)
    import muztool.douyin as douyin_module
    monkeypatch.setattr(douyin_module, "run_spark", fake_run_spark)

    asyncio.run(scheduler_module.douyin_hourly())
    today = datetime.now(TZ_BEIJING).date().isoformat()
    assert user["douyin"]["auto_blocked_date"] == today
    assert user["douyin"]["auto_blocked_reason"] == "security_challenge"
    assert scheduler_module.should_run_douyin_auto(user["douyin"], datetime.now(TZ_BEIJING)) is False


def test_scheduler_keeps_nonadmin_douyin_enabled(monkeypatch):
    user = {"id": "u-other", "username": "other_user", "douyin": {"enabled": True, "hour": 0}}
    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda value: None)
    monkeypatch.setattr(scheduler_module, "push_notification", lambda *_args, **_kwargs: None)
    import muztool.douyin as douyin_module
    monkeypatch.setattr(douyin_module, "run_spark", lambda _user, **_kwargs: {"success": True, "results": []})
    asyncio.run(scheduler_module.douyin_hourly())
    assert user["douyin"]["enabled"] is True
    assert "disabled_reason" not in user["douyin"]


def test_tibo_monitor_prefers_user_cookie_and_skips_anonymous(monkeypatch):
    import muztool.tibo as tibo_module
    from datetime import datetime, timezone

    user = {"id": "u1", "tibo": {"enabled": True, "x_cookies_encrypted": "v1:x"}}
    monkeypatch.setattr(tibo_module, "iter_x_cookie_users", lambda: [user])
    monkeypatch.setattr(tibo_module, "get_user_x_cookies", lambda _u: {"auth_token": "a", "ct0": "c"})

    async def fake_auth_fetch(cookies, now, lookback_hours=168):
        return tibo_module.FetchResult(("1",), ())

    monkeypatch.setattr(tibo_module, "fetch_tibo_posts_authenticated", fake_auth_fetch)

    calls = []

    async def fake_check(fetcher=None, **_kwargs):
        if fetcher is not None:
            result = await fetcher(frozenset(), datetime.now(timezone.utc), 168)
            calls.append(("auth", result.discovered_ids))
        else:
            calls.append(("anonymous",))
        return tibo_module.CheckReport(False, 0, 0, 0)

    monkeypatch.setattr(tibo_module, "check_tibo_updates", fake_check)
    asyncio.run(scheduler_module.tibo_monitor())
    assert calls == [("auth", ("1",))]


def test_tibo_monitor_notifies_expired_cookie_and_falls_back(monkeypatch):
    import muztool.tibo as tibo_module
    from datetime import datetime, timezone

    user = {"id": "u1", "tibo": {"enabled": True, "x_cookies_encrypted": "v1:x"}}
    monkeypatch.setattr(tibo_module, "iter_x_cookie_users", lambda: [user])
    monkeypatch.setattr(tibo_module, "get_user_x_cookies", lambda _u: {"auth_token": "a", "ct0": "c"})
    expired = []
    monkeypatch.setattr(tibo_module, "notify_x_cookie_expired", lambda u, now: expired.append(u["id"]))

    async def fake_auth_fetch(cookies, now, lookback_hours=168):
        raise tibo_module.XAuthError("expired")

    monkeypatch.setattr(tibo_module, "fetch_tibo_posts_authenticated", fake_auth_fetch)

    calls = []

    async def fake_check(fetcher=None, **_kwargs):
        if fetcher is not None:
            await fetcher(frozenset(), datetime.now(timezone.utc), 168)
        calls.append("auth" if fetcher is not None else "anonymous")
        return tibo_module.CheckReport(False, 0, 0, 0)

    monkeypatch.setattr(tibo_module, "check_tibo_updates", fake_check)
    asyncio.run(scheduler_module.tibo_monitor())
    assert expired == ["u1"]
    # The authenticated fetch raised XAuthError before finishing, so only the
    # anonymous fallback check completes.
    assert calls == ["anonymous"]


def test_tibo_monitor_falls_back_when_no_cookie_users(monkeypatch):
    import muztool.tibo as tibo_module

    monkeypatch.setattr(tibo_module, "iter_x_cookie_users", lambda: [])
    calls = []

    async def fake_check(fetcher=None, **_kwargs):
        calls.append(fetcher is not None)
        return tibo_module.CheckReport(False, 0, 0, 0)

    monkeypatch.setattr(tibo_module, "check_tibo_updates", fake_check)
    asyncio.run(scheduler_module.tibo_monitor())
    assert calls == [False]
