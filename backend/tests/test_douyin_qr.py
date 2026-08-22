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
