import sys
import types

import pytest

from muztool.douyin import (
    DouyinAmbiguousSend,
    DouyinBusy,
    DouyinStructureChanged,
    MAX_SPARK_TARGETS,
    SPARK_SEND_INTERVAL_MS,
    _execution_guard,
    _conversation_friend,
    _douyin_account_from_payload,
    _send_and_confirm,
    _target_matches,
    _verify_active_conversation,
    message_for,
    normalize_target,
    run_spark,
    same_douyin_session,
)


def test_spark_limits_and_send_interval_match_product_settings():
    assert MAX_SPARK_TARGETS == 15
    assert SPARK_SEND_INTERVAL_MS == 20_000


def test_account_profile_uses_stable_identifier_without_exposing_it():
    first_key, nickname = _douyin_account_from_payload(
        {"data": {"user": {"sec_uid": "stable-account-id", "nickname": "测试用户"}}}
    )
    second_key, _ = _douyin_account_from_payload(
        {"user_info": {"sec_uid": "stable-account-id", "nickname": "新昵称"}}
    )
    other_key, _ = _douyin_account_from_payload(
        {"data": {"sec_uid": "other-account-id", "nickname": "其他用户"}}
    )
    assert first_key == second_key
    assert first_key != other_key
    assert first_key != "stable-account-id"
    assert nickname == "测试用户"


def test_same_douyin_session_only_matches_account_session_cookies():
    cached = [{"name": "sessionid", "value": "account-session"}, {"name": "ttwid", "value": "browser"}]
    assert same_douyin_session(cached, [{"name": "sessionid", "value": "account-session"}]) is True
    assert same_douyin_session(cached, [{"name": "sessionid", "value": "different"}]) is False
    assert same_douyin_session(
        [{"name": "uid_tt", "value": "stable-user"}],
        [{"name": "uid_tt", "value": "stable-user"}],
    ) is True
    assert same_douyin_session(cached, [{"name": "ttwid", "value": "browser"}]) is False


def test_normalize_target_defaults_to_standard_mode():
    assert normalize_target({"name": "好友A"}) == {
        "name": "好友A",
        "mode": "standard",
        "message": "",
        "conversation_id": "",
        "conversation_short_id": "",
        "conversation_type": "",
    }


def test_normalize_target_keeps_custom_mode_and_conversation_identity():
    assert normalize_target(
        {
            "name": " 群聊B ",
            "mode": "custom",
            "message": " 专属文案 ",
            "conversation_id": " group-id ",
            "conversation_short_id": " short-id ",
            "conversation_type": "group",
        }
    ) == {
        "name": "群聊B",
        "mode": "custom",
        "message": "专属文案",
        "conversation_id": "group-id",
        "conversation_short_id": "short-id",
        "conversation_type": "group",
    }


def test_legacy_message_infers_custom_mode():
    assert normalize_target({"name": "好友C", "message": "旧版专属文案"})["mode"] == "custom"


def test_message_for_uses_default_in_standard_mode():
    assert message_for({"name": "好友A", "mode": "standard", "message": "不应使用"}, "默认文案") == "默认文案"


def test_message_for_uses_custom_message_in_custom_mode():
    assert message_for({"name": "好友A", "mode": "custom", "message": "专属文案"}, "默认文案") == "专属文案"


class _FakeTextLocator:
    def __init__(self, text="", attribute=""):
        self.first = self
        self._text = text
        self._attribute = attribute

    def inner_text(self):
        return self._text

    def get_attribute(self, _name):
        return self._attribute


class _FakeConversationItem:
    def __init__(self, name="", avatar="", conversation_id="", short_id="", raw_type=0):
        self.name = name
        self.avatar = avatar
        self.meta = {"id": conversation_id, "shortId": short_id, "type": raw_type}

    def locator(self, selector):
        from muztool.douyin import CONVERSATION_TITLE_SELECTOR

        if selector == CONVERSATION_TITLE_SELECTOR:
            return _FakeTextLocator(self.name)
        if selector == "img":
            return _FakeTextLocator(attribute=self.avatar)
        raise AssertionError(selector)

    def evaluate(self, _script):
        return self.meta


