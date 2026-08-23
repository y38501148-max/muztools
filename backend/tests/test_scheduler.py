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


def test_scheduler_disables_nonadmin_douyin(monkeypatch):
    user = {"id": "u-other", "username": "other_user", "douyin": {"enabled": True, "hour": 0}}
    saved = []
    monkeypatch.setattr(scheduler_module, "iter_users", lambda: [user])
    monkeypatch.setattr(scheduler_module, "save_user", lambda value: saved.append(value))
    asyncio.run(scheduler_module.douyin_hourly())
    assert user["douyin"]["enabled"] is False
    assert user["douyin"]["disabled_reason"] == "temporary_admin_only"
    assert saved == [user]
