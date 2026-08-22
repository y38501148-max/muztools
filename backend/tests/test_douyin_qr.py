import base64

from muztool.douyin_qr import QrSession, decode_qr_image, public_qr


PNG = b"\x89PNG\r\n\x1a\n" + b"testdata"


def test_decode_qr_image_from_base64():
    encoded = base64.b64encode(PNG).decode("ascii")
    assert decode_qr_image({"qrcode": encoded}) == PNG
    assert decode_qr_image({"qrcode": "data:image/png;base64," + encoded}) == PNG


def test_decode_qr_image_empty():
    assert decode_qr_image({}) == b""
    assert decode_qr_image({"qrcode": "not-base64"}) == b""


def test_public_qr_payload():
    session = QrSession(login_id="login1", user_id="user1", qr_png=PNG, status="pending")
    payload = public_qr(session)
    assert payload["login_id"] == "login1"
    assert payload["status"] == "pending"
    assert payload["valid"] is False
    assert payload["qr_image"] == base64.b64encode(PNG).decode("ascii")
