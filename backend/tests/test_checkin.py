import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Random import get_random_bytes
from Crypto.PublicKey import RSA

from muztool import api as api_module
from muztool import config, invites, store
from muztool.checkin import (
    CheckinAuthError,
    CheckinError,
    get_provider,
    list_providers,
)
from muztool.checkin import qiandao as qiandao_provider
from muztool.checkin.qiandao import (
    check_token,
    fetch_activity,
    merge_form_values,
    submit_sign,
    validate_activity_code,
    validate_token,
)
from muztool.store import get_checkin_token, set_checkin_token


SIGN_INFO = {
    "code": 1,
    "info": "获取签到活动详情",
    "data": {
        "info": {
            "id": 716790,
            "type": 2,
            "code": "AS202608243746752343",
            "name": "软工大模型班签到",
            "start_at": "2026-08-24 12:00:00",
            "end_at": "2026-09-23 23:59:59",
            "token_status": 0,
            "location_status": 1,
            "location_address": "北航主楼M楼",
            "location_longitude": "116.35062",
            "location_latitude": "39.984077",
            "location_min_distance": "500",
            "can_sign": 1,
        },
        "from_data": [
            {"title": "姓名", "form_data_type": 1, "options": [], "is_required": 1, "is_check": True},
            {"title": "学号", "form_data_type": 1, "options": ["", ""], "is_required": 1, "is_check": True},
        ],
        "sign_time": [["09:00:00", "12:00:59"], ["14:00:00", "17:00:59"]],
    },
}


