"""
Tests for OutletReplyBot (src/outlet_reply_bot.py).

Covers:
  - Config and registry loading
  - Reply history loading, saving, and cleanup
  - Candidate selection (recent journalism posts)
  - Meta angle scoring
  - Tweet matching and scoring
  - Reply composition (templates, character limits)
  - Safety limits (daily cap, per-outlet cooldown, duplicate prevention)
  - run_reply_cycle orchestration
  - Error handling
"""

import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-import module mocking
# ---------------------------------------------------------------------------

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_project_root, "src")
for _p in (_project_root, _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_mock_content_gen = types.ModuleType("content_generator")
_mock_content_gen._truncate_at_sentence = lambda text, max_len=280: text[:max_len]
sys.modules.setdefault("content_generator", _mock_content_gen)

_mock_tweepy = types.ModuleType("tweepy")
_mock_tweepy.Client = MagicMock
_mock_tweepy.API = MagicMock
_mock_tweepy.OAuth1UserHandler = MagicMock
_mock_tweepy.TweepyException = Exception
_mock_tweepy.TooManyRequests = Exception
sys.modules.setdefault("tweepy", _mock_tweepy)

_mock_twitter_bot_mod = types.ModuleType("twitter_bot")
_mock_twitter_bot_mod.TwitterBot = MagicMock
sys.modules.setdefault("twitter_bot", _mock_twitter_bot_mod)

# Mock yaml for controlled config loading
_real_yaml = None
try:
    import yaml as _real_yaml
except ImportError:
    pass

from src.outlet_reply_bot import OutletReplyBot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bot(tmp_path):
    """OutletReplyBot with mocked TwitterBot and isolated files."""
    with patch.dict(os.environ, {
        "X_API_KEY": "k", "X_API_SECRET": "s",
        "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts",
        "X_BEARER_TOKEN": "b",
    }):
        b = OutletReplyBot()
        b.bot = Mock()
        b.bot.client = Mock()
        b.bot.reply_to_tweet = Mock(return_value={"id": "reply123"})

        # Isolated history file
        history_path = tmp_path / "outlet_reply_history.json"
        history_path.write_text(json.dumps({
            "replies": [],
            "last_cleanup": datetime.now(timezone.utc).isoformat()
        }))
        b.history_path = history_path
        b.reply_history = {
            "replies": [],
            "last_cleanup": datetime.now(timezone.utc).isoformat()
        }

        # Default config (enabled)
        b.config = {
            "enabled": True,
            "max_replies_per_day": 2,
            "per_outlet_cooldown_hours": 72,
            "min_meta_score": 3,
            "eligible_window_hours": 8,
            "priority_outlets": ["Reuters", "AP", "nytimes", "washingtonpost"],
        }

        # Minimal registry
        b.registry = {
            "Reuters": {"name": "Reuters", "handle": "Reuters", "priority": 1},
            "Associated Press": {"name": "Associated Press", "handle": "AP", "priority": 1},
            "The New York Times": {"name": "The New York Times", "handle": "nytimes", "priority": 1},
            "The Washington Post": {"name": "The Washington Post", "handle": "washingtonpost", "priority": 1},
            "Fox News": {"name": "Fox News", "handle": "FoxNews", "priority": 2},
        }

        # Mock dossier store
        b.dossier_store = Mock()

        return b


def _make_post(dossier_id="2026-04-17-test-story-abc123", post_type="REPORT",
               hours_ago=2):
    """Build a journalism post entry."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "timestamp": ts,
        "topic": "Hungary's PM-elect Peter Magyar sworn in",
        "url": "https://reuters.com/example",
        "source": "Reuters",
        "content": "Post text here",
        "x_tweet_id": "123456",
        "dossier_id": dossier_id,
        "post_type": post_type,
        "post_pipeline": "journalism",
    }


def _make_dossier_data(disagreements=True, missing_context=True, framing_outlets=4,
                       post_type="REPORT", confidence=0.65):
    """Build a dossier data dict with brief."""
    brief = {
        "story_id": "2026-04-17-test-story-abc123",
        "consensus_facts": ["Fact 1", "Fact 2"],
        "disagreements": [
            {"topic": "casualty count", "positions": {"Reuters": "14", "Fox News": "20"}}
        ] if disagreements else [],
        "framing_analysis": {
            f"Outlet{i}": f"framing {i}" for i in range(framing_outlets)
        },
        "missing_context": ["Context 1", "Context 2"] if missing_context else [],
        "suggested_post_type": post_type,
        "confidence": confidence,
    }
    dossier = {
        "story_id": "2026-04-17-test-story-abc123",
        "headline_seed": "Hungary's PM-elect Peter Magyar sworn in amid protests",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "articles": [
            {"outlet": "Reuters", "url": "https://reuters.com/article1", "title": "Article 1",
             "body": "body", "fetched_at": datetime.now(timezone.utc).isoformat()},
            {"outlet": "The New York Times", "url": "https://nytimes.com/article2", "title": "Article 2",
             "body": "body", "fetched_at": datetime.now(timezone.utc).isoformat()},
            {"outlet": "The Washington Post", "url": "https://washingtonpost.com/article3", "title": "Article 3",
             "body": "body", "fetched_at": datetime.now(timezone.utc).isoformat()},
            {"outlet": "Fox News", "url": "https://foxnews.com/article4", "title": "Article 4",
             "body": "body", "fetched_at": datetime.now(timezone.utc).isoformat()},
        ],
    }
    return {"brief": brief, "dossier": dossier}


# ---------------------------------------------------------------------------
# Meta angle scoring
# ---------------------------------------------------------------------------

class TestHasMeaningfulMetaAngle:
    def test_high_quality_dossier_passes(self, bot):
        brief = {
            "disagreements": [{"topic": "x", "positions": {}}],
            "framing_analysis": {"A": "a", "B": "b", "C": "c"},
            "missing_context": ["ctx1"],
            "suggested_post_type": "META",
            "confidence": 0.70,
        }
        assert bot._has_meaningful_meta_angle(brief) is True

    def test_empty_brief_fails(self, bot):
        brief = {
            "disagreements": [],
            "framing_analysis": {},
            "missing_context": [],
            "suggested_post_type": "BULLETIN",
            "confidence": 0.30,
        }
        assert bot._has_meaningful_meta_angle(brief) is False

    def test_disagreements_alone_scores_2(self, bot):
        brief = {
            "disagreements": [{"topic": "x"}],
            "framing_analysis": {"A": "a"},
            "missing_context": [],
            "suggested_post_type": "REPORT",
            "confidence": 0.40,
        }
        # score = 2 (disagreements), below default threshold of 3
        assert bot._has_meaningful_meta_angle(brief) is False

    def test_disagreements_plus_confidence_scores_3(self, bot):
        brief = {
            "disagreements": [{"topic": "x"}],
            "framing_analysis": {"A": "a"},
            "missing_context": [],
            "suggested_post_type": "REPORT",
            "confidence": 0.65,
        }
        # score = 2 (disagreements) + 1 (confidence) = 3
        assert bot._has_meaningful_meta_angle(brief) is True

    def test_meta_post_type_scores_3(self, bot):
        brief = {
            "disagreements": [],
            "framing_analysis": {},
            "missing_context": [],
            "suggested_post_type": "META",
            "confidence": 0.40,
        }
        # score = 3 (META)
        assert bot._has_meaningful_meta_angle(brief) is True

    def test_missing_context_caps_at_3(self, bot):
        brief = {
            "disagreements": [],
            "framing_analysis": {},
            "missing_context": ["a", "b", "c", "d", "e"],
            "suggested_post_type": "REPORT",
            "confidence": 0.40,
        }
        # score = 3 (capped missing_context)
        assert bot._has_meaningful_meta_angle(brief) is True

    def test_framing_with_3_outlets_scores_2(self, bot):
        brief = {
            "disagreements": [],
            "framing_analysis": {"A": "a", "B": "b", "C": "c"},
            "missing_context": [],
            "suggested_post_type": "REPORT",
            "confidence": 0.65,
        }
        # score = 2 (framing) + 1 (confidence) = 3
        assert bot._has_meaningful_meta_angle(brief) is True


# ---------------------------------------------------------------------------
# Tweet matching
# ---------------------------------------------------------------------------

class TestScoreTweetMatch:
    def test_shared_nouns_score(self, bot):
        score = bot._score_tweet_match(
            "Hungary's Magyar faces protests after swearing in",
            "Hungary's PM-elect Peter Magyar sworn in",
            []
        )
        # "hungary" and "magyar" shared → 2 * 0.5 = 1.0
        assert score >= 1.0

    def test_no_shared_nouns(self, bot):
        score = bot._score_tweet_match(
            "Stock market drops 500 points",
            "Hungary's PM-elect Peter Magyar sworn in",
            []
        )
        assert score == 0.0

    def test_url_domain_match_adds_score(self, bot):
        score = bot._score_tweet_match(
            "Breaking news from reuters.com about politics",
            "Some headline with no shared nouns",
            ["https://reuters.com/article"]
        )
        assert score >= 1.0

    def test_combined_scoring(self, bot):
        score = bot._score_tweet_match(
            "Hungary's Magyar in reuters.com report",
            "Hungary's PM-elect Peter Magyar sworn in",
            ["https://reuters.com/article"]
        )
        # nouns + URL domain
        assert score >= 2.0


class TestFindOutletTweet:
    def test_returns_best_match(self, bot):
        tweet = Mock()
        tweet.id = "tw1"
        tweet.text = "Hungary's Magyar faces protests after inauguration"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "Reuters",
            "Hungary's PM-elect Peter Magyar sworn in amid protests",
            ["https://reuters.com/article"]
        )

        assert result is not None
        assert result['tweet_id'] == "tw1"

    def test_returns_none_when_no_results(self, bot):
        resp = Mock()
        resp.data = None
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet("Reuters", "Some headline", [])

        assert result is None

    def test_returns_none_when_score_too_low(self, bot):
        tweet = Mock()
        tweet.id = "tw1"
        tweet.text = "Completely unrelated tweet about cooking"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "Reuters",
            "Hungary's PM-elect Peter Magyar sworn in",
            []
        )

        assert result is None

    def test_returns_none_on_api_error(self, bot):
        bot.bot.client.search_recent_tweets.side_effect = Exception("API down")

        result = bot._find_outlet_tweet("Reuters", "Some headline", [])

        assert result is None

    def test_query_uses_or_of_top_2_nouns(self, bot):
        """Regression for the French-peacekeeper miss: the AND-of-3-nouns
        query required outlet tweets to contain every one of the headline's
        longest proper nouns, which most wire-style tweets don't. Now the
        top-2 longest nouns are OR-ed so partial-subset tweets still hit."""
        resp = Mock()
        resp.data = None
        bot.bot.client.search_recent_tweets.return_value = resp

        bot._find_outlet_tweet(
            "BBCWorld",
            "A French soldier serving with the UN peacekeeping mission in "
            "Lebanon was killed in an attack that UNIFIL and French "
            "officials said was carried out by Hezbollah",
            [],
        )

        actual_query = bot.bot.client.search_recent_tweets.call_args.kwargs["query"]
        # Top 2 longest proper nouns from that headline: hezbollah (9),
        # lebanon (7). Both must appear inside an OR group.
        assert "from:BBCWorld" in actual_query
        assert "(hezbollah OR lebanon)" in actual_query or \
               "(lebanon OR hezbollah)" in actual_query
        assert "-is:retweet" in actual_query

    def test_matches_partial_overlap_tweet(self, bot):
        """Under the new OR query + 1.0 score floor, a tweet that shares
        2 of the headline's 5 proper nouns should still match (2 * 0.5 =
        1.0 meets the threshold). Previously the AND query would have
        made this unreachable."""
        tweet = Mock()
        tweet.id = "tw-bbc-1"
        # Outlet tweet has only 2 of the 5 headline proper nouns:
        # lebanon, hezbollah. No UNIFIL, no French, no UN.
        tweet.text = "UN peacekeeper killed in Lebanon — France blames Hezbollah"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "BBCWorld",
            "A French soldier serving with the UN peacekeeping mission in "
            "Lebanon was killed in an attack that UNIFIL and French "
            "officials said was carried out by Hezbollah",
            [],
        )

        assert result is not None, \
            "partial-overlap outlet tweet should now match (shared: france, un, lebanon, hezbollah)"
        assert result["tweet_id"] == "tw-bbc-1"

    def test_single_shared_noun_rejected(self, bot):
        """Score threshold 1.0 means a single shared proper noun (0.5) with
        no URL-domain match is below threshold. Without this guard, the
        broader OR query would accept false positives like unrelated
        same-region tweets."""
        tweet = Mock()
        tweet.id = "tw-loose"
        tweet.text = "Hezbollah leader gives speech about economy"  # only "hezbollah"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "BBCWorld",
            "A French soldier serving with the UN peacekeeping mission in "
            "Lebanon was killed in an attack that UNIFIL and French "
            "officials said was carried out by Hezbollah",
            [],
        )

        assert result is None, "single-noun match without URL should be rejected"

    def test_single_noun_plus_url_match_accepted(self, bot):
        """One shared proper noun (0.5) + URL-domain match (1.0) = 1.5 ≥ 1.0
        → accepted. This path preserves the 'the outlet linked to an
        article we already have in the dossier' signal."""
        tweet = Mock()
        tweet.id = "tw-urlhit"
        # Shares only 'hezbollah' but links to a dossier article:
        tweet.text = "Hezbollah statement today: https://reuters.com/article/xyz"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "BBCWorld",
            "A French soldier serving with the UN peacekeeping mission in "
            "Lebanon was killed in an attack that UNIFIL and French "
            "officials said was carried out by Hezbollah",
            ["https://reuters.com/article/xyz"],
        )

        assert result is not None
        assert result["tweet_id"] == "tw-urlhit"

    def test_return_dict_includes_tweet_url(self, bot):
        """Result dict must include a clickable tweet URL for log/history
        traceability. Previously only tweet_id was returned, which forced
        anyone debugging a miss to manually construct the URL."""
        tweet = Mock()
        tweet.id = "123456789"
        tweet.text = "Hungary's Magyar faces protests"
        tweet.reply_settings = "everyone"
        resp = Mock()
        resp.data = [tweet]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "Reuters",
            "Hungary's PM-elect Peter Magyar sworn in amid protests",
            [],
        )

        assert result is not None
        assert result["tweet_url"] == "https://x.com/Reuters/status/123456789"

    def test_skips_reply_restricted_tweets(self, bot):
        """Tweets with reply_settings != 'everyone' ('following',
        'mentionedUsers', 'subscribers') are skipped before scoring so
        we don't burn a doomed API POST. If all candidates are restricted,
        we return None."""
        # One restricted, one unrestricted — should pick the unrestricted
        # even though the restricted one has a slightly higher text match.
        restricted = Mock()
        restricted.id = "tw-restricted"
        restricted.text = "Hungary's Magyar Peter protests inauguration"
        restricted.reply_settings = "following"

        unrestricted = Mock()
        unrestricted.id = "tw-open"
        unrestricted.text = "Hungary's Magyar protests"
        unrestricted.reply_settings = "everyone"

        resp = Mock()
        resp.data = [restricted, unrestricted]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "Reuters",
            "Hungary's PM-elect Peter Magyar sworn in amid protests",
            [],
        )

        assert result is not None
        assert result["tweet_id"] == "tw-open", \
            "should skip the reply-restricted tweet and return the open one"

    def test_all_restricted_returns_none(self, bot):
        """If every candidate is reply-restricted, return None so the
        caller can try the next outlet."""
        t1 = Mock()
        t1.id = "r1"
        t1.text = "Hungary's Magyar Peter protests"
        t1.reply_settings = "following"
        t2 = Mock()
        t2.id = "r2"
        t2.text = "Magyar sworn in Hungary"
        t2.reply_settings = "mentionedUsers"

        resp = Mock()
        resp.data = [t1, t2]
        bot.bot.client.search_recent_tweets.return_value = resp

        result = bot._find_outlet_tweet(
            "Reuters",
            "Hungary's PM-elect Peter Magyar sworn in amid protests",
            [],
        )
        assert result is None


