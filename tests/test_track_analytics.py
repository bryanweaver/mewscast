"""Tests for scripts/track_analytics.py follower-snapshot helpers."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_script():
    """Import track_analytics.py without pulling live credentials."""
    sys.modules.setdefault(
        "dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
    )
    script_path = Path(__file__).parent.parent / "scripts" / "track_analytics.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("track_analytics", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def track():
    return _load_script()


class TestUtcDay:
    def test_iso_with_offset(self, track):
        assert track.utc_day("2026-04-12T23:08:04.389609+00:00") == "2026-04-12"

    def test_zulu_suffix(self, track):
        assert track.utc_day("2026-05-04T23:16:48.518179Z") == "2026-05-04"

    def test_empty(self, track):
        assert track.utc_day("") is None
        assert track.utc_day(None) is None


class TestUpsertFollowerSnapshot:
    def test_appends_to_empty_list(self, track):
        snap = {"timestamp": "2026-05-04T23:00:00+00:00", "followers": 58}
        out = track.upsert_follower_snapshot([], snap)
        assert out == [snap]

    def test_replaces_last_snapshot_on_same_utc_day(self, track):
        existing = [
            {"timestamp": "2026-04-12T02:23:28+00:00", "followers": 45},
            {"timestamp": "2026-04-12T13:08:19+00:00", "followers": 49},
        ]
        newest = {"timestamp": "2026-04-12T23:08:04+00:00", "followers": 54}
        out = track.upsert_follower_snapshot(existing, newest)
        assert out[-1] == newest
        assert out[-1]["followers"] == 54
        assert len(out) == 2  # replaced last only; earlier same-day row kept

    def test_appends_when_last_snapshot_is_a_different_day(self, track):
        existing = [
            {"timestamp": "2026-05-03T23:13:49+00:00", "followers": 58},
        ]
        newest = {"timestamp": "2026-05-04T23:16:48+00:00", "followers": 58}
        out = track.upsert_follower_snapshot(existing, newest)
        assert len(out) == 2
        assert out[-1] is newest

    def test_does_not_collapse_older_same_day_duplicates(self, track):
        """Historical same-day duplicates stay; only the trailing same-day row is replaced."""
        existing = [
            {"timestamp": "2026-04-12T02:23:28+00:00", "followers": 45},
            {"timestamp": "2026-04-12T02:38:26+00:00", "followers": 45},
            {"timestamp": "2026-04-12T02:40:32+00:00", "followers": 45},
            {"timestamp": "2026-04-12T13:08:19+00:00", "followers": 49},
            {"timestamp": "2026-04-13T23:00:00+00:00", "followers": 55},
        ]
        newest = {"timestamp": "2026-04-14T01:00:00+00:00", "followers": 56}
        out = track.upsert_follower_snapshot(list(existing), newest)
        assert [s["followers"] for s in out] == [45, 45, 45, 49, 55, 56]
        assert len(out) == 6

    def test_treats_none_list_as_empty(self, track):
        snap = {"timestamp": "2026-05-04T23:00:00+00:00", "followers": 58}
        out = track.upsert_follower_snapshot(None, snap)
        assert out == [snap]


def _install_fake_twitter_bot(monkeypatch, client):
    """Point track_analytics' inner `from twitter_bot import TwitterBot` at a stub."""
    import twitter_bot

    class FakeTwitterBot:
        def __init__(self):
            self.client = client

    monkeypatch.setattr(twitter_bot, "TwitterBot", FakeTwitterBot)
    return FakeTwitterBot


def _me_response(followers=61, following=12, posts=400, headers=None):
    data = types.SimpleNamespace(
        public_metrics={
            "followers_count": followers,
            "following_count": following,
            "tweet_count": posts,
        }
    )
    return types.SimpleNamespace(data=data, headers=headers or {})


class TestXUsageHeaders:
    def test_keeps_rate_limit_and_usage_headers(self, track):
        headers = {
            "x-rate-limit-limit": "75",
            "x-rate-limit-remaining": "74",
            "X-Rate-Limit-Reset": "1710000000",
            "x-usage-limit": "10000",
            "credit-limit-remaining": "42",
            "content-type": "application/json",
        }
        assert track._x_usage_headers(headers) == {
            "x-rate-limit-limit": "75",
            "x-rate-limit-remaining": "74",
            "X-Rate-Limit-Reset": "1710000000",
            "x-usage-limit": "10000",
            "credit-limit-remaining": "42",
        }

    def test_empty_or_unusable_mapping(self, track):
        assert track._x_usage_headers(None) == {}
        assert track._x_usage_headers("not-a-mapping") == {}