def make_mock_client(sign_info=None, sign_do=None, captured=None):
    sign_info = SIGN_INFO if sign_info is None else sign_info

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append((request.url.path, request.headers.get("authori-zation"), request.read().decode()))
        if request.url.path == "/api/activity/signInfo":
            return httpx.Response(200, json=sign_info)
        if request.url.path == "/api/activity/signDo":
            return httpx.Response(200, json=sign_do or {"code": 1, "info": "签到成功", "data": {}})
        return httpx.Response(200, json={"code": 0, "info": "签到活动已关闭", "data": {}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- provider 注册表 ----------


def test_provider_registry_contains_qiandaoerweima():
    providers = list_providers()
    assert [p["id"] for p in providers] == [qiandao_provider.PROVIDER_ID]
    assert providers[0]["name"] == "签到二维码"
    assert get_provider("qiandaoerweima") is qiandao_provider
    with pytest.raises(ValueError):
        get_provider("nonexistent")


# ---------- 协议客户端单元测试 ----------


def test_validate_token_accepts_hex_and_rejects_others():
    assert validate_token("  0123456789ABCDEF0123456789ABCDEF ") == "0123456789abcdef0123456789abcdef"
    for bad in ("", "xyz", "90f1b63bf197ef4a0bb7ddc2331a117", "g" * 32):
        with pytest.raises(ValueError):
            validate_token(bad)


def test_validate_activity_code_format():
    assert validate_activity_code("as202608243746752343 ") == "AS202608243746752343"
    for bad in ("", "BS202608243746752343", "AS123", "AS" + "1" * 30):
        with pytest.raises(ValueError):
            validate_activity_code(bad)


def test_check_token_detects_valid_token():
    client = make_mock_client()
    assert asyncio.run(check_token("a" * 32, client=client))


def test_check_token_detects_expired_token():
    client = make_mock_client(sign_info={"code": 500, "info": "请重新登录，登录认证无效", "data": []})
    assert not asyncio.run(check_token("a" * 32, client=client))


def test_fetch_activity_parses_details():
    client = make_mock_client()
    activity = asyncio.run(fetch_activity("a" * 32, "AS202608243746752343", client=client))
    assert activity["code"] == "AS202608243746752343"
    assert activity["name"] == "软工大模型班签到"
    assert activity["location_required"] is True
    assert activity["location_longitude"] == "116.35062"
    assert activity["sign_time"] == [["09:00:00", "12:00:59"], ["14:00:00", "17:00:59"]]
    assert [f["title"] for f in activity["fields"]] == ["姓名", "学号"]
    assert activity["fields"][0]["required"] is True


def test_fetch_activity_auth_error():
    client = make_mock_client(sign_info={"code": 500, "info": "请重新登录，登录认证无效", "data": []})
    with pytest.raises(CheckinAuthError):
        asyncio.run(fetch_activity("a" * 32, "AS202608243746752343", client=client))


def test_fetch_activity_business_error():
    client = make_mock_client(sign_info={"code": 0, "info": "签到活动已关闭", "data": {}})
    with pytest.raises(CheckinError):
        asyncio.run(fetch_activity("a" * 32, "AS202608243746752343", client=client))


def test_merge_form_values_reports_missing_required_fields():
    raw = SIGN_INFO["data"]["from_data"]
    with pytest.raises(CheckinError) as exc:
        merge_form_values(raw, {"姓名": "张三"})
    assert "学号" in str(exc.value)

    merged = merge_form_values(raw, {"姓名": "张三", "学号": "2413010"})
    assert merged[0]["value"] == "张三"
    assert merged[0]["title"] == "姓名"
    # 原始字段结构必须原样保留。
    assert merged[1]["options"] == ["", ""]


def test_submit_sign_uses_activity_coordinates_and_form_values():
    captured = []
    client = make_mock_client(captured=captured)
    result = asyncio.run(
        submit_sign(
            "a" * 32,
            "AS202608243746752343",
            {"姓名": "张三", "学号": "2413010"},
            client=client,
        )
    )
    assert result == {"success": True, "message": "签到成功", "activity": "软工大模型班签到"}

    sign_do = [c for c in captured if c[0] == "/api/activity/signDo"][0]
    body = parse_qs(sign_do[2])
    assert body["code"] == ["AS202608243746752343"]
    assert body["lng"] == ["116.35062"]
    assert body["lat"] == ["39.984077"]
    form = json.loads(body["from_data"][0])
    assert form[0]["value"] == "张三"
    assert form[1]["value"] == "2413010"


def test_submit_sign_uses_manual_coordinates_when_activity_hides_them():
    sign_info = json.loads(json.dumps(SIGN_INFO))
    sign_info["data"]["info"]["location_longitude"] = ""
    sign_info["data"]["info"]["location_latitude"] = ""
    captured = []
    client = make_mock_client(sign_info=sign_info, captured=captured)
    result = asyncio.run(
        submit_sign(
            "a" * 32,
            "AS202608243746752343",
            {"姓名": "张三", "学号": "2413010"},
            {"lng": "116.35062", "lat": "39.984077"},
            client=client,
        )
    )
    assert result["success"] is True
    body = parse_qs([item for item in captured if item[0] == "/api/activity/signDo"][0][2])
    assert body["lng"] == ["116.35062"]
    assert body["lat"] == ["39.984077"]


def test_submit_sign_requires_manual_coordinates_when_activity_hides_them():
    sign_info = json.loads(json.dumps(SIGN_INFO))
    sign_info["data"]["info"]["location_longitude"] = ""
    sign_info["data"]["info"]["location_latitude"] = ""
    with pytest.raises(CheckinError, match="手动填写签到经纬度"):
        asyncio.run(
            submit_sign(
                "a" * 32,
                "AS202608243746752343",
                {"姓名": "张三", "学号": "2413010"},
                client=make_mock_client(sign_info=sign_info),
            )
        )


def test_submit_sign_rejects_invalid_manual_coordinates():
    sign_info = json.loads(json.dumps(SIGN_INFO))
    sign_info["data"]["info"]["location_longitude"] = ""
    sign_info["data"]["info"]["location_latitude"] = ""
    with pytest.raises(CheckinError, match="经度超出有效范围"):
        asyncio.run(
            submit_sign(
                "a" * 32,
                "AS202608243746752343",
                {"姓名": "张三", "学号": "2413010"},
                {"lng": "181", "lat": "39.984077"},
                client=make_mock_client(sign_info=sign_info),
            )
        )


def test_submit_sign_maps_business_reject_to_result():
    client = make_mock_client(sign_do={"code": 0, "info": "已签到，无需再次签到！", "data": {}})
    result = asyncio.run(
        submit_sign("a" * 32, "AS202608243746752343", {"姓名": "张三", "学号": "2413010"}, client=client)
    )
    assert result["success"] is False
    assert result["message"] == "已签到，无需再次签到！"


def test_submit_sign_rejects_oversized_value():
    with pytest.raises(CheckinError):
        asyncio.run(submit_sign("a" * 32, "AS202608243746752343", {"姓名": "超" * 201}, client=make_mock_client()))


# ---------- API 路由测试 ----------


def encrypted_payload(client, fields, *, keep_login=True):
    public = client.get("/api/security/public-key")
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

    user = store.create_user("checkin_user", "Secret1", "Checkin")
    store.save_user(user)

    with TestClient(api_module.app) as client:
        login = client.post(
            "/api/auth/login",
            json=encrypted_payload(client, {"username": "checkin_user", "password": "Secret1"}),
        )
        assert login.status_code == 200
        yield client, user


def test_checkin_routes_require_auth():
    with TestClient(api_module.app) as client:
        assert client.get("/api/checkin/providers").status_code == 401
        assert client.get("/api/checkin/qiandaoerweima/config").status_code == 401


def test_checkin_macos_tool_download():
    with TestClient(api_module.app) as client:
        response = client.get("/downloads/muz-checkin-token-macos.zip")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert "MuzTool-Checkin-Token-macOS.zip" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"PK")
    with ZipFile(BytesIO(response.content)) as archive:
        info = archive.getinfo("MuzTool-Checkin-Token-macOS.command")
        assert info.external_attr >> 16 & 0o111
        assert archive.read(info).startswith(b"#!/bin/bash")


def test_checkin_unknown_provider_returns_404(client_and_user):
    client, _ = client_and_user
    assert client.get("/api/checkin/nonexistent/config").status_code == 404


def test_checkin_providers_endpoint(client_and_user):
    client, _ = client_and_user
    response = client.get("/api/checkin/providers")
    assert response.status_code == 200
    assert response.json()["providers"][0]["id"] == "qiandaoerweima"


def test_checkin_webui_wraps_token_in_encrypted_envelope():
    html = Path(api_module.WEB_DIR, "index.html").read_text(encoding="utf-8")
    handler_start = html.index('if (action === "checkin-save-token")')
    handler_end = html.index('if (action === "checkin-edit-token")', handler_start)
    handler = html[handler_start:handler_end]

    assert "const payload = {encrypted: await encryptedFields({token})};" in handler
    assert "body: payload" in handler
    assert "const payload = await encryptedFields({token});" not in handler


def test_checkin_save_token_roundtrip(client_and_user, monkeypatch):
    client, user = client_and_user

    async def fake_check_token(token, client=None):
        return token == "a" * 32

    monkeypatch.setattr(qiandao_provider, "check_token", fake_check_token)

    saved = client.put("/api/checkin/qiandaoerweima/config", json=encrypted_payload(client, {"token": "a" * 32}))
    assert saved.status_code == 200
    assert saved.json()["connected"] is True
    assert saved.json()["token_tail"] == "a" * 6

    status = client.get("/api/checkin/qiandaoerweima/config")
    assert status.status_code == 200
    assert status.json() == {"provider": "qiandaoerweima", "connected": True, "token_tail": "a" * 6}

    fresh = store.load_user(user["id"])
    assert get_checkin_token(fresh["checkin"]["qiandaoerweima"]) == "a" * 32
    # 静态存储必须是密文。
    assert fresh["checkin"]["qiandaoerweima"]["token_encrypted"].startswith("v1:")


def test_checkin_save_token_rejects_bad_format(client_and_user):
    client, _ = client_and_user
    response = client.put("/api/checkin/qiandaoerweima/config", json=encrypted_payload(client, {"token": "not-hex"}))
    assert response.status_code == 400
    assert "格式无效" in response.json()["detail"]


def test_checkin_save_token_rejects_expired_token(client_and_user, monkeypatch):
    client, _ = client_and_user

    async def fake_check_token(token, client=None):
        return False

    monkeypatch.setattr(qiandao_provider, "check_token", fake_check_token)
    response = client.put("/api/checkin/qiandaoerweima/config", json=encrypted_payload(client, {"token": "a" * 32}))
    assert response.status_code == 400
    assert "无效或已过期" in response.json()["detail"]


def test_checkin_preview_requires_token(client_and_user):
    client, _ = client_and_user
    response = client.post("/api/checkin/qiandaoerweima/preview", json={"code": "AS202608243746752343"})
    assert response.status_code == 400
    assert "请先配置签到 token" in response.json()["detail"]


def _save_token_for(user):
    fresh = store.load_user(user["id"])
    fresh.setdefault("checkin", {}).setdefault("qiandaoerweima", {})
    set_checkin_token(fresh["checkin"]["qiandaoerweima"], "b" * 32)
    store.save_user(fresh)


def test_checkin_preview_returns_activity(client_and_user, monkeypatch):
    client, user = client_and_user
    _save_token_for(user)

    async def fake_fetch(token, code, client=None):
        assert token == "b" * 32
        return {"code": code, "name": "测试活动", "fields": [], "sign_time": []}

    monkeypatch.setattr(qiandao_provider, "fetch_activity", fake_fetch)
    response = client.post("/api/checkin/qiandaoerweima/preview", json={"code": "AS202608243746752343"})
    assert response.status_code == 200
    assert response.json()["activity"]["name"] == "测试活动"


def test_checkin_sign_returns_result(client_and_user, monkeypatch):
    client, user = client_and_user
    _save_token_for(user)

    async def fake_submit(token, code, values, options=None, client=None):
        assert values == {"姓名": "张三"}
        assert options == {}
        return {"success": True, "message": "签到成功", "activity": "测试活动"}

    monkeypatch.setattr(qiandao_provider, "submit_sign", fake_submit)
    response = client.post(
        "/api/checkin/qiandaoerweima/sign",
        json={"code": "AS202608243746752343", "values": {"姓名": "张三"}},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_checkin_sign_maps_auth_error(client_and_user, monkeypatch):
    client, user = client_and_user
    _save_token_for(user)

    async def fake_submit(token, code, values, options=None, client=None):
        raise CheckinAuthError("签到 token 已失效，请重新获取并配置")

    monkeypatch.setattr(qiandao_provider, "submit_sign", fake_submit)
    response = client.post("/api/checkin/qiandaoerweima/sign", json={"code": "AS202608243746752343", "values": {}})
    assert response.status_code == 400
    assert "token 已失效" in response.json()["detail"]