# ---------------------------------------------------------------------------
# Reply composition
# ---------------------------------------------------------------------------

class TestComposeReply:
    def test_disagreements_template(self, bot):
        brief = {"disagreements": [{"topic": "x"}], "missing_context": [], "framing_analysis": {}}
        reply = bot._compose_reply(brief, "https://mewscast.us/dossiers/test.html", 5)

        assert "https://mewscast.us/dossiers/test.html" in reply
        assert len(reply) <= 280

    def test_missing_context_template(self, bot):
        brief = {"disagreements": [], "missing_context": ["ctx"], "framing_analysis": {}}
        reply = bot._compose_reply(brief, "https://mewscast.us/dossiers/test.html", 4)

        assert "https://mewscast.us/dossiers/test.html" in reply
        assert len(reply) <= 280

    def test_framing_template(self, bot):
        brief = {
            "disagreements": [],
            "missing_context": [],
            "framing_analysis": {"A": "a", "B": "b", "C": "c"},
        }
        reply = bot._compose_reply(brief, "https://mewscast.us/dossiers/test.html", 3)

        assert "https://mewscast.us/dossiers/test.html" in reply
        assert len(reply) <= 280

    def test_fallback_template(self, bot):
        brief = {"disagreements": [], "missing_context": [], "framing_analysis": {}}
        reply = bot._compose_reply(brief, "https://mewscast.us/dossiers/test.html", 5)

        assert "https://mewscast.us/dossiers/test.html" in reply
        assert len(reply) <= 280

    def test_all_templates_under_280_chars(self, bot):
        """Verify all template variants stay under limit with a realistic URL."""
        url = "https://mewscast.us/dossiers/2026-04-17-hungary-pm-elect-peter-magyar-78f7255ac9.html"
        for i in range(20):  # Random sampling
            for brief_variant in [
                {"disagreements": [{"topic": "x"}], "missing_context": [], "framing_analysis": {}},
                {"disagreements": [], "missing_context": ["ctx"], "framing_analysis": {}},
                {"disagreements": [], "missing_context": [], "framing_analysis": {"A": "a", "B": "b", "C": "c"}},
                {"disagreements": [], "missing_context": [], "framing_analysis": {}},
            ]:
                reply = bot._compose_reply(brief_variant, url, 8)
                assert len(reply) <= 280, f"Reply too long ({len(reply)}): {reply}"


# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

class TestDailyReplyLimit:
    def test_under_limit_returns_true(self, bot):
        assert bot._check_daily_reply_limit() is True

    def test_at_limit_returns_false(self, bot):
        now = datetime.now(timezone.utc)
        bot.reply_history['replies'] = [
            {"timestamp": now.isoformat(), "dossier_id": "a"},
            {"timestamp": now.isoformat(), "dossier_id": "b"},
        ]
        assert bot._check_daily_reply_limit() is False

    def test_old_replies_dont_count(self, bot):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
        bot.reply_history['replies'] = [
            {"timestamp": yesterday.isoformat(), "dossier_id": "a"},
            {"timestamp": yesterday.isoformat(), "dossier_id": "b"},
        ]
        assert bot._check_daily_reply_limit() is True


class TestPerOutletCooldown:
    def test_no_recent_reply_returns_true(self, bot):
        assert bot._check_per_outlet_cooldown("Reuters") is True

    def test_recent_reply_returns_false(self, bot):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        bot.reply_history['replies'] = [
            {"outlet_handle": "Reuters", "timestamp": recent.isoformat()},
        ]
        assert bot._check_per_outlet_cooldown("Reuters") is False

    def test_old_reply_returns_true(self, bot):
        old = datetime.now(timezone.utc) - timedelta(hours=80)
        bot.reply_history['replies'] = [
            {"outlet_handle": "Reuters", "timestamp": old.isoformat()},
        ]
        assert bot._check_per_outlet_cooldown("Reuters") is True

    def test_different_outlet_returns_true(self, bot):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        bot.reply_history['replies'] = [
            {"outlet_handle": "nytimes", "timestamp": recent.isoformat()},
        ]
        assert bot._check_per_outlet_cooldown("Reuters") is True


