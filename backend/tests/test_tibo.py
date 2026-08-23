from datetime import datetime, timedelta, timezone

from muztool import tibo

NOW = datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc)


def post(post_id: str, text: str = "Limits will reset soon") -> tibo.TiboPost:
    return tibo.TiboPost(
        id=post_id,
        created_at=NOW - timedelta(minutes=5),
        text=text,
        url=f"https://x.com/thsottiaux/status/{post_id}",
    )


def test_first_check_creates_baseline_without_backlog_notifications(tmp_path, monkeypatch):
    users = [{"id": "1", "notifications": []}, {"id": "2", "notifications": []}]
    monkeypatch.setattr(tibo, "iter_users", lambda: users)

    async def fetcher(_seen, _now, _lookback):
        return tibo.FetchResult(("201",), (post("201"),))

    report = __import__("asyncio").run(
        tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=tmp_path / "state.json")
    )
    assert report.initialized is True
    assert report.notified_users == 0
    assert all(not user["notifications"] for user in users)


def test_new_reset_post_notifies_only_users_with_tibo_enabled(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": ["200"], "last_checked": ""}, state_path)
    users = [
        {"id": "1", "approvals": {"signin": "none", "td": "none", "spark": "none"}, "tibo": {"enabled": True}, "notifications": []},
        {"id": "2", "approvals": {}, "tibo": {"enabled": False}, "notifications": []},
        {"id": "3", "approvals": {}, "notifications": []},
    ]
    monkeypatch.setattr(tibo, "iter_users", lambda: users)

    async def fetcher(seen, _now, _lookback):
        assert seen == frozenset({"200"})
        return tibo.FetchResult(("201",), (post("201"),))

    report = __import__("asyncio").run(
        tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=state_path)
    )
    assert report.notified_users == 1
    item = users[0]["notifications"][0]
    assert item["body"] == "tibo发布了一条与重置有关的推特，请点击查看"
    assert item["url"].endswith("/201")
    assert item["source_id"] == "tibo:201"
    assert users[1]["notifications"] == []
    assert users[2]["notifications"] == []


def test_non_reset_post_is_seen_but_not_notified(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": [], "last_checked": ""}, state_path)
    users = [{"id": "1", "notifications": []}]
    monkeypatch.setattr(tibo, "iter_users", lambda: users)

    async def fetcher(_seen, _now, _lookback):
        return tibo.FetchResult(("202",), (post("202", "A regular product update"),))

    report = __import__("asyncio").run(
        tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=state_path)
    )
    assert report.matched == 0
    assert users[0]["notifications"] == []


def test_duplicate_source_id_is_not_sent_twice(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": [], "last_checked": ""}, state_path)
    users = [{"id": "1", "tibo": {"enabled": True}, "notifications": [{"source_id": "tibo:203"}]}]
    monkeypatch.setattr(tibo, "iter_users", lambda: users)

    async def fetcher(_seen, _now, _lookback):
        return tibo.FetchResult(("203",), (post("203"),))

    report = __import__("asyncio").run(
        tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=state_path)
    )
    assert report.notified_users == 0
    assert len(users[0]["notifications"]) == 1



def test_profile_html_parser_reads_top_level_posts_and_ignores_nested_quote():
    html = """
    <article data-tweet-id="300">
      <meta itemprop="datePublished" content="2026-08-23T00:00:00.000Z">
      <meta itemprop="url" content="https://x.com/thsottiaux/status/300">
      <meta itemprop="text" content="Limits RESET today">
      <article data-tweet-id="100">
        <meta itemprop="text" content="nested quoted post">
      </article>
    </article>
    <article data-tweet-id="299">
      <meta itemprop="datePublished" content="2026-08-22T23:00:00.000Z">
      <meta itemprop="url" content="https://x.com/thsottiaux/status/299">
      <meta itemprop="text" content="regular update">
    </article>
    """
    posts = tibo.parse_profile_html(html)
    assert tuple(item.id for item in posts) == ("300", "299")
    assert posts[0].text == "Limits RESET today"
    assert tibo.is_reset_post(posts[0].text) is True


def test_history_cache_keeps_latest_100_reset_posts(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": [], "last_checked": "", "history": []}, state_path)
    monkeypatch.setattr(tibo, "iter_users", lambda: [])
    rows = tuple(
        tibo.TiboPost(
            id=str(10_000 + index),
            created_at=NOW - timedelta(minutes=index),
            text=f"reset notice {index}",
            url=f"https://x.com/thsottiaux/status/{10_000 + index}",
        )
        for index in range(120)
    )

    async def fetcher(_seen, _now, _lookback):
        return tibo.FetchResult(tuple(item.id for item in rows), rows)

    __import__("asyncio").run(tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=state_path))
    history = tibo.list_tibo_history(state_path)
    assert history["count"] == 100
    assert history["items"][0]["id"] == "10119"
    assert history["items"][-1]["id"] == "10020"
