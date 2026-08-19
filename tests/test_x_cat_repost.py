"""
Tests for the X cat repost feature.

Covers:
- TwitterBot.retweet() method
- Daily cap enforcement (max 2 RTs per UTC day)
- No fallback to quote_tweet on failure
- Reject keyword filtering
"""
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)


@pytest.fixture
def twitter_env():
    """Set Twitter/X credentials in the environment."""
    with patch.dict(os.environ, {
        "X_API_KEY": "fake-api-key",
        "X_API_SECRET": "fake-api-secret",
        "X_ACCESS_TOKEN": "fake-access-token",
        "X_ACCESS_TOKEN_SECRET": "fake-access-token-secret",
        "X_BEARER_TOKEN": "fake-bearer-token",
    }):
        yield


class TestTwitterBotRetweet:
    """Tests for TwitterBot.retweet() method."""

    @pytest.fixture
    def bot(self, twitter_env):
        with patch("twitter_bot.tweepy.API"), \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from twitter_bot import TwitterBot
            bot = TwitterBot()
            yield bot

    def test_retweet_success(self, bot):
        """retweet returns data on success."""
        bot.client.retweet.return_value = Mock(data={"retweeted": True})
        result = bot.retweet("123456789")
        assert result is not None
        assert result["retweeted"] is True
        assert result["source_tweet_id"] == "123456789"
        bot.client.retweet.assert_called_once_with("123456789")

    def test_retweet_api_error_returns_none(self, bot):
        """retweet returns None on API error (does not raise)."""
        import tweepy
        error = tweepy.TweepyException("403 Forbidden")
        error.response = Mock(status_code=403, text='{"detail":"Forbidden"}')
        bot.client.retweet.side_effect = error

        result = bot.retweet("123456789")
        assert result is None

    def test_retweet_rate_limit_raises(self, bot):
        """retweet re-raises TooManyRequests for CI/CD failure."""
        import tweepy
        resp = Mock()
        resp.status_code = 429
        resp.reason = "Too Many Requests"
        resp.json.return_value = {}
        bot.client.retweet.side_effect = tweepy.TooManyRequests(resp)

        with pytest.raises(tweepy.TooManyRequests):
            bot.retweet("123456789")

    def test_retweet_does_not_call_quote_tweet(self, bot):
        """retweet NEVER falls back to quote_tweet."""
        import tweepy
        error = tweepy.TweepyException("403 Forbidden")
        error.response = Mock(status_code=403, text='{"detail":"Forbidden"}')
        bot.client.retweet.side_effect = error

        result = bot.retweet("123456789")
        assert result is None
        bot.client.create_tweet.assert_not_called()

    def test_retweet_unexpected_response_returns_none(self, bot):
        """retweet returns None when response lacks retweeted=True."""
        bot.client.retweet.return_value = Mock(data={"retweeted": False})
        result = bot.retweet("123456789")
        assert result is None


class TestXCatRepostCap:
    """Tests for the daily cap enforcement in x_cat_repost.py."""

    def test_count_today_reposts_empty_history(self):
        """count_today_reposts returns 0 for empty history."""
        from x_cat_repost import count_today_reposts
        history = {"reposts": []}
        assert count_today_reposts(history) == 0

    def test_count_today_reposts_counts_only_today(self):
        """count_today_reposts only counts today's successful reposts."""
        from x_cat_repost import count_today_reposts
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = "2020-01-01"  # definitely not today

        history = {
            "reposts": [
                {"date": today, "success": True, "tweet_id": "1"},
                {"date": today, "success": True, "tweet_id": "2"},
                {"date": today, "success": False, "tweet_id": "3"},  # failed, not counted
                {"date": yesterday, "success": True, "tweet_id": "4"},  # not today
            ]
        }
        assert count_today_reposts(history) == 2

    def test_count_today_reposts_ignores_failures(self):
        """count_today_reposts ignores failed attempts."""
        from x_cat_repost import count_today_reposts
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        history = {
            "reposts": [
                {"date": today, "success": False, "tweet_id": "1"},
                {"date": today, "success": False, "tweet_id": "2"},
            ]
        }
        assert count_today_reposts(history) == 0


class TestXCatRepostKeywordFilter:
    """Tests for the keyword rejection filter."""

    def test_contains_reject_keywords_detects_politics(self):
        """contains_reject_keywords rejects politics keywords."""
        from x_cat_repost import contains_reject_keywords
        assert contains_reject_keywords("Check out this election news!") is True
        assert contains_reject_keywords("The president signed a bill") is True
        assert contains_reject_keywords("Breaking news from congress") is True

    def test_contains_reject_keywords_allows_cat_content(self):
        """contains_reject_keywords allows innocent cat content."""
        from x_cat_repost import contains_reject_keywords
        assert contains_reject_keywords("Look at this cute kitty!") is False
        assert contains_reject_keywords("My cat is sleeping again") is False
        assert contains_reject_keywords("Fluffiest cat ever 🐱") is False

    def test_contains_reject_keywords_handles_none(self):
        """contains_reject_keywords handles None input."""
        from x_cat_repost import contains_reject_keywords
        assert contains_reject_keywords(None) is False

    def test_contains_reject_keywords_case_insensitive(self):
        """contains_reject_keywords is case-insensitive."""
        from x_cat_repost import contains_reject_keywords
        assert contains_reject_keywords("BREAKING NEWS") is True
        assert contains_reject_keywords("Breaking News") is True


class TestXCatRepostHistoryPersistence:
    """Tests for history file load/save."""

    def test_load_history_missing_file(self, tmp_path, monkeypatch):
        """load_history returns empty history when file doesn't exist."""
        monkeypatch.chdir(tmp_path)
        from x_cat_repost import load_history, HISTORY_FILE
        # Ensure file doesn't exist
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        history = load_history()
        assert history == {"reposts": []}

    def test_load_history_corrupt_file(self, tmp_path, monkeypatch):
        """load_history returns empty history for corrupt JSON."""
        monkeypatch.chdir(tmp_path)
        from x_cat_repost import load_history, HISTORY_FILE
        with open(HISTORY_FILE, "w") as f:
            f.write("NOT VALID JSON {{{")
        history = load_history()
        assert history == {"reposts": []}

    def test_save_and_load_history(self, tmp_path, monkeypatch):
        """save_history persists data that load_history can read."""
        monkeypatch.chdir(tmp_path)
        from x_cat_repost import save_history, load_history

        test_history = {
            "reposts": [
                {"tweet_id": "123", "date": "2026-08-19", "success": True}
            ]
        }
        save_history(test_history)
        loaded = load_history()
        assert loaded == test_history


class TestNoQuoteFallbackIntegration:
    """Integration test ensuring retweet failure never triggers quote_tweet."""

    def test_retweet_failure_does_not_quote(self, twitter_env):
        """When retweet fails, we do NOT fall back to quote_tweet."""
        import tweepy

        with patch("twitter_bot.tweepy.API"), \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            error = tweepy.TweepyException("403 Forbidden")
            error.response = Mock(status_code=403, text='{"detail":"Forbidden"}')
            mock_client.retweet.side_effect = error

            from twitter_bot import TwitterBot
            bot = TwitterBot()

            result = bot.retweet("999")
            assert result is None

            mock_client.create_tweet.assert_not_called()

            result2 = bot.quote_tweet("999", "test")
            mock_client.create_tweet.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
