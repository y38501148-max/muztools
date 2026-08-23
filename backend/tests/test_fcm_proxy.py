from __future__ import annotations

from muztool import fcm


def test_fcm_post_uses_dedicated_proxy(monkeypatch):
    captured = {}

    class FakeResponse:
        pass

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["post"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(fcm.config, "FCM_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr(fcm.httpx, "Client", FakeClient)

    response = fcm._post("https://example.invalid/send", json={"ok": True}, timeout=7)

    assert isinstance(response, FakeResponse)
    assert captured["client"] == {"timeout": 7, "proxy": "http://127.0.0.1:7890"}
    assert captured["url"] == "https://example.invalid/send"
    assert captured["post"] == {"json": {"ok": True}}
