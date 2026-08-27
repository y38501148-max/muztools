from __future__ import annotations

import json
import re
import socket
import struct
from datetime import datetime, timezone
from html.parser import HTMLParser
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
TERM_RE = re.compile(r"^(\d{4})\s*[-–—~至]\s*(\d{4})$")
CURRENT_TERM_RE = re.compile(
    r"function\s+getStuEventDetail\s*\([^)]*\)\s*\{"
    r"[\s\S]{0,1000}?\bvar\s+xn\s*=\s*['\"](\d{4})\s*[-–—~至]\s*(\d{4})['\"]"
    r"[\s\S]{0,300}?\bvar\s+xq\s*=\s*['\"]([12])['\"]",
    re.I,
)
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?")
TD_SCORE_COLUMNS = {
    "td_old_count": "TD旧",
    "app_count": "App锻炼",
    "machine_count": "TD考勤机",
    "activity_count": "活动转换",
    "running_count": "奔跑在北航",
    "count": "TD合计",
}
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


def _normalized_cell(value: str) -> str:
    return "".join(value.split())


class _TableParser(HTMLParser):
    """Collect top-level HTML table rows without depending on page styling."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            if self._table_depth == 0:
                self._table = []
            self._table_depth += 1
        elif tag == "tr" and self._table_depth == 1:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth == 1 and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._table_depth == 1 and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
        elif tag == "tr" and self._table_depth == 1 and self._row is not None:
            if self._table is not None and self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                if self._table:
                    self.tables.append(self._table)
                self._table = None


def _numeric_cell(value: str) -> int | float:
    text = _normalized_cell(value).replace(",", "")
    match = NUMBER_RE.match(text)
    if not match:
        # New Health Cloud rows render an empty source as only “（查看明细）”.
        if not text or "查看明细" in text:
            return 0
        raise ValueError("健康云返回了无法识别的 TD 次数")
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _new_score_rows(page_html: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(page_html)
    rows: list[dict[str, Any]] = []

    for table in parser.tables:
        for header_index, header in enumerate(table):
            normalized_header = [_normalized_cell(cell) for cell in header]
            column_indexes: dict[str, int] = {}
            for field, label in TD_SCORE_COLUMNS.items():
                index = next(
                    (i for i, cell in enumerate(normalized_header) if cell.casefold().startswith(label.casefold())),
                    None,
                )
                if index is not None:
                    column_indexes[field] = index
            if "count" not in column_indexes:
                continue

            year_index = next((i for i, cell in enumerate(normalized_header) if cell == "学年"), None)
            term_index = next((i for i, cell in enumerate(normalized_header) if cell == "学期"), None)
            if year_index is None or term_index is None:
                continue

            required_index = max(year_index, term_index, *column_indexes.values())
            for row in table[header_index + 1 :]:
                if len(row) <= required_index:
                    continue
                term_match = TERM_RE.fullmatch(_normalized_cell(row[year_index]))
                if not term_match:
                    continue
                term_text = _normalized_cell(row[term_index])
                if not term_text.isdigit():
                    continue
                item: dict[str, Any] = {
                    "term_start": int(term_match.group(1)),
                    "term_end": int(term_match.group(2)),
                    "term_no": int(term_text),
                }
                for field, index in column_indexes.items():
                    item[field] = _numeric_cell(row[index])
                rows.append(item)
            break
    return rows


def _current_score_term(page_html: str) -> tuple[int, int, int] | None:
    """Read the term selected by Health Cloud, including an empty new term.

    Health Cloud omits the aggregate row until a term has valid records, but
    its detail-dialog script still publishes the current academic year and
    semester. That value is the authoritative latest term for the status API.
    """
    match = CURRENT_TERM_RE.search(page_html)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _empty_term_row(term: tuple[int, int, int]) -> dict[str, Any]:
    start, end, number = term
    return {
        "term_start": start,
        "term_end": end,
        "term_no": number,
        "td_old_count": 0,
        "app_count": 0,
        "machine_count": 0,
        "activity_count": 0,
        "running_count": 0,
        "count": 0,
        "has_records": False,
    }


def parse_td_score_rows(page_html: str) -> list[dict[str, Any]]:
    rows = _new_score_rows(page_html)
    if not rows:
        rows = [
            {
                "term_start": int(match.group(1)),
                "term_end": int(match.group(2)),
                "term_no": int(match.group(3)),
                "count": int(match.group(4)),
            }
            for match in SCORE_RE.finditer(page_html)
        ]

    current_term = _current_score_term(page_html)
    row_terms = {(row["term_start"], row["term_end"], row["term_no"]) for row in rows}
    if current_term and current_term not in row_terms:
        rows.append(_empty_term_row(current_term))

    rows.sort(key=lambda item: (item["term_start"], item["term_end"], item["term_no"]), reverse=True)
    return rows


async def query_td_counts(student_id: str, password: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers={"User-Agent": UA}, timeout=20) as client:
        await sso_login(client, student_id, password, use_vpn=False)
        # This request establishes the Health Cloud school and user context.
        # Going straight to stu_sun_score can silently render another module.
        index = await client.get(TD_INDEX_URL)
        index.raise_for_status()
        page = await client.get(TD_SCORE_URL)
        page.raise_for_status()
    rows = parse_td_score_rows(page.text)
    if not rows:
        raise ValueError("健康云未返回可识别的 TD 次数统计，请稍后重试；手动打卡不受影响")
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