class TestStoryReplyTracking:
    def test_story_reply_count_zero(self, bot):
        assert bot._story_reply_count("new-dossier-id") == 0

    def test_story_reply_count_tracks(self, bot):
        bot.reply_history['replies'] = [
            {"dossier_id": "story1", "outlet_handle": "Reuters", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"dossier_id": "story1", "outlet_handle": "nytimes", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"dossier_id": "story2", "outlet_handle": "Reuters", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        assert bot._story_reply_count("story1") == 2
        assert bot._story_reply_count("story2") == 1

    def test_is_story_completed(self, bot):
        bot.reply_history['replies'] = [
            {"dossier_id": "done", "outlet_handle": f"outlet{i}", "timestamp": datetime.now(timezone.utc).isoformat()}
            for i in range(3)
        ]
        assert bot._is_story_completed("done") is True
        assert bot._is_story_completed("new") is False

    def test_outlets_already_replied(self, bot):
        bot.reply_history['replies'] = [
            {"dossier_id": "story1", "outlet_handle": "Reuters", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"dossier_id": "story1", "outlet_handle": "nytimes", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        replied = bot._outlets_already_replied("story1")
        assert "Reuters" in replied
        assert "nytimes" in replied
        assert "AP" not in replied


# ---------------------------------------------------------------------------
# History cleanup
# ---------------------------------------------------------------------------

class TestCleanupHistory:
    def test_skips_if_recent(self, bot):
        bot.reply_history['last_cleanup'] = datetime.now(timezone.utc).isoformat()
        bot.reply_history['replies'] = [
            {"timestamp": "2000-01-01T00:00:00+00:00", "dossier_id": "old"},
        ]
        bot._cleanup_old_history()
        # Old entry survives because cleanup ran recently
        assert len(bot.reply_history['replies']) == 1

    def test_removes_old_entries(self, bot):
        bot.reply_history['last_cleanup'] = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        bot.reply_history['replies'] = [
            {"timestamp": old, "dossier_id": "old"},
            {"timestamp": recent, "dossier_id": "recent"},
        ]
        bot._cleanup_old_history()
        assert len(bot.reply_history['replies']) == 1
        assert bot.reply_history['replies'][0]['dossier_id'] == 'recent'


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

class TestGetRecentJournalismPosts:
    def _call_with_posts(self, bot, tmp_path, posts, hours=8):
        """Write posts_history.json to tmp_path and call the method with patched path."""
        posts_file = tmp_path / "posts_history.json"
        posts_file.write_text(json.dumps({"posts": posts}))
        with patch.object(Path, '__truediv__', side_effect=lambda self, other:
                          tmp_path / other if other == "posts_history.json" else Path.__truediv__(self, other)):
            # Simpler: just inject the data directly
            pass
        # Cleanest approach: read the file in test and filter same way the method does
        # But we want to test the actual method. Patch json.load instead.
        with patch('src.outlet_reply_bot.json') as mock_json, \
             patch('src.outlet_reply_bot.open', create=True):
            mock_json.load.return_value = {"posts": posts}
            return bot._get_recent_journalism_posts(hours=hours)

    def test_returns_recent_journalism_posts(self, bot, tmp_path):
        result = self._call_with_posts(bot, tmp_path, [
            _make_post(dossier_id="recent", hours_ago=2),
            _make_post(dossier_id="old", hours_ago=20),
            {"timestamp": datetime.now(timezone.utc).isoformat(), "post_pipeline": "legacy"},
        ])

        assert len(result) == 1
        assert result[0]['dossier_id'] == 'recent'

    def test_excludes_legacy_pipeline(self, bot, tmp_path):
        result = self._call_with_posts(bot, tmp_path, [
            {"timestamp": datetime.now(timezone.utc).isoformat(),
             "post_pipeline": "legacy", "dossier_id": "x"},
        ])
        assert len(result) == 0

    def test_excludes_posts_without_dossier_id(self, bot, tmp_path):
        result = self._call_with_posts(bot, tmp_path, [
            {"timestamp": datetime.now(timezone.utc).isoformat(),
             "post_pipeline": "journalism", "dossier_id": None},
        ])
        assert len(result) == 0

    def test_returns_most_recent_first(self, bot, tmp_path):
        result = self._call_with_posts(bot, tmp_path, [
            _make_post(dossier_id="older", hours_ago=5),
            _make_post(dossier_id="newer", hours_ago=1),
        ])
        assert len(result) == 2
        assert result[0]['dossier_id'] == 'newer'
        assert result[1]['dossier_id'] == 'older'

    def test_empty_history_returns_empty(self, bot, tmp_path):
        result = self._call_with_posts(bot, tmp_path, [])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# run_reply_cycle orchestration
# ---------------------------------------------------------------------------

class TestRunReplyCycle:
    def test_aborts_when_disabled(self, bot):
        bot.config['enabled'] = False
        assert bot.run_reply_cycle() is False

    def test_aborts_when_daily_limit_reached(self, bot):
        now = datetime.now(timezone.utc)
        bot.reply_history['replies'] = [
            {"timestamp": now.isoformat(), "dossier_id": "a"},
            {"timestamp": now.isoformat(), "dossier_id": "b"},
        ]
        assert bot.run_reply_cycle() is False

    def test_aborts_when_no_posts(self, bot):
        with patch.object(bot, '_get_recent_journalism_posts', return_value=[]):
            assert bot.run_reply_cycle() is False

    def test_skips_completed_story(self, bot):
        post = _make_post(dossier_id="already-done")
        bot.reply_history['replies'] = [
            {"dossier_id": "already-done", "outlet_handle": f"outlet{i}", "timestamp": datetime.now(timezone.utc).isoformat()}
            for i in range(3)  # 3 replies = completed
        ]
        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]):
            assert bot.run_reply_cycle() is False

    def test_skips_low_meta_angle(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data(
            disagreements=False, missing_context=False,
            framing_outlets=1, confidence=0.30
        )
        bot.dossier_store.read_raw.return_value = dossier_data

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]):
            assert bot.run_reply_cycle() is False

    def test_skips_non_priority_outlets(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        # Replace articles with only Fox News (not in priority list)
        dossier_data['dossier']['articles'] = [
            {"outlet": "Fox News", "url": "https://foxnews.com/art", "title": "T",
             "body": "b", "fetched_at": datetime.now(timezone.utc).isoformat()},
        ]
        bot.dossier_store.read_raw.return_value = dossier_data

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]):
            assert bot.run_reply_cycle() is False

    def test_successful_reply_cycle(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data

        tweet_match = {"tweet_id": "outlet_tw1", "text": "Hungary story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            result = bot.run_reply_cycle()

        assert result is True
        bot.bot.reply_to_tweet.assert_called_once()
        assert len(bot.reply_history['replies']) == 1
        assert bot.reply_history['replies'][0]['outlet_tweet_id'] == "outlet_tw1"

    def test_follows_outlet_before_replying(self, bot):
        """Experiment: we attempt to follow the outlet just before posting
        the reply. Follow is best-effort; it shouldn't block the reply."""
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data

        tweet_match = {"tweet_id": "tw1", "text": "x", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            bot.run_reply_cycle()

        bot.bot.follow_user_by_handle.assert_called_once()
        # And the reply still went out
        bot.bot.reply_to_tweet.assert_called_once()

    def test_reply_still_attempted_when_follow_raises(self, bot):
        """If follow_user_by_handle raises, the reply attempt should still
        proceed — follow is non-fatal, reply is the goal."""
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data

        tweet_match = {"tweet_id": "tw1", "text": "x", "score": 1.5}
        bot.bot.follow_user_by_handle.side_effect = Exception("follow boom")

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            result = bot.run_reply_cycle()

        assert result is True
        bot.bot.reply_to_tweet.assert_called_once()

    def test_dry_run_does_not_post(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data

        tweet_match = {"tweet_id": "outlet_tw1", "text": "Hungary story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            result = bot.run_reply_cycle(dry_run=True)

        assert result is True
        bot.bot.reply_to_tweet.assert_not_called()

    def test_continues_to_next_outlet_on_no_match(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data

        # First outlet (Reuters) no match, second (NYT) matches
        call_count = [0]
        def mock_find(handle, headline, urls):
            call_count[0] += 1
            if handle == "Reuters":
                return None
            return {"tweet_id": "nyt_tw1", "text": "Hungary story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', side_effect=mock_find):
            result = bot.run_reply_cycle()

        assert result is True
        assert call_count[0] >= 2

    def test_stops_after_one_successful_reply(self, bot):
        post1 = _make_post(dossier_id="story1")
        post2 = _make_post(dossier_id="story2")

        dossier1 = _make_dossier_data()
        dossier1['brief']['story_id'] = 'story1'
        dossier2 = _make_dossier_data()
        dossier2['brief']['story_id'] = 'story2'

        def mock_read(story_id):
            if story_id == "story1":
                return dossier1
            return dossier2

        bot.dossier_store.read_raw.side_effect = mock_read

        tweet_match = {"tweet_id": "tw1", "text": "Story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post1, post2]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            bot.run_reply_cycle()

        # Should only reply once (to the first post)
        assert bot.bot.reply_to_tweet.call_count == 1

    def test_reply_failure_continues(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data
        bot.bot.reply_to_tweet.return_value = None  # Reply fails

        tweet_match = {"tweet_id": "tw1", "text": "Story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            result = bot.run_reply_cycle()

        # All outlets tried but none succeeded
        assert result is False

    def test_api_exception_during_reply_is_handled(self, bot):
        post = _make_post()
        dossier_data = _make_dossier_data()
        bot.dossier_store.read_raw.return_value = dossier_data
        bot.bot.reply_to_tweet.side_effect = Exception("API error")

        tweet_match = {"tweet_id": "tw1", "text": "Story", "score": 1.5}

        with patch.object(bot, '_get_recent_journalism_posts', return_value=[post]), \
             patch.object(bot, '_find_outlet_tweet', return_value=tweet_match):
            result = bot.run_reply_cycle()

        assert result is False  # Graceful failure
