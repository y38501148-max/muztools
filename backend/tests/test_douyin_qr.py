import base64

from muztool.douyin_qr import QrSession, _apply_event, decode_qr_image, public_qr


PNG = b"\x89PNG\r\n\x1a\n" + b"testdata"


def test_decode_qr_image_from_base64():
    encoded = base64.b64encode(PNG).decode("ascii")
    assert decode_qr_image({"qrcode": encoded}) == PNG
    assert decode_qr_image({"qrcode": "data:image/png;base64," + encoded}) == PNG


def test_decode_qr_image_empty():
    assert decode_qr_image({}) == b""
    assert decode_qr_image({"qrcode": "not-base64"}) == b""


def test_decode_qr_image_ignores_html_and_redirect():
    html = "<!doctype html><html><head></head><body>" + ("x" * 200) + "</body></html>"
    assert decode_qr_image({"qrcode": html}) == b""
    assert decode_qr_image({"url": html, "redirect_url": "https://www.douyin.com/login/?ticket=abc"}) == b""
    assert decode_qr_image({"qrcode_index_url": html}) == b""


def test_apply_event_freezes_qr_after_scan():
    first = base64.b64encode(PNG).decode("ascii")
    second = base64.b64encode(PNG + b"more").decode("ascii")
    session = QrSession(login_id="a", user_id="b", qr_png=PNG)
    _apply_event(session, {"event": "status", "status": "scanned"})
    _apply_event(session, {"event": "qr", "png": second})
    assert session.status == "scanned"
    assert session.qr_png == PNG
    _apply_event(session, {"event": "qr", "png": first})
    assert session.qr_png == PNG


def test_public_qr_payload():
    session = QrSession(login_id="login1", user_id="user1", qr_png=PNG, status="pending")
    payload = public_qr(session)
    assert payload["login_id"] == "login1"
    assert payload["status"] == "pending"
    assert payload["valid"] is False
    assert payload["qr_image"] == base64.b64encode(PNG).decode("ascii")


from muztool.douyin_qr import _logged_in, _handle_check_payload, _is_login_redirect, _merge_cookies
from muztool.douyin import normalize_cookies


def test_logged_in_cookie_names():
    assert _logged_in([{"name": "sessionid", "value": "x"}])
    assert _logged_in([{"name": "sid_tt", "value": "x"}])
    assert not _logged_in([{"name": "ttwid", "value": "x"}])


def test_handle_check_confirms_redirect(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    state = {"redirect": "", "done": False, "confirmed": False}
    _handle_check_payload({"status": "3", "redirect_url": "https://www.douyin.com/passport/sso/login/callback/?x=1"}, state, events)
    assert state["confirmed"] is True
    assert state["redirect"].startswith("https://")
    assert "scanned" in events.read_text(encoding="utf-8")


def test_handle_check_requires_mfa_without_confirming_static_asset(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    state = {
        "redirect": "",
        "done": False,
        "confirmed": False,
        "verification_required": False,
    }
    _handle_check_payload(
        {
            "status": "2046",
            "url": (
                "https://auth.zijieapi.com/ucenter_web/app/second_verification_web/"
                "dist/index.umd.production.js?error_code=2046&std_verify_type=MFA"
            ),
            "verify_ways": ["mobile_sms_verify", "pwd_verify"],
        },
        state,
        events,
    )
    assert state["confirmed"] is False
    assert state["redirect"] == ""
    assert state["verification_required"] is True
    text = events.read_text(encoding="utf-8")
    assert '"status": "scanned"' in text
    assert "后端网页登录" in text


def test_static_or_verification_url_is_not_login_redirect():
    assert not _is_login_redirect(
        "https://auth.zijieapi.com/ucenter_web/app/second_verification_web/dist/index.js"
    )
    assert not _is_login_redirect("https://www.douyin.com/static/login.js")
    assert not _is_login_redirect("https://example.com/passport/sso/login/callback")
    assert _is_login_redirect("https://www.douyin.com/passport/sso/login/callback/?x=1")


def test_arbitrary_http_url_does_not_confirm_login(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    state = {"redirect": "", "done": False, "confirmed": False}
    _handle_check_payload(
        {"status": "2046", "url": "https://auth.zijieapi.com/static/index.js"},
        state,
        events,
    )
    assert state["confirmed"] is False
    assert state["redirect"] == ""


def test_apply_event_preserves_scanned_guidance():
    session = QrSession(login_id="a", user_id="b")
    _apply_event(
        session,
        {"event": "status", "status": "scanned", "error": "请在抖音 App 中完成二次验证"},
    )
    assert session.status == "scanned"
    assert "二次验证" in session.error
    _apply_event(session, {"event": "status", "status": "scanned"})
    assert "二次验证" in session.error


def test_success_event_requires_authenticated_cookie():
    from muztool.douyin_qr import _apply_event

    session = QrSession(login_id="a", user_id="b")
    _apply_event(session, {"event": "success", "cookies": []})
    assert session.status == "failed"
    assert "Cookie" in session.error


def test_merge_cookies_keeps_latest_value_by_scope():
    cookies = _merge_cookies(
        [{"name": "sessionid", "value": "old", "domain": ".douyin.com", "path": "/"}],
        [{"name": "sessionid", "value": "new", "domain": ".douyin.com", "path": "/"}],
    )
    assert cookies == [{"name": "sessionid", "value": "new", "domain": ".douyin.com", "path": "/"}]


def test_normalize_cookies_scopes_douyin_cookies_for_creator_pages():
    cookies = normalize_cookies([{"name": "sessionid", "value": "x", "domain": "www.douyin.com"}])
    assert cookies[0]["domain"] == ".douyin.com"
