"""
Unit tests for src/trend_detector.py — Stage 1 of the Walter Croncat
journalism workflow.

Covers:
  - Query construction from a registry (from:X OR from:Y clauses)
  - Handle chunking when the registry exceeds the per-query cap
  - Tweet clustering by proper-noun overlap
  - Story-id determinism
  - Fallback to NewsFetcher on X API failure
  - max_candidates cap
  - Graceful empty-state when both X and NewsFetcher are absent
"""
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Path setup
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from trend_detector import (  # noqa: E402
    TrendCandidate,
    TrendDetector,
    _extract_proper_nouns,
    _normalize_headline,
    _stable_story_id,
)


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _FakeTweet:
    """Quacks like a tweepy Tweet object."""

    def __init__(self, text, author_id, like=0, rt=0, reply=0, created_at=None):
        self.text = text
        self.author_id = author_id
        self.public_metrics = {
            "like_count": like,
            "retweet_count": rt,
            "reply_count": reply,
        }
        self.created_at = created_at or "2026-04-08T19:30:00+00:00"
        self.entities = {}


class _FakeIncludes(dict):
    """dict subclass so attribute-style access mirrors tweepy's Response.includes."""
    pass


class _FakeResponse:
    def __init__(self, data, users=None):
        self.data = data
        self.includes = _FakeIncludes(users=users or [])


class _FakeUser:
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username


class _FakeTweepyClient:
    def __init__(self, responses):
        """responses: list of _FakeResponse, one per chunk call. Raise an
        exception by making an entry an Exception instance instead."""
        self._responses = list(responses)
        self.calls: list[dict] = []

    def search_recent_tweets(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            return _FakeResponse([])
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class _FakeTwitterBot:
    def __init__(self, client):
        self.client = client


class _StubNewsFetcher:
    def __init__(self, stories=None, raise_on_call=False):
        self._stories = stories or []
        self._raise = raise_on_call

    def get_top_stories(self, max_stories=20):
        if self._raise:
            raise RuntimeError("boom")
        return list(self._stories[:max_stories])


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    def test_extract_proper_nouns_skips_sentence_starters(self):
        nouns = _extract_proper_nouns("The Senate passes a bill")
        assert "senate" in nouns
        assert "the" not in nouns

    def test_extract_proper_nouns_lowercases(self):
        nouns = _extract_proper_nouns("Reuters: Senate Passes Bill")
        assert "reuters" in nouns
        assert "Reuters" not in nouns

    def test_normalize_headline_strips_urls(self):
        out = _normalize_headline("Senate vote https://t.co/abc123 happens now")
        assert "t.co" not in out
        assert "Senate" in out

    def test_stable_story_id_is_deterministic(self):
        a = _stable_story_id("Senate passes bill", "2026-04-08T19:30:00+00:00")
        b = _stable_story_id("Senate passes bill", "2026-04-08T19:45:00+00:00")
        # Same day → same id
        assert a == b

    def test_stable_story_id_different_days(self):
        a = _stable_story_id("Senate passes bill", "2026-04-08T19:30:00+00:00")
        c = _stable_story_id("Senate passes bill", "2026-04-09T00:00:00+00:00")
        assert a != c

    def test_stable_story_id_includes_day_bucket(self):
        sid = _stable_story_id("Senate passes bill", "2026-04-08T19:30:00+00:00")
        assert sid.startswith("2026-04-08-")


# ---------------------------------------------------------------------------
# Query construction + chunking
# ---------------------------------------------------------------------------

class TestQueryConstruction:
    def test_build_query_uses_from_clauses(self):
        outlets = [
            {"handle": "Reuters"},
            {"handle": "AP"},
            {"handle": "FoxNews"},
        ]
        q = TrendDetector._build_query(outlets)
        assert "from:Reuters" in q
        assert "from:AP" in q
        assert "from:FoxNews" in q
        assert " OR " in q
        assert "-is:retweet" in q
        assert "lang:en" in q

    def test_build_query_empty_returns_empty_string(self):
        assert TrendDetector._build_query([]) == ""

    def test_chunk_handles_produces_correct_sized_chunks(self):
        outlets = [{"handle": f"h{i}"} for i in range(12)]
        chunks = list(TrendDetector._chunk_handles(outlets, 5))
        assert len(chunks) == 3
        assert len(chunks[0]) == 5 and len(chunks[1]) == 5 and len(chunks[2]) == 2


# ---------------------------------------------------------------------------
# X recent-search path
# ---------------------------------------------------------------------------

class TestDetectViaX:
    def test_builds_query_from_registry(self, tmp_path):
        # Write a tiny registry to disk
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n"
            "  - name: Reuters\n    handle: Reuters\n    slant: wire\n"
            "  - name: AP\n    handle: AP\n    slant: wire\n",
            encoding="utf-8",
        )

        client = _FakeTweepyClient([_FakeResponse([])])
        bot = _FakeTwitterBot(client)

        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=bot,
            news_fetcher=None,
        )
        # Trigger the X path
        detector._detect_via_x(max_candidates=5)

        assert len(client.calls) >= 1
        q = client.calls[0]["query"]
        assert "from:Reuters" in q
        assert "from:AP" in q

    def test_clusters_tweets_by_proper_noun_overlap(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n"
            "  - name: Reuters\n    handle: Reuters\n    slant: wire\n"
            "  - name: AP\n    handle: AP\n    slant: wire\n"
            "  - name: FoxNews\n    handle: FoxNews\n    slant: right-mainstream\n",
            encoding="utf-8",
        )
        # Three tweets about the same Senate vote → should cluster.
        tweets = [
            _FakeTweet(
                "Senate passes Appropriations Bill 68-32 averting shutdown",
                author_id=1, like=100, rt=50, reply=20,
            ),
            _FakeTweet(
                "BREAKING: Senate Appropriations vote 68-32 midnight passage",
                author_id=2, like=80, rt=30, reply=10,
            ),
            _FakeTweet(
                "Senate Appropriations clears chamber 68-32 in late-night vote",
                author_id=3, like=60, rt=20, reply=5,
            ),
        ]
        users = [
            _FakeUser(1, "Reuters"),
            _FakeUser(2, "AP"),
            _FakeUser(3, "FoxNews"),
        ]
        client = _FakeTweepyClient([_FakeResponse(tweets, users=users)])
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=_FakeTwitterBot(client),
            news_fetcher=None,
        )
        candidates = detector._detect_via_x(max_candidates=10)
        assert candidates, "expected at least one cluster"
        senate = next(
            (c for c in candidates if "senate" in c.headline_seed.lower()),
            None,
        )
        assert senate is not None
        assert len(senate.source_signals) >= 2
        assert senate.engagement > 0

    def test_x_api_failure_returns_empty_without_crashing(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        client = _FakeTweepyClient([RuntimeError("rate limit")])
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=_FakeTwitterBot(client),
            news_fetcher=None,
        )
        candidates = detector._detect_via_x(max_candidates=5)
        assert candidates == []

    def test_no_twitter_bot_short_circuits(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=None,
            news_fetcher=None,
        )
        assert detector._detect_via_x(max_candidates=5) == []


