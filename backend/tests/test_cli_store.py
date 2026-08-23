import json
import os
from pathlib import Path

import pytest

os.environ["MUZTOOLS_DATA"] = str(Path("/tmp/muztools-test-data"))

from muztool import config, invites, notify, store  # noqa: E402
from muztool.cli import main  # noqa: E402
from muztool.security import validate_password, validate_username  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZTOOLS_DATA", str(tmp_path))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SECRET_FILE", tmp_path / "secret.key")
    monkeypatch.setattr(config, "VAULT_KEY_FILE", tmp_path / "vault.key")
    monkeypatch.setattr(config, "RSA_PRIVATE_KEY_FILE", tmp_path / "transport_rsa.pem")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "ensure_dirs", config.ensure_dirs)
    monkeypatch.setattr(invites, "INVITES_FILE", tmp_path / "invite_codes.json")
    monkeypatch.setattr(invites, "INVITES_LOCK", tmp_path / "invite_codes.lock")
    config.ensure_dirs()
    yield tmp_path


def test_existing_users_receive_default_permissions_and_signin_can_be_enabled(capsys):
    user = store.create_user("alice_1", "Secret1", "Alice")
    user["student"]["student_id"] = "25371537"
    user["student"]["real_name"] = "测试"
    user["student"]["status"] = "verified"
    user["approvals"] = {"signin": "pending", "td": "none", "spark": "rejected"}
    store.save_user(user)

    reloaded = store.find_user_by_username("alice_1")
    assert reloaded["approvals"] == {"signin": "approved", "td": "approved", "spark": "approved"}

    main(["enable-signin", "alice_1"])
    assert "已开启" in capsys.readouterr().out
    assert store.find_user_by_username("alice_1")["student"]["auto_signin"] is True


def test_generate_invites_and_stats_do_not_print_plaintext_codes(capsys):
    main(["generate-invites", "--count", "3"])
    generated = json.loads(capsys.readouterr().out)
    assert generated == {"generated": 3, "available": 3}

    main(["invite-stats"])
    stats = json.loads(capsys.readouterr().out)
    assert stats == {"available": 3, "issued": 0, "used": 0}

    persisted = invites.INVITES_FILE.read_text(encoding="utf-8")
    data = json.loads(persisted)
    assert len(data["codes"]) == 3
    assert all(item.get("code_encrypted", "").startswith("v1:") for item in data["codes"])
    assert all("code" not in item for item in data["codes"])


def test_message_command_persists_and_queues_notification_without_echoing_body(capsys, monkeypatch):
    user = store.create_user("notice_1", "Secret1", "Notice")
    monkeypatch.setattr(notify, "_live_loop", None)

    main(["message", user["id"], "后台", "测试消息", "--title", "测试提示"])
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["success"] is True
    assert payload["user_id"] == user["id"]
    assert "后台 测试消息" not in output

    saved = store.load_user(user["id"])
    item = saved["notifications"][0]
    assert item["title"] == "测试提示"
    assert item["body"] == "后台 测试消息"
    event_files = list((config.DATA_DIR / "notification_events").glob("*.json"))
    assert len(event_files) == 1
    assert event_files[0].stat().st_mode & 0o777 == 0o600

    queue = notify.subscribe_live_notifications(user["id"])
    assert notify.drain_live_notification_events() == 1
    assert queue.get_nowait()["id"] == item["id"]
    notify.unsubscribe_live_notifications(user["id"], queue)


def test_message_command_rejects_oversized_body():
    user = store.create_user("notice_2", "Secret1", "Notice")
    with pytest.raises(SystemExit, match="500"):
        main(["message", user["id"], "x" * 501])


def test_username_and_password_rules():
    assert validate_username("alice_1") == "alice_1"
    with pytest.raises(ValueError):
        validate_username("abc")
    with pytest.raises(ValueError):
        validate_password("abcdef")
    assert validate_password("Abcdef1") == "Abcdef1"


def test_legacy_student_password_migrates_to_encrypted_storage():
    user = store.create_user("legacy_1", "Secret1", "Legacy")
    raw = store.load_user(user["id"])
    raw["student"].pop("password_encrypted", None)
    raw["student"]["password"] = "CampusSecret1"
    store._locked_write(store.user_path(user["id"]), raw)

    migrated = store.load_user(user["id"])
    contents = store.user_path(user["id"]).read_text(encoding="utf-8")
    assert "CampusSecret1" not in contents
    assert '"password"' not in contents
    assert store.get_student_password(migrated["student"]) == "CampusSecret1"


def test_legacy_douyin_secrets_migrate_and_user_file_is_private(isolated_data):
    user = store.create_user("muzermat", "Secret1", "Admin")
    raw = store.load_user(user["id"])
    raw["douyin"].pop("cookies_encrypted", None)
    raw["douyin"]["cookies"] = [
        {"name": "sessionid", "value": "legacy-cookie-secret", "domain": ".douyin.com", "path": "/"}
    ]
    raw["douyin"]["friends_cache"] = [
        {"name": "private-friend-name", "conversation_id": "d1", "conversation_type": "direct"}
    ]
    store._locked_write(store.user_path(user["id"]), raw)

    migrated = store.load_user(user["id"])
    contents = store.user_path(user["id"]).read_text(encoding="utf-8")
    persisted = json.loads(contents)
    assert "legacy-cookie-secret" not in contents
    assert "private-friend-name" not in contents
    assert "cookies" not in persisted["douyin"]
    assert "friends_cache" not in persisted["douyin"]
    assert migrated["douyin"]["cookies_encrypted"].startswith("v1:")
    assert migrated["douyin"]["friends_cache_encrypted"].startswith("v1:")
    assert store.get_douyin_cookies(migrated["douyin"])[0]["value"] == "legacy-cookie-secret"
    assert store.get_douyin_friends_cache(migrated["douyin"])[0]["name"] == "private-friend-name"
    assert store.user_path(user["id"]).stat().st_mode & 0o777 == 0o600
    assert (isolated_data / "users").stat().st_mode & 0o777 == 0o700


def test_nonadmin_douyin_auto_is_disabled_during_migration():
    user = store.create_user("ordinary_1", "Secret1", "Ordinary")
    user["douyin"]["enabled"] = True
    store.save_user(user)
    reloaded = store.load_user(user["id"])
    assert reloaded["douyin"]["enabled"] is False
    assert reloaded["douyin"]["disabled_reason"] == "temporary_admin_only"
    assert store.public_user(reloaded)["can_use_douyin"] is False
