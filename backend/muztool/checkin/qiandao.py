"""签到二维码小程序 provider（qiandaoerweima.yuleji.top）。

协议于 2026-08-27 通过 mitmproxy 抓包逆向并实测验证：

- ``POST /api/activity/signInfo``（body: ``code=活动码``）返回活动详情，
  响应中直接包含定位校验坐标 ``location_longitude/latitude`` 与表单定义
  ``from_data``。
- ``POST /api/activity/signDo``（body: ``code`` + ``from_data=JSON`` +
  ``lng/lat=客户端上报经纬度``）执行签到。服务端仅校验上报坐标与活动
  坐标的距离，无签名 / IP / UA 校验；口令签到（``token_status=1``）的
  口令同样不做服务端校验。
- 鉴权仅需 ``authori-zation`` 请求头中的 32 位十六进制 token，该 token
  由小程序 ``wx.login`` 换取，约 2 小时过期且重新登录会使旧 token 失效，
  因此本模块只负责消费用户提供的 token，不负责获取。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import CheckinAuthError, CheckinError

PROVIDER_ID = "qiandaoerweima"
PROVIDER_NAME = "签到二维码"
PROVIDER_DESCRIPTION = "签到二维码小程序活动签到：输入活动码自动读取表单，远程一键签到"

API_BASE = "https://qiandaoerweima.yuleji.top"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Mac"
)
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
ACTIVITY_CODE_RE = re.compile(r"^AS\d{15,25}$")
# 探测 token 有效性用的哨兵活动码：服务端先做鉴权，token 有效时对该码
# 返回业务错误（"签到活动已关闭"），无效时返回"请重新登录"。
PROBE_ACTIVITY_CODE = "AS000000000000000000000"

MAX_FIELDS = 20
MAX_FIELD_TITLE = 64
MAX_FIELD_VALUE = 200


def validate_token(token: Any) -> str:
    text = str(token or "").strip().lower()
    if not TOKEN_RE.fullmatch(text):
        raise ValueError("签到 token 格式无效，应为 32 位十六进制字符串")
    return text


def validate_activity_code(code: Any) -> str:
    text = str(code or "").strip().upper()
    if not ACTIVITY_CODE_RE.fullmatch(text):
        raise ValueError("活动码格式无效，应为 AS 开头的活动码")
    return text


def _headers(token: str) -> dict[str, str]:
    return {
        "api-name": "wxapp",
        "authori-zation": token,
        "user-agent": UA,
    }


async def _post(
    path: str,
    token: str,
    data: dict[str, str],
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=25)
    try:
        try:
            response = await client.post(
                API_BASE + path,
                data=data,
                headers=_headers(token),
            )
        except httpx.HTTPError as exc:
            raise CheckinError("签到服务暂时无法访问，请稍后重试") from exc
    finally:
        if own:
            await client.aclose()
    try:
        payload = response.json()
    except ValueError as exc:
        raise CheckinError("签到服务返回了无法解析的响应") from exc
    if not isinstance(payload, dict):
        raise CheckinError("签到服务返回了无法解析的响应")
    info = str(payload.get("info") or "")
    if int(payload.get("code") or 0) == 500 or "重新登录" in info:
        raise CheckinAuthError("签到 token 已失效，请重新获取并配置")
    return payload


async def check_token(token: str, client: httpx.AsyncClient | None = None) -> bool:
    """探测 token 是否仍然有效。"""
    try:
        await _post("/api/activity/signInfo", token, {"code": PROBE_ACTIVITY_CODE}, client=client)
    except CheckinAuthError:
        return False
    except CheckinError:
        # 业务错误（如"签到活动已关闭"）说明鉴权已经通过。
        return True
    return True


def _normalize_fields(raw: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return fields
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or len(title) > MAX_FIELD_TITLE:
            continue
        options = []
        for option in item.get("options") or []:
            if not isinstance(option, str):
                continue
            text = option.strip()
            if text:
                options.append(text)
        try:
            data_type = int(item.get("form_data_type") or 1)
        except (TypeError, ValueError):
            data_type = 1
        fields.append(
            {
                "title": title,
                "data_type": data_type,
                "options": options,
                "required": str(item.get("is_required") or "0") == "1",
            }
        )
        if len(fields) >= MAX_FIELDS:
            break
    return fields


def _activity_payload(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    info = data.get("info")
    info = info if isinstance(info, dict) else {}
    if int(payload.get("code") or 0) != 1 or not info:
        raise CheckinError(str(payload.get("info") or "签到活动不存在或已关闭"))
    sign_time = data.get("sign_time")
    return {
        "code": str(info.get("code") or code),
        "name": str(info.get("name") or ""),
        "start_at": str(info.get("start_at") or ""),
        "end_at": str(info.get("end_at") or ""),
        "can_sign": int(info.get("can_sign") or 0),
        "location_required": str(info.get("location_status") or "0") == "1",
        "location_address": str(info.get("location_address") or ""),
        "location_longitude": str(info.get("location_longitude") or ""),
        "location_latitude": str(info.get("location_latitude") or ""),
        "sign_time": sign_time if isinstance(sign_time, list) else [],
        "fields": _normalize_fields(data.get("from_data")),
    }


async def fetch_activity(
    token: str,
    code: Any,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """查询签到活动详情，返回供前端渲染的归一化结构。"""
    code = validate_activity_code(code)
    payload = await _post("/api/activity/signInfo", token, {"code": code}, client=client)
    return _activity_payload(code, payload)


def merge_form_values(raw: Any, values: dict[str, str]) -> list[dict[str, Any]]:
    """把用户填写的内容合并进服务端下发的表单结构。

    signDo 要求原样带回 signInfo 返回的 ``from_data`` 数组并给每个字段
    附加 ``value``，字段结构必须逐项保持一致。
    """
    merged: list[dict[str, Any]] = []
    missing: list[str] = []
    if not isinstance(raw, list):
        return merged
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        value = str(values.get(title) or "").strip()
        if str(item.get("is_required") or "0") == "1" and not value:
            missing.append(title)
            continue
        field = dict(item)
        field["value"] = value
        merged.append(field)
    if missing:
        raise CheckinError("以下必填项未填写：" + "、".join(missing))
    return merged


def _sanitize_values(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ValueError("表单内容格式无效")
    clean: dict[str, str] = {}
    for key, value in values.items():
        title = str(key or "").strip()
        text = str(value or "").strip()
        if not title or len(title) > MAX_FIELD_TITLE:
            continue
        if len(text) > MAX_FIELD_VALUE:
            raise CheckinError(f"字段「{title}」内容过长（最多 {MAX_FIELD_VALUE} 字）")
        clean[title] = text
    if len(clean) > MAX_FIELDS:
        raise ValueError(f"表单字段数量过多（最多 {MAX_FIELDS} 项）")
    return clean


async def submit_sign(
    token: str,
    code: Any,
    values: dict[str, str],
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """执行签到。

    定位签到直接使用活动自身坐标作为上报坐标（服务端只比较距离），
    口令签到无需携带口令（服务端不校验）。
    """
    code = validate_activity_code(code)
    clean = _sanitize_values(values)
    payload = await _post("/api/activity/signInfo", token, {"code": code}, client=client)
    activity = _activity_payload(code, payload)

    # 重新取原始 from_data 结构用于回填，避免归一化时丢失字段。
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    form = merge_form_values(data.get("from_data"), clean)

    body = {"code": code, "from_data": json.dumps(form, ensure_ascii=False, separators=(",", ":"))}
    if activity["location_required"]:
        lng = activity["location_longitude"]
        lat = activity["location_latitude"]
        if lng and lat:
            body["lng"] = lng
            body["lat"] = lat

    result = await _post("/api/activity/signDo", token, body, client=client)
    success = int(result.get("code") or 0) == 1
    return {
        "success": success,
        "message": str(result.get("info") or ("签到成功" if success else "签到失败")),
        "activity": activity["name"],
    }