# ---------------------------------------------------------------------------
# NewsFetcher fallback + full detect_trends orchestration
# ---------------------------------------------------------------------------

class TestDetectTrendsFallback:
    def test_fallback_to_news_fetcher_on_empty_x(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        stub_news = _StubNewsFetcher(stories=[
            {
                "title": "Senate passes bill",
                "source": "Reuters",
                "published_date": "2026-04-08T12:00:00+00:00",
            },
            {
                "title": "Fed holds rates steady",
                "source": "Bloomberg",
                "published_date": "2026-04-08T11:00:00+00:00",
            },
        ])
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=None,         # forces fallback
            news_fetcher=stub_news,
        )
        candidates = detector.detect_trends(max_candidates=5)
        assert len(candidates) == 2
        assert any("Senate" in c.headline_seed for c in candidates)

    def test_fallback_to_news_fetcher_on_x_failure(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        client = _FakeTweepyClient([RuntimeError("rate limit")])
        stub_news = _StubNewsFetcher(stories=[
            {"title": "Senate bill passes", "source": "Reuters",
             "published_date": "2026-04-08T12:00:00+00:00"},
        ])
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=_FakeTwitterBot(client),
            news_fetcher=stub_news,
        )
        candidates = detector.detect_trends(max_candidates=5)
        assert len(candidates) == 1
        assert "Senate" in candidates[0].headline_seed

    def test_detect_trends_respects_max_candidates(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        stories = [
            {"title": f"Story {i}", "source": "Reuters",
             "published_date": "2026-04-08T12:00:00+00:00"}
            for i in range(20)
        ]
        stub_news = _StubNewsFetcher(stories=stories)
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=None,
            news_fetcher=stub_news,
        )
        candidates = detector.detect_trends(max_candidates=5)
        assert len(candidates) == 5

    def test_detect_trends_empty_when_no_sources(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=None,
            news_fetcher=None,
        )
        candidates = detector.detect_trends(max_candidates=5)
        assert candidates == []

    def test_news_fetcher_exception_degrades_to_empty(self, tmp_path):
        registry = tmp_path / "outlets.yaml"
        registry.write_text(
            "outlets:\n  - name: Reuters\n    handle: Reuters\n    slant: wire\n",
            encoding="utf-8",
        )
        stub_news = _StubNewsFetcher(raise_on_call=True)
        detector = TrendDetector(
            registry_path=str(registry),
            twitter_bot=None,
            news_fetcher=stub_news,
        )
        assert detector.detect_trends(max_candidates=5) == []