def test_conversation_friend_extracts_group_identity():
    assert _conversation_friend(
        _FakeConversationItem(" 群聊D ", "https://example.test/avatar.jpg", "conv-2", "2", 2)
    ) == {
        "name": "群聊D",
        "avatar_url": "https://example.test/avatar.jpg",
        "conversation_id": "conv-2",
        "conversation_short_id": "2",
        "conversation_type": "group",
    }


def test_target_matching_prefers_id_and_type():
    group = {"name": "同名会话", "conversation_id": "g1", "conversation_type": "group"}
    direct = {"name": "同名会话", "conversation_id": "d1", "conversation_type": "direct"}
    assert _target_matches({"name": "同名会话", "conversation_id": "g1", "conversation_type": "group"}, group)
    assert not _target_matches({"name": "同名会话", "conversation_id": "g1", "conversation_type": "group"}, direct)
    assert not _target_matches({"name": "同名会话", "conversation_type": "group"}, group)
    assert not _target_matches({"name": "同名会话", "conversation_type": "group"}, direct)


def test_group_only_guard_rejects_any_non_group_or_multiple_target():
    user = {
        "douyin": {
            "cookies": [{"name": "sessionid", "value": "x"}],
            "targets": [],
        }
    }
    with pytest.raises(ValueError, match="只能包含一个目标"):
        run_spark(
            user,
            targets_override=[
                {"name": "群A", "conversation_id": "g1", "conversation_type": "group"},
                {"name": "群B", "conversation_id": "g2", "conversation_type": "group"},
            ],
            group_only=True,
        )
    with pytest.raises(ValueError, match="明确的群聊"):
        run_spark(
            user,
            targets_override=[{"name": "单聊", "conversation_id": "d1", "conversation_type": "direct"}],
            group_only=True,
        )


def test_search_friends_filters_crawled_list(monkeypatch):
    import muztool.douyin as douyin

    monkeypatch.setattr(
        douyin,
        "list_douyin_friends",
        lambda _cookies, limit=200: [
            {"name": "张三", "avatar_url": "", "conversation_id": "d1", "conversation_type": "direct"},
            {"name": "小李同学", "avatar_url": "", "conversation_id": "g1", "conversation_type": "group"},
        ],
    )
    assert douyin.search_douyin_friends([{"name": "x"}], "李") == [
        {"name": "小李同学", "avatar_url": "", "conversation_id": "g1", "conversation_type": "group"}
    ]
    assert len(douyin.search_douyin_friends([{"name": "x"}])) == 2


def test_per_user_execution_guard_rejects_overlapping_tasks():
    with _execution_guard("same-user"):
        with pytest.raises(DouyinBusy):
            with _execution_guard("same-user"):
                pass
        with _execution_guard("different-user"):
            pass


class _FakeActiveLocator:
    first = None

    def __init__(self):
        self.first = self

    def wait_for(self, **_kwargs):
        return None


class _FakeActivePage:
    def locator(self, _selector):
        return _FakeActiveLocator()


def test_active_conversation_requires_stable_identity(monkeypatch):
    import muztool.douyin as douyin

    monkeypatch.setattr(douyin, "_conversation_friend", lambda _item: {"name": "目标", "conversation_id": "", "conversation_type": ""})
    with pytest.raises(DouyinStructureChanged):
        _verify_active_conversation(
            _FakeActivePage(),
            {"name": "目标", "conversation_id": "d1", "conversation_type": "direct"},
        )


def test_active_conversation_rejects_mismatched_id(monkeypatch):
    import muztool.douyin as douyin

    monkeypatch.setattr(
        douyin,
        "_conversation_friend",
        lambda _item: {"name": "目标", "conversation_id": "d2", "conversation_type": "direct"},
    )
    with pytest.raises(DouyinAmbiguousSend):
        _verify_active_conversation(
            _FakeActivePage(),
            {"name": "目标", "conversation_id": "d1", "conversation_type": "direct"},
        )


