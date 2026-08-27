import pytest

from muztool import td
from muztool.signin_core import get_network_urls
from muztool.td import card_id_from_student, parse_td_score_rows, plan_timestamps
from muztool.vpn import to_vpn_url


def test_signin_defaults_to_campus_direct_urls():
    urls = get_network_urls()
    assert urls["sso"] == "https://sso.buaa.edu.cn/login"
    assert all("d.buaa.edu.cn" not in value for value in urls.values())
    assert card_id_from_student("22375080") == "1556AA8"


def test_webvpn_sso_host():
    wrapped = to_vpn_url("https://sso.buaa.edu.cn/login")
    assert wrapped.startswith("https://d.buaa.edu.cn/https/")
    assert "77726476706e69737468656265737421" in wrapped
    assert wrapped.endswith("/login")


def test_plan_gap_default_four_minutes():
    # 2024-01-01 08:00 Asia/Shanghai
    entrance, exit_ts = plan_timestamps(240, now_ms=1_704_067_200_000)
    assert exit_ts - entrance == 240_000


def test_parse_current_health_cloud_td_table():
    html = """
    <table id="searchtermresults">
      <tr>
        <td>学年</td><td>学期</td><td>TD旧(800)/次</td><td>App锻炼(801)/次</td>
        <td>TD考勤机(802)/次</td><td>活动转换(803)/次</td>
        <td>奔跑在北航(804)/次</td><td>TD合计(888)</td>
      </tr>
      <tr>
        <td>2025-2026</td><td>2</td><td><a>（查看明细）</a></td>
        <td>1（查看明细）</td><td>3.0（查看明细）</td>
        <td>12（查看明细）</td><td>0.5（查看明细）</td><td>16.5（查看明细）</td>
      </tr>
      <tr>
        <td>2024-2025</td><td>1</td><td>2（查看明细）</td>
        <td>0（查看明细）</td><td>4（查看明细）</td>
        <td>8（查看明细）</td><td>1（查看明细）</td><td>15（查看明细）</td>
      </tr>
    </table>
    """

    rows = parse_td_score_rows(html)

    assert rows == [
        {
            "term_start": 2025,
            "term_end": 2026,
            "term_no": 2,
            "td_old_count": 0,
            "app_count": 1,
            "machine_count": 3,
            "activity_count": 12,
            "running_count": 0.5,
            "count": 16.5,
        },
        {
            "term_start": 2024,
            "term_end": 2025,
            "term_no": 1,
            "td_old_count": 2,
            "app_count": 0,
            "machine_count": 4,
            "activity_count": 8,
            "running_count": 1,
            "count": 15,
        },
    ]


def test_parse_td_table_uses_labels_instead_of_fixed_column_order():
    html = """
    <table>
      <tr><th>学期</th><th>TD合计(888)</th><th>学年</th><th>TD考勤机(802)/次</th></tr>
      <tr><td>1</td><td>9（查看明细）</td><td>2026—2027</td><td>2（查看明细）</td></tr>
    </table>
    """

    assert parse_td_score_rows(html) == [
        {
            "term_start": 2026,
            "term_end": 2027,
            "term_no": 1,
            "machine_count": 2,
            "count": 9,
        }
    ]


def test_parse_legacy_td_table_remains_supported():
    html = """
    <table><tr><td>2023 - 2024</td><td>2</td><td>18</td><td>-</td></tr></table>
    """
    assert parse_td_score_rows(html) == [
        {"term_start": 2023, "term_end": 2024, "term_no": 2, "count": 18}
    ]


def test_parse_unrelated_health_cloud_page_returns_no_td_rows():
    html = """
    <table><tr><td>学年</td><td>学期</td><td>体育课程</td><td>学期得分</td></tr>
    <tr><td>2025-2026</td><td>2</td><td>篮球</td><td>尚未开放</td></tr></table>
    """
    assert parse_td_score_rows(html) == []


def test_parse_unrecognized_td_count_fails_closed():
    html = """
    <table><tr><td>学年</td><td>学期</td><td>TD合计(888)</td></tr>
    <tr><td>2025-2026</td><td>2</td><td>数据异常</td></tr></table>
    """
    with pytest.raises(ValueError, match="无法识别"):
        parse_td_score_rows(html)


def test_latest_health_cloud_term_is_returned_when_summary_row_is_omitted():
    html = """
    <table>
      <tr><td>学年</td><td>学期</td><td>TD考勤机(802)/次</td><td>TD合计(888)</td></tr>
      <tr><td>2025-2026</td><td>1</td><td>3（查看明细）</td><td>19（查看明细）</td></tr>
    </table>
    <script>
      function getStuEventDetail(stuNo, eventNo) {
        var xn = "2025-2026"
        var xq = "2"
      }
    </script>
    """

    rows = parse_td_score_rows(html)

    assert rows[0] == {
        "term_start": 2025,
        "term_end": 2026,
        "term_no": 2,
        "td_old_count": 0,
        "app_count": 0,
        "machine_count": 0,
        "activity_count": 0,
        "running_count": 0,
        "count": 0,
        "has_records": False,
    }
    assert rows[1]["term_no"] == 1
    assert rows[1]["count"] == 19


def test_latest_health_cloud_term_does_not_duplicate_existing_summary():
    html = """
    <table>
      <tr><td>学年</td><td>学期</td><td>TD合计(888)</td></tr>
      <tr><td>2025-2026</td><td>2</td><td>4（查看明细）</td></tr>
    </table>
    <script>
      function getStuEventDetail(stuNo, eventNo) {
        var xn = '2025-2026'
        var xq = '2'
      }
    </script>
    """

    rows = parse_td_score_rows(html)

    assert len(rows) == 1
    assert rows[0]["term_no"] == 2
    assert rows[0]["count"] == 4
    assert "has_records" not in rows[0]


@pytest.mark.asyncio
async def test_query_td_establishes_school_context_before_score_page(monkeypatch):
    calls = []
    html = """
    <table><tr><td>学年</td><td>学期</td><td>TD合计(888)</td></tr>
    <tr><td>2025-2026</td><td>2</td><td>12（查看明细）</td></tr></table>
    """

    class Response:
        def __init__(self, text=""):
            self.text = text

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def get(self, url):
            calls.append(("get", url))
            return Response(html if url == td.TD_SCORE_URL else "")

    async def fake_sso_login(client, student_id, password, *, use_vpn):
        del client, password
        calls.append(("sso", student_id, use_vpn))

    monkeypatch.setattr(td.httpx, "AsyncClient", Client)
    monkeypatch.setattr(td, "sso_login", fake_sso_login)

    rows = await td.query_td_counts("12345678", "test-password")

    assert rows[0]["count"] == 12
    assert calls == [
        ("sso", "12345678", False),
        ("get", td.TD_INDEX_URL),
        ("get", td.TD_SCORE_URL),
    ]
