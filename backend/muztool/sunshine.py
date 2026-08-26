from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from .signin_core import UA, sso_login

API_BASE = "https://ygdk.buaa.edu.cn/api/Front"
OAUTH_URL = (
    "https://app.buaa.edu.cn/uc/api/oauth/index"
    "?redirect=https%3A%2F%2Fygdk.buaa.edu.cn%2F%23%2Fhome"
    "&appid=200230221144501510&state=STATE&qrcode=1"
)
CODE_RE = re.compile(r"[?&#]code=([^&#]+)")


def _api(path: str) -> str:
    return API_BASE + path


async def _sso_client(student_id: str, password: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(verify=False, follow_redirects=True, headers={"User-Agent": UA}, timeout=25)
    await sso_login(client, student_id, password, use_vpn=False)
    return client


def _extract_code(text: str) -> str | None:
    match = CODE_RE.search(text)
    if not match:
        return None
    return unquote(match.group(1))


async def _oauth_code(client: httpx.AsyncClient) -> str:
    current = OAUTH_URL
    no_redirect = httpx.AsyncClient(
        verify=False,
        follow_redirects=False,
        cookies=client.cookies,
        headers={"User-Agent": UA},
        timeout=25,
    )
    try:
        for _ in range(12):
            response = await no_redirect.get(current)
            for candidate in (str(response.url), response.headers.get("Location", ""), response.text[:4000]):
                code = _extract_code(candidate)
                if code:
                    return code
            location = response.headers.get("Location")
            if not location:
                break
            if location.startswith("/"):
                parsed = urlparse(current)
                current = f"{parsed.scheme}://{parsed.netloc}{location}"
            else:
                current = location if location.startswith("http") else urljoin(current, location)
    finally:
        await no_redirect.aclose()
    raise ValueError("无法从阳光打卡 OAuth 跳转中获取 code")


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("e")) not in {"0", "None"} and payload.get("e") not in {0, None}:
        raise ValueError(payload.get("m") or "阳光打卡接口失败")
    data = payload.get("d") or payload.get("data") or payload
    return data if isinstance(data, dict) else payload


async def query_sunshine(student_id: str, password: str) -> dict[str, Any]:
    client = await _sso_client(student_id, password)
    try:
        code = await _oauth_code(client)
        login = await client.get(_api("/Clockin/User/campusAppLogin"), params={"code": code})
        login.raise_for_status()
        session = _unwrap(login.json())
        uid = session.get("uid")
        token = unquote(str(session.get("token") or ""))
        if not uid or not token:
            raise ValueError("阳光打卡登录响应缺少 uid/token")
        form = {"uid": str(uid), "token": token}
        classify_res = await client.post(
            _api("/Clockin/Classify/getList"),
            data=form,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        classify_res.raise_for_status()
        classify_list = (_unwrap(classify_res.json()).get("list") or [])
        classify = next((item for item in classify_list if "体育" in str(item.get("name", ""))), None)
        classify = classify or next((item for item in classify_list if item.get("classify_id") == 1), None)
        classify = classify or (classify_list[0] if classify_list else None)
        if not classify:
            raise ValueError("未获取到阳光打卡分类")
        count_res = await client.post(
            _api("/Clockin/Clockin/getCount"),
            data={**form, "classify_id": str(classify.get("classify_id")), "user_id": str(uid)},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        count_res.raise_for_status()
        counts = _unwrap(count_res.json())

        def _int(*keys: str) -> int:
            for key in keys:
                value = counts.get(key)
                if value not in (None, ""):
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        continue
            return 0

        good = _int("term_good_count_show", "term_good_count")
        term = good if ("term_good_count_show" in counts or "term_good_count" in counts) else _int("term_count_show", "term_count")
        return {
            "classify_id": classify.get("classify_id"),
            "classify_name": classify.get("name"),
            "term_count": term,
            "term_target": _int("term_num") or 16,
            "week_count": _int("week_count"),
            "week_target": _int("week_num") or 4,
            "day_count": _int("day_count"),
            "good_count": good,
        }
    finally:
        await client.aclose()