class _FakeEditor:
    def click(self):
        return None

    def inner_text(self):
        return ""


class _FakeKeyboard:
    def insert_text(self, _text):
        return None

    def press(self, _key):
        return None


class _FakeExactText:
    def __init__(self, counts):
        self.counts = list(counts)
        self.index = 0

    def count(self):
        value = self.counts[min(self.index, len(self.counts) - 1)]
        self.index += 1
        return value


class _FakeSendPage:
    def __init__(self, counts):
        self.keyboard = _FakeKeyboard()
        self.exact = _FakeExactText(counts)

    def get_by_text(self, _text, exact=True):
        assert exact is True
        return self.exact

    def wait_for_timeout(self, _milliseconds):
        return None


def test_send_confirmation_requires_message_count_increase(monkeypatch):
    import muztool.douyin as douyin

    block_checks = []
    monkeypatch.setattr(douyin, "_detect_page_block", lambda _page: block_checks.append(1) or None)
    _send_and_confirm(_FakeSendPage([2, 2, 3]), _FakeEditor(), "续火花")
    assert block_checks == []


def test_ambiguous_send_checks_page_block_once_then_stops(monkeypatch):
    import muztool.douyin as douyin

    block_checks = []
    monkeypatch.setattr(douyin, "_detect_page_block", lambda _page: block_checks.append(1) or None)
    with pytest.raises(DouyinAmbiguousSend):
        _send_and_confirm(_FakeSendPage([2]), _FakeEditor(), "续火花")
    assert block_checks == [1]


def test_successful_run_persists_refreshed_cookies_and_records_status(monkeypatch):
    import muztool.douyin as douyin

    initial = [{"name": "sessionid", "value": "old", "domain": ".douyin.com", "path": "/"}]
    refreshed = [{"name": "sessionid", "value": "new", "domain": ".douyin.com", "path": "/"}]
    persisted = []
    monkeypatch.setattr(douyin, "get_douyin_cookies", lambda _cfg: initial)
    monkeypatch.setattr(douyin, "set_douyin_cookies", lambda _cfg, cookies: persisted.append(cookies))

    class FakeContext:
        def cookies(self):
            return refreshed

        def close(self):
            return None

    class FakeBrowser:
        def close(self):
            return None

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    playwright_package = types.ModuleType("playwright")
    sync_api_module = types.ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = lambda: FakeSyncPlaywright()
    playwright_package.sync_api = sync_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)
    monkeypatch.setattr(douyin, "_open_chat", lambda _browser, _cookies: (FakeContext(), FakePage(), object()))
    opened = []
    waits = []
    monkeypatch.setattr(
        douyin,
        "_open_target_conversation",
        lambda _page, target: (
            opened.append(target["conversation_id"]) or object(),
            {"conversation_id": target["conversation_id"], "conversation_type": target["conversation_type"]},
        ),
    )
    monkeypatch.setattr(douyin, "_send_and_confirm", lambda *_args: None)

    class FakePage:
        def wait_for_timeout(self, milliseconds):
            waits.append(milliseconds)

    user = {
        "id": "run-user",
        "douyin": {
            "default_message": "续火花",
            "targets": [
                {"name": "目标一", "conversation_id": "d1", "conversation_type": "direct"},
                {"name": "目标二", "conversation_id": "d2", "conversation_type": "direct"},
            ],
        },
    }
    result = run_spark(user)
    assert result["success"] is True
    assert result["retryable"] is False
    assert persisted == [refreshed]
    assert opened == ["d1", "d2"]
    assert waits == [douyin.SPARK_SEND_INTERVAL_MS]
    assert user["douyin"]["target_status"]["id:d1"]["status"] == "success"
    assert user["douyin"]["target_status"]["id:d2"]["status"] == "success"
    assert user["douyin"]["last_result"]["success_count"] == 2
    assert user["douyin"]["last_result"]["failure_count"] == 0
