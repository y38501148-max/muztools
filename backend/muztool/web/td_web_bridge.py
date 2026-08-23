#!/usr/bin/env python3
"""MuzTool computer-side TD bridge.

Run this script on a computer connected to the campus network. The MuzTool
WebUI sends a signed local request to 127.0.0.1; this bridge performs the raw
TCP protocol that a normal browser cannot open.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import socket
import struct
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SERVER_HOST = "10.212.28.38"
SERVER_PORT = 8888
CHECK_TYPE = 80
PHOTO_TYPE = 100
TZ_BEIJING = timezone(timedelta(hours=8))
WINDOWS = ((7 * 60 + 30, 10 * 60), (11 * 60 + 30, 14 * 60), (15 * 60 + 30, 20 * 60))
MAX_BODY = 32 * 1024 * 1024
COUNT_RE = re.compile(r"本学期锻炼次数\s*[:：]\s*(\d+)")
MACHINES = {
    "xueyuanlu": {
        "entrance": {2: ("20211025001", "北航本部TD入口1"), 4: ("20230417001", "北航本部TD入口2"), 3: ("20220301004", "北航本部TD入口3")},
        "exit": {6: ("20210420002", "北航本部TD出口1"), 5: ("20210421003", "北航本部TD出口2"), 7: ("20220301003", "北航本部TD出口3")},
    },
    "shahe": {
        "entrance": {8: ("20210511001", "北航沙河TD入口1"), 9: ("20210511002", "北航沙河TD入口2"), 10: ("20210511003", "北航沙河TD入口3")},
        "exit": {11: ("20220218001", "北航沙河TD出口1"), 12: ("20220218002", "北航沙河TD出口2"), 13: ("20220218003", "北航沙河TD出口3")},
    },
}


def card_id_from_student(student_id: str) -> str:
    value = student_id.strip()
    if not value.isdigit() or not 6 <= len(value) <= 20:
        raise ValueError("学号格式不正确")
    return hex(int(value))[2:].upper()


def _window_index(timestamp_ms: int) -> int | None:
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(TZ_BEIJING)
    minute = dt.hour * 60 + dt.minute
    for index, (start, end) in enumerate(WINDOWS):
        if start <= minute <= end:
            return index
    return None


def plan_timestamps(gap_seconds: int, now_ms: int | None = None) -> tuple[int, int]:
    current = int(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else int(now_ms)
    if _window_index(current) is None:
        raise ValueError("当前时间不在 TD 打卡窗口内（07:30-10:00 / 11:30-14:00 / 15:30-20:00）")
    gap = max(60, min(int(gap_seconds), 3600))
    exit_time = current + gap * 1000
    if _window_index(exit_time) != _window_index(current):
        raise ValueError("出口时间超出当前合法打卡窗口，请缩短时间差")
    return current, exit_time


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("TD 连接已关闭")
        data += chunk
    return data


def tcp_request(payload: bytes, request_type: int, timeout: float = 10.0) -> dict[str, Any]:
    with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(struct.pack(">lB", len(payload), request_type) + payload)
        length, _code = struct.unpack(">lB", _recv_exact(sock, 5))
        if length <= 0 or length > 4 * 1024 * 1024:
            raise ConnectionError("TD 服务器返回了无效响应")
        return json.loads(_recv_exact(sock, length).decode("utf-8"))


def _decode_photo(value: Any) -> bytes:
    text = str(value or "")
    if "," in text and text.startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        data = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("照片数据格式无效") from exc
    if not data or len(data) > 12 * 1024 * 1024:
        raise ValueError("照片为空或超过 12 MB")
    return data


def _machine(campus: str, kind: str, machine_id: int) -> tuple[str, str]:
    group = MACHINES.get(campus, {}).get(kind, {})
    if machine_id not in group:
        raise ValueError("所选打卡机不属于当前校区")
    return group[machine_id]


def _check(student_id: str, campus: str, kind: str, machine_id: int, photo: bytes, timestamp_ms: int) -> dict[str, Any]:
    serial, location = _machine(campus, kind, machine_id)
    payload = {
        "cardno": card_id_from_student(student_id),
        "userno": student_id.upper(),
        "timestamp": str(timestamp_ms),
        "type": 1,
        "eventno": "802",
        "ln": str(machine_id),
        "sn": serial,
        "schoolno": "10006",
    }
    response = tcp_request(json.dumps(payload, ensure_ascii=False).encode("utf-8"), CHECK_TYPE)
    if response.get("status") != "success":
        raise ValueError("TD 打卡服务器拒绝了请求")
    raw_message = str(response.get("srvresp") or "")
    success = "成功" in raw_message
    if success:
        upload = tcp_request(f"{serial}_{timestamp_ms}".encode("utf-8") + photo, PHOTO_TYPE)
        if upload.get("status") != "success":
            raise ValueError("TD 照片上传失败")
    count_match = COUNT_RE.search(raw_message)
    return {
        "success": success,
        "message": raw_message.strip().replace("\n", ", "),
        "count": int(count_match.group(1)) if count_match else None,
        "location": location,
        "timestamp_ms": timestamp_ms,
    }


def manual_check(payload: dict[str, Any]) -> dict[str, Any]:
    student_id = str(payload.get("student_id") or "").strip()
    card_id_from_student(student_id)
    campus = str(payload.get("campus") or "xueyuanlu")
    if campus not in MACHINES:
        raise ValueError("校区参数无效")
    try:
        entrance_id = int(payload.get("entrance_machine_id") or (8 if campus == "shahe" else 2))
        exit_id = int(payload.get("exit_machine_id") or (11 if campus == "shahe" else 6))
        gap_seconds = int(payload.get("gap_seconds") or 240)
    except (TypeError, ValueError) as exc:
        raise ValueError("打卡参数格式不正确") from exc
    if not 60 <= gap_seconds <= 15 * 60:
        raise ValueError("入口至出口时间差需为 1～15 分钟")
    entrance_photo = _decode_photo(payload.get("entrance_photo"))
    exit_photo = _decode_photo(payload.get("exit_photo"))
    entrance_time, exit_time = plan_timestamps(gap_seconds)
    entrance = _check(student_id, campus, "entrance", entrance_id, entrance_photo, entrance_time)
    if not entrance["success"]:
        return {"success": False, "message": f"入口打卡失败：{entrance['message']}", "entrance": entrance, "exit": None}
    exit_result = _check(student_id, campus, "exit", exit_id, exit_photo, exit_time)
    return {
        "success": bool(exit_result["success"]),
        "message": "电脑端 TD 打卡完成" if exit_result["success"] else f"出口打卡失败：{exit_result['message']}",
        "entrance": entrance,
        "exit": exit_result,
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "MuzToolTDBridge/1.0"

    def _headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MuzTool-Bridge-Token")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _json(self, data: dict[str, Any], status: int = 200) -> None:
        self._headers(status)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(204)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-MuzTool-Bridge-Token") or "", self.server.bridge_token)  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/health":
            self._json({"success": False, "message": "not found"}, 404)
            return
        if not self._authorized():
            self._json({"success": False, "message": "桥接码不正确"}, 401)
            return
        self._json({"success": True, "message": "电脑端 TD 桥接服务已连接"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/td/manual":
            self._json({"success": False, "message": "not found"}, 404)
            return
        if not self._authorized():
            self._json({"success": False, "message": "桥接码不正确"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求体为空或过大")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self._json(manual_check(payload))
        except (ValueError, ConnectionError, OSError, json.JSONDecodeError) as exc:
            self._json({"success": False, "message": str(exc)}, 400)
        except Exception:
            self._json({"success": False, "message": "电脑端桥接执行失败"}, 500)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[TD Bridge] {self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MuzTool 电脑端 TD 本地桥接")
    parser.add_argument("--port", type=int, default=18788)
    parser.add_argument("--token", default="", help="自定义桥接码；不填写则自动生成")
    args = parser.parse_args()
    token = args.token.strip() or secrets.token_urlsafe(12)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BridgeHandler)
    server.bridge_token = token  # type: ignore[attr-defined]
    print("MuzTool 电脑端 TD 桥接已启动")
    print(f"地址：http://127.0.0.1:{args.port}")
    print(f"桥接码：{token}")
    print("请保持此窗口打开，并在 WebUI 中填写桥接码。按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
