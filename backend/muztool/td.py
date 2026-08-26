from __future__ import annotations

import json
import re
import socket
import struct
from datetime import datetime, timezone
from typing import Any

import httpx

from . import config
from .signin_core import UA, TZ_BEIJING, sso_login

TD_SERVER_HOST = config.TD_SERVER_HOST
TD_INDEX_URL = f"http://{TD_SERVER_HOST}/index.php?schoolno=10006"
TD_SCORE_URL = f"http://{TD_SERVER_HOST}/main.php?module=stu&title=stu_sun_score"
TD_SERVER_PORT = 8888
TD_SERVER_IP = TD_SERVER_HOST
COUNT_RE = re.compile(r"本学期锻炼次数\s*[:：]\s*(\d+)")
SCORE_RE = re.compile(
    r"<td>\s*(\d{4})\s*-\s*(\d{4})\s*</td>\s*<td>\s*(\d+)\s*</td>\s*<td>\s*(\d+)\s*</td>\s*<td>\s*-\s*</td>",
    re.S,
)
WINDOWS = [(7 * 60 + 30, 10 * 60), (11 * 60 + 30, 14 * 60), (15 * 60 + 30, 20 * 60)]

MACHINES = {
    "xueyuanlu": {
        "entrance": [
            {"id": 2, "sn": "20211025001", "location": "北航本部TD入口1"},
            {"id": 4, "sn": "20230417001", "location": "北航本部TD入口2"},
            {"id": 3, "sn": "20220301004", "location": "北航本部TD入口3"},
        ],
        "exit": [
            {"id": 6, "sn": "20210420002", "location": "北航本部TD出口1"},
            {"id": 5, "sn": "20210421003", "location": "北航本部TD出口2"},
            {"id": 7, "sn": "20220301003", "location": "北航本部TD出口3"},
        ],
    },
    "shahe": {
        "entrance": [
            {"id": 8, "sn": "20210511001", "location": "北航沙河TD入口1"},
            {"id": 9, "sn": "20210511002", "location": "北航沙河TD入口2"},
            {"id": 10, "sn": "20210511003", "location": "北航沙河TD入口3"},
        ],
        "exit": [
            {"id": 11, "sn": "20220218001", "location": "北航沙河TD出口1"},
            {"id": 12, "sn": "20220218002", "location": "北航沙河TD出口2"},
            {"id": 13, "sn": "20220218003", "location": "北航沙河TD出口3"},
        ],
    },
}

MACHINE_BY_ID = {
    item["id"]: item
    for campus in MACHINES.values()
    for group in campus.values()
    for item in group
}


def card_id_from_student(student_id: str) -> str:
    return hex(int(student_id))[2:].upper()


def beijing_minutes(ts_ms: int) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(TZ_BEIJING)
    return dt.hour * 60 + dt.minute


def window_index(minutes: int) -> int | None:
    for index, (start, end) in enumerate(WINDOWS):
        if start <= minutes <= end:
            return index
    return None


def plan_timestamps(gap_seconds: int = 240, now_ms: int | None = None) -> tuple[int, int]:
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) if now_ms is None else now_ms
    if window_index(beijing_minutes(now_ms)) is None:
        raise ValueError("当前时间不在 TD 打卡窗口内（07:30-10:00 / 11:30-14:00 / 15:30-20:00）")
    gap = max(60, min(int(gap_seconds), 3600))
    exit_ms = now_ms + gap * 1000
    if window_index(beijing_minutes(exit_ms)) is None:
        raise ValueError("伪造出口时间超出合法打卡窗口，请缩短时间差")
    return now_ms, exit_ms


