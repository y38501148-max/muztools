import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Random import get_random_bytes
from Crypto.PublicKey import RSA

from muztool import api as api_module
from muztool import config, invites, store
from muztool.security import hash_password


TEST_PASSWORD = "StrongPass1!"


def encrypted_payload(client, fields, *, keep_login=False):
    public = client.get("/api/security/public-key")
    assert public.status_code == 200
    data = public.json()
    key = RSA.construct((int(data["modulus_hex"], 16), int(data["exponent"])))
    cipher = PKCS1_v1_5.new(key)
    return {
        "encrypted": {
            name: base64.b64encode(cipher.encrypt(str(value).encode("utf-8"))).decode("ascii")
            for name, value in fields.items()
        },
        "keep_login": keep_login,
    }


def login_payload(client, *, keep_login=True, username="persist_1", password=TEST_PASSWORD):
    return encrypted_payload(
        client,
        {"username": username, "password": password},
        keep_login=keep_login,
    )


def hybrid_secret_payload(client, value: str):
    public = client.get("/api/security/public-key")
    assert public.status_code == 200
    data = public.json()
    rsa_key = RSA.construct((int(data["modulus_hex"], 16), int(data["exponent"])))
    aes_key = get_random_bytes(32)
    nonce = get_random_bytes(12)
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
    return {
        "encrypted_secret": {
            "key": base64.b64encode(PKCS1_v1_5.new(rsa_key).encrypt(aes_key)).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext + tag).decode("ascii"),
        }
    }


def enable_admin_douyin(client, user):
    user["username"] = "muzermat"
    store.save_user(user)
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True, username="muzermat"),
    )
    assert login.status_code == 200


@pytest.fixture()
def client_and_user(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SECRET_FILE", tmp_path / "secret.key")
    monkeypatch.setattr(config, "VAULT_KEY_FILE", tmp_path / "vault.key")
    monkeypatch.setattr(config, "RSA_PRIVATE_KEY_FILE", tmp_path / "transport_rsa.pem")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "ensure_dirs", config.ensure_dirs)
    monkeypatch.setattr(invites, "INVITES_FILE", tmp_path / "invite_codes.json")
    monkeypatch.setattr(invites, "INVITES_LOCK", tmp_path / "invite_codes.lock")
    api_module._AUTH_RATE.clear()
    monkeypatch.setattr(api_module, "start_scheduler", lambda: None)
    config.ensure_dirs()

    user = store.create_user("persist_1", TEST_PASSWORD, "Persist")
    user["student"].update({"student_id": "12345678", "status": "verified"})
    user["approvals"] = {"signin": "none", "td": "none", "spark": "approved"}
    store.save_user(user)

    with TestClient(api_module.app) as client:
        yield client, user


def test_keep_login_cookie_restores_session(client_and_user):
    client, _user = client_and_user
    response = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert response.status_code == 200
    assert client.cookies.get(api_module.SESSION_COOKIE)

    restored = client.get("/api/auth/session")
    assert restored.status_code == 200
    assert restored.json()["token"] == response.json()["token"]
    assert restored.json()["user"]["username"] == "persist_1"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.cookies.get(api_module.SESSION_COOKIE) is None



def test_existing_legacy_password_still_logs_in(client_and_user):
    client, user = client_and_user
    legacy_password = "OldPass1"
    user["password_hash"] = hash_password(legacy_password)
    store.save_user(user)

    response = client.post(
        "/api/auth/login",
        json=login_payload(client, password=legacy_password),
    )
    assert response.status_code == 200


def test_persistent_cookie_wins_when_browser_bearer_is_stale(client_and_user):
    client, _user = client_and_user
    response = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert response.status_code == 200

    restored = client.get(
        "/api/auth/session",
        headers={"Authorization": "Bearer stale-browser-token"},
    )
    assert restored.status_code == 200
    assert restored.json()["token"] == response.json()["token"]


