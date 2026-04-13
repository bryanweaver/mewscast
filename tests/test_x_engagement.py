"""
Tests for XEngagementBot (src/x_engagement_bot.py).

Covers:
  - History loading and saving
  - 90-day history cleanup (weekly cadence)
  - Follow ratio safety check
  - Account filtering (followers, bio, verified, ratio)
  - Deduplication — skip already-followed accounts / already-liked tweets
  - find_and_follow_cat_account: success and edge cases
  - find_and_like_cat_post: success, auto-follow, bonus-follow
  - run_engagement_cycle: orchestration and summary
  - Error handling for API failures
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
# Pre-import module mocking — inject stubs before real imports
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

from src.x_engagement_bot import XEngagementBot  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers for building mock API objects
# ---------------------------------------------------------------------------

def _make_user(
    user_id="u1",
    username="catperson",
    followers_count=500,
    following_count=200,
    description="I love my cat Whiskers",
    verified=False,
):
    user = Mock()
    user.id = user_id
    user.username = username
    user.description = description
    user.verified = verified
    user.public_metrics = {
        "followers_count": followers_count,
        "following_count": following_count,
    }
    return user


def _make_tweet(
    tweet_id="t1",
    author_id="u1",
    like_count=50,
    retweet_count=10,
    text="Look at my adorable cat!",
    created_at=None,
):
    tweet = Mock()
    tweet.id = tweet_id
    tweet.author_id = author_id
    tweet.text = text
    tweet.public_metrics = {
        "like_count": like_count,
        "retweet_count": retweet_count,
    }
    tweet.created_at = created_at or datetime.now(timezone.utc)
    return tweet


def _make_search_response(tweets=None, users=None):
    """Build a mock tweepy search response with .data and .includes['users']."""
    resp = Mock()
    resp.data = tweets or []
    resp.includes = {"users": users or []}
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_history():
    return {
        "followed_users": [],
        "liked_tweets": [],
        "last_cleanup": datetime.now().isoformat(),
    }


@pytest.fixture
def bot(fresh_history, tmp_path):
    """XEngagementBot with a mocked TwitterBot and isolated history file."""
    with patch.dict(os.environ, {
        "X_API_KEY": "k",
        "X_API_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
        "X_BEARER_TOKEN": "b",
    }):
        b = XEngagementBot()
        b.bot = Mock()
        b.bot.client = Mock()

        history_path = tmp_path / "x_engagement_history.json"
        history_path.write_text(json.dumps(fresh_history))
        b.engagement_log_path = history_path
        b.engagement_history = fresh_history

        return b


# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_returns_empty_structure_when_no_file(self, tmp_path):
        with patch.dict(os.environ, {
            "X_API_KEY": "k", "X_API_SECRET": "s",
            "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts",
            "X_BEARER_TOKEN": "b",
        }):
            b = XEngagementBot()
            b.engagement_log_path = tmp_path / "nonexistent.json"
            history = b._load_engagement_history()

        assert history["followed_users"] == []
        assert history["liked_tweets"] == []
        assert "last_cleanup" in history

    def test_loads_existing_history(self, tmp_path):
        data = {
            "followed_users": [{"user_id": "u1", "username": "cat1", "timestamp": "2026-01-01T00:00:00"}],
            "liked_tweets": [],
            "last_cleanup": "2026-01-01T00:00:00",
        }
        history_path = tmp_path / "x_engagement_history.json"
        history_path.write_text(json.dumps(data))

        with patch.dict(os.environ, {
            "X_API_KEY": "k", "X_API_SECRET": "s",
            "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts",
            "X_BEARER_TOKEN": "b",
        }):
            b = XEngagementBot()
            b.engagement_log_path = history_path
            history = b._load_engagement_history()

        assert len(history["followed_users"]) == 1
        assert history["followed_users"][0]["username"] == "cat1"


# ---------------------------------------------------------------------------
# History cleanup
# ---------------------------------------------------------------------------

class TestCleanupHistory:
    def test_skips_cleanup_if_recent(self, bot):
        """Cleanup should not run if last cleanup was less than 7 days ago."""
        bot.engagement_history["last_cleanup"] = datetime.now().isoformat()
        bot.engagement_history["followed_users"] = [
            {"user_id": "u1", "username": "old", "timestamp": "2000-01-01T00:00:00"}
        ]
        bot._cleanup_old_history()
        # Old entry should survive because we're within the 7-day window
        assert len(bot.engagement_history["followed_users"]) == 1

    def test_removes_entries_older_than_90_days(self, bot):
        bot.engagement_history["last_cleanup"] = (datetime.now() - timedelta(days=8)).isoformat()
        cutoff = datetime.now() - timedelta(days=91)
        recent = datetime.now() - timedelta(days=10)

        bot.engagement_history["followed_users"] = [
            {"user_id": "old", "username": "old_cat", "timestamp": cutoff.isoformat()},
            {"user_id": "new", "username": "new_cat", "timestamp": recent.isoformat()},
        ]
        bot.engagement_history["liked_tweets"] = [
            {"tweet_id": "told", "author": "x", "timestamp": cutoff.isoformat()},
        ]

        bot._cleanup_old_history()

        assert len(bot.engagement_history["followed_users"]) == 1
        assert bot.engagement_history["followed_users"][0]["user_id"] == "new"
        assert len(bot.engagement_history["liked_tweets"]) == 0


# ---------------------------------------------------------------------------
# Follow ratio safety check
# ---------------------------------------------------------------------------

class TestFollowRatioSafe:
    def _mock_me(self, bot, followers, following):
        me_data = Mock()
        me_data.public_metrics = {
            "followers_count": followers,
            "following_count": following,
        }
        resp = Mock()
        resp.data = me_data
        bot.bot.client.get_me.return_value = resp

    def test_healthy_ratio_returns_true(self, bot):
        self._mock_me(bot, followers=100, following=200)
        assert bot._check_follow_ratio_safe() is True

    def test_high_ratio_returns_false(self, bot):
        self._mock_me(bot, followers=100, following=300)  # ratio = 3.0 > 2.5
        assert bot._check_follow_ratio_safe() is False

    def test_zero_followers_below_bootstrap_limit_returns_true(self, bot):
        self._mock_me(bot, followers=0, following=10)
        assert bot._check_follow_ratio_safe() is True

    def test_zero_followers_at_bootstrap_limit_returns_false(self, bot):
        self._mock_me(bot, followers=0, following=50)
        assert bot._check_follow_ratio_safe() is False

    def test_api_error_returns_false(self, bot):
        bot.bot.client.get_me.side_effect = Exception("API error")
        assert bot._check_follow_ratio_safe() is False

    def test_no_data_returns_false(self, bot):
        resp = Mock()
        resp.data = None
        bot.bot.client.get_me.return_value = resp
        assert bot._check_follow_ratio_safe() is False


# ---------------------------------------------------------------------------
# _follow_account helper
# ---------------------------------------------------------------------------

class TestFollowAccount:
    def test_successful_follow_is_recorded(self, bot):
        result = bot._follow_account("u99", "newcat")

        assert result is True
        bot.bot.client.follow_user.assert_called_once_with(target_user_id="u99")
        assert any(e["user_id"] == "u99" for e in bot.engagement_history["followed_users"])

    def test_api_error_returns_false(self, bot):
        bot.bot.client.follow_user.side_effect = Exception("Rate limited")
        result = bot._follow_account("u99", "newcat")

        assert result is False
        assert bot.engagement_history["followed_users"] == []


# ---------------------------------------------------------------------------
# find_and_follow_cat_account
# ---------------------------------------------------------------------------

class TestFindAndFollowCatAccount:
    def _mock_ratio_ok(self, bot):
        me_data = Mock()
        me_data.public_metrics = {"followers_count": 200, "following_count": 100}
        resp = Mock()
        resp.data = me_data
        bot.bot.client.get_me.return_value = resp

    def test_follows_qualifying_account(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=500, following_count=100, description="cat lover")
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is True
        bot.bot.client.follow_user.assert_called_once_with(target_user_id=user.id)

    def test_skips_already_followed(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=500, description="cat lover")
        tweet = _make_tweet(author_id=user.id)
        bot.engagement_history["followed_users"] = [
            {"user_id": user.id, "username": user.username, "timestamp": datetime.now().isoformat()}
        ]
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False
        bot.bot.client.follow_user.assert_not_called()

    def test_skips_too_few_followers(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=50, description="cat lover")  # < 100
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_skips_too_many_followers(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=200000, description="cat lover")  # > 100K
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_skips_verified_account(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=500, description="cat lover", verified=True)
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_skips_non_cat_bio(self, bot):
        self._mock_ratio_ok(bot)
        user = _make_user(followers_count=500, description="I love dogs and birds")
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_skips_follow_spammer(self, bot):
        self._mock_ratio_ok(bot)
        # following/followers = 3000/500 = 6 > 5
        user = _make_user(followers_count=500, following_count=3000, description="cat lover")
        tweet = _make_tweet(author_id=user.id)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_skips_when_ratio_check_fails(self, bot):
        # Ratio too high — don't follow anyone
        me_data = Mock()
        me_data.public_metrics = {"followers_count": 100, "following_count": 400}
        resp = Mock()
        resp.data = me_data
        bot.bot.client.get_me.return_value = resp

        result = bot.find_and_follow_cat_account()

        assert result is False
        bot.bot.client.search_recent_tweets.assert_not_called()

    def test_returns_false_when_no_search_results(self, bot):
        self._mock_ratio_ok(bot)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(tweets=None)

        result = bot.find_and_follow_cat_account()

        assert result is False

    def test_api_exception_returns_false(self, bot):
        self._mock_ratio_ok(bot)
        bot.bot.client.search_recent_tweets.side_effect = Exception("API down")

        result = bot.find_and_follow_cat_account()

        assert result is False


# ---------------------------------------------------------------------------
# find_and_like_cat_post
# ---------------------------------------------------------------------------

class TestFindAndLikeCatPost:
    def _mock_ratio_ok(self, bot):
        me_data = Mock()
        me_data.public_metrics = {"followers_count": 200, "following_count": 100}
        resp = Mock()
        resp.data = me_data
        bot.bot.client.get_me.return_value = resp

    def test_likes_qualifying_post(self, bot):
        user = _make_user()
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post()

        assert result is True
        bot.bot.client.like.assert_called_once_with(tweet_id=tweet.id)
        assert any(e["tweet_id"] == tweet.id for e in bot.engagement_history["liked_tweets"])

    def test_skips_already_liked_tweet(self, bot):
        user = _make_user()
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.engagement_history["liked_tweets"] = [
            {"tweet_id": tweet.id, "author": user.username, "timestamp": datetime.now().isoformat()}
        ]
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_like_cat_post()

        assert result is False
        bot.bot.client.like.assert_not_called()

    def test_skips_post_with_too_few_likes(self, bot):
        user = _make_user()
        tweet = _make_tweet(author_id=user.id, like_count=2)  # < 5
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_like_cat_post()

        assert result is False

    def test_skips_post_with_too_many_likes(self, bot):
        user = _make_user()
        tweet = _make_tweet(author_id=user.id, like_count=15000)  # > 10K
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_like_cat_post()

        assert result is False

    def test_skips_post_older_than_24h(self, bot):
        user = _make_user()
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        tweet = _make_tweet(author_id=user.id, like_count=50, created_at=old_time)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )

        result = bot.find_and_like_cat_post()

        assert result is False

    def test_auto_follows_post_author_when_no_cat_account_found(self, bot):
        """If already_followed_account=False, always follow the post author."""
        user = _make_user(user_id="au1", username="catauthor", followers_count=500, following_count=100)
        tweet = _make_tweet(tweet_id="tw1", author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post(already_followed_account=False)

        assert result is True
        bot.bot.client.follow_user.assert_called_once_with(target_user_id=user.id)

    def test_auto_follow_skipped_when_ratio_high(self, bot):
        """Auto-follow is skipped if the ratio check fails."""
        user = _make_user(user_id="au1", followers_count=500, following_count=100)
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        # Simulate high ratio
        me_data = Mock()
        me_data.public_metrics = {"followers_count": 100, "following_count": 400}
        resp = Mock()
        resp.data = me_data
        bot.bot.client.get_me.return_value = resp

        result = bot.find_and_like_cat_post(already_followed_account=False)

        assert result is True  # Like still succeeds
        bot.bot.client.follow_user.assert_not_called()

    def test_bonus_follow_skipped_for_out_of_range_followers(self, bot):
        """With already_followed_account=True, skip bonus follow if follower count out of range."""
        user = _make_user(user_id="au1", followers_count=50, following_count=10)  # < 100
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post(already_followed_account=True)

        assert result is True
        bot.bot.client.follow_user.assert_not_called()

    def test_bonus_follow_skipped_for_follow_spammer(self, bot):
        """With already_followed_account=True, skip bonus follow if follow ratio too high."""
        user = _make_user(user_id="au1", followers_count=500, following_count=3000)
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post(already_followed_account=True)

        assert result is True
        bot.bot.client.follow_user.assert_not_called()

    def test_bonus_follow_succeeds_for_qualifying_author(self, bot):
        """With already_followed_account=True, follow post author if they qualify."""
        user = _make_user(user_id="au1", followers_count=500, following_count=100)
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post(already_followed_account=True)

        assert result is True
        bot.bot.client.follow_user.assert_called_once_with(target_user_id=user.id)

    def test_does_not_auto_follow_already_followed_author(self, bot):
        user = _make_user(user_id="au1", followers_count=500, following_count=100)
        tweet = _make_tweet(author_id=user.id, like_count=50)
        bot.engagement_history["followed_users"] = [
            {"user_id": user.id, "username": user.username, "timestamp": datetime.now().isoformat()}
        ]
        bot.bot.client.search_recent_tweets.return_value = _make_search_response(
            tweets=[tweet], users=[user]
        )
        self._mock_ratio_ok(bot)

        result = bot.find_and_like_cat_post(already_followed_account=False)

        assert result is True
        bot.bot.client.follow_user.assert_not_called()

    def test_api_exception_returns_false(self, bot):
        bot.bot.client.search_recent_tweets.side_effect = Exception("API down")

        result = bot.find_and_like_cat_post()

        assert result is False


# ---------------------------------------------------------------------------
# run_engagement_cycle
# ---------------------------------------------------------------------------

class TestRunEngagementCycle:
    def test_calls_both_follow_and_like(self, bot):
        with patch.object(bot, 'find_and_follow_cat_account', return_value=True) as mock_follow, \
             patch.object(bot, 'find_and_like_cat_post', return_value=True) as mock_like:
            result = bot.run_engagement_cycle()

        assert result is True
        mock_follow.assert_called_once()
        mock_like.assert_called_once_with(already_followed_account=True)

    def test_passes_follow_status_to_like(self, bot):
        """Follow result is forwarded to like so auto-follow logic gets correct context."""
        with patch.object(bot, 'find_and_follow_cat_account', return_value=False), \
             patch.object(bot, 'find_and_like_cat_post', return_value=True) as mock_like:
            bot.run_engagement_cycle()

        mock_like.assert_called_once_with(already_followed_account=False)

    def test_returns_false_when_both_fail(self, bot):
        with patch.object(bot, 'find_and_follow_cat_account', return_value=False), \
             patch.object(bot, 'find_and_like_cat_post', return_value=False):
            result = bot.run_engagement_cycle()

        assert result is False

    def test_continues_after_follow_exception(self, bot):
        """A crash in follow should not prevent the like attempt."""
        with patch.object(bot, 'find_and_follow_cat_account', side_effect=Exception("crash")), \
             patch.object(bot, 'find_and_like_cat_post', return_value=True) as mock_like:
            result = bot.run_engagement_cycle()

        assert result is True
        mock_like.assert_called_once_with(already_followed_account=False)

    def test_continues_after_like_exception(self, bot):
        with patch.object(bot, 'find_and_follow_cat_account', return_value=True), \
             patch.object(bot, 'find_and_like_cat_post', side_effect=Exception("crash")):
            result = bot.run_engagement_cycle()

        assert result is True  # follow_success=True is still returned