def _tcp_request(payload: bytes, request_type: int, timeout: float = 10.0) -> dict[str, Any]:
    header = struct.pack(">lB", len(payload), request_type)
    with socket.create_connection((TD_SERVER_IP, TD_SERVER_PORT), timeout=timeout) as sock:
        sock.sendall(header + payload)
        response_header = _recv_exact(sock, 5)
        length, _code = struct.unpack(">lB", response_header)
        if length <= 0:
            raise ConnectionError("TD 服务器返回空响应")
        body = _recv_exact(sock, length)
    return json.loads(body.decode("utf-8"))


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("TD 连接已关闭")
        data += chunk
    return data


def _clean(message: str) -> str:
    return message.strip().replace("\n \n", "\n").replace("\n", ", ")


def _count(message: str) -> int | None:
    match = COUNT_RE.search(message)
    return int(match.group(1)) if match else None


def _check_and_upload(student_id: str, machine_id: int, photo: bytes, timestamp_ms: int) -> dict[str, Any]:
    machine = MACHINE_BY_ID.get(machine_id)
    if not machine:
        raise ValueError(f"未知机位: {machine_id}")
    payload = {
        "cardno": card_id_from_student(student_id),
        "userno": student_id.upper(),
        "timestamp": str(timestamp_ms),
        "type": 1,
        "eventno": "802",
        "ln": str(machine["id"]),
        "sn": machine["sn"],
        "schoolno": "10006",
    }
    response = _tcp_request(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 80)
    if response.get("status") != "success":
        raise ValueError(f"TD 打卡请求失败: {response}")
    message = _clean(response.get("srvresp") or "")
    success = "成功" in (response.get("srvresp") or "")
    if success and photo:
        photo_payload = f"{machine['sn']}_{timestamp_ms}".encode("utf-8") + photo
        upload = _tcp_request(photo_payload, 100)
        if upload.get("status") != "success":
            raise ValueError(f"TD 照片上传失败: {upload}")
    return {
        "success": success,
        "message": message,
        "count": _count(message),
        "timestamp_ms": timestamp_ms,
        "machine": machine,
    }


async def query_td_counts(student_id: str, password: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers={"User-Agent": UA}, timeout=20) as client:
        await sso_login(client, student_id, password, use_vpn=False)
        index = await client.get(TD_INDEX_URL)
        index.raise_for_status()
        page = await client.get(TD_SCORE_URL)
        page.raise_for_status()
    rows = [
        {
            "term_start": int(match.group(1)),
            "term_end": int(match.group(2)),
            "term_no": int(match.group(3)),
            "count": int(match.group(4)),
        }
        for match in SCORE_RE.finditer(page.text)
    ]
    if not rows:
        raise ValueError("未能解析 TD 次数页面，请确认学号密码或稍后重试")
    rows.sort(key=lambda item: (item["term_start"], item["term_end"], item["term_no"]), reverse=True)
    return rows


def latest_count(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0]


def manual_td(
    student_id: str,
    entrance_machine_id: int,
    exit_machine_id: int,
    entrance_photo: bytes,
    exit_photo: bytes,
    gap_seconds: int = 240,
) -> dict[str, Any]:
    if not entrance_photo or not exit_photo:
        raise ValueError("请先上传入口图和出口图")
    entrance_ts, exit_ts = plan_timestamps(gap_seconds)
    entrance = _check_and_upload(student_id, entrance_machine_id, entrance_photo, entrance_ts)
    if not entrance["success"]:
        return {
            "success": False,
            "message": f"入口打卡失败：{entrance['message']}",
            "entrance": entrance,
            "exit": None,
            "count": entrance.get("count"),
        }
    exit_result = _check_and_upload(student_id, exit_machine_id, exit_photo, exit_ts)
    success = bool(exit_result["success"])
    return {
        "success": success,
        "message": "TD 手动打卡完成" if success else f"出口打卡失败：{exit_result['message']}",
        "entrance": entrance,
        "exit": exit_result,
        "count": exit_result.get("count") or entrance.get("count"),
        "gap_seconds": gap_seconds,
    }


def campus_machines(campus: str) -> dict[str, Any]:
    return MACHINES.get(campus, MACHINES["xueyuanlu"])
