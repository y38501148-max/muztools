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
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 0)) is True


def test_successful_auto_run_blocks_duplicate_for_the_day():
    cfg = {"enabled": True, "hour": 6, "last_auto_run": dt(6, 2).isoformat()}
    assert scheduler_module.should_run_douyin_auto(cfg, dt(20, 0)) is False


def test_missed_exact_minute_is_caught_up_later():
    cfg = {"enabled": True, "hour": 6, "last_auto_run": "", "last_auto_attempt": ""}
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 37)) is True


def test_failed_attempt_waits_before_retry():
    cfg = {
        "enabled": True,
        "hour": 6,
        "last_auto_run": "",
        "last_auto_attempt": dt(6, 5).isoformat(),
    }
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 14)) is False
    assert scheduler_module.should_run_douyin_auto(cfg, dt(6, 15)) is True


def test_scheduler_runs_playwright_worker_off_asyncio_loop(monkeypatch):
    user = {
        "id": "u1",
        "approvals": {"spark": "approved"},
        "douyin": {"enabled": True, "hour": 0, "last_auto_run": "", "last_auto_attempt": ""},
    }
    saved = []

    def fake_run_spark(target_user):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise AssertionError("sync Playwright worker ran in asyncio event loop")
        target_user["douyin"]["last_run"] = dt(6).isoformat()
        return {"success": True, "results": [{"ok": True}]}

    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda value: saved.append(value.copy()))
    monkeypatch.setattr(scheduler_module, "push_notification", lambda *args, **kwargs: None)
    import muztool.douyin as douyin_module
    monkeypatch.setattr(douyin_module, "run_spark", fake_run_spark)

    asyncio.run(scheduler_module.douyin_hourly())
    assert user["douyin"]["last_auto_run"]
    assert saved
