"""Tests for scripts/x_mentions_digest.py.

All X/tweepy calls are mocked. No live API traffic.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _load_script():
    script_path = Path(__file__).parent.parent / "scripts" / "x_mentions_digest.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("x_mentions_digest", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def digest_mod():
    return _load_script()


def _tweet(
    tweet_id,
    text,
    *,
    author_id="99",
    created_at=None,
    conversation_id=None,
    referenced=None,
):
    return SimpleNamespace(
        id=str(tweet_id),
        text=text,
        author_id=str(author_id),
        created_at=created_at or datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
        conversation_id=conversation_id,
        referenced_tweets=referenced,
    )


def _user(user_id, username):
    return SimpleNamespace(id=str(user_id), username=username)


def _response(tweets, users=None):
    return SimpleNamespace(
        data=tweets,
        includes=SimpleNamespace(users=users or []),
    )


def _client(mod, inner=None):
    inner = inner or MagicMock()
    return mod.ReadOnlyXClient(inner), inner


def _write_posts(path: Path, posts: list[dict]) -> Path:
    path.write_text(json.dumps({"posts": posts}), encoding="utf-8")
    return path


class TestLooksLikeCorrection:
    def test_flags_known_keywords(self, digest_mod):
        flagged, keys = digest_mod.looks_like_correction(
            "This is wrong and misleading."
        )
        assert flagged is True
        assert "wrong" in keys
        assert "misleading" in keys

    def test_flags_false_and_correction(self, digest_mod):
        flagged, keys = digest_mod.looks_like_correction(
            "Correction: that claim is false and inaccurate."
        )
        assert flagged is True
        assert set(keys) == {"correction", "false", "inaccurate"}

    def test_prefix_match_wrongly(self, digest_mod):
        flagged, keys = digest_mod.looks_like_correction("You reported this wrongly.")
        assert flagged is True
        assert "wrong" in keys

    def test_plain_praise_not_flagged(self, digest_mod):
        flagged, keys = digest_mod.looks_like_correction("Solid sourcing, thanks.")
        assert flagged is False
        assert keys == []

    def test_empty_not_flagged(self, digest_mod):
        assert digest_mod.looks_like_correction("") == (False, [])
        assert digest_mod.looks_like_correction(None) == (False, [])


class TestPostsLookback:
    def test_only_last_three_days_with_x_id(self, digest_mod):
        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts = [
            {
                "timestamp": "2026-10-20T12:00:00+00:00",
                "x_tweet_id": "new1",
                "topic": "today",
            },
            {
                "timestamp": "2026-10-18T00:00:01+00:00",
                "x_tweet_id": "edge",
                "topic": "inside window",
            },
            {
                "timestamp": "2026-10-17T22:59:00+00:00",
                "x_tweet_id": "old",
                "topic": "too old",
            },
            {
                "timestamp": "2026-10-20T12:00:00+00:00",
                "topic": "no x id",
            },
        ]
        recent = digest_mod.posts_in_lookback(posts, now, days=3)
        assert [p["x_tweet_id"] for p in recent] == ["new1", "edge"]


class TestMaxSnowflakeAndDedup:
    def test_max_snowflake(self, digest_mod):
        assert digest_mod.max_snowflake("10", "2", None, "9") == "10"
        assert digest_mod.max_snowflake(None, "") is None

    def test_merge_items_dedups_by_id(self, digest_mod):
        existing = [{"id": "1", "text": "old", "created_at": "2026-10-19T00:00:00+00:00"}]
        incoming = [
            {"id": "1", "text": "dup", "created_at": "2026-10-20T00:00:00+00:00"},
            {"id": "2", "text": "new", "created_at": "2026-10-20T01:00:00+00:00"},
        ]
        merged, new_count = digest_mod.merge_items(existing, incoming)
        assert new_count == 1
        assert [i["id"] for i in merged] == ["2", "1"]
        assert merged[1]["text"] == "old"


class TestHeaderExtraction:
    def test_extracts_rate_limit_and_usage_headers(self, digest_mod):
        headers = {
            "x-rate-limit-remaining": "12",
            "x-rate-limit-reset": "99",
            "x-usage-24hour": "3",
            "content-type": "application/json",
        }
        interesting = digest_mod.extract_interesting_headers(headers)
        assert interesting["x-rate-limit-remaining"] == "12"
        assert "x-usage-24hour" in interesting
        assert "content-type" not in interesting

    def test_headers_from_exception_response(self, digest_mod):
        exc = SimpleNamespace(
            response=SimpleNamespace(
                headers={"x-rate-limit-remaining": "0", "x-rate-limit-reset": "1"}
            )
        )
        found = digest_mod.headers_from_obj(exc)
        assert found["x-rate-limit-remaining"] == "0"


class TestReadOnlyCaps:
    def test_mentions_cap_at_50(self, digest_mod):
        wrapper, inner = _client(digest_mod)
        inner.get_users_mentions.return_value = _response([])
        wrapper.get_users_mentions(id="1", max_results=999)
        inner.get_users_mentions.assert_called_once()
        assert inner.get_users_mentions.call_args.kwargs["max_results"] == 50

    def test_quotes_cap_at_20(self, digest_mod):
        wrapper, inner = _client(digest_mod)
        inner.get_quote_tweets.return_value = _response([])
        wrapper.get_quote_tweets(id="1", max_results=100)
        assert inner.get_quote_tweets.call_args.kwargs["max_results"] == 20

    def test_refuses_unknown_method(self, digest_mod):
        wrapper, _inner = _client(digest_mod)
        with pytest.raises(RuntimeError, match="refused"):
            wrapper._call("create_tweet", text="nope")


class TestRunDigest:
    def test_mentions_then_quotes_persist_since_id(self, digest_mod, tmp_path):
        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(
            tmp_path / "posts_history.json",
            [
                {
                    "timestamp": (now - timedelta(hours=2)).isoformat(),
                    "x_tweet_id": "555",
                    "x_reply_tweet_id": "556",
                    "topic": "Farm costs",
                },
                {
                    "timestamp": (now - timedelta(days=10)).isoformat(),
                    "x_tweet_id": "111",
                    "topic": "Old post",
                },
            ],
        )
        digest_path = tmp_path / "x_mentions_digest.json"
        digest_path.write_text(
            json.dumps({"account": "mewscast", "since_id": "100", "items": []}),
            encoding="utf-8",
        )

        inner = MagicMock()
        inner.get_me.return_value = SimpleNamespace(
            data=SimpleNamespace(id="42", username="mewscast")
        )
        mention = _tweet(
            "200",
            "@mewscast this is wrong",
            author_id="77",
            referenced=[SimpleNamespace(id="555", type="replied_to")],
            conversation_id="555",
        )
        inner.get_users_mentions.return_value = _response(
            [mention], users=[_user("77", "alice")]
        )
        quote = _tweet(
            "300",
            "quoting the farm post",
            author_id="88",
            created_at=datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc),
        )
        inner.get_quote_tweets.return_value = _response(
            [quote], users=[_user("88", "bob")]
        )

        wrapper = digest_mod.ReadOnlyXClient(inner)
        result = digest_mod.run_digest(
            client=wrapper,
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )

        inner.get_me.assert_called_once()
        mention_kwargs = inner.get_users_mentions.call_args.kwargs
        assert mention_kwargs["id"] == "42"
        assert mention_kwargs["since_id"] == "100"
        assert mention_kwargs["max_results"] <= 50

        inner.get_quote_tweets.assert_called_once()
        quote_kwargs = inner.get_quote_tweets.call_args.kwargs
        assert quote_kwargs["id"] == "555"
        assert quote_kwargs["max_results"] <= 20

        inner.create_tweet.assert_not_called()
        inner.like.assert_not_called()
        inner.retweet.assert_not_called()
        inner.create_direct_message.assert_not_called()

        ids = {item["id"] for item in result["items"]}
        assert ids == {"200", "300"}
        mention_item = next(i for i in result["items"] if i["id"] == "200")
        assert mention_item["author_handle"] == "alice"
        assert mention_item["url"] == "https://x.com/alice/status/200"
        assert mention_item["looks_like_correction"] is True
        assert mention_item["referenced_mewscast_post"]["x_tweet_id"] == "555"
        assert mention_item["referenced_mewscast_post"]["topic"] == "Farm costs"

        quote_item = next(i for i in result["items"] if i["id"] == "300")
        assert quote_item["kind"] == "quote"
        assert quote_item["author_handle"] == "bob"
        assert quote_item["referenced_mewscast_post"]["x_tweet_id"] == "555"

        assert result["since_id"] == "200"
        assert result["last_run"]["request_counts"]["get_me"] == 1
        assert result["last_run"]["request_counts"]["get_users_mentions"] == 1
        assert result["last_run"]["request_counts"]["get_quote_tweets"] == 1

        saved = json.loads(digest_path.read_text(encoding="utf-8"))
        assert saved["since_id"] == "200"
        assert {i["id"] for i in saved["items"]} == {"200", "300"}

    def test_dedup_and_since_id_not_rewound(self, digest_mod, tmp_path):
        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(tmp_path / "posts.json", [])
        digest_path = tmp_path / "digest.json"
        digest_path.write_text(
            json.dumps(
                {
                    "since_id": "500",
                    "items": [
                        {
                            "id": "200",
                            "kind": "mention",
                            "text": "already stored",
                            "created_at": "2026-10-19T00:00:00+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        inner = MagicMock()
        inner.get_me.return_value = SimpleNamespace(
            data=SimpleNamespace(id="42", username="mewscast")
        )
        inner.get_users_mentions.return_value = _response(
            [_tweet("200", "already stored", author_id="77")],
            users=[_user("77", "alice")],
        )
        wrapper = digest_mod.ReadOnlyXClient(inner)
        result = digest_mod.run_digest(
            client=wrapper,
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )
        assert result["since_id"] == "500"
        assert len(result["items"]) == 1
        assert result["last_run"]["new_items"] == 0

    def test_fail_soft_on_rate_limit(self, digest_mod, tmp_path):
        import tweepy

        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(
            tmp_path / "posts.json",
            [
                {
                    "timestamp": now.isoformat(),
                    "x_tweet_id": "555",
                    "topic": "live",
                }
            ],
        )
        digest_path = tmp_path / "digest.json"

        resp = MagicMock()
        resp.headers = {
            "x-rate-limit-remaining": "0",
            "x-rate-limit-reset": "1700000000",
            "x-usage-24hour": "capped",
        }
        rate_err = tweepy.TooManyRequests(resp)
        rate_err.response = resp

        inner = MagicMock()
        inner.get_me.return_value = SimpleNamespace(
            data=SimpleNamespace(id="42", username="mewscast")
        )
        inner.get_users_mentions.side_effect = rate_err
        inner.get_quote_tweets.side_effect = rate_err

        wrapper = digest_mod.ReadOnlyXClient(inner)
        result = digest_mod.run_digest(
            client=wrapper,
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )
        assert result["items"] == []
        assert result["since_id"] is None
        assert result["last_run"]["errors"]
        header_blob = json.dumps(result["last_run"]["rate_limit_headers"])
        assert "x-rate-limit-remaining" in header_blob
        assert digest_path.exists()

    def test_missing_credentials_fail_soft(self, digest_mod, tmp_path, monkeypatch):
        for key in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "X_BEARER_TOKEN",
        ):
            monkeypatch.delenv(key, raising=False)

        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(tmp_path / "posts.json", [])
        digest_path = tmp_path / "digest.json"

        result = digest_mod.run_digest(
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )
        assert result["last_run"]["errors"]
        assert any("credentials" in err.lower() or "missing" in err.lower()
                   for err in result["last_run"]["errors"])
        assert digest_path.exists()

    def test_main_always_exits_zero(self, digest_mod, tmp_path, monkeypatch):
        monkeypatch.setattr(
            digest_mod,
            "run_digest",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        assert digest_mod.main() == 0

    def test_skips_own_mentions(self, digest_mod, tmp_path):
        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(tmp_path / "posts.json", [])
        digest_path = tmp_path / "digest.json"

        inner = MagicMock()
        inner.get_me.return_value = SimpleNamespace(
            data=SimpleNamespace(id="42", username="mewscast")
        )
        inner.get_users_mentions.return_value = _response(
            [_tweet("900", "our own mention", author_id="42")],
            users=[_user("42", "mewscast")],
        )
        wrapper = digest_mod.ReadOnlyXClient(inner)
        result = digest_mod.run_digest(
            client=wrapper,
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )
        assert result["items"] == []
        assert result["since_id"] == "900"

    def test_does_not_quote_old_posts(self, digest_mod, tmp_path):
        now = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        posts_path = _write_posts(
            tmp_path / "posts.json",
            [
                {
                    "timestamp": (now - timedelta(days=10)).isoformat(),
                    "x_tweet_id": "old-id",
                    "topic": "ancient",
                }
            ],
        )
        digest_path = tmp_path / "digest.json"
        inner = MagicMock()
        inner.get_me.return_value = SimpleNamespace(
            data=SimpleNamespace(id="42", username="mewscast")
        )
        inner.get_users_mentions.return_value = _response([])
        wrapper = digest_mod.ReadOnlyXClient(inner)
        digest_mod.run_digest(
            client=wrapper,
            now=now,
            digest_path=str(digest_path),
            posts_path=str(posts_path),
        )
        inner.get_quote_tweets.assert_not_called()


class TestBuildReadonlyClient:
    def test_uses_mewscast_x_secrets(self, digest_mod, monkeypatch):
        monkeypatch.setenv("X_API_KEY", "key")
        monkeypatch.setenv("X_API_SECRET", "secret")
        monkeypatch.setenv("X_ACCESS_TOKEN", "token")
        monkeypatch.setenv("X_ACCESS_TOKEN_SECRET", "token-secret")
        monkeypatch.setenv("X_BEARER_TOKEN", "bearer")

        fake_tweepy = MagicMock()
        fake_client = MagicMock()
        fake_tweepy.Client.return_value = fake_client
        with patch.dict("sys.modules", {"tweepy": fake_tweepy}):
            wrapper = digest_mod.build_readonly_client()

        fake_tweepy.Client.assert_called_once()
        kwargs = fake_tweepy.Client.call_args.kwargs
        assert kwargs["bearer_token"] == "bearer"
        assert kwargs["consumer_key"] == "key"
        assert kwargs["access_token"] == "token"
        assert kwargs["wait_on_rate_limit"] is False
        assert isinstance(wrapper, digest_mod.ReadOnlyXClient)
        assert wrapper._client is fake_client
