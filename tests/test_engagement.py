#!/usr/bin/env python3
"""
Test suite for engagement bot automation (Twitter/X and Bluesky).

Covers:
  - Engagement target selection and filtering (followers, bios, ratios)
  - History tracking and deduplication (avoiding re-engagement)
  - History cleanup (90-day expiry, weekly cadence)
  - Follow-ratio safety checks (Bluesky-specific)
  - Repost/rescue post logic (Bluesky-specific)
  - Auto-follow and bonus-follow behavior during like cycles
  - Engagement cycle orchestration
  - Error handling for API failures
  - Platform-specific differences between Twitter and Bluesky
"""

import pytest
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open

# ---------------------------------------------------------------------------
# Pre-import module mocking
#
# The source modules use bare imports (e.g. ``from atproto import Client``,
# ``from twitter_bot import TwitterBot``) that would fail in a test
# environment where third-party packages may not be installed or where
# the ``src/`` directory is not the working directory.  We inject mock
# modules into ``sys.modules`` *before* the real imports happen.
# ---------------------------------------------------------------------------

# Ensure project root and src/ are importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_project_root, "src")
for _p in (_project_root, _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Mock 'atproto' so ``from atproto import Client`` succeeds
_mock_atproto = types.ModuleType("atproto")
_mock_atproto.Client = MagicMock
sys.modules.setdefault("atproto", _mock_atproto)

# Mock 'anthropic' so ``from anthropic import Anthropic`` succeeds
_mock_anthropic = types.ModuleType("anthropic")
_mock_anthropic.Anthropic = MagicMock
sys.modules.setdefault("anthropic", _mock_anthropic)

# Mock bare 'content_generator' (imported by twitter_bot.py)
_mock_content_generator = types.ModuleType("content_generator")
_mock_content_generator._truncate_at_sentence = lambda text, max_len=280: text[:max_len]
sys.modules.setdefault("content_generator", _mock_content_generator)

# Mock bare 'twitter_bot' (imported by engagement_bot.py)
_mock_twitter_bot_mod = types.ModuleType("twitter_bot")
_mock_twitter_bot_mod.TwitterBot = MagicMock
sys.modules.setdefault("twitter_bot", _mock_twitter_bot_mod)

# Now we can safely import the source modules
from src.engagement_bot import EngagementBot
from src.bluesky_engagement_bot import BlueskyEngagementBot


# ---------------------------------------------------------------------------
# Helpers for building mock API response objects
# ---------------------------------------------------------------------------

def _make_twitter_user(
    user_id="123",
    username="catperson",
    followers_count=500,
    following_count=200,
    description="I love my cat Whiskers",
    verified=False,
):
    """Return a mock Twitter user object."""
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


def _make_twitter_tweet(
    tweet_id="t1",
    author_id="123",
    like_count=50,
    retweet_count=10,
    text="Look at my adorable cat!",
    created_at=None,
):
    """Return a mock Twitter tweet object."""
    tweet = Mock()
    tweet.id = tweet_id
    tweet.author_id = author_id
    tweet.text = text
    tweet.public_metrics = {
        "like_count": like_count,
        "retweet_count": retweet_count,
    }
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    tweet.created_at = created_at
    return tweet


def _make_bluesky_author(
    did="did:plc:abc123",
    handle="catfan.bsky.social",
    display_name="Cat Fan",
    followers_count=500,
    follows_count=200,
    description="I love cats and kittens",
):
    """Return a mock Bluesky author object."""
    author = Mock()
    author.did = did
    author.handle = handle
    author.display_name = display_name
    author.followers_count = followers_count
    author.follows_count = follows_count
    author.description = description
    return author


def _make_bluesky_post(
    uri="at://did:plc:abc123/app.bsky.feed.post/xyz",
    cid="bafyabc",
    author=None,
    text="Look at my cute cat!",
    like_count=20,
    repost_count=5,
    indexed_at=None,
    has_images=False,
    embed_type="app.bsky.embed.images",
):
    """Return a mock Bluesky post object."""
    if author is None:
        author = _make_bluesky_author()
    if indexed_at is None:
        indexed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    post = Mock()
    post.uri = uri
    post.cid = cid
    post.author = author
    post.like_count = like_count
    post.repost_count = repost_count
    post.indexed_at = indexed_at

    record = Mock()
    record.text = text
    post.record = record

    if has_images:
        embed = Mock()
        embed.py_type = embed_type
        record.embed = embed
    else:
        record.embed = None

    return post


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_history():
    """Return a fresh, empty engagement history dict."""
    return {
        "followed_users": [],
        "liked_tweets": [],
        "last_cleanup": datetime.now().isoformat(),
    }


@pytest.fixture
def empty_bluesky_history():
    """Return a fresh, empty Bluesky engagement history dict."""
    return {
        "followed_users": [],
        "liked_posts": [],
        "reposted_posts": [],
        "last_cleanup": datetime.now().isoformat(),
    }


@pytest.fixture
def twitter_bot(empty_history, tmp_path):
    """
    Create an EngagementBot with mocked TwitterBot and history file.
    The history file is written to a temp directory so tests are isolated.
    """
    with patch.dict(os.environ, {
        "X_API_KEY": "k",
        "X_API_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
        "X_BEARER_TOKEN": "b",
    }):
        mock_client = Mock()
        bot = EngagementBot()
        bot.bot = Mock()
        bot.bot.client = mock_client

        # Redirect history to tmp_path for test isolation
        history_path = tmp_path / "engagement_history.json"
        with open(history_path, "w") as f:
            json.dump(empty_history, f)
        bot.engagement_log_path = history_path
        bot.engagement_history = empty_history

        return bot


@pytest.fixture
def bluesky_bot(empty_bluesky_history, tmp_path):
    """
    Create a BlueskyEngagementBot with mocked atproto Client and history file.
    """
    with patch.dict(os.environ, {
        "BLUESKY_USERNAME": "testcat.bsky.social",
        "BLUESKY_PASSWORD": "secret",
    }):
        with patch("src.bluesky_engagement_bot.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.login.return_value = None
            mock_me = Mock()
            mock_me.did = "did:plc:me123"
            mock_client.me = mock_me

            bot = BlueskyEngagementBot()

            # Redirect history to tmp_path for test isolation
            history_path = tmp_path / "bluesky_engagement_history.json"
            with open(history_path, "w") as f:
                json.dump(empty_bluesky_history, f)
            bot.engagement_log_path = history_path
            bot.engagement_history = empty_bluesky_history

            return bot


# ===================================================================
# TWITTER ENGAGEMENT BOT TESTS
# ===================================================================


class TestTwitterHistoryTracking:
    """Tests for engagement history load/save/cleanup on the Twitter bot."""

    def test_load_empty_history_when_file_missing(self, tmp_path):
        """When the history file does not exist, a default dict is returned."""
        bot = EngagementBot()
        bot.engagement_log_path = tmp_path / "nonexistent.json"
        history = bot._load_engagement_history()

        assert history["followed_users"] == []
        assert history["liked_tweets"] == []
        assert "last_cleanup" in history

    def test_load_existing_history(self, tmp_path):
        """When a history file exists, its data is returned faithfully."""
        data = {
            "followed_users": [{"user_id": "1", "username": "u", "timestamp": "2025-01-01T00:00:00"}],
            "liked_tweets": [{"tweet_id": "t1", "author": "a", "timestamp": "2025-01-01T00:00:00"}],
            "last_cleanup": "2025-01-01T00:00:00",
        }
        path = tmp_path / "history.json"
        path.write_text(json.dumps(data))

        bot = EngagementBot()
        bot.engagement_log_path = path
        history = bot._load_engagement_history()

        assert len(history["followed_users"]) == 1
        assert history["followed_users"][0]["user_id"] == "1"

    def test_save_engagement_history_writes_json(self, twitter_bot):
        """_save_engagement_history persists the current state to disk."""
        twitter_bot.engagement_history["followed_users"].append(
            {"user_id": "999", "username": "newcat", "timestamp": datetime.now().isoformat()}
        )
        twitter_bot._save_engagement_history()

        with open(twitter_bot.engagement_log_path) as f:
            saved = json.load(f)
        assert any(e["user_id"] == "999" for e in saved["followed_users"])

    def test_cleanup_skipped_when_recent(self, twitter_bot):
        """Cleanup should be skipped if last_cleanup was less than 7 days ago."""
        twitter_bot.engagement_history["last_cleanup"] = datetime.now().isoformat()
        twitter_bot.engagement_history["followed_users"].append(
            {"user_id": "old", "username": "old", "timestamp": (datetime.now() - timedelta(days=100)).isoformat()}
        )
        twitter_bot._cleanup_old_history()
        # Old entry should still be there because cleanup was skipped
        assert len(twitter_bot.engagement_history["followed_users"]) == 1

    def test_cleanup_removes_old_entries(self, twitter_bot):
        """Cleanup removes follows and likes older than 90 days."""
        twitter_bot.engagement_history["last_cleanup"] = (
            datetime.now() - timedelta(days=8)
        ).isoformat()
        old_ts = (datetime.now() - timedelta(days=100)).isoformat()
        recent_ts = (datetime.now() - timedelta(days=10)).isoformat()

        twitter_bot.engagement_history["followed_users"] = [
            {"user_id": "old", "username": "old", "timestamp": old_ts},
            {"user_id": "recent", "username": "recent", "timestamp": recent_ts},
        ]
        twitter_bot.engagement_history["liked_tweets"] = [
            {"tweet_id": "old_t", "author": "a", "timestamp": old_ts},
        ]

        twitter_bot._cleanup_old_history()

        assert len(twitter_bot.engagement_history["followed_users"]) == 1
        assert twitter_bot.engagement_history["followed_users"][0]["user_id"] == "recent"
        assert len(twitter_bot.engagement_history["liked_tweets"]) == 0


class TestTwitterTargetSelection:
    """Tests for how the Twitter bot selects accounts and posts."""

    def test_skips_already_followed_users(self, twitter_bot):
        """Users already in history should be excluded from candidates."""
        twitter_bot.engagement_history["followed_users"] = [
            {"user_id": "123", "username": "alreadyfollowed", "timestamp": datetime.now().isoformat()},
        ]

        user = _make_twitter_user(user_id="123", username="alreadyfollowed")
        tweet = _make_twitter_tweet(author_id="123")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_low_follower_accounts(self, twitter_bot):
        """Accounts with fewer than 100 followers should be filtered out."""
        user = _make_twitter_user(user_id="1", followers_count=50)
        tweet = _make_twitter_tweet(author_id="1")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_mega_accounts(self, twitter_bot):
        """Accounts with more than 100K followers should be filtered out."""
        user = _make_twitter_user(user_id="2", followers_count=200_000)
        tweet = _make_twitter_tweet(author_id="2")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_verified_accounts(self, twitter_bot):
        """Verified accounts should be filtered out."""
        user = _make_twitter_user(user_id="3", verified=True)
        tweet = _make_twitter_tweet(author_id="3")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_non_cat_bios(self, twitter_bot):
        """Accounts without cat keywords in bio should be filtered out."""
        user = _make_twitter_user(user_id="4", description="I love dogs and hiking")
        tweet = _make_twitter_tweet(author_id="4")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_follow_spammers(self, twitter_bot):
        """Accounts with follow ratio > 5 should be filtered out."""
        user = _make_twitter_user(
            user_id="5",
            followers_count=200,
            following_count=2000,  # ratio = 10, well above 5
            description="cat lover",
        )
        tweet = _make_twitter_tweet(author_id="5")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False

    def test_successfully_follows_quality_account(self, twitter_bot):
        """A cat-related account meeting all criteria should be followed."""
        user = _make_twitter_user(
            user_id="10",
            username="qualitycat",
            followers_count=500,
            following_count=200,
            description="Cat mom of two tabbies",
            verified=False,
        )
        tweet = _make_twitter_tweet(author_id="10")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response
        twitter_bot.bot.client.follow_user.return_value = None

        result = twitter_bot.find_and_follow_cat_account()
        assert result is True
        twitter_bot.bot.client.follow_user.assert_called_once_with(target_user_id="10")
        assert any(
            e["user_id"] == "10" for e in twitter_bot.engagement_history["followed_users"]
        )

    def test_no_search_results_returns_false(self, twitter_bot):
        """When the search returns no data, the method returns False."""
        response = Mock()
        response.data = None
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        assert twitter_bot.find_and_follow_cat_account() is False


class TestTwitterLikePost:
    """Tests for the Twitter like-post flow."""

    def test_skips_already_liked_tweets(self, twitter_bot):
        """Tweets already in liked history should be skipped."""
        twitter_bot.engagement_history["liked_tweets"] = [
            {"tweet_id": "t1", "author": "a", "timestamp": datetime.now().isoformat()}
        ]

        user = _make_twitter_user(user_id="200")
        tweet = _make_twitter_tweet(tweet_id="t1", author_id="200", like_count=50)

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_low_engagement_posts(self, twitter_bot):
        """Posts with fewer than 5 likes should be filtered out."""
        user = _make_twitter_user(user_id="201")
        tweet = _make_twitter_tweet(tweet_id="t_low", author_id="201", like_count=2)

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_mega_viral_posts(self, twitter_bot):
        """Posts with more than 10K likes should be filtered out."""
        user = _make_twitter_user(user_id="202")
        tweet = _make_twitter_tweet(tweet_id="t_viral", author_id="202", like_count=50_000)

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_old_posts(self, twitter_bot):
        """Posts older than 24 hours should be filtered out."""
        user = _make_twitter_user(user_id="203")
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        tweet = _make_twitter_tweet(
            tweet_id="t_old", author_id="203", like_count=50, created_at=old_time
        )

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        result = twitter_bot.find_and_like_cat_post()
        assert result is False

    def test_successfully_likes_quality_post(self, twitter_bot):
        """A recent post with moderate engagement should be liked."""
        user = _make_twitter_user(user_id="204", username="catperson")
        tweet = _make_twitter_tweet(
            tweet_id="t_good",
            author_id="204",
            like_count=100,
            retweet_count=20,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response
        twitter_bot.bot.client.like.return_value = None

        result = twitter_bot.find_and_like_cat_post()
        assert result is True
        twitter_bot.bot.client.like.assert_called_once_with(tweet_id="t_good")
        assert any(
            e["tweet_id"] == "t_good" for e in twitter_bot.engagement_history["liked_tweets"]
        )


class TestTwitterEngagementCycle:
    """Tests for the top-level Twitter engagement cycle."""

    def test_cycle_calls_follow_and_like(self, twitter_bot):
        """run_engagement_cycle should attempt both follow and like."""
        with patch.object(twitter_bot, "find_and_follow_cat_account", return_value=True) as mock_follow, \
             patch.object(twitter_bot, "find_and_like_cat_post", return_value=True) as mock_like:
            result = twitter_bot.run_engagement_cycle()

        mock_follow.assert_called_once()
        mock_like.assert_called_once()
        assert result is True

    def test_cycle_returns_false_when_both_fail(self, twitter_bot):
        """Cycle returns False when neither follow nor like succeed."""
        with patch.object(twitter_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(twitter_bot, "find_and_like_cat_post", return_value=False):
            result = twitter_bot.run_engagement_cycle()
        assert result is False

    def test_cycle_returns_true_when_only_like_succeeds(self, twitter_bot):
        """Cycle returns True if at least one action succeeds."""
        with patch.object(twitter_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(twitter_bot, "find_and_like_cat_post", return_value=True):
            result = twitter_bot.run_engagement_cycle()
        assert result is True

    def test_cycle_handles_follow_exception(self, twitter_bot):
        """If follow throws, cycle should still attempt like."""
        with patch.object(
            twitter_bot, "find_and_follow_cat_account", side_effect=Exception("API down")
        ), patch.object(twitter_bot, "find_and_like_cat_post", return_value=True) as mock_like:
            result = twitter_bot.run_engagement_cycle()

        mock_like.assert_called_once()
        assert result is True

    def test_cycle_handles_like_exception(self, twitter_bot):
        """If like throws, cycle should still return based on follow result."""
        with patch.object(twitter_bot, "find_and_follow_cat_account", return_value=True), \
             patch.object(
                 twitter_bot, "find_and_like_cat_post", side_effect=Exception("Rate limited")
             ):
            result = twitter_bot.run_engagement_cycle()
        assert result is True


class TestTwitterErrorHandling:
    """Tests for graceful error handling in the Twitter engagement bot."""

    def test_follow_api_error_returns_false(self, twitter_bot):
        """If the search API raises, find_and_follow_cat_account returns False."""
        twitter_bot.bot.client.search_recent_tweets.side_effect = Exception("Network error")
        assert twitter_bot.find_and_follow_cat_account() is False

    def test_like_api_error_returns_false(self, twitter_bot):
        """If the search API raises, find_and_like_cat_post returns False."""
        twitter_bot.bot.client.search_recent_tweets.side_effect = Exception("Timeout")
        assert twitter_bot.find_and_like_cat_post() is False

    def test_follow_user_api_error_returns_false(self, twitter_bot):
        """If the follow_user call itself fails, the method returns False."""
        user = _make_twitter_user(user_id="err1", description="cat lover")
        tweet = _make_twitter_tweet(author_id="err1")

        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response
        twitter_bot.bot.client.follow_user.side_effect = Exception("403 Forbidden")

        result = twitter_bot.find_and_follow_cat_account()
        assert result is False


# ===================================================================
# BLUESKY ENGAGEMENT BOT TESTS
# ===================================================================


class TestBlueskyHistoryTracking:
    """Tests for Bluesky-specific history load/save/cleanup."""

    def test_load_empty_history_when_file_missing(self, tmp_path):
        """Default history dict is returned when file does not exist."""
        with patch.dict(os.environ, {
            "BLUESKY_USERNAME": "test.bsky.social",
            "BLUESKY_PASSWORD": "pw",
        }):
            with patch("src.bluesky_engagement_bot.Client") as MockClient:
                mock_client = MockClient.return_value
                mock_client.login.return_value = None
                mock_client.me = Mock(did="did:plc:x")

                bot = BlueskyEngagementBot()
                bot.engagement_log_path = tmp_path / "nonexistent.json"
                history = bot._load_engagement_history()

        assert history["followed_users"] == []
        assert history["liked_posts"] == []
        assert "last_cleanup" in history

    def test_cleanup_removes_old_entries_including_reposts(self, bluesky_bot):
        """Cleanup should remove old follows, likes, AND reposts beyond 90 days."""
        bluesky_bot.engagement_history["last_cleanup"] = (
            datetime.now() - timedelta(days=8)
        ).isoformat()

        old_ts = (datetime.now() - timedelta(days=100)).isoformat()
        recent_ts = (datetime.now() - timedelta(days=10)).isoformat()

        bluesky_bot.engagement_history["followed_users"] = [
            {"did": "old", "handle": "old.bsky.social", "timestamp": old_ts},
            {"did": "new", "handle": "new.bsky.social", "timestamp": recent_ts},
        ]
        bluesky_bot.engagement_history["liked_posts"] = [
            {"uri": "at://old", "author": "old", "timestamp": old_ts},
        ]
        bluesky_bot.engagement_history["reposted_posts"] = [
            {"uri": "at://old_rp", "author": "old_rp", "text": "x", "timestamp": old_ts},
            {"uri": "at://new_rp", "author": "new_rp", "text": "y", "timestamp": recent_ts},
        ]

        bluesky_bot._cleanup_old_history()

        assert len(bluesky_bot.engagement_history["followed_users"]) == 1
        assert bluesky_bot.engagement_history["followed_users"][0]["did"] == "new"
        assert len(bluesky_bot.engagement_history["liked_posts"]) == 0
        assert len(bluesky_bot.engagement_history["reposted_posts"]) == 1
        assert bluesky_bot.engagement_history["reposted_posts"][0]["uri"] == "at://new_rp"

    def test_cleanup_skipped_when_recent(self, bluesky_bot):
        """Cleanup should be skipped if it was run within the last 7 days."""
        bluesky_bot.engagement_history["last_cleanup"] = datetime.now().isoformat()
        old_ts = (datetime.now() - timedelta(days=100)).isoformat()
        bluesky_bot.engagement_history["followed_users"] = [
            {"did": "old", "handle": "old", "timestamp": old_ts},
        ]

        bluesky_bot._cleanup_old_history()
        # Entry should still be present
        assert len(bluesky_bot.engagement_history["followed_users"]) == 1


class TestBlueskyFollowRatioSafety:
    """Tests for the follow-ratio safety gate unique to the Bluesky bot."""

    def test_ratio_too_high_blocks_follows(self, bluesky_bot):
        """When following/followers ratio > 2.5, follows are blocked."""
        profile = Mock()
        profile.followers_count = 100
        profile.follows_count = 300  # ratio = 3.0
        bluesky_bot.client.app.bsky.actor.get_profile.return_value = profile

        assert bluesky_bot._check_follow_ratio_safe() is False

    def test_ratio_healthy_allows_follows(self, bluesky_bot):
        """When ratio < 2.5, follows are allowed."""
        profile = Mock()
        profile.followers_count = 200
        profile.follows_count = 300  # ratio = 1.5
        bluesky_bot.client.app.bsky.actor.get_profile.return_value = profile

        assert bluesky_bot._check_follow_ratio_safe() is True

    def test_zero_followers_allows_up_to_50(self, bluesky_bot):
        """With 0 followers, following up to 50 accounts is allowed."""
        profile = Mock()
        profile.followers_count = 0
        profile.follows_count = 30
        bluesky_bot.client.app.bsky.actor.get_profile.return_value = profile

        assert bluesky_bot._check_follow_ratio_safe() is True

    def test_zero_followers_blocks_after_50(self, bluesky_bot):
        """With 0 followers and 50+ following, follows are paused."""
        profile = Mock()
        profile.followers_count = 0
        profile.follows_count = 55
        bluesky_bot.client.app.bsky.actor.get_profile.return_value = profile

        assert bluesky_bot._check_follow_ratio_safe() is False

    def test_api_error_defaults_to_cautious(self, bluesky_bot):
        """If profile lookup fails, err on the side of caution (block follows)."""
        bluesky_bot.client.app.bsky.actor.get_profile.side_effect = Exception("API Error")

        assert bluesky_bot._check_follow_ratio_safe() is False


class TestBlueskyTargetSelection:
    """Tests for how the Bluesky bot selects accounts to follow."""

    def test_skips_already_followed_dids(self, bluesky_bot):
        """DIDs in followed_users history should be excluded."""
        bluesky_bot.engagement_history["followed_users"] = [
            {"did": "did:plc:abc123", "handle": "x", "timestamp": datetime.now().isoformat()},
        ]
        # Stub ratio check to pass
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(did="did:plc:abc123")
        post = _make_bluesky_post(author=author)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_own_account(self, bluesky_bot):
        """The bot's own posts/accounts should be excluded."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)
        bluesky_bot.username = "testcat.bsky.social"

        author = _make_bluesky_author(
            did="did:plc:someone",
            handle="testcat",  # matches username without .bsky.social
            description="I love cats",
        )
        post = _make_bluesky_post(author=author, text="My cute cat")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_low_follower_accounts(self, bluesky_bot):
        """Accounts under 50 followers should be filtered out on Bluesky."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:lowf",
            handle="lowfollowers.bsky.social",
            followers_count=20,
            description="cat person",
        )
        post = _make_bluesky_post(author=author, text="my cat")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is False

    def test_skips_mega_accounts(self, bluesky_bot):
        """Accounts over 50K followers should be filtered out on Bluesky."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:mega",
            handle="megacat.bsky.social",
            followers_count=100_000,
            description="cat person",
        )
        post = _make_bluesky_post(author=author, text="my cat")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is False

    def test_accepts_cat_keyword_in_post_when_bio_lacks_it(self, bluesky_bot):
        """If bio has no cat keywords but the post text does, the account qualifies."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:nobiocat",
            handle="nobiokw.bsky.social",
            followers_count=300,
            follows_count=100,
            description="animal lover",  # no cat keyword
        )
        post = _make_bluesky_post(author=author, text="Look at this cute kitten!")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is True

    def test_deduplicates_candidate_accounts_by_did(self, bluesky_bot):
        """When the same author appears in multiple posts, they should be deduplicated."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:dup",
            handle="dupcat.bsky.social",
            followers_count=300,
            follows_count=100,
            description="cat person",
        )
        post1 = _make_bluesky_post(uri="at://1", author=author, text="my cat")
        post2 = _make_bluesky_post(uri="at://2", author=author, text="another cat pic")
        response = Mock()
        response.posts = [post1, post2]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is True
        # follow.create should be called exactly once
        bluesky_bot.client.app.bsky.graph.follow.create.assert_called_once()

    def test_ratio_check_blocks_follow_attempt(self, bluesky_bot):
        """If the follow ratio is unsafe, find_and_follow_cat_account returns False."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=False)
        result = bluesky_bot.find_and_follow_cat_account()
        assert result is False

    def test_successfully_follows_quality_bluesky_account(self, bluesky_bot):
        """A valid account on Bluesky should be followed and logged."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:good",
            handle="goodcat.bsky.social",
            followers_count=500,
            follows_count=200,
            description="I love my cat and kittens",
        )
        post = _make_bluesky_post(author=author, text="cute cat photo")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        result = bluesky_bot.find_and_follow_cat_account()
        assert result is True
        assert any(
            e["did"] == "did:plc:good"
            for e in bluesky_bot.engagement_history["followed_users"]
        )


class TestBlueskyLikePost:
    """Tests for the Bluesky like-post flow."""

    def test_skips_already_liked_uris(self, bluesky_bot):
        """URIs present in liked_posts history should be skipped."""
        bluesky_bot.engagement_history["liked_posts"] = [
            {"uri": "at://already", "author": "a", "timestamp": datetime.now().isoformat()},
        ]

        author = _make_bluesky_author(did="did:plc:liker")
        post = _make_bluesky_post(uri="at://already", author=author, like_count=50)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_own_posts(self, bluesky_bot):
        """The bot should skip its own posts."""
        bluesky_bot.username = "testcat.bsky.social"

        author = _make_bluesky_author(did="did:plc:me", handle="testcat")
        post = _make_bluesky_post(uri="at://own", author=author, like_count=50)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_low_engagement_posts(self, bluesky_bot):
        """Posts with fewer than 3 likes should be filtered out on Bluesky."""
        author = _make_bluesky_author(did="did:plc:low")
        post = _make_bluesky_post(uri="at://low", author=author, like_count=1)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_mega_viral_posts(self, bluesky_bot):
        """Posts with more than 5000 likes should be filtered out on Bluesky."""
        author = _make_bluesky_author(did="did:plc:viral")
        post = _make_bluesky_post(uri="at://viral", author=author, like_count=10_000)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_skips_old_bluesky_posts(self, bluesky_bot):
        """Posts older than 48 hours should be filtered out on Bluesky."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        author = _make_bluesky_author(did="did:plc:old")
        post = _make_bluesky_post(
            uri="at://old", author=author, like_count=50, indexed_at=old_time
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_authoritative_api_check_prevents_double_like(self, bluesky_bot):
        """If _is_post_liked returns True, the like is skipped even if not in local history."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(did="did:plc:dbl", handle="dbl.bsky.social")
        post = _make_bluesky_post(
            uri="at://dbl", author=author, like_count=50, indexed_at=recent_time
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        # Simulate API saying we already liked it
        bluesky_bot._is_post_liked = Mock(return_value=True)

        result = bluesky_bot.find_and_like_cat_post()
        assert result is False

    def test_successfully_likes_and_logs(self, bluesky_bot):
        """A valid post should be liked, logged, and return True."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:likeme",
            handle="likeme.bsky.social",
            followers_count=10,  # Below auto-follow threshold
        )
        post = _make_bluesky_post(
            uri="at://likeme",
            cid="cid_good",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        # Stub ratio check for potential auto-follow
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        result = bluesky_bot.find_and_like_cat_post()
        assert result is True
        assert any(
            e["uri"] == "at://likeme" for e in bluesky_bot.engagement_history["liked_posts"]
        )


class TestBlueskyAutoFollow:
    """Tests for the auto-follow/bonus-follow logic triggered during like."""

    def test_auto_follow_when_no_prior_follow(self, bluesky_bot):
        """If we have not followed an account this cycle, auto-follow the liked post author."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:autofollow",
            handle="autofollow.bsky.social",
            followers_count=500,
            follows_count=100,
        )
        post = _make_bluesky_post(
            uri="at://autofollow",
            cid="cid_af",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        result = bluesky_bot.find_and_like_cat_post(already_followed_account=False)
        assert result is True
        # Verify follow was attempted (auto-follow path)
        bluesky_bot.client.app.bsky.graph.follow.create.assert_called()
        assert any(
            e["did"] == "did:plc:autofollow"
            for e in bluesky_bot.engagement_history["followed_users"]
        )

    def test_auto_follow_skipped_when_ratio_unsafe(self, bluesky_bot):
        """Auto-follow should be skipped if the follow ratio is too high."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:noauto",
            handle="noauto.bsky.social",
            followers_count=500,
        )
        post = _make_bluesky_post(
            uri="at://noauto",
            cid="cid_na",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=False)

        result = bluesky_bot.find_and_like_cat_post(already_followed_account=False)
        assert result is True
        # Follow should NOT have been called
        bluesky_bot.client.app.bsky.graph.follow.create.assert_not_called()

    def test_bonus_follow_skips_spammy_accounts(self, bluesky_bot):
        """Bonus follow (when we already followed someone) should skip spammy accounts."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:spammy",
            handle="spammy.bsky.social",
            followers_count=100,
            follows_count=1000,  # follow ratio = 10 > 5
        )
        post = _make_bluesky_post(
            uri="at://spammy",
            cid="cid_sp",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        result = bluesky_bot.find_and_like_cat_post(already_followed_account=True)
        assert result is True
        # Follow should NOT have been called (spammy ratio)
        bluesky_bot.client.app.bsky.graph.follow.create.assert_not_called()

    def test_bonus_follow_skips_small_accounts(self, bluesky_bot):
        """Bonus follow should skip accounts under 50 followers."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:small",
            handle="small.bsky.social",
            followers_count=10,
            follows_count=5,
        )
        post = _make_bluesky_post(
            uri="at://small",
            cid="cid_sm",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        result = bluesky_bot.find_and_like_cat_post(already_followed_account=True)
        assert result is True
        bluesky_bot.client.app.bsky.graph.follow.create.assert_not_called()

    def test_bonus_follow_succeeds_for_quality_account(self, bluesky_bot):
        """Bonus follow should proceed for a quality account when already_followed is True."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(
            did="did:plc:bonus",
            handle="bonus.bsky.social",
            followers_count=500,
            follows_count=200,
        )
        post = _make_bluesky_post(
            uri="at://bonus",
            cid="cid_bn",
            author=author,
            like_count=50,
            indexed_at=recent_time,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        result = bluesky_bot.find_and_like_cat_post(already_followed_account=True)
        assert result is True
        bluesky_bot.client.app.bsky.graph.follow.create.assert_called()
        assert any(
            e["did"] == "did:plc:bonus"
            for e in bluesky_bot.engagement_history["followed_users"]
        )


class TestBlueskyIsPostLiked:
    """Tests for the authoritative _is_post_liked API check."""

    def test_returns_true_when_viewer_has_like(self, bluesky_bot):
        """If the API shows viewer.like is set, the post is already liked."""
        post_mock = Mock()
        post_mock.viewer = Mock()
        post_mock.viewer.like = "at://some-like-uri"
        response = Mock()
        response.posts = [post_mock]
        bluesky_bot.client.app.bsky.feed.get_posts.return_value = response

        assert bluesky_bot._is_post_liked("at://testpost") is True

    def test_returns_false_when_no_like(self, bluesky_bot):
        """If viewer.like is absent, the post is not liked."""
        post_mock = Mock()
        post_mock.viewer = Mock()
        post_mock.viewer.like = None
        response = Mock()
        response.posts = [post_mock]
        bluesky_bot.client.app.bsky.feed.get_posts.return_value = response

        assert bluesky_bot._is_post_liked("at://testpost") is False

    def test_returns_false_on_api_error(self, bluesky_bot):
        """If the API call fails, assume the post is not liked."""
        bluesky_bot.client.app.bsky.feed.get_posts.side_effect = Exception("Error")
        assert bluesky_bot._is_post_liked("at://testpost") is False

    def test_returns_false_when_no_posts_returned(self, bluesky_bot):
        """If the API returns no posts, the check returns False."""
        response = Mock()
        response.posts = []
        bluesky_bot.client.app.bsky.feed.get_posts.return_value = response

        assert bluesky_bot._is_post_liked("at://testpost") is False


class TestBlueskyIsPostReposted:
    """Tests for the authoritative _is_post_reposted API check."""

    def test_returns_true_when_viewer_has_repost(self, bluesky_bot):
        """If the API shows viewer.repost is set, the post is already reposted."""
        post_mock = Mock()
        post_mock.viewer = Mock()
        post_mock.viewer.repost = "at://some-repost-uri"
        response = Mock()
        response.posts = [post_mock]
        bluesky_bot.client.app.bsky.feed.get_posts.return_value = response

        assert bluesky_bot._is_post_reposted("at://testpost") is True

    def test_returns_false_when_no_repost(self, bluesky_bot):
        """If viewer.repost is absent, the post is not reposted."""
        post_mock = Mock()
        post_mock.viewer = Mock()
        post_mock.viewer.repost = None
        response = Mock()
        response.posts = [post_mock]
        bluesky_bot.client.app.bsky.feed.get_posts.return_value = response

        assert bluesky_bot._is_post_reposted("at://testpost") is False

    def test_returns_false_on_api_error(self, bluesky_bot):
        """If the API call fails, assume the post is not reposted."""
        bluesky_bot.client.app.bsky.feed.get_posts.side_effect = Exception("Error")
        assert bluesky_bot._is_post_reposted("at://testpost") is False


class TestBlueskyRepostRescue:
    """Tests for the find_and_repost_cat_rescue method."""

    def _make_rescue_post(self, uri="at://rescue", has_images=True, text=None):
        """Helper to create a valid rescue post mock."""
        if text is None:
            text = "These cats need homes, please repost to help them find a forever home!"
        author = _make_bluesky_author(
            did="did:plc:rescuer",
            handle="rescuer.bsky.social",
        )
        return _make_bluesky_post(
            uri=uri,
            cid="cid_rescue",
            author=author,
            text=text,
            like_count=30,
            repost_count=10,
            has_images=has_images,
            embed_type="app.bsky.embed.images",
        )

    def test_skips_already_reposted_uris(self, bluesky_bot):
        """Posts already in reposted_posts history should be skipped."""
        bluesky_bot.engagement_history["reposted_posts"] = [
            {"uri": "at://rescue", "author": "x", "text": "x", "timestamp": datetime.now().isoformat()},
        ]

        post = self._make_rescue_post(uri="at://rescue")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_skips_posts_without_repost_keywords(self, bluesky_bot):
        """Posts not asking for reposts/shares should be filtered out."""
        post = self._make_rescue_post(
            text="These cats need homes."  # No repost/boost keyword
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_skips_posts_without_rescue_keywords(self, bluesky_bot):
        """Posts that ask for reposts but are not about rescue should be filtered out."""
        post = self._make_rescue_post(
            text="My cute cat just did something funny, please repost this!"
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_skips_posts_without_images(self, bluesky_bot):
        """Rescue posts without images should be filtered out."""
        post = self._make_rescue_post(has_images=False)
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_skips_old_rescue_posts(self, bluesky_bot):
        """Rescue posts older than 72 hours should be filtered out."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=80)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        author = _make_bluesky_author(did="did:plc:old_rescuer", handle="old.bsky.social")
        post = _make_bluesky_post(
            uri="at://old_rescue",
            author=author,
            text="These cats need homes, please repost!",
            like_count=30,
            indexed_at=old_time,
            has_images=True,
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_api_check_prevents_double_repost(self, bluesky_bot):
        """If _is_post_reposted returns True, the repost is skipped."""
        post = self._make_rescue_post(uri="at://double_rp")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_reposted = Mock(return_value=True)

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is False

    def test_successfully_reposts_and_logs(self, bluesky_bot):
        """A valid rescue post should be reposted and logged."""
        post = self._make_rescue_post(uri="at://good_rescue")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_reposted = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.repost.create.return_value = None

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is True
        bluesky_bot.client.app.bsky.feed.repost.create.assert_called_once()
        assert any(
            e["uri"] == "at://good_rescue"
            for e in bluesky_bot.engagement_history["reposted_posts"]
        )

    def test_prefers_higher_engagement_rescue_posts(self, bluesky_bot):
        """Rescue posts should be sorted by engagement, preferring the highest."""
        author1 = _make_bluesky_author(did="did:plc:r1", handle="r1.bsky.social")
        post1 = _make_bluesky_post(
            uri="at://rescue_low",
            cid="cid1",
            author=author1,
            text="Cats need homes, please repost to help them find a forever home!",
            like_count=5,
            repost_count=2,
            has_images=True,
        )
        author2 = _make_bluesky_author(did="did:plc:r2", handle="r2.bsky.social")
        post2 = _make_bluesky_post(
            uri="at://rescue_high",
            cid="cid2",
            author=author2,
            text="Cats need a home please repost to help adopt them!",
            like_count=100,
            repost_count=50,
            has_images=True,
        )
        response = Mock()
        response.posts = [post1, post2]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_reposted = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.repost.create.return_value = None

        result = bluesky_bot.find_and_repost_cat_rescue()
        assert result is True
        # The reposted post should be the higher-engagement one
        logged = bluesky_bot.engagement_history["reposted_posts"][-1]
        assert logged["uri"] == "at://rescue_high"


class TestBlueskyEngagementCycle:
    """Tests for the top-level Bluesky engagement cycle."""

    def test_cycle_calls_all_three_actions(self, bluesky_bot):
        """run_engagement_cycle should attempt follow, like, and repost."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=True) as m_follow, \
             patch.object(bluesky_bot, "find_and_like_cat_post", return_value=True) as m_like, \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=True) as m_repost:
            result = bluesky_bot.run_engagement_cycle()

        m_follow.assert_called_once()
        m_like.assert_called_once_with(already_followed_account=True)
        m_repost.assert_called_once()
        assert result is True

    def test_cycle_passes_follow_status_to_like(self, bluesky_bot):
        """Like method receives already_followed_account=False when follow failed."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(bluesky_bot, "find_and_like_cat_post", return_value=False) as m_like, \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=False):
            bluesky_bot.run_engagement_cycle()

        m_like.assert_called_once_with(already_followed_account=False)

    def test_cycle_returns_false_when_all_fail(self, bluesky_bot):
        """Cycle returns False when all three actions fail."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(bluesky_bot, "find_and_like_cat_post", return_value=False), \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=False):
            result = bluesky_bot.run_engagement_cycle()
        assert result is False

    def test_cycle_returns_true_when_only_repost_succeeds(self, bluesky_bot):
        """Cycle returns True if at least one action succeeds."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(bluesky_bot, "find_and_like_cat_post", return_value=False), \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=True):
            result = bluesky_bot.run_engagement_cycle()
        assert result is True

    def test_cycle_handles_follow_exception(self, bluesky_bot):
        """If follow throws, the cycle should still attempt like and repost."""
        with patch.object(
            bluesky_bot, "find_and_follow_cat_account", side_effect=Exception("fail")
        ), patch.object(bluesky_bot, "find_and_like_cat_post", return_value=True) as m_like, \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=False) as m_repost:
            result = bluesky_bot.run_engagement_cycle()

        m_like.assert_called_once()
        m_repost.assert_called_once()
        assert result is True

    def test_cycle_handles_like_exception(self, bluesky_bot):
        """If like throws, the cycle should still attempt repost."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=False), \
             patch.object(
                 bluesky_bot, "find_and_like_cat_post", side_effect=Exception("fail")
             ), \
             patch.object(bluesky_bot, "find_and_repost_cat_rescue", return_value=True) as m_rp:
            result = bluesky_bot.run_engagement_cycle()

        m_rp.assert_called_once()
        assert result is True

    def test_cycle_handles_repost_exception(self, bluesky_bot):
        """If repost throws, the cycle should still return based on other results."""
        with patch.object(bluesky_bot, "find_and_follow_cat_account", return_value=True), \
             patch.object(bluesky_bot, "find_and_like_cat_post", return_value=False), \
             patch.object(
                 bluesky_bot, "find_and_repost_cat_rescue", side_effect=Exception("fail")
             ):
            result = bluesky_bot.run_engagement_cycle()
        assert result is True


class TestBlueskyErrorHandling:
    """Tests for graceful error handling in the Bluesky engagement bot."""

    def test_follow_search_api_error_returns_false(self, bluesky_bot):
        """If the search API raises, find_and_follow_cat_account returns False."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)
        bluesky_bot.client.app.bsky.feed.search_posts.side_effect = Exception("Network error")

        assert bluesky_bot.find_and_follow_cat_account() is False

    def test_like_search_api_error_returns_false(self, bluesky_bot):
        """If the search API raises, find_and_like_cat_post returns False."""
        bluesky_bot.client.app.bsky.feed.search_posts.side_effect = Exception("Timeout")

        assert bluesky_bot.find_and_like_cat_post() is False

    def test_repost_search_api_error_returns_false(self, bluesky_bot):
        """If the search API raises, find_and_repost_cat_rescue returns False."""
        bluesky_bot.client.app.bsky.feed.search_posts.side_effect = Exception("Error")

        assert bluesky_bot.find_and_repost_cat_rescue() is False

    def test_no_search_results_returns_false_for_follow(self, bluesky_bot):
        """Empty search results should return False gracefully."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)
        response = Mock()
        response.posts = []
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response

        assert bluesky_bot.find_and_follow_cat_account() is False

    def test_missing_credentials_raises_on_init(self):
        """BlueskyEngagementBot should raise ValueError with missing credentials."""
        with patch.dict(os.environ, {"BLUESKY_USERNAME": "", "BLUESKY_PASSWORD": ""}, clear=False):
            with patch("src.bluesky_engagement_bot.Client"):
                with pytest.raises(ValueError, match="Missing Bluesky credentials"):
                    BlueskyEngagementBot()


# ===================================================================
# PLATFORM DIFFERENCES
# ===================================================================


class TestPlatformDifferences:
    """Tests verifying key behavioral differences between Twitter and Bluesky bots."""

    def test_twitter_follower_threshold_is_100(self, twitter_bot):
        """Twitter bot requires at least 100 followers (vs 50 on Bluesky)."""
        # 80 followers should be rejected on Twitter
        user = _make_twitter_user(user_id="pd1", followers_count=80, description="cat person")
        tweet = _make_twitter_tweet(author_id="pd1")
        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        assert twitter_bot.find_and_follow_cat_account() is False

    def test_bluesky_follower_threshold_is_50(self, bluesky_bot):
        """Bluesky bot requires at least 50 followers (lower than Twitter)."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        # 80 followers should pass on Bluesky (but fail on Twitter)
        author = _make_bluesky_author(
            did="did:plc:pd2",
            handle="pd2.bsky.social",
            followers_count=80,
            follows_count=40,
            description="I love my cat",
        )
        post = _make_bluesky_post(author=author, text="cute cat")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        assert bluesky_bot.find_and_follow_cat_account() is True

    def test_twitter_like_threshold_is_5(self, twitter_bot):
        """Twitter bot requires at least 5 likes to consider a post."""
        user = _make_twitter_user(user_id="pd3")
        tweet = _make_twitter_tweet(
            tweet_id="t_low", author_id="pd3", like_count=4,
            created_at=datetime.now(timezone.utc),
        )
        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        assert twitter_bot.find_and_like_cat_post() is False

    def test_bluesky_like_threshold_is_3(self, bluesky_bot):
        """Bluesky bot requires at least 3 likes (lower than Twitter's 5)."""
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        author = _make_bluesky_author(did="did:plc:pd4", handle="pd4.bsky.social")
        # 4 likes should pass on Bluesky (but fail on Twitter)
        post = _make_bluesky_post(
            uri="at://pd4", author=author, like_count=4, indexed_at=recent_time
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        assert bluesky_bot.find_and_like_cat_post() is True

    def test_twitter_recency_window_is_24h(self, twitter_bot):
        """Twitter bot filters out posts older than 24 hours."""
        user = _make_twitter_user(user_id="pd5")
        # 25 hours old -- should be rejected
        tweet = _make_twitter_tweet(
            tweet_id="t_25h", author_id="pd5", like_count=50,
            created_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response

        assert twitter_bot.find_and_like_cat_post() is False

    def test_bluesky_recency_window_is_48h(self, bluesky_bot):
        """Bluesky bot allows posts up to 48 hours old (longer than Twitter)."""
        # 30 hours old -- should pass on Bluesky (but fail on Twitter)
        aged_time = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        author = _make_bluesky_author(did="did:plc:pd6", handle="pd6.bsky.social")
        post = _make_bluesky_post(
            uri="at://pd6", author=author, like_count=50, indexed_at=aged_time
        )
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot._is_post_liked = Mock(return_value=False)
        bluesky_bot.client.app.bsky.feed.like.create.return_value = None
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        assert bluesky_bot.find_and_like_cat_post() is True

    def test_twitter_has_no_follow_ratio_check(self, twitter_bot):
        """Twitter bot does not have a _check_follow_ratio_safe method."""
        assert not hasattr(twitter_bot, "_check_follow_ratio_safe")

    def test_bluesky_has_follow_ratio_check(self, bluesky_bot):
        """Bluesky bot has a _check_follow_ratio_safe method."""
        assert hasattr(bluesky_bot, "_check_follow_ratio_safe")

    def test_twitter_uses_tweet_id_key(self, twitter_bot):
        """Twitter bot history tracks liked_tweets with tweet_id keys."""
        assert "liked_tweets" in twitter_bot.engagement_history

    def test_bluesky_uses_uri_key(self, bluesky_bot):
        """Bluesky bot history tracks liked_posts with uri keys."""
        assert "liked_posts" in bluesky_bot.engagement_history

    def test_twitter_tracks_user_id_for_follows(self, twitter_bot):
        """Twitter follow history uses user_id field."""
        user = _make_twitter_user(user_id="follow_key_test", description="cat lover")
        tweet = _make_twitter_tweet(author_id="follow_key_test")
        response = Mock()
        response.data = [tweet]
        response.includes = {"users": [user]}
        twitter_bot.bot.client.search_recent_tweets.return_value = response
        twitter_bot.bot.client.follow_user.return_value = None

        twitter_bot.find_and_follow_cat_account()
        if twitter_bot.engagement_history["followed_users"]:
            entry = twitter_bot.engagement_history["followed_users"][-1]
            assert "user_id" in entry
            assert "did" not in entry

    def test_bluesky_tracks_did_for_follows(self, bluesky_bot):
        """Bluesky follow history uses did field."""
        bluesky_bot._check_follow_ratio_safe = Mock(return_value=True)

        author = _make_bluesky_author(
            did="did:plc:key_test", handle="keytest.bsky.social",
            followers_count=300, follows_count=100, description="cat person",
        )
        post = _make_bluesky_post(author=author, text="cute cat")
        response = Mock()
        response.posts = [post]
        bluesky_bot.client.app.bsky.feed.search_posts.return_value = response
        bluesky_bot.client.app.bsky.graph.follow.create.return_value = None

        bluesky_bot.find_and_follow_cat_account()
        if bluesky_bot.engagement_history["followed_users"]:
            entry = bluesky_bot.engagement_history["followed_users"][-1]
            assert "did" in entry
            assert "user_id" not in entry

    def test_bluesky_has_repost_functionality(self, bluesky_bot):
        """Bluesky bot supports reposting rescue posts (Twitter bot does not)."""
        assert hasattr(bluesky_bot, "find_and_repost_cat_rescue")

    def test_twitter_has_no_repost_functionality(self, twitter_bot):
        """Twitter bot does not have a repost/rescue method."""
        assert not hasattr(twitter_bot, "find_and_repost_cat_rescue")
