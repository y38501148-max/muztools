from muztool.td import card_id_from_student, plan_timestamps
from muztool.vpn import to_vpn_url


def test_card_id():
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