def test_expired_bearer_session_is_rejected(client_and_user):
    client, _user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=False))
    token = login.json()["token"]
    session_file = store.session_path(token)
    session = json.loads(session_file.read_text(encoding="utf-8"))
    session["created_at"] = "2020-01-01T00:00:00+08:00"
    store._locked_write(session_file, session)
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_student_payload_exposes_auto_signin_even_when_schedule_fails(client_and_user):
    client, user = client_and_user
    user["student"]["auto_signin"] = True
    store.save_user(user)
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert login.status_code == 200

    status = client.get("/api/student")
    assert status.status_code == 200
    assert status.json()["auto_signin"] is True

def test_login_without_keep_login_does_not_persist_cookie(client_and_user):
    client, _user = client_and_user
    response = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=False),
    )
    assert response.status_code == 200
    assert client.cookies.get(api_module.SESSION_COOKIE) is None


def test_manual_spark_runs_sync_playwright_worker_off_event_loop(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)

    def fake_run_spark(user):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        user.setdefault("douyin", {})["last_run"] = "worker-thread"
        return {"success": True, "results": []}

    monkeypatch.setattr(api_module, "run_spark", fake_run_spark)
    response = client.post("/api/douyin/run")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_single_target_spark_uses_configured_target_in_worker_thread(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    target = {
        "name": "测试好友",
        "mode": "custom",
        "message": "单独测试",
        "conversation_id": "direct-1",
        "conversation_short_id": "short-1",
        "conversation_type": "direct",
    }
    user["douyin"]["targets"] = [target]
    store.save_user(user)
    captured = {}

    def fake_run_spark(worker_user, *, targets_override=None):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        captured["user"] = worker_user["username"]
        captured["targets"] = targets_override
        return {"success": True, "results": [{"ok": True, "target": "测试好友"}]}

    monkeypatch.setattr(api_module, "run_spark", fake_run_spark)
    response = client.post("/api/douyin/run-target", json={"target_key": "id:direct-1"})
    assert response.status_code == 200
    assert response.json()["single_target"] is True
    assert response.json()["target"] == "测试好友"
    assert captured == {"user": "muzermat", "targets": [target]}


def test_single_target_spark_rejects_unconfigured_target(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    user["douyin"]["targets"] = [
        {"name": "已配置好友", "conversation_id": "direct-1", "conversation_type": "direct"}
    ]
    store.save_user(user)
    monkeypatch.setattr(api_module, "run_spark", lambda *_args, **_kwargs: pytest.fail("不应执行发送"))

    response = client.post("/api/douyin/run-target", json={"target_key": "id:other"})
    assert response.status_code == 404
    assert "目标不存在" in response.json()["detail"]


def test_friend_list_uses_cache_until_explicit_refresh(client_and_user, monkeypatch):
    client, user = client_and_user
    user["username"] = "muzermat"
    store.set_douyin_cookies(user["douyin"], [{"name": "sessionid", "value": "test", "domain": ".douyin.com", "path": "/"}])
    user["douyin"].pop("friends_cache_encrypted", None)
    user["douyin"]["friends_cache_initialized"] = False
    user["douyin"].pop("friends_cached_at", None)
    store.save_user(user)

    calls = []

    def fake_list(_cookies):
        calls.append(len(calls) + 1)
        return [{"name": f"好友{calls[-1]}", "avatar_url": ""}]

    monkeypatch.setattr(api_module, "list_douyin_friends", fake_list)
    enable_admin_douyin(client, user)

    first = client.get("/api/douyin/friends")
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert first.json()["friends"][0]["name"] == "好友1"
    assert len(calls) == 1

    second = client.get("/api/douyin/friends")
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["friends"][0]["name"] == "好友1"
    assert len(calls) == 1

    refreshed = client.get("/api/douyin/friends?refresh=1")
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False
    assert refreshed.json()["friends"][0]["name"] == "好友2"
    assert len(calls) == 2


def test_bearer_session_refreshes_persistent_cookie(client_and_user):
    client, _user = client_and_user
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    token = login.json()["token"]
    client.cookies.clear()
    restored = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert restored.status_code == 200
    assert client.cookies.get(api_module.SESSION_COOKIE) == token


def test_cached_home_does_not_call_external_td_services(client_and_user, monkeypatch):
    client, user = client_and_user
    user["approvals"]["td"] = "approved"
    user["student"]["schedule_date"] = ""
    store.save_user(user)
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert login.status_code == 200

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("cached home must not call external services")

    monkeypatch.setattr(api_module, "safe_fetch_schedule", forbidden)
    monkeypatch.setattr(api_module, "load_td", forbidden)
    monkeypatch.setattr(api_module, "load_sunshine", forbidden)
    response = client.get("/api/home?cached=1")
    assert response.status_code == 200
    assert response.json()["cached"] is True


def test_live_notification_websocket_delivers_new_item(client_and_user):
    from muztool.notify import push_notification

    client, user = client_and_user
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    token = login.json()["token"]
    with client.websocket_connect(
        "/api/notifications/ws",
        headers={"Authorization": f"Bearer {token}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        push_notification(user, "测试", "实时到达", "general", source_id="test-live")
        payload = websocket.receive_json()
        assert payload["type"] == "notification"
        assert payload["item"]["content"] == "实时到达"


def test_websocket_rejects_query_string_token(client_and_user):
    client, _user = client_and_user
    token = client.post("/api/auth/login", json=login_payload(client)).json()["token"]
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/api/notifications/ws?token={token}"):
            pass
    assert caught.value.code == 4401


def test_websocket_accepts_bounded_first_message_auth(client_and_user):
    client, _user = client_and_user
    token = client.post("/api/auth/login", json=login_payload(client, keep_login=False)).json()["token"]
    client.cookies.clear()
    with client.websocket_connect("/api/notifications/ws") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        assert websocket.receive_json()["type"] == "ready"


def test_tibo_history_endpoint_reads_cache_only(client_and_user, monkeypatch):
    client, _user = client_and_user
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert login.status_code == 200
    monkeypatch.setattr(
        api_module,
        "list_tibo_history",
        lambda: {"items": [{"id": "1", "text": "reset", "created_at": "2026-08-23T09:00:00+08:00", "url": "https://x.com/x/status/1"}], "count": 1, "last_checked": "now"},
    )
    response = client.get("/api/tibo/history")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_td_manual_runs_from_server_saved_photos(client_and_user, monkeypatch):
    client, user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    uploaded = client.post(
        "/api/td/photos",
        files={
            "entrance": ("entrance.jpg", b"entrance-photo", "image/jpeg"),
            "exit": ("exit.jpg", b"exit-photo", "image/jpeg"),
        },
    )
    assert uploaded.status_code == 200
    captured = {}

    def fake_manual(student_id, entrance_id, exit_id, entrance_photo, exit_photo, gap_seconds):
        captured.update({
            "student_id": student_id,
            "entrance_id": entrance_id,
            "exit_id": exit_id,
            "entrance_photo": entrance_photo,
            "exit_photo": exit_photo,
            "gap_seconds": gap_seconds,
        })
        return {"success": True, "message": "TD 手动打卡完成", "count": 7}

    monkeypatch.setattr(api_module.td, "manual_td", fake_manual)
    response = client.post(
        "/api/td/manual",
        json={"campus": "xueyuanlu", "entrance_machine_id": 4, "exit_machine_id": 5, "gap_seconds": 240},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured == {
        "student_id": "12345678",
        "entrance_id": 4,
        "exit_id": 5,
        "entrance_photo": b"entrance-photo",
        "exit_photo": b"exit-photo",
        "gap_seconds": 240,
    }
    saved = store.load_user(user["id"])
    assert saved["td"]["entrance_machine_id"] == 4
    assert saved["td"]["exit_machine_id"] == 5


def test_security_surface_is_hardened(client_and_user):
    client, _user = client_and_user
    for path in ("/openapi.json", "/docs", "/redoc", "/api/not-a-real-route"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.text == "Not Found"
        assert response.headers["content-type"].startswith("text/plain")

    home = client.get("https://testserver/")
    assert home.status_code == 200
    csp = home.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self' 'nonce-" in csp
    nonce = csp.split("'nonce-", 1)[1].split("'", 1)[0]
    assert f'<script nonce="{nonce}">' in home.text
    assert "strict-transport-security" in home.headers
    assert home.headers["cross-origin-opener-policy"] == "same-origin"


def test_update_artifacts_require_authentication_on_main_service(client_and_user):
    client, _user = client_and_user
    assert client.get("/api/app/version").status_code == 401
    assert client.get("/api/app/apk").status_code == 401


def test_login_rate_limit_runs_before_decryption(client_and_user):
    client, _user = client_and_user
    for _ in range(30):
        assert client.post("/api/auth/login", json={}).status_code == 400
    limited = client.post("/api/auth/login", json={})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_relay_only_mode_exposes_only_update_endpoints(client_and_user, monkeypatch):
    client, _user = client_and_user
    monkeypatch.setattr(config, "RELAY_ONLY", True)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/app/version").status_code == 200
    assert client.get("/api/auth/session").status_code == 404


def test_nonadmin_douyin_is_open_even_without_approval(client_and_user):
    client, user = client_and_user
    user["student"] = {"student_id": "", "status": "unbound", "auto_signin": False}
    user["approvals"] = {"signin": "none", "td": "pending", "spark": "rejected"}
    store.save_user(user)
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    compatibility = client.post("/api/student/request", json={"feature": "spark"})
    assert compatibility.status_code == 200
    assert compatibility.json()["user"]["approvals"] == {
        "signin": "approved", "td": "approved", "spark": "approved"
    }

    assert login.json()["user"]["can_use_douyin"] is True
    session = client.get("/api/douyin/session")
    assert session.status_code == 200
    assert session.json()["valid"] is False
    response = client.put(
        "/api/douyin/config",
        json={"enabled": False, "default_message": "续火花", "hour": 9, "targets": []},
    )
    assert response.status_code == 200

def test_tibo_push_setting_defaults_off_and_persists(client_and_user, monkeypatch):
    client, user = client_and_user
    login = client.post(
        "/api/auth/login",
        json=login_payload(client, keep_login=True),
    )
    assert login.status_code == 200
    monkeypatch.setattr(
        api_module,
        "list_tibo_history",
        lambda: {"items": [], "count": 0, "last_checked": "now"},
    )

    initial = client.get("/api/tibo/history")
    assert initial.status_code == 200
    assert initial.json()["enabled"] is False

    enabled = client.put("/api/tibo/config", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    stored = store.load_user(user["id"])
    assert stored is not None
    assert stored["tibo"]["enabled"] is True

    refreshed = client.get("/api/tibo/history")
    assert refreshed.status_code == 200
    assert refreshed.json()["enabled"] is True


def test_friend_cache_preserves_group_identity_and_enriches_existing_target(client_and_user, monkeypatch):
    client, user = client_and_user
    user["username"] = "muzermat"
    store.set_douyin_cookies(user["douyin"], [{"name": "sessionid", "value": "test", "domain": ".douyin.com", "path": "/"}])
    user["douyin"]["targets"] = [{"name": "测试群", "mode": "standard", "message": ""}]
    user["douyin"].pop("friends_cache_encrypted", None)
    user["douyin"]["friends_cache_initialized"] = False
    store.save_user(user)

    monkeypatch.setattr(
        api_module,
        "list_douyin_friends",
        lambda _cookies: [
            {
                "name": "测试群",
                "avatar_url": "avatar",
                "conversation_id": "conversation-2",
                "conversation_short_id": "2",
                "conversation_type": "group",
            }
        ],
    )
    enable_admin_douyin(client, user)
    response = client.get("/api/douyin/friends")
    assert response.status_code == 200
    assert response.json()["friends"][0]["conversation_type"] == "group"
    saved = store.load_user(user["id"])
    assert saved["douyin"]["targets"][0]["conversation_id"] == "conversation-2"
    assert saved["douyin"]["targets"][0]["conversation_type"] == "group"


def test_plaintext_credentials_are_rejected(client_and_user):
    client, _user = client_and_user
    login = client.post(
        "/api/auth/login",
        json={"username": "persist_1", "password": "Secret1", "keep_login": True},
    )
    assert login.status_code == 400
    assert "仅接受加密凭据" in login.json()["detail"]

    register = client.post(
        "/api/auth/register",
        json={"username": "new_user", "password": "Secret1", "invite_code": "none"},
    )
    assert register.status_code == 400

    token = client.post("/api/auth/login", json=login_payload(client)).json()["token"]
    bind = client.post(
        "/api/student/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={"student_id": "12345678", "password": "Campus1"},
    )
    assert bind.status_code == 400


def test_invite_registration_is_single_use_and_not_stored_in_plaintext(client_and_user):
    client, _user = client_and_user
    invites.generate_invites(1)
    issued = invites.issue_invite("test-suite")
    code = issued["code"]

    missing = client.post(
        "/api/auth/register",
        json=encrypted_payload(
            client,
            {"username": "new_user1", "password": "StrongPass1!", "display_name": "New", "invite_code": ""},
        ),
    )
    assert missing.status_code == 400

    registered = client.post(
        "/api/auth/register",
        json=encrypted_payload(
            client,
            {"username": "new_user1", "password": "StrongPass1!", "display_name": "New", "invite_code": code},
        ),
    )
    assert registered.status_code == 200
    assert registered.json()["user"]["approvals"] == {
        "signin": "approved", "td": "approved", "spark": "approved"
    }

    reused = client.post(
        "/api/auth/register",
        json=encrypted_payload(
            client,
            {"username": "new_user2", "password": "StrongPass1!", "display_name": "New 2", "invite_code": code},
        ),
    )
    assert reused.status_code == 400
    persisted = invites.INVITES_FILE.read_text(encoding="utf-8")
    assert code not in persisted
    assert json.loads(persisted)["codes"][0]["status"] == "used"


def test_only_muzermat_can_issue_invites(client_and_user):
    client, _user = client_and_user
    invites.generate_invites(2)
    ordinary_login = client.post("/api/auth/login", json=login_payload(client))
    assert ordinary_login.status_code == 200
    assert client.post("/api/invites/issue").status_code == 404

    admin = store.create_user("muzermat", TEST_PASSWORD, "Admin")
    store.save_user(admin)
    admin_login = client.post(
        "/api/auth/login",
        json=login_payload(client, username="muzermat", password=TEST_PASSWORD),
    )
    assert admin_login.status_code == 200
    issued = client.post("/api/invites/issue")
    assert issued.status_code == 200
    assert issued.json()["code"]
    assert issued.json()["remaining"] == 1


def test_student_password_is_encrypted_at_rest_and_legacy_value_migrates(client_and_user):
    _client, user = client_and_user
    store.set_student_password(user["student"], "CampusSecret1")
    store.save_user(user)
    raw = store.user_path(user["id"]).read_text(encoding="utf-8")
    assert "CampusSecret1" not in raw
    assert '"password"' not in raw
    assert store.get_student_password(store.load_user(user["id"])["student"]) == "CampusSecret1"

    legacy = store.load_user(user["id"])
    legacy["student"].pop("password_encrypted", None)
    legacy["student"]["password"] = "LegacyCampus1"
    store._locked_write(store.user_path(user["id"]), legacy)
    migrated = store.load_user(user["id"])
    migrated_raw = store.user_path(user["id"]).read_text(encoding="utf-8")
    assert "LegacyCampus1" not in migrated_raw
    assert "password_encrypted" in migrated["student"]
    assert store.get_student_password(migrated["student"]) == "LegacyCampus1"


def test_fcm_token_registration_is_encrypted_and_replaceable(client_and_user):
    client, user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    first = client.post(
        "/api/devices/fcm",
        json={"token": "fcm-token-1", "device_id": "android-1", "app_version": "1.3.1"},
    )
    assert first.status_code == 200
    assert first.json()["provider"] == "fcm"
    saved = store.load_user(user["id"])
    assert saved is not None
    records = [item for item in saved["devices"] if isinstance(item, dict) and item.get("kind") == "fcm"]
    assert len(records) == 1
    assert "fcm-token-1" not in json.dumps(records, ensure_ascii=False)
    assert records[0]["token_encrypted"].startswith("v1:")

    second = client.post(
        "/api/devices/fcm",
        json={"token": "fcm-token-1", "device_id": "android-1", "app_version": "1.3.2"},
    )
    assert second.status_code == 200
    saved = store.load_user(user["id"])
    records = [item for item in saved["devices"] if isinstance(item, dict) and item.get("kind") == "fcm"]
    assert len(records) == 1
    assert records[0]["app_version"] == "1.3.2"

    deleted = client.request("DELETE", "/api/devices/fcm", json={"token": "fcm-token-1"})
    assert deleted.status_code == 200
    saved = store.load_user(user["id"])
    assert not [item for item in saved["devices"] if isinstance(item, dict) and item.get("kind") == "fcm"]


def test_douyin_cookie_requires_hybrid_envelope_and_is_encrypted_at_rest(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    saved = store.load_user(user["id"])
    store.set_douyin_cookies(
        saved["douyin"],
        [{"name": "sessionid", "value": "old-account-session", "domain": ".douyin.com", "path": "/"}],
    )
    store.set_douyin_friends_cache(
        saved["douyin"],
        [{"name": "旧好友", "conversation_id": "old-id", "conversation_type": "direct"}],
    )
    saved["douyin"].update(
        {
            "account_key": "old-account-key",
            "enabled": True,
            "targets": [{"name": "旧目标", "conversation_id": "old-id", "conversation_type": "direct"}],
            "target_status": {"id:old-id": {"status": "success"}},
            "auto_schedule_date": "2026-08-27",
            "auto_schedule_hour": 9,
            "auto_schedule_offset_minutes": 3,
            "auto_scheduled_at": "2026-08-27T09:03:00+08:00",
        }
    )
    store.save_user(saved)
    monkeypatch.setattr(
        api_module,
        "validate_douyin_cookies",
        lambda cookies: (cookies, "测试抖音账号", "new-account-key"),
    )

    plaintext = client.post("/api/douyin/session", json={"cookies": "sessionid=plaintext-secret"})
    assert plaintext.status_code == 400
    assert "仅接受加密凭据" in plaintext.json()["detail"]

    cookie_json = json.dumps(
        [{"name": "sessionid", "value": "encrypted-cookie-secret", "domain": ".douyin.com", "path": "/"}]
    )
    response = client.post("/api/douyin/session", json=hybrid_secret_payload(client, cookie_json))
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["account_unchanged"] is False
    assert "账号变化" in response.json()["message"]

    reloaded = store.load_user(user["id"])
    raw = store.user_path(user["id"]).read_text(encoding="utf-8")
    persisted = json.loads(raw)
    assert "encrypted-cookie-secret" not in raw
    assert "cookies" not in persisted["douyin"]
    assert reloaded["douyin"]["cookies_encrypted"].startswith("v1:")
    assert store.get_douyin_cookies(reloaded["douyin"])[0]["value"] == "encrypted-cookie-secret"
    assert reloaded["douyin"]["enabled"] is False
    assert reloaded["douyin"]["targets"] == []
    assert reloaded["douyin"]["target_status"] == {}
    assert reloaded["douyin"]["friends_cache_initialized"] is False
    assert "auto_scheduled_at" not in reloaded["douyin"]
    assert "auto_schedule_date" not in reloaded["douyin"]


def test_same_douyin_account_import_preserves_configuration_cache_and_daily_time(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    saved = store.load_user(user["id"])
    store.set_douyin_cookies(
        saved["douyin"],
        [{"name": "sessionid", "value": "old-session", "domain": ".douyin.com", "path": "/"}],
    )
    friends = [{"name": "保留好友", "conversation_id": "friend-1", "conversation_type": "direct"}]
    store.set_douyin_friends_cache(saved["douyin"], friends)
    saved["douyin"].update(
        {
            "account_key": "same-account-key",
            "username": "原昵称",
            "enabled": True,
            "targets": [{"name": "保留好友", "conversation_id": "friend-1", "conversation_type": "direct"}],
            "target_status": {"id:friend-1": {"status": "success"}},
            "auto_progress_date": "2026-08-27",
            "auto_completed_target_keys": ["id:friend-1"],
            "auto_schedule_date": "2026-08-27",
            "auto_schedule_hour": 9,
            "auto_schedule_offset_minutes": -4,
            "auto_scheduled_at": "2026-08-27T08:56:00+08:00",
        }
    )
    store.save_user(saved)
    monkeypatch.setattr(
        api_module,
        "validate_douyin_cookies",
        lambda cookies: (cookies, "新昵称", "same-account-key"),
    )
    imported = json.dumps(
        [{"name": "sessionid", "value": "refreshed-session", "domain": ".douyin.com", "path": "/"}]
    )

    response = client.post("/api/douyin/session", json=hybrid_secret_payload(client, imported))

    assert response.status_code == 200
    assert response.json()["account_unchanged"] is True
    assert response.json()["configuration_preserved"] is True
    assert "已保留" in response.json()["message"]
    reloaded = store.load_user(user["id"])
    assert reloaded["douyin"]["enabled"] is True
    assert reloaded["douyin"]["targets"][0]["conversation_id"] == "friend-1"
    assert reloaded["douyin"]["target_status"]["id:friend-1"]["status"] == "success"
    assert reloaded["douyin"]["auto_scheduled_at"] == "2026-08-27T08:56:00+08:00"
    assert reloaded["douyin"]["auto_completed_target_keys"] == ["id:friend-1"]
    assert store.get_douyin_friends_cache(reloaded["douyin"]) == friends
    assert store.get_douyin_cookies(reloaded["douyin"])[0]["value"] == "refreshed-session"


def test_douyin_hybrid_envelope_rejects_tampering(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    monkeypatch.setattr(api_module, "validate_douyin_cookies", lambda cookies: (cookies, "测试账号", "account-key"))
    payload = hybrid_secret_payload(client, '[{"name":"sessionid","value":"secret"}]')
    sealed = bytearray(base64.b64decode(payload["encrypted_secret"]["ciphertext"]))
    sealed[-1] ^= 1
    payload["encrypted_secret"]["ciphertext"] = base64.b64encode(sealed).decode("ascii")
    response = client.post("/api/douyin/session", json=payload)
    assert response.status_code == 400
    assert "校验失败" in response.json()["detail"]


def test_douyin_config_requires_stable_targets_and_enforces_limits(client_and_user):
    client, user = client_and_user
    enable_admin_douyin(client, user)

    unstable = client.put(
        "/api/douyin/config",
        json={"enabled": True, "targets": [{"name": "旧版目标", "mode": "standard"}]},
    )
    assert unstable.status_code == 400
    assert "稳定标识" in unstable.json()["detail"]

    allowed = [
        {"name": f"目标{i}", "conversation_id": f"d{i}", "conversation_type": "direct"}
        for i in range(15)
    ]
    assert client.put("/api/douyin/config", json={"enabled": False, "targets": allowed}).status_code == 200

    too_many = [
        {"name": f"目标{i}", "conversation_id": f"d{i}", "conversation_type": "direct"}
        for i in range(16)
    ]
    assert client.put("/api/douyin/config", json={"enabled": False, "targets": too_many}).status_code == 400
    assert client.put("/api/douyin/config", json={"default_message": "x" * 201}).status_code == 400


def test_douyin_hour_change_clears_daily_random_schedule(client_and_user):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    user["douyin"].update({
        "hour": 6,
        "auto_schedule_date": "2026-08-23",
        "auto_schedule_hour": 6,
        "auto_schedule_offset_minutes": 4,
        "auto_scheduled_at": "2026-08-23T06:04:00+08:00",
    })
    store.save_user(user)

    response = client.put("/api/douyin/config", json={"hour": 7})
    assert response.status_code == 200
    saved = store.load_user(user["id"])
    assert saved["douyin"]["hour"] == 7
    assert "auto_scheduled_at" not in saved["douyin"]
    assert "auto_schedule_offset_minutes" not in saved["douyin"]

    midnight = client.put("/api/douyin/config", json={"hour": 0})
    assert midnight.status_code == 200
    assert store.load_user(user["id"])["douyin"]["hour"] == 0


def test_manual_douyin_run_is_rate_limited(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    monkeypatch.setattr(api_module, "run_spark", lambda _user: {"success": True, "results": []})
    assert [client.post("/api/douyin/run").status_code for _ in range(3)] == [200, 200, 200]
    assert client.post("/api/douyin/run").status_code == 429


def test_single_target_and_full_run_share_rate_limit(client_and_user, monkeypatch):
    client, user = client_and_user
    enable_admin_douyin(client, user)
    user["douyin"]["targets"] = [
        {"name": "测试好友", "conversation_id": "direct-1", "conversation_type": "direct"}
    ]
    store.save_user(user)
    monkeypatch.setattr(api_module, "run_spark", lambda _user, **_kwargs: {"success": True, "results": []})

    assert client.post("/api/douyin/run").status_code == 200
    assert client.post("/api/douyin/run-target", json={"target_key": "id:direct-1"}).status_code == 200
    assert client.post("/api/douyin/run").status_code == 200
    assert client.post("/api/douyin/run-target", json={"target_key": "id:direct-1"}).status_code == 429


def test_web_aes_fallback_asset_is_served(client_and_user):
    client, _user = client_and_user
    response = client.get("/assets/aes-gcm.min.js")
    assert response.status_code == 200
    assert "muzAesGcmEncrypt" in response.text


def test_web_exposes_single_target_spark_test_action(client_and_user):
    client, _user = client_and_user
    response = client.get("/")
    assert response.status_code == 200
    assert 'data-action="run-spark-target"' in response.text
    assert 'api("/api/douyin/run-target"' in response.text
    assert "const MAX_SPARK_TARGETS = 15" in response.text
    assert "每位好友间隔 20 秒" in response.text
    assert "configuration_preserved" in response.text


def test_tibo_x_session_import_encrypts_at_rest(client_and_user, monkeypatch):
    client, user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    async def fake_verify(cookies):
        assert cookies == {"auth_token": "tok-secret", "ct0": "ct-secret"}

    monkeypatch.setattr(api_module.tibo, "verify_x_cookies", fake_verify)

    plaintext = client.post("/api/tibo/x-session", json={"cookies": "auth_token=tok-secret"})
    assert plaintext.status_code == 400
    assert "仅接受加密凭据" in plaintext.json()["detail"]

    response = client.post(
        "/api/tibo/x-session",
        json=hybrid_secret_payload(client, "auth_token=tok-secret; ct0=ct-secret"),
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True

    raw = store.user_path(user["id"]).read_text(encoding="utf-8")
    assert "tok-secret" not in raw
    assert "ct-secret" not in raw
    reloaded = store.load_user(user["id"])
    assert reloaded["tibo"]["x_cookies_encrypted"].startswith("v1:")
    assert store.get_tibo_x_cookies(reloaded["tibo"]) == {"auth_token": "tok-secret", "ct0": "ct-secret"}
    assert store.public_user(reloaded)["tibo"]["x_connected"] is True

    history = client.get("/api/tibo/history")
    assert history.status_code == 200
    assert history.json()["x_connected"] is True

    removed = client.delete("/api/tibo/x-session")
    assert removed.status_code == 200
    reloaded = store.load_user(user["id"])
    assert "x_cookies_encrypted" not in reloaded["tibo"]
    assert store.public_user(reloaded)["tibo"]["x_connected"] is False


def test_tibo_x_session_rejects_invalid_cookie(client_and_user, monkeypatch):
    client, _user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    async def fake_verify(cookies):
        raise ValueError("X Cookie 无效或已过期")

    monkeypatch.setattr(api_module.tibo, "verify_x_cookies", fake_verify)
    response = client.post(
        "/api/tibo/x-session",
        json=hybrid_secret_payload(client, "auth_token=bad; ct0=bad"),
    )
    assert response.status_code == 400
    assert "无效" in response.json()["detail"]


def test_tibo_x_session_rejects_cookie_without_required_keys(client_and_user, monkeypatch):
    client, _user = client_and_user
    login = client.post("/api/auth/login", json=login_payload(client, keep_login=True))
    assert login.status_code == 200

    async def fake_verify(cookies):
        raise AssertionError("must not be called")

    monkeypatch.setattr(api_module.tibo, "verify_x_cookies", fake_verify)
    response = client.post(
        "/api/tibo/x-session",
        json=hybrid_secret_payload(client, "sessionid=only"),
    )
    assert response.status_code == 400
    assert "auth_token" in response.json()["detail"]
