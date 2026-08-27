import json
from datetime import datetime, timedelta, timezone

import pytest

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
    <article>
      <meta itemProp="identifier" content="300">
      <meta itemProp="datePublished" content="2026-08-23T00:00:00.000Z">
      <meta itemProp="url" content="https://x.com/thsottiaux/status/300">
      <meta itemProp="text" content="Limits RESET today">
      <meta itemProp="alternateName" content="thsottiaux">
      <article>
        <meta itemProp="text" content="nested quoted post">
        <meta itemProp="alternateName" content="openai">
      </article>
    </article>
    <article>
      <meta itemProp="datePublished" content="2026-08-22T23:00:00.000Z">
      <meta itemProp="url" content="https://x.com/thsottiaux/status/299">
      <meta itemProp="text" content="regular update">
      <meta itemProp="alternateName" content="thsottiaux">
    </article>
    """
    posts = tibo.parse_profile_html(html)
    assert tuple(item.id for item in posts) == ("300", "299")
    assert posts[0].text == "Limits RESET today"
    assert tibo.is_reset_post(posts[0].text) is True


def test_profile_html_parser_accepts_lowercase_itemprop_and_skips_retweets():
    html = """
    <article>
      <meta itemprop="datePublished" content="2026-08-23T00:00:00.000Z">
      <meta itemprop="url" content="https://x.com/thsottiaux/status/301">
      <meta itemprop="text" content="legacy lowercase attributes">
      <meta itemprop="alternateName" content="thsottiaux">
    </article>
    <article>
      <meta itemprop="url" content="https://x.com/openai/status/999">
      <meta itemprop="text" content="reset retweeted from another author">
      <meta itemprop="alternateName" content="openai">
    </article>
    """
    posts = tibo.parse_profile_html(html)
    assert [item.id for item in posts] == ["301"]


def test_parse_x_cookie_text_accepts_header_string():
    cookies = tibo.parse_x_cookie_text("auth_token=abc123; ct0=def456; k=v")
    assert cookies == {"auth_token": "abc123", "ct0": "def456"}


def test_parse_x_cookie_text_accepts_browser_export_array():
    raw = json.dumps(
        [
            {"name": "auth_token", "value": "tok", "domain": ".x.com"},
            {"name": "ct0", "value": "csrf", "domain": ".x.com"},
            {"name": "twid", "value": "u%3D1"},
        ]
    )
    assert tibo.parse_x_cookie_text(raw) == {"auth_token": "tok", "ct0": "csrf"}


def test_parse_x_cookie_text_accepts_object_and_newlines():
    assert tibo.parse_x_cookie_text('{"auth_token": "a", "ct0": "b"}') == {"auth_token": "a", "ct0": "b"}
    assert tibo.parse_x_cookie_text("auth_token=a\nct0=b") == {"auth_token": "a", "ct0": "b"}


def test_parse_x_cookie_text_requires_both_keys():
    with pytest.raises(ValueError, match="auth_token"):
        tibo.parse_x_cookie_text("auth_token=only")
    with pytest.raises(ValueError, match="ct0"):
        tibo.parse_x_cookie_text("ct0=only")
    with pytest.raises(ValueError, match="X Cookie"):
        tibo.parse_x_cookie_text("")


def test_iter_x_cookie_users_requires_enabled_tibo(tmp_path, monkeypatch):
    users = [
        {"id": "1", "tibo": {"enabled": True, "x_cookies_encrypted": "v1:x"}},
        {"id": "2", "tibo": {"enabled": False, "x_cookies_encrypted": "v1:x"}},
        {"id": "3", "tibo": {"enabled": True}},
    ]
    monkeypatch.setattr(tibo, "iter_users", lambda: users)
    assert [item["id"] for item in tibo.iter_x_cookie_users()] == ["1"]


def test_x_script_discovery_supports_current_entry_module_and_relay_metadata():
    page_url = "https://x.com/thsottiaux"
    page = '<script type="module" src="https://abs.twimg.com/x-web/x-web/entry-client-HASH.js"></script>'
    assert tibo._x_script_urls(page_url, page) == [
        "https://abs.twimg.com/x-web/x-web/entry-client-HASH.js"
    ]
    script = """
      const client_id = 'AAAAAAAAAAAAAAAAAAAAAtest-value-012345678901234567890';
      const user = {params:{id:`user-query-id`,metadata:{},name:`intentFollowUserByScreenNameQuery`,operationKind:`query`}};
      const tweets = {params:{id:`tweets-query-id`,metadata:{},name:`UserTweets`,operationKind:`query`}};
    """
    assert tibo._X_BEARER_RE.search(script).group(2) == "AAAAAAAAAAAAAAAAAAAAAtest-value-012345678901234567890"
    assert tibo._operation_query_id(script, ("intentFollowUserByScreenNameQuery",)) == "user-query-id"
    assert tibo._operation_query_id(script, ("UserTweets",)) == "tweets-query-id"


def test_x_script_discovery_keeps_legacy_operation_format():
    script = 'const x={queryId:"tweets-id",operationName:"UserTweets"};'
    assert tibo._operation_query_id(script, ("UserTweets",)) == "tweets-id"


def test_resolve_x_endpoint_fetches_current_entry_and_relay_chunk():
    class FakeResponse:
        def __init__(self, url, text):
            self.url = url
            self.text = text

        def raise_for_status(self):
            return None

    entry_url = "https://abs.twimg.com/x-web/x-web/entry-client-HASH.js"
    chunk_url = "https://abs.twimg.com/x-web/x-web/assets/profile-HASH.js"
    responses = {
        "https://x.com/thsottiaux": FakeResponse(
            "https://x.com/thsottiaux",
            f'<script type="module" src="{entry_url}"></script>',
        ),
        entry_url: FakeResponse(entry_url, 'import "./assets/profile-HASH.js";'),
        chunk_url: FakeResponse(
            chunk_url,
            """
            const client_id = 'AAAAAAAAAAAAAAAAAAAAAtest-value-012345678901234567890';
            const user = {params:{id:`user-query-id`,metadata:{},name:`intentFollowUserByScreenNameQuery`}};
            const tweets = {params:{id:`tweets-query-id`,metadata:{},name:`UserTweets`}};
            """,
        ),
    }

    class FakeClient:
        async def get(self, url, **_kwargs):
            return responses[url]

    tibo._x_endpoint_cache.clear()
    endpoint = __import__("asyncio").run(tibo._resolve_x_endpoint(FakeClient()))
    assert endpoint["bearer"].startswith("AAAAAAAAA")
    assert endpoint["user_by_screen_name"] == "user-query-id"
    assert endpoint["user_tweets"] == "tweets-query-id"


def test_graphql_tweet_parser_filters_authors_and_reads_cursor():
    payload = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "content": {
                                                "entryType": "TimelineTimelineCursor",
                                                "cursorType": "Bottom",
                                                "content": {"value": "cursor-1"},
                                            }
                                        },
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "__typename": "Tweet",
                                                            "rest_id": "2091688655828246890",
                                                            "legacy": {
                                                                "id_str": "2091688655828246890",
                                                                "created_at": "Sun Aug 23 16:46:00 +0000 2026",
                                                                "full_text": "Good Sunday. Reset has been propagated",
                                                            },
                                                            "core": {"user_results": {"result": {"legacy": {"screen_name": "thsottiaux"}}}},
                                                        }
                                                    }
                                                }
                                            }
                                        },
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "__typename": "Tweet",
                                                            "rest_id": "2091000000000000000",
                                                            "legacy": {
                                                                "id_str": "2091000000000000000",
                                                                "created_at": "Sat Aug 22 00:00:00 +0000 2026",
                                                                "full_text": "reset from another author",
                                                            },
                                                            "core": {"user_results": {"result": {"legacy": {"screen_name": "someoneelse"}}}},
                                                        }
                                                    }
                                                }
                                            }
                                        },
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    tweets, cursor = tibo._parse_graphql_tweets(payload)
    assert cursor == "cursor-1"
    assert [item["id"] for item in tweets] == ["2091688655828246890", "2091000000000000000"]
    assert tweets[0]["screen"] == "thsottiaux"


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


def test_scheduler_checks_tibo_immediately_and_hourly(monkeypatch):
    from muztool import scheduler as scheduler_module

    calls = []

    class FakeScheduler:
        running = False

        def add_job(self, func, trigger, **kwargs):
            calls.append((func, trigger, kwargs))

        def start(self):
            calls.append(("start", "", {}))

    fake = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake)
    scheduler_module.start_scheduler()

    tibo_job = next(item for item in calls if item[2].get("id") == "tibo_monitor")
    assert tibo_job[1] == "interval"
    assert tibo_job[2]["hours"] == 1
    assert tibo_job[2]["next_run_time"].tzinfo is not None
    assert tibo_job[2]["max_instances"] == 1
    assert tibo_job[2]["coalesce"] is True


def test_status_thread_parser_reads_tibo_self_reply_and_uses_canonical_url():
    # Real thread-page structure: only date/url metas are rendered; the text
    # lives in a whitespace-pre-wrap span and the author in a profile anchor.
    html = """
    <article>
      <meta itemProp="datePublished" content="2026-08-23T06:11:36.000Z">
      <meta itemProp="url" content="https://x.com/thsottiaux/status/2091407991736332689">
      <a href="/thsottiaux">Tibo</a>
      <span class="font-chirp max-w-full whitespace-pre-wrap break-words text-inherit text-[length:inherit] font-inherit">Parent mentions a full reset.</span>
    </article>
    <article>
      <meta itemProp="datePublished" content="2026-08-23T06:29:05.000Z">
      <meta itemProp="url" content="https://x.com/thsottiaux/status/2091412393368945027">
      <a href="/thsottiaux">Tibo</a>
      <span class="font-chirp max-w-full whitespace-pre-wrap break-words text-inherit text-[length:inherit] font-inherit">Reset will land around 14pm PST tomorrow.</span>
    </article>
    <article>
      <meta itemProp="url" content="https://x.com/lucas/status/2091423631406518518">
      <a href="/lucas">Lucas</a>
      <a href="/thsottiaux">@thsottiaux</a>
      <span class="font-chirp max-w-full whitespace-pre-wrap break-words text-inherit text-[length:inherit] font-inherit">reset question mentioning tibo</span>
    </article>
    """
    posts = tibo.parse_profile_html(html)
    assert [item.id for item in posts] == ["2091407991736332689", "2091412393368945027"]
    assert posts[1].text == "Reset will land around 14pm PST tomorrow."
    assert posts[1].url == "https://x.com/thsottiaux/status/2091412393368945027"


def test_profile_engagement_url_is_normalized_to_status_url():
    html = """
    <article>
      <meta itemProp="url" content="https://x.com/thsottiaux/status/2091407991736332689/retweets">
      <meta itemProp="text" content="A full reset is planned">
      <meta itemProp="alternateName" content="thsottiaux">
    </article>
    """
    post = tibo.parse_profile_html(html)[0]
    assert post.id == "2091407991736332689"
    assert post.url == "https://x.com/thsottiaux/status/2091407991736332689"


def test_check_uses_one_week_lookback(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": [], "last_checked": ""}, state_path)
    monkeypatch.setattr(tibo, "iter_users", lambda: [])
    captured = {}

    async def fetcher(_seen, _now, lookback):
        captured["lookback"] = lookback
        return tibo.FetchResult((), ())

    __import__("asyncio").run(tibo.check_tibo_updates(fetcher=fetcher, now=NOW, state_path=state_path))
    assert captured["lookback"] == 168


def test_zero_discovery_streak_alerts_admin_once(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    tibo._write_state({"initialized": True, "seen_ids": [], "last_checked": ""}, state_path)
    admin = {"id": "1", "username": "muzermat", "tibo": {"enabled": False}, "notifications": []}
    monkeypatch.setattr(tibo, "iter_users", lambda: [admin, {"id": "2", "username": "other"}])

    async def empty_fetcher(_seen, _now, _lookback):
        return tibo.FetchResult((), ())

    run = __import__("asyncio").run
    for _ in range(tibo.STALL_ALERT_CHECKS - 1):
        run(tibo.check_tibo_updates(fetcher=empty_fetcher, now=NOW, state_path=state_path))
    assert admin["notifications"] == []

    run(tibo.check_tibo_updates(fetcher=empty_fetcher, now=NOW, state_path=state_path))
    assert len(admin["notifications"]) == 1
    assert admin["notifications"][0]["source_id"] == "tibo:monitor-stalled"

    # Further empty checks do not repeat the alert.
    run(tibo.check_tibo_updates(fetcher=empty_fetcher, now=NOW, state_path=state_path))
    assert len(admin["notifications"]) == 1

    # A successful discovery clears the stall state.
    async def ok_fetcher(_seen, _now, _lookback):
        return tibo.FetchResult(("201",), ())

    run(tibo.check_tibo_updates(fetcher=ok_fetcher, now=NOW, state_path=state_path))
    state = tibo._read_state(state_path)
    assert state["empty_check_streak"] == 0
    assert state["stall_alerted"] is False
