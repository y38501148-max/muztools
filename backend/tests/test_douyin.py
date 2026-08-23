import pytest

from muztool.douyin import (
    _conversation_friend,
    _target_matches,
    message_for,
    normalize_target,
    run_spark,
)


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
    assert _target_matches({"name": "同名会话", "conversation_type": "group"}, group)
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
    with pytest.raises(ValueError, match="明确的群聊标识"):
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