class TestFetchXFollowerCount:
    def test_returns_public_metrics_from_get_me(self, track, monkeypatch, capsys):
        client = types.SimpleNamespace(
            get_me=lambda **kwargs: _me_response(followers=61),
            session=None,
        )
        _install_fake_twitter_bot(monkeypatch, client)

        result = track.fetch_x_follower_count()

        assert result == {"followers": 61, "following": 12, "posts": 400}
        out = capsys.readouterr().out
        assert "X follower read: 1 request (users/me)" in out

    def test_get_me_is_the_only_client_call(self, track, monkeypatch):
        calls = []

        def get_me(**kwargs):
            calls.append(("get_me", kwargs))
            return _me_response()

        def forbidden(*args, **kwargs):
            raise AssertionError("daily tracker must not call other X endpoints")

        client = types.SimpleNamespace(
            get_me=get_me,
            get_tweets=forbidden,
            create_tweet=forbidden,
            like=forbidden,
            unlike=forbidden,
            get_users_mentions=forbidden,
            session=None,
        )
        _install_fake_twitter_bot(monkeypatch, client)

        assert track.fetch_x_follower_count()["followers"] == 61
        assert calls == [("get_me", {"user_fields": ["public_metrics"]})]

    def test_logs_rate_limit_headers_from_response(self, track, monkeypatch, capsys):
        headers = {
            "x-rate-limit-limit": "75",
            "x-rate-limit-remaining": "74",
            "content-type": "application/json",
        }
        client = types.SimpleNamespace(
            get_me=lambda **kwargs: _me_response(headers=headers),
            session=None,
        )
        _install_fake_twitter_bot(monkeypatch, client)

        track.fetch_x_follower_count()
        out = capsys.readouterr().out
        assert "X follower read: 1 request (users/me)" in out
        assert "x-rate-limit-limit: 75" in out
        assert "x-rate-limit-remaining: 74" in out
        assert "content-type" not in out

    def test_logs_headers_captured_from_session_hook(self, track, monkeypatch, capsys):
        hooks = {"response": []}

        def get_me(**kwargs):
            raw = types.SimpleNamespace(headers={
                "x-rate-limit-remaining": "73",
                "x-user-usage": "1",
            })
            for hook in list(hooks.get("response", [])):
                hook(raw)
            return _me_response()

        client = types.SimpleNamespace(
            get_me=get_me,
            session=types.SimpleNamespace(hooks=hooks),
        )
        _install_fake_twitter_bot(monkeypatch, client)

        track.fetch_x_follower_count()
        out = capsys.readouterr().out
        assert "X follower read: 1 request (users/me)" in out
        assert "x-rate-limit-remaining: 73" in out
        assert "x-user-usage: 1" in out

    def test_object_shaped_public_metrics(self, track, monkeypatch):
        metrics = types.SimpleNamespace(
            followers_count=58, following_count=9, tweet_count=350
        )
        me = types.SimpleNamespace(
            data=types.SimpleNamespace(public_metrics=metrics),
            headers={},
        )
        client = types.SimpleNamespace(
            get_me=lambda **kwargs: me,
            session=None,
        )
        _install_fake_twitter_bot(monkeypatch, client)
        assert track.fetch_x_follower_count() == {
            "followers": 58, "following": 9, "posts": 350
        }

    def test_returns_none_on_x_error_without_raising(self, track, monkeypatch, capsys):
        def boom(**kwargs):
            raise RuntimeError("429 Too Many Requests")

        client = types.SimpleNamespace(get_me=boom, session=None)
        _install_fake_twitter_bot(monkeypatch, client)

        assert track.fetch_x_follower_count() is None
        out = capsys.readouterr().out
        assert "Could not fetch X follower count: 429 Too Many Requests" in out
        assert "X follower read: 1 request (users/me)" in out

    def test_error_logs_headers_from_exception_response(self, track, monkeypatch, capsys):
        class FakeXError(Exception):
            def __init__(self):
                super().__init__("payment required")
                self.response = types.SimpleNamespace(headers={
                    "x-rate-limit-remaining": "0",
                    "x-usage-daily": "1",
                })

        def boom(**kwargs):
            raise FakeXError()

        client = types.SimpleNamespace(get_me=boom, session=None)
        _install_fake_twitter_bot(monkeypatch, client)

        assert track.fetch_x_follower_count() is None
        out = capsys.readouterr().out
        assert "Could not fetch X follower count" in out
        assert "x-rate-limit-remaining: 0" in out
        assert "x-usage-daily: 1" in out

    def test_missing_credentials_returns_none(self, track, monkeypatch, capsys):
        for key in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "X_BEARER_TOKEN",
        ):
            monkeypatch.delenv(key, raising=False)

        assert track.fetch_x_follower_count() is None
        out = capsys.readouterr().out
        assert "Could not fetch X follower count" in out
        # Init failed before the request, so do not claim a users/me read.
        assert "X follower read: 1 request (users/me)" not in out

    def test_empty_payload_returns_none(self, track, monkeypatch):
        client = types.SimpleNamespace(
            get_me=lambda **kwargs: types.SimpleNamespace(data=None, headers={}),
            session=None,
        )
        _install_fake_twitter_bot(monkeypatch, client)
        assert track.fetch_x_follower_count() is None

    def test_failed_fetch_leaves_existing_history(self, track, monkeypatch):
        existing = [
            {"timestamp": "2026-05-04T23:16:48+00:00", "followers": 58},
        ]
        monkeypatch.setattr(track, "fetch_x_follower_count", lambda: None)
        x_followers = track.fetch_x_follower_count()
        history = list(existing)
        if x_followers:
            history = track.upsert_follower_snapshot(
                history,
                {"timestamp": "2026-10-20T23:00:00+00:00", **x_followers},
            )
        assert history == existing
