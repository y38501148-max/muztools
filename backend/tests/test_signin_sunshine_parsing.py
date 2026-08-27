import pytest

from muztool import sunshine
from muztool.api import format_schedule
from muztool.signin_core import parse_schedule_payload


def test_schedule_payload_empty_status_without_errmsg_returns_empty():
    # iClass replies {"STATUS":"2"} when the student has no courses that day.
    assert parse_schedule_payload({"STATUS": "2"}) == []


def test_schedule_payload_success_returns_rows():
    rows = [{"id": 1, "courseName": "数学"}]
    assert parse_schedule_payload({"STATUS": "0", "result": rows}) == rows


def test_schedule_payload_error_message_raises():
    with pytest.raises(ValueError, match="session"):
        parse_schedule_payload({"STATUS": "1", "ERRMSG": "session 已失效"})


def test_unwrap_new_format_with_data_wrapper():
    payload = {"code": 1, "result": {"data": {"uid": 1, "token": "t"}}, "msg": ""}
    assert sunshine._unwrap(payload) == {"uid": 1, "token": "t"}


def test_unwrap_new_format_plain_result():
    payload = {"code": 1, "result": {"list": [{"classify_id": 1}], "total": 1}, "msg": ""}
    assert sunshine._unwrap(payload)["list"] == [{"classify_id": 1}]


def test_unwrap_new_format_error_raises_msg():
    with pytest.raises(ValueError, match="参数错误"):
        sunshine._unwrap({"code": 0, "result": None, "msg": "参数错误"})


def test_unwrap_new_format_expired_login():
    with pytest.raises(ValueError, match="失效"):
        sunshine._unwrap({"code": -98, "result": None, "msg": ""})


def test_unwrap_legacy_format_still_supported():
    assert sunshine._unwrap({"e": 0, "d": {"uid": 2}}) == {"uid": 2}
    with pytest.raises(ValueError):
        sunshine._unwrap({"e": 1, "m": "失败"})


def test_format_schedule_empty_has_no_class_message():
    payload = format_schedule([], enabled=True, approved=True, today="20260827", cached=False)
    assert payload["message"] == "您今天没有需要签到的课"
    assert payload["courses"] == []


def test_format_schedule_non_empty_has_no_message():
    payload = format_schedule(
        [{"id": 1, "courseName": "数学", "classBeginTime": "2026-09-14 08:00"}],
        enabled=True,
        approved=True,
        today="20260914",
        cached=False,
    )
    assert "message" not in payload
    assert len(payload["schedule"]) == 1
