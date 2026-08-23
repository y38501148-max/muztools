from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest


BRIDGE_PATH = Path(__file__).resolve().parents[1] / "muztool" / "web" / "td_web_bridge.py"
SPEC = importlib.util.spec_from_file_location("muztool_td_web_bridge", BRIDGE_PATH)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def beijing_ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=bridge.TZ_BEIJING).timestamp() * 1000)


def test_card_id_and_time_window_validation():
    assert bridge.card_id_from_student("12345678") == hex(12345678)[2:].upper()
    with pytest.raises(ValueError, match="学号格式"):
        bridge.card_id_from_student("not-a-student")

    entrance, exit_time = bridge.plan_timestamps(240, beijing_ms(2026, 8, 23, 8, 0))
    assert exit_time - entrance == 240_000

    with pytest.raises(ValueError, match="不在 TD 打卡窗口"):
        bridge.plan_timestamps(240, beijing_ms(2026, 8, 23, 10, 30))
    with pytest.raises(ValueError, match="超出当前合法打卡窗口"):
        bridge.plan_timestamps(15 * 60, beijing_ms(2026, 8, 23, 9, 50))


def test_manual_check_sends_entrance_and_exit_in_protocol_order(monkeypatch):
    calls: list[tuple[int, bytes]] = []
    responses = iter([
        {"status": "success", "srvresp": "打卡成功\n本学期锻炼次数：9"},
        {"status": "success"},
        {"status": "success", "srvresp": "打卡成功\n本学期锻炼次数：10"},
        {"status": "success"},
    ])

    def fake_tcp_request(payload: bytes, request_type: int, timeout: float = 10.0):
        del timeout
        calls.append((request_type, payload))
        return next(responses)

    monkeypatch.setattr(bridge, "tcp_request", fake_tcp_request)
    monkeypatch.setattr(bridge, "plan_timestamps", lambda _gap: (1_000, 241_000))

    payload = {
        "student_id": "12345678",
        "campus": "xueyuanlu",
        "entrance_machine_id": 4,
        "exit_machine_id": 5,
        "gap_seconds": 240,
        "entrance_photo": "data:image/jpeg;base64," + bridge.base64.b64encode(b"entrance-image").decode(),
        "exit_photo": bridge.base64.b64encode(b"exit-image").decode(),
    }
    result = bridge.manual_check(payload)

    assert result["success"] is True
    assert result["entrance"]["count"] == 9
    assert result["exit"]["count"] == 10
    assert [request_type for request_type, _ in calls] == [bridge.CHECK_TYPE, bridge.PHOTO_TYPE, bridge.CHECK_TYPE, bridge.PHOTO_TYPE]

    entrance_request = json.loads(calls[0][1].decode())
    exit_request = json.loads(calls[2][1].decode())
    assert entrance_request["ln"] == "4"
    assert entrance_request["sn"] == "20230417001"
    assert entrance_request["timestamp"] == "1000"
    assert exit_request["ln"] == "5"
    assert exit_request["sn"] == "20210421003"
    assert exit_request["timestamp"] == "241000"
    assert calls[1][1] == b"20230417001_1000entrance-image"
    assert calls[3][1] == b"20210421003_241000exit-image"


def test_manual_check_rejects_invalid_local_payload():
    valid_photo = bridge.base64.b64encode(b"photo").decode()
    with pytest.raises(ValueError, match="校区参数"):
        bridge.manual_check({
            "student_id": "12345678",
            "campus": "unknown",
            "entrance_photo": valid_photo,
            "exit_photo": valid_photo,
        })

    with pytest.raises(ValueError, match="1～15 分钟"):
        bridge.manual_check({
            "student_id": "12345678",
            "campus": "xueyuanlu",
            "gap_seconds": 3600,
            "entrance_photo": valid_photo,
            "exit_photo": valid_photo,
        })
