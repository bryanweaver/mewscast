"""Tests for scripts/x_engagement.py — mocked tweepy, no live X calls."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _load_module():
    script_path = Path(__file__).parent.parent / "scripts" / "x_engagement.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("x_engagement", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def xe():
    return _load_module()


def _ts(days_ago: float, *, now=None) -> str:
    now = now or datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
    return (now - timedelta(days=days_ago)).isoformat()


def _post(
    tweet_id,
    *,
    days_ago=1,
    post_type="REPORT",
    pipeline="journalism",
    topic="A story",
    now=None,
):
    return {
        "timestamp": _ts(days_ago, now=now),
        "topic": topic,
        "x_tweet_id": tweet_id,
        "post_type": post_type,
        "post_pipeline": pipeline,
        "dossier_id": f"dossier-{tweet_id}" if tweet_id else None,
    }


class FakeTweet:
    def __init__(self, tweet_id, public_metrics, created_at=None):
        self.id = tweet_id
        self.public_metrics = public_metrics
        self.created_at = created_at


class FakeResponse:
    def __init__(self, tweets, headers=None):
        self.data = tweets
        self.headers = headers or {}


class RecordingClient:
    """tweepy-shaped client that only implements get_tweets."""

    def __init__(self, batches, error=None):
        self._batches = list(batches)
        self._error = error
        self.calls = []

    def get_tweets(self, ids, tweet_fields=None, **kwargs):
        self.calls.append({"ids": list(ids), "tweet_fields": tweet_fields, "kwargs": kwargs})
        if self._error is not None:
            raise self._error
        if not self._batches:
            return FakeResponse([])
        return self._batches.pop(0)

    def create_tweet(self, *args, **kwargs):
        raise AssertionError("create_tweet must not be called")

    def like(self, *args, **kwargs):
        raise AssertionError("like must not be called")

    def retweet(self, *args, **kwargs):
        raise AssertionError("retweet must not be called")

    def create_tweet_reply(self, *args, **kwargs):
        raise AssertionError("reply must not be called")


NOW = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)


class TestJournalismPostSelection:
    def test_keeps_recent_journalism_with_x_id(self, xe):
        posts = [
            _post("111", days_ago=1, post_type="REPORT", now=NOW),
            _post("222", days_ago=3, post_type="BRIEF", now=NOW),
        ]
        selected = xe.journalism_posts_with_x_ids(posts, now=NOW, days=14)
        assert [p["x_tweet_id"] for p in selected] == ["111", "222"]

    def test_skips_legacy_pipeline(self, xe):
        posts = [_post("111", pipeline="legacy", now=NOW)]
        assert xe.journalism_posts_with_x_ids(posts, now=NOW) == []

    def test_skips_missing_x_id(self, xe):
        posts = [_post(None, now=NOW)]
        assert xe.journalism_posts_with_x_ids(posts, now=NOW) == []

    def test_skips_posts_older_than_window(self, xe):
        posts = [
            _post("old", days_ago=15, now=NOW),
            _post("new", days_ago=13.9, now=NOW),
        ]
        selected = xe.journalism_posts_with_x_ids(posts, now=NOW, days=14)
        assert [p["x_tweet_id"] for p in selected] == ["new"]

    def test_dedupes_tweet_ids(self, xe):
        posts = [
            _post("111", days_ago=1, topic="first", now=NOW),
            _post("111", days_ago=2, topic="duplicate", now=NOW),
        ]
        selected = xe.journalism_posts_with_x_ids(posts, now=NOW)
        assert len(selected) == 1
        assert selected[0]["topic"] == "first"

    def test_skips_unparseable_timestamps(self, xe):
        posts = [_post("111", now=NOW)]
        posts[0]["timestamp"] = "not-a-date"
        assert xe.journalism_posts_with_x_ids(posts, now=NOW) == []

    def test_rejects_string_posts_payload(self, xe):
        assert xe.journalism_posts_with_x_ids("not-a-list", now=NOW) == []


class TestBatching:
    def test_chunks_at_100(self, xe):
        ids = [str(i) for i in range(101)]
        batches = xe.chunked(ids, 100)
        assert len(batches) == 2
        assert len(batches[0]) == 100
        assert batches[1] == ["100"]

    def test_empty(self, xe):
        assert xe.chunked([], 100) == []


class TestFetchPublicMetrics:
    def test_calls_get_tweets_with_required_fields_only(self, xe):
        tweet = FakeTweet(
            "111",
            {
                "like_count": 4,
                "retweet_count": 1,
                "reply_count": 2,
                "quote_count": 3,
                "impression_count": 50,
            },
            created_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
        )
        headers = {
            "x-rate-limit-limit": "300",
            "x-rate-limit-remaining": "299",
            "x-app-limit-24hour-remaining": "9999",
            "content-type": "application/json",
        }
        client = RecordingClient([FakeResponse([tweet], headers=headers)])
        logs = []
        metrics, count = xe.fetch_public_metrics(client, ["111"], log=logs.append)

        assert count == 1
        assert client.calls[0]["tweet_fields"] == ["public_metrics", "created_at"]
        assert client.calls[0]["kwargs"] == {}
        assert metrics["111"]["likes"] == 4
        assert metrics["111"]["reposts"] == 1
        assert metrics["111"]["replies"] == 2
        assert metrics["111"]["quotes"] == 3
        assert metrics["111"]["impressions"] == 50
        assert any("request count: 1" in line for line in logs)
        assert any("x-rate-limit-remaining: 299" in line for line in logs)
        assert any("x-app-limit-24hour-remaining: 9999" in line for line in logs)
        assert not any("content-type" in line.lower() for line in logs)

    def test_impressions_optional(self, xe):
        tweet = FakeTweet("111", {"like_count": 1, "retweet_count": 0, "reply_count": 0, "quote_count": 0})
        client = RecordingClient([FakeResponse([tweet])])
        metrics, _ = xe.fetch_public_metrics(client, ["111"], log=lambda *_: None)
        assert metrics["111"]["impressions"] is None

    def test_batches_over_100_ids(self, xe):
        def tweet(i):
            return FakeTweet(str(i), {"like_count": i})

        first = FakeResponse([tweet(i) for i in range(100)])
        second = FakeResponse([tweet(100)])
        client = RecordingClient([first, second])
        ids = [str(i) for i in range(101)]
        metrics, count = xe.fetch_public_metrics(client, ids, log=lambda *_: None)
        assert count == 2
        assert len(client.calls) == 2
        assert len(client.calls[0]["ids"]) == 100
        assert client.calls[1]["ids"] == ["100"]
        assert len(metrics) == 101

    def test_soft_fails_a_batch_and_continues(self, xe):
        class PartialClient:
            def __init__(self):
                self.calls = 0

            def get_tweets(self, ids, tweet_fields=None, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    err = RuntimeError("429 rate limit")
                    err.headers = {"x-rate-limit-remaining": "0"}
                    raise err
                return FakeResponse([FakeTweet("200", {"like_count": 9})])

        client = PartialClient()
        logs = []
        metrics, count = xe.fetch_public_metrics(
            client, [str(i) for i in range(100)] + ["200"], log=logs.append
        )
        assert count == 2
        assert "200" in metrics
        assert metrics["200"]["likes"] == 9
        assert any("non-fatal" in line for line in logs)
        assert any("x-rate-limit-remaining: 0" in line for line in logs)

    def test_no_requests_when_id_list_empty(self, xe):
        client = RecordingClient([])
        metrics, count = xe.fetch_public_metrics(client, [], log=lambda *_: None)
        assert metrics == {}
        assert count == 0
        assert client.calls == []


class TestAverages:
    def test_averages_by_post_type(self, xe):
        rows = [
            {"post_type": "REPORT", "likes": 2, "reposts": 0, "replies": 2, "quotes": 0, "impressions": 10},
            {"post_type": "REPORT", "likes": 4, "reposts": 2, "replies": 0, "quotes": 2, "impressions": 20},
            {"post_type": "BRIEF", "likes": 1, "reposts": 1, "replies": 1, "quotes": 1, "impressions": None},
        ]
        averages = xe.averages_by_post_type(rows)
        assert averages["REPORT"]["count"] == 2
        assert averages["REPORT"]["likes"] == 3.0
        assert averages["REPORT"]["reposts"] == 1.0
        assert averages["REPORT"]["impressions"] == 15.0
        assert averages["BRIEF"]["count"] == 1
        assert averages["BRIEF"]["impressions"] is None
        assert averages["ALL"]["count"] == 3
        assert averages["ALL"]["likes"] == 2.33

    def test_empty_rows_have_no_averages(self, xe):
        assert xe.averages_by_post_type([]) == {}


class TestReadonlyClient:
    def test_missing_secrets_raise(self, xe):
        with pytest.raises(ValueError, match="Missing X API"):
            xe.build_readonly_client(env={})

    def test_builds_tweepy_client_with_journalism_secrets(self, xe, monkeypatch):
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake_tweepy = types.SimpleNamespace(Client=FakeClient)
        monkeypatch.setitem(sys.modules, "tweepy", fake_tweepy)
        client = xe.build_readonly_client(env={
            "X_API_KEY": "k",
            "X_API_SECRET": "s",
            "X_ACCESS_TOKEN": "t",
            "X_ACCESS_TOKEN_SECRET": "ts",
            "X_BEARER_TOKEN": "b",
        })
        assert isinstance(client, FakeClient)
        assert captured["bearer_token"] == "b"
        assert captured["wait_on_rate_limit"] is False


class TestRunXEngagement:
    def test_writes_json_and_embeds_html(self, xe, tmp_path):
        posts = [
            _post("111", days_ago=1, post_type="REPORT", topic="Court ruling", now=NOW),
            _post("222", days_ago=2, post_type="META", topic="Coverage gap", now=NOW),
            _post("legacy", days_ago=1, pipeline="legacy", now=NOW),
        ]
        tweets = [
            FakeTweet("111", {"like_count": 5, "retweet_count": 1, "reply_count": 0, "quote_count": 1, "impression_count": 80}),
            FakeTweet("222", {"like_count": 1, "retweet_count": 0, "reply_count": 3, "quote_count": 0}),
        ]
        client = RecordingClient([FakeResponse(tweets, headers={"x-rate-limit-remaining": "50"})])
        data_path = tmp_path / "x_engagement.json"
        html_path = tmp_path / "analytics.html"
        html_path.write_text(
            "const X_ENGAGEMENT_DATA = /* X_ENGAGEMENT_DATA_PLACEHOLDER */ {} /* END_X_ENGAGEMENT_DATA */;\n",
            encoding="utf-8",
        )
        logs = []

        payload = xe.run_x_engagement(
            posts=posts,
            now=NOW,
            client=client,
            data_path=str(data_path),
            html_path=str(html_path),
            log=logs.append,
        )

        assert payload is not None
        assert payload["request_count"] == 1
        assert [p["x_tweet_id"] for p in payload["posts"]] == ["111", "222"]
        assert payload["posts"][0]["post_type"] == "REPORT"
        assert payload["posts"][0]["likes"] == 5
        assert payload["posts"][0]["impressions"] == 80
        assert payload["posts"][1]["impressions"] is None
        assert "REPORT" in payload["averages"]
        assert "META" in payload["averages"]

        saved = json.loads(data_path.read_text(encoding="utf-8"))
        assert saved["posts"][0]["topic"] == "Court ruling"

        html = html_path.read_text(encoding="utf-8")
        assert "X_ENGAGEMENT_DATA_PLACEHOLDER" in html
        assert "Court ruling" in html
        assert any("request count: 1" in line for line in logs)

        # Read-only: only get_tweets was used
        assert hasattr(client, "create_tweet")
        assert len(client.calls) == 1

    def test_missing_credentials_fail_soft(self, xe, tmp_path, monkeypatch):
        monkeypatch.setattr(xe, "build_readonly_client", MagicMock(side_effect=ValueError("Missing X API")))
        logs = []
        result = xe.run_x_engagement(
            posts=[_post("111", now=NOW)],
            now=NOW,
            data_path=str(tmp_path / "x.json"),
            html_path=str(tmp_path / "missing.html"),
            log=logs.append,
        )
        assert result is None
        assert any("non-fatal" in line for line in logs)
        assert not (tmp_path / "x.json").exists()

    def test_api_outage_fail_soft_still_writes_empty_metrics(self, xe, tmp_path):
        class Boom:
            def get_tweets(self, *args, **kwargs):
                raise RuntimeError("connection reset")

        data_path = tmp_path / "x.json"
        html_path = tmp_path / "a.html"
        html_path.write_text(
            "/* X_ENGAGEMENT_DATA_PLACEHOLDER */ {} /* END_X_ENGAGEMENT_DATA */",
            encoding="utf-8",
        )
        payload = xe.run_x_engagement(
            posts=[_post("111", now=NOW)],
            now=NOW,
            client=Boom(),
            data_path=str(data_path),
            html_path=str(html_path),
            log=lambda *_: None,
        )
        assert payload is not None
        assert payload["posts"][0]["likes"] == 0
        assert payload["request_count"] == 1

    def test_main_returns_zero(self, xe, monkeypatch):
        monkeypatch.setattr(xe, "run_x_engagement", lambda: {"posts": []})
        assert xe.main() == 0

    def test_run_never_raises_on_broken_inputs(self, xe, monkeypatch):
        monkeypatch.setattr(
            xe,
            "journalism_posts_with_x_ids",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert xe.run_x_engagement(posts=[], log=lambda *_: None) is None


class TestDashboardEmbed:
    def test_embed_replaces_placeholder_only(self, xe, tmp_path):
        html_path = tmp_path / "analytics.html"
        html_path.write_text(
            "const ANALYTICS_DATA = /* ANALYTICS_DATA_PLACEHOLDER */ {\"keep\": true} /* END_ANALYTICS_DATA */;\n"
            "const X_ENGAGEMENT_DATA = /* X_ENGAGEMENT_DATA_PLACEHOLDER */ {} /* END_X_ENGAGEMENT_DATA */;\n",
            encoding="utf-8",
        )
        payload = {
            "last_updated": "2026-10-20T23:00:00+00:00",
            "window_days": 14,
            "request_count": 1,
            "posts": [{"x_tweet_id": "111", "post_type": "REPORT", "topic": "Hello", "likes": 2}],
            "averages": {"REPORT": {"count": 1, "likes": 2.0}},
        }
        assert xe.embed_in_dashboard(payload, str(html_path)) is True
        html = html_path.read_text(encoding="utf-8")
        assert '{"keep": true}' in html
        assert "ANALYTICS_DATA_PLACEHOLDER" in html
        assert "Hello" in html
        assert "REPORT" in html


class TestTrackAnalyticsHook:
    def test_track_analytics_calls_x_engagement(self):
        src = (Path(__file__).parent.parent / "scripts" / "track_analytics.py").read_text(encoding="utf-8")
        assert "run_x_engagement" in src
        assert "x_engagement" in src

    def test_workflow_uses_journalism_x_secrets(self):
        src = (
            Path(__file__).parent.parent / ".github" / "workflows" / "track-analytics.yml"
        ).read_text(encoding="utf-8")
        assert "X_API_KEY" in src
        assert "X_BEARER_TOKEN" in src
        assert "docs/x_engagement.json" in src
        assert "0 23 * * *" in src
