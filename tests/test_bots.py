"""
Test suite for the mewscast bot posting pipeline.

Covers Bluesky bot, Twitter/X bot, image generator, content generation,
configuration loading, and main pipeline orchestration. All external API
calls (Bluesky ATProto, Twitter/X Tweepy, xAI Grok, Anthropic Claude,
Google News RSS, HTTP requests) are mocked.
"""

import json
import os
import sys
import tempfile
from unittest.mock import Mock, MagicMock, patch, mock_open, call

import pytest
import requests as _requests_lib

# ---------------------------------------------------------------------------
# Path setup so imports resolve from the project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")

sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)


def _make_rate_limit_response():
    """Build a mock response object that tweepy.TooManyRequests can consume."""
    resp = Mock()
    resp.status_code = 429
    resp.reason = "Too Many Requests"
    resp.json.side_effect = _requests_lib.JSONDecodeError("", "", 0)
    return resp


# =========================================================================
# Fixtures shared across test classes
# =========================================================================

@pytest.fixture
def bluesky_env():
    """Set Bluesky credentials in the environment."""
    with patch.dict(os.environ, {
        "BLUESKY_USERNAME": "testcat.bsky.social",
        "BLUESKY_PASSWORD": "secret-password",
    }):
        yield


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


@pytest.fixture
def image_gen_env():
    """Set xAI image generation credentials in the environment."""
    with patch.dict(os.environ, {"X_AI_API_KEY": "fake-xai-key"}):
        yield


@pytest.fixture
def anthropic_env():
    """Set Anthropic credentials in the environment."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-anthropic-key"}):
        yield


@pytest.fixture
def all_env(bluesky_env, twitter_env, image_gen_env, anthropic_env):
    """Convenience fixture that activates every credential at once."""
    yield


@pytest.fixture
def sample_config():
    """Return a minimal config dict matching config.yaml structure."""
    return {
        "bot": {"name": "mewscast", "version": "0.2.0"},
        "content": {
            "persona": "professional news reporter cat",
            "topics": ["breaking political scandals", "stock market volatility"],
            "cat_vocabulary_by_topic": {
                "politics": {
                    "keywords": ["president", "congress"],
                    "phrases": ["paw-litical", "claws out"],
                },
            },
            "cat_vocabulary_universal": ["breaking mews", "from my perch"],
            "engagement_hooks": ["What's your take?"],
            "time_of_day": {"morning": ["Fresh from my morning perch"]},
            "cat_humor": ["Filing this report between naps"],
            "editorial_guidelines": ["Report facts with context"],
            "style": "serious journalist with cheeky feline wordplay",
            "max_length": 250,
            "ai_provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
        },
        "safety": {
            "avoid_topics": ["politics", "religion"],
            "max_posts_per_day": 5,
            "min_hours_between_posts": 4,
        },
        "deduplication": {
            "enabled": True,
            "topic_cooldown_hours": 72,
            "topic_similarity_threshold": 0.40,
            "content_cooldown_hours": 72,
            "content_similarity_threshold": 0.65,
            "url_deduplication": True,
            "max_history_days": 30,
            "allow_updates": True,
            "update_keywords": ["update", "breaking"],
        },
        "post_angles": {"framing_chance": 0.5},
        "scheduling": {"post_times": ["0 13 * * *"]},
    }


@pytest.fixture
def sample_config_yaml(sample_config, tmp_path):
    """Write sample_config to a temporary YAML file and return its path."""
    import yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(sample_config))
    return str(config_file)


# =========================================================================
# Bluesky Bot Tests
# =========================================================================

class TestBlueskyBotAuthentication:
    """Tests for BlueskyBot credential validation and login."""

    def test_missing_credentials_raises(self):
        """BlueskyBot raises ValueError when env vars are absent."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Missing Bluesky credentials"):
                from bluesky_bot import BlueskyBot
                BlueskyBot()

    def test_missing_password_raises(self):
        """BlueskyBot raises when only username is set."""
        with patch.dict(os.environ, {"BLUESKY_USERNAME": "user"}, clear=True):
            with pytest.raises(ValueError, match="Missing Bluesky credentials"):
                from bluesky_bot import BlueskyBot
                BlueskyBot()

    @patch("bluesky_bot.Client")
    def test_successful_login(self, mock_client_cls, bluesky_env):
        """BlueskyBot logs in and stores the client on success."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        from bluesky_bot import BlueskyBot
        bot = BlueskyBot()

        mock_client.login.assert_called_once_with(
            "testcat.bsky.social", "secret-password"
        )
        assert bot.client is mock_client

    @patch("bluesky_bot.Client")
    def test_failed_login_raises(self, mock_client_cls, bluesky_env):
        """BlueskyBot raises ValueError when atproto login fails."""
        mock_client = MagicMock()
        mock_client.login.side_effect = Exception("Bad credentials")
        mock_client_cls.return_value = mock_client

        from bluesky_bot import BlueskyBot
        with pytest.raises(ValueError, match="Failed to authenticate with Bluesky"):
            BlueskyBot()


class TestBlueskyBotPosting:
    """Tests for BlueskyBot post creation."""

    @pytest.fixture
    def bot(self, bluesky_env):
        """Return a BlueskyBot with a mocked client."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()
            yield bot

    def test_post_skeet_success(self, bot):
        """post_skeet returns uri and cid on success."""
        bot.client.send_post.return_value = Mock(
            uri="at://did:plc:abc/app.bsky.feed.post/123",
            cid="bafyabc123",
        )

        result = bot.post_skeet("Breaking mews from the perch!")
        assert result == {
            "uri": "at://did:plc:abc/app.bsky.feed.post/123",
            "cid": "bafyabc123",
        }
        bot.client.send_post.assert_called_once_with(
            text="Breaking mews from the perch!"
        )

    def test_post_skeet_truncates_long_text(self, bot):
        """post_skeet truncates text exceeding 300 chars."""
        bot.client.send_post.return_value = Mock(
            uri="at://did:plc:abc/app.bsky.feed.post/456",
            cid="bafydef456",
        )

        long_text = "A" * 301
        result = bot.post_skeet(long_text)
        # Should still post (truncated), not error
        assert result is not None
        # The text sent should be <= 300 chars
        sent_text = bot.client.send_post.call_args[1]["text"]
        assert len(sent_text) <= 300

    def test_post_skeet_api_error_returns_none(self, bot):
        """post_skeet returns None when the API call fails."""
        bot.client.send_post.side_effect = Exception("Network error")

        result = bot.post_skeet("Test post")
        assert result is None


class TestBlueskyBotImagePosting:
    """Tests for BlueskyBot image upload and posting."""

    @pytest.fixture
    def bot(self, bluesky_env):
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()
            yield bot

    def test_post_skeet_with_image_success(self, bot, tmp_path):
        """post_skeet_with_image reads file and posts with image data."""
        # Create a temporary image file
        img_file = tmp_path / "test_image.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        bot.client.send_image.return_value = Mock(
            uri="at://did:plc:abc/app.bsky.feed.post/789",
            cid="bafyimg789",
        )

        result = bot.post_skeet_with_image("Cat news!", str(img_file))
        assert result is not None
        assert result["uri"] == "at://did:plc:abc/app.bsky.feed.post/789"

        # Verify send_image was called with binary data
        call_kwargs = bot.client.send_image.call_args[1]
        assert call_kwargs["text"] == "Cat news!"
        assert isinstance(call_kwargs["image"], bytes)
        assert call_kwargs["image_alt"] == "News reporter cat illustration"

    def test_post_skeet_with_image_file_not_found(self, bot):
        """post_skeet_with_image returns None for missing image file."""
        result = bot.post_skeet_with_image("Cat news!", "/nonexistent/image.png")
        assert result is None

    def test_post_skeet_with_image_api_error(self, bot, tmp_path):
        """post_skeet_with_image returns None on API failure."""
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        bot.client.send_image.side_effect = Exception("Upload failed")

        result = bot.post_skeet_with_image("Text", str(img_file))
        assert result is None

    def test_post_skeet_with_image_truncates_long_text(self, bot, tmp_path):
        """post_skeet_with_image truncates text exceeding 300 chars."""
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        bot.client.send_image.return_value = Mock(
            uri="at://did:plc:abc/app.bsky.feed.post/trunc",
            cid="bafytrunc",
        )

        long_text = "Word. " * 60  # > 300 chars
        result = bot.post_skeet_with_image(long_text, str(img_file))
        assert result is not None
        sent_text = bot.client.send_image.call_args[1]["text"]
        assert len(sent_text) <= 300


class TestBlueskyBotReplies:
    """Tests for BlueskyBot reply functionality."""

    @pytest.fixture
    def bot(self, bluesky_env):
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()
            yield bot

    def test_reply_to_skeet_success(self, bot):
        """reply_to_skeet fetches parent, creates reference, and posts reply."""
        parent_uri = "at://did:plc:abc/app.bsky.feed.post/parent1"

        # Mock get_post_thread
        mock_thread = Mock()
        mock_thread.thread.post.cid = "parentcid123"
        bot.client.app.bsky.feed.get_post_thread.return_value = mock_thread

        bot.client.send_post.return_value = Mock(
            uri="at://did:plc:abc/app.bsky.feed.post/reply1",
            cid="replycid123",
        )

        result = bot.reply_to_skeet(parent_uri, "Great reporting!")
        assert result is not None
        assert result["uri"] == "at://did:plc:abc/app.bsky.feed.post/reply1"
        bot.client.send_post.assert_called_once()

    def test_reply_to_skeet_invalid_uri(self, bot):
        """reply_to_skeet returns None for malformed AT URI."""
        result = bot.reply_to_skeet("invalid-uri", "Reply text")
        assert result is None

    def test_reply_to_skeet_api_error(self, bot):
        """reply_to_skeet returns None when API fails."""
        parent_uri = "at://did:plc:abc/app.bsky.feed.post/parent2"
        bot.client.app.bsky.feed.get_post_thread.side_effect = Exception("API error")

        result = bot.reply_to_skeet(parent_uri, "Reply text")
        assert result is None

    def test_reply_to_skeet_with_link_url_too_long(self, bot):
        """reply_to_skeet_with_link returns None if URL exceeds 300 chars."""
        long_url = "https://example.com/" + "a" * 300
        parent_uri = "at://did:plc:abc/app.bsky.feed.post/parent3"

        result = bot.reply_to_skeet_with_link(parent_uri, long_url)
        assert result is None


class TestBlueskyBotEngagement:
    """Tests for BlueskyBot like and notification methods."""

    @pytest.fixture
    def bot(self, bluesky_env):
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()
            yield bot

    def test_is_post_liked_true(self, bot):
        """is_post_liked returns True when viewer.like is set."""
        mock_post = Mock()
        mock_post.viewer.like = "at://did:plc:abc/app.bsky.feed.like/xyz"
        bot.client.app.bsky.feed.get_posts.return_value = Mock(posts=[mock_post])

        assert bot.is_post_liked("at://did:plc:abc/app.bsky.feed.post/123") is True

    def test_is_post_liked_false(self, bot):
        """is_post_liked returns False when viewer.like is None."""
        mock_post = Mock()
        mock_post.viewer.like = None
        bot.client.app.bsky.feed.get_posts.return_value = Mock(posts=[mock_post])

        assert bot.is_post_liked("at://did:plc:abc/app.bsky.feed.post/123") is False

    def test_is_post_liked_api_error_returns_false(self, bot):
        """is_post_liked returns False (not True) on API errors."""
        bot.client.app.bsky.feed.get_posts.side_effect = Exception("API down")
        assert bot.is_post_liked("at://some/post/uri") is False

    def test_like_post_success(self, bot):
        """like_post calls client.like and returns True."""
        # is_post_liked returns False (not already liked)
        mock_post = Mock()
        mock_post.viewer.like = None
        bot.client.app.bsky.feed.get_posts.return_value = Mock(posts=[mock_post])

        result = bot.like_post("at://did:plc:abc/app.bsky.feed.post/1", "cid1")
        assert result is True
        bot.client.like.assert_called_once_with(
            "at://did:plc:abc/app.bsky.feed.post/1", "cid1"
        )

    def test_like_post_already_liked(self, bot):
        """like_post returns False if post was already liked."""
        mock_post = Mock()
        mock_post.viewer.like = "at://did:plc:abc/app.bsky.feed.like/existing"
        bot.client.app.bsky.feed.get_posts.return_value = Mock(posts=[mock_post])

        result = bot.like_post("at://did:plc:abc/app.bsky.feed.post/1", "cid1")
        assert result is False
        bot.client.like.assert_not_called()

    def test_get_notifications_success(self, bot):
        """get_notifications returns a list of notification objects."""
        notif1 = Mock(reason="mention", uri="at://mention/1")
        notif2 = Mock(reason="like", uri="at://like/1")
        bot.client.app.bsky.notification.list_notifications.return_value = Mock(
            notifications=[notif1, notif2]
        )

        result = bot.get_notifications(limit=10)
        assert len(result) == 2

    def test_get_notifications_empty(self, bot):
        """get_notifications returns empty list when none exist."""
        bot.client.app.bsky.notification.list_notifications.return_value = Mock(
            notifications=None
        )
        assert bot.get_notifications() == []

    def test_get_notifications_api_error(self, bot):
        """get_notifications returns empty list on API error."""
        bot.client.app.bsky.notification.list_notifications.side_effect = Exception(
            "error"
        )
        assert bot.get_notifications() == []

    def test_get_mentions_filters_correctly(self, bot):
        """get_mentions only returns mention and reply notifications."""
        notifs = [
            Mock(reason="mention", uri="at://m/1", cid="c1",
                 author=Mock(handle="user1"), indexed_at="2025-01-01", is_read=False),
            Mock(reason="like", uri="at://l/1", cid="c2",
                 author=Mock(handle="user2"), indexed_at="2025-01-01", is_read=False),
            Mock(reason="reply", uri="at://r/1", cid="c3",
                 author=Mock(handle="user3"), indexed_at="2025-01-01", is_read=True),
            Mock(reason="repost", uri="at://rp/1", cid="c4",
                 author=Mock(handle="user4"), indexed_at="2025-01-01", is_read=False),
        ]
        bot.client.app.bsky.notification.list_notifications.return_value = Mock(
            notifications=notifs
        )

        mentions = bot.get_mentions()
        assert len(mentions) == 2
        assert mentions[0]["reason"] == "mention"
        assert mentions[1]["reason"] == "reply"


class TestBlueskyBotDeletion:
    """Tests for BlueskyBot post deletion."""

    @pytest.fixture
    def bot(self, bluesky_env):
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()
            yield bot

    def test_delete_post_success(self, bot):
        """delete_post returns True on success."""
        uri = "at://did:plc:abc/app.bsky.feed.post/rkey123"
        result = bot.delete_post(uri)
        assert result is True
        bot.client.com.atproto.repo.delete_record.assert_called_once()

    def test_delete_post_invalid_uri(self, bot):
        """delete_post returns False for malformed URI."""
        result = bot.delete_post("bad-uri")
        assert result is False

    def test_delete_post_api_error(self, bot):
        """delete_post returns False on API failure."""
        uri = "at://did:plc:abc/app.bsky.feed.post/rkey456"
        bot.client.com.atproto.repo.delete_record.side_effect = Exception("error")
        result = bot.delete_post(uri)
        assert result is False


# =========================================================================
# Twitter/X Bot Tests
# =========================================================================

class TestTwitterBotAuthentication:
    """Tests for TwitterBot credential validation and client setup."""

    def test_missing_credentials_raises(self):
        """TwitterBot raises ValueError when env vars are absent."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Missing X API credentials"):
                from twitter_bot import TwitterBot
                TwitterBot()

    def test_partial_credentials_raises(self):
        """TwitterBot raises when only some credentials are set."""
        with patch.dict(os.environ, {
            "X_API_KEY": "key",
            "X_API_SECRET": "secret",
            # Missing access token, access token secret, bearer token
        }, clear=True):
            with pytest.raises(ValueError, match="Missing X API credentials"):
                from twitter_bot import TwitterBot
                TwitterBot()

    @patch("twitter_bot.tweepy.API")
    @patch("twitter_bot.tweepy.OAuth1UserHandler")
    @patch("twitter_bot.tweepy.Client")
    def test_successful_init(self, mock_client_cls, mock_auth_cls, mock_api_cls, twitter_env):
        """TwitterBot initializes both v2 Client and v1.1 API."""
        from twitter_bot import TwitterBot
        bot = TwitterBot()

        mock_client_cls.assert_called_once_with(
            bearer_token="fake-bearer-token",
            consumer_key="fake-api-key",
            consumer_secret="fake-api-secret",
            access_token="fake-access-token",
            access_token_secret="fake-access-token-secret",
            wait_on_rate_limit=False,
        )
        mock_auth_cls.assert_called_once()
        mock_api_cls.assert_called_once()
        assert bot.client is mock_client_cls.return_value
        assert bot.api_v1 is mock_api_cls.return_value


class TestTwitterBotTweetPosting:
    """Tests for TwitterBot tweet creation."""

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

    def test_post_tweet_success(self, bot):
        """post_tweet returns response data on success."""
        bot.client.create_tweet.return_value = Mock(
            data={"id": "12345", "text": "Breaking mews!"}
        )

        result = bot.post_tweet("Breaking mews!")
        assert result == {"id": "12345", "text": "Breaking mews!"}
        bot.client.create_tweet.assert_called_once_with(text="Breaking mews!")

    def test_post_tweet_truncates_long_text(self, bot):
        """post_tweet truncates text exceeding 280 chars."""
        bot.client.create_tweet.return_value = Mock(
            data={"id": "99999", "text": "truncated"}
        )

        long_text = "Sentence one. " * 25  # > 280 chars
        result = bot.post_tweet(long_text)
        assert result is not None
        sent_text = bot.client.create_tweet.call_args[1]["text"]
        assert len(sent_text) <= 280

    def test_post_tweet_rate_limit_raises(self, bot):
        """post_tweet re-raises TooManyRequests for CI/CD failure."""
        import tweepy
        bot.client.create_tweet.side_effect = tweepy.TooManyRequests(
            _make_rate_limit_response()
        )

        with pytest.raises(tweepy.TooManyRequests):
            bot.post_tweet("Test tweet")

    def test_post_tweet_tweepy_error_returns_none(self, bot):
        """post_tweet returns None on general TweepyException."""
        import tweepy
        error = tweepy.TweepyException("Something went wrong")
        bot.client.create_tweet.side_effect = error

        result = bot.post_tweet("Test tweet")
        assert result is None

    def test_post_tweet_tweepy_error_with_response(self, bot):
        """post_tweet logs response details when available."""
        import tweepy
        error = tweepy.TweepyException("Error")
        error.response = Mock(status_code=403, text="Forbidden")
        bot.client.create_tweet.side_effect = error

        result = bot.post_tweet("Test tweet")
        assert result is None


class TestTwitterBotImagePosting:
    """Tests for TwitterBot media upload and image tweet posting."""

    @pytest.fixture
    def bot(self, twitter_env):
        with patch("twitter_bot.tweepy.API") as mock_api_cls, \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_api_v1 = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_api_cls.return_value = mock_api_v1
            from twitter_bot import TwitterBot
            bot = TwitterBot()
            yield bot

    def test_post_tweet_with_image_success(self, bot, tmp_path):
        """post_tweet_with_image uploads media then creates tweet with media_id."""
        img_file = tmp_path / "cat.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        bot.api_v1.media_upload.return_value = Mock(media_id=987654)
        bot.client.create_tweet.return_value = Mock(
            data={"id": "tweet_img_1", "text": "Cat news with image!"}
        )

        result = bot.post_tweet_with_image("Cat news with image!", str(img_file))
        assert result == {"id": "tweet_img_1", "text": "Cat news with image!"}
        bot.api_v1.media_upload.assert_called_once_with(filename=str(img_file))
        bot.client.create_tweet.assert_called_once_with(
            text="Cat news with image!",
            media_ids=[987654],
        )

    def test_post_tweet_with_image_file_not_found(self, bot):
        """post_tweet_with_image returns None for missing file."""
        bot.api_v1.media_upload.side_effect = FileNotFoundError("No such file")

        result = bot.post_tweet_with_image("Text", "/nonexistent/image.png")
        assert result is None

    def test_post_tweet_with_image_rate_limit_raises(self, bot, tmp_path):
        """post_tweet_with_image re-raises TooManyRequests."""
        import tweepy

        img_file = tmp_path / "cat.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        bot.api_v1.media_upload.return_value = Mock(media_id=111)
        bot.client.create_tweet.side_effect = tweepy.TooManyRequests(
            _make_rate_limit_response()
        )

        with pytest.raises(tweepy.TooManyRequests):
            bot.post_tweet_with_image("Text", str(img_file))

    def test_post_tweet_with_image_truncates_long_text(self, bot, tmp_path):
        """post_tweet_with_image truncates text exceeding 280 chars."""
        img_file = tmp_path / "cat.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        bot.api_v1.media_upload.return_value = Mock(media_id=222)
        bot.client.create_tweet.return_value = Mock(
            data={"id": "trunc_img", "text": "truncated"}
        )

        long_text = "Word. " * 55  # > 280 chars
        result = bot.post_tweet_with_image(long_text, str(img_file))
        assert result is not None
        sent_text = bot.client.create_tweet.call_args[1]["text"]
        assert len(sent_text) <= 280


class TestTwitterBotReplies:
    """Tests for TwitterBot reply functionality."""

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

    def test_reply_to_tweet_success(self, bot):
        """reply_to_tweet posts with in_reply_to_tweet_id."""
        bot.client.create_tweet.return_value = Mock(
            data={"id": "reply1", "text": "Nice scoop!"}
        )

        result = bot.reply_to_tweet("original_id_123", "Nice scoop!")
        assert result == {"id": "reply1", "text": "Nice scoop!"}
        bot.client.create_tweet.assert_called_once_with(
            text="Nice scoop!",
            in_reply_to_tweet_id="original_id_123",
        )

    def test_reply_to_tweet_rate_limit_raises(self, bot):
        """reply_to_tweet re-raises TooManyRequests."""
        import tweepy
        bot.client.create_tweet.side_effect = tweepy.TooManyRequests(
            _make_rate_limit_response()
        )
        with pytest.raises(tweepy.TooManyRequests):
            bot.reply_to_tweet("id", "text")

    def test_reply_to_tweet_truncates_long_text(self, bot):
        """reply_to_tweet truncates text exceeding 280 chars."""
        bot.client.create_tweet.return_value = Mock(
            data={"id": "reply_trunc", "text": "truncated"}
        )

        long_text = "A" * 300
        result = bot.reply_to_tweet("tid", long_text)
        assert result is not None
        sent_text = bot.client.create_tweet.call_args[1]["text"]
        assert len(sent_text) <= 280


class TestTwitterBotDeletion:
    """Tests for TwitterBot tweet deletion."""

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

    def test_delete_tweet_success(self, bot):
        """delete_tweet returns True on success."""
        result = bot.delete_tweet("tweet_to_delete_123")
        assert result is True
        bot.client.delete_tweet.assert_called_once_with("tweet_to_delete_123")

    def test_delete_tweet_api_error(self, bot):
        """delete_tweet returns False on API failure."""
        import tweepy
        bot.client.delete_tweet.side_effect = tweepy.TweepyException("Error")
        result = bot.delete_tweet("tweet_id")
        assert result is False


class TestTwitterBotMentionsAndTimeline:
    """Tests for TwitterBot get_mentions, get_timeline, and get_trending_topics."""

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

    def test_get_mentions_success(self, bot):
        """get_mentions returns mention data."""
        bot.client.get_me.return_value = Mock(data=Mock(id="user_id_1"))
        mock_mentions = [Mock(text="@mewscast great post")]
        bot.client.get_users_mentions.return_value = Mock(data=mock_mentions)

        result = bot.get_mentions(max_results=5)
        assert len(result) == 1
        bot.client.get_users_mentions.assert_called_once_with(
            id="user_id_1", max_results=5
        )

    def test_get_mentions_empty(self, bot):
        """get_mentions returns empty list when no mentions exist."""
        bot.client.get_me.return_value = Mock(data=Mock(id="uid"))
        bot.client.get_users_mentions.return_value = Mock(data=None)

        result = bot.get_mentions()
        assert result == []

    def test_get_mentions_api_error(self, bot):
        """get_mentions returns empty list on API error."""
        import tweepy
        bot.client.get_me.side_effect = tweepy.TweepyException("Error")
        assert bot.get_mentions() == []

    def test_get_timeline_success(self, bot):
        """get_timeline returns user tweets."""
        bot.client.get_me.return_value = Mock(data=Mock(id="uid"))
        bot.client.get_users_tweets.return_value = Mock(
            data=[Mock(text="My tweet")]
        )
        result = bot.get_timeline(max_results=3)
        assert len(result) == 1

    def test_get_timeline_caps_at_100(self, bot):
        """get_timeline caps max_results at 100."""
        bot.client.get_me.return_value = Mock(data=Mock(id="uid"))
        bot.client.get_users_tweets.return_value = Mock(data=[])

        bot.get_timeline(max_results=200)
        bot.client.get_users_tweets.assert_called_once_with(
            id="uid", max_results=100
        )

    def test_get_trending_topics_with_hashtags(self, bot):
        """get_trending_topics extracts hashtags from popular tweets."""
        mock_tweet = Mock()
        mock_tweet.entities = {
            "hashtags": [{"tag": "CatNews"}, {"tag": "BreakingMews"}]
        }
        bot.client.search_recent_tweets.return_value = Mock(data=[mock_tweet])

        result = bot.get_trending_topics(count=5)
        assert "CatNews" in result
        assert "BreakingMews" in result

    def test_get_trending_topics_fallback(self, bot):
        """get_trending_topics returns fallback topics when search fails."""
        import tweepy
        bot.client.search_recent_tweets.side_effect = tweepy.TweepyException(
            "Not available"
        )

        result = bot.get_trending_topics(count=3)
        assert len(result) == 3
        assert "breaking news" in result


# =========================================================================
# Image Generator Tests
# =========================================================================

class TestImageGenerator:
    """Tests for ImageGenerator xAI Grok integration."""

    def test_missing_api_key_raises(self):
        """ImageGenerator raises ValueError without X_AI_API_KEY."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Missing X_AI_API_KEY"):
                from image_generator import ImageGenerator
                ImageGenerator()

    @patch("image_generator.OpenAI")
    def test_init_configures_xai_base_url(self, mock_openai_cls, image_gen_env):
        """ImageGenerator points the OpenAI client at xAI base URL."""
        from image_generator import ImageGenerator
        gen = ImageGenerator()

        mock_openai_cls.assert_called_once_with(
            api_key="fake-xai-key",
            base_url="https://api.x.ai/v1",
        )
        assert gen.model == "grok-imagine-image"

    @patch("image_generator.requests.get")
    @patch("image_generator.OpenAI")
    def test_generate_image_success(self, mock_openai_cls, mock_requests_get,
                                     image_gen_env, tmp_path):
        """generate_image creates image, downloads it, and saves to disk."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Mock API response with image URL
        mock_image_data = Mock()
        mock_image_data.url = "https://example.com/generated_cat.png"
        mock_client.images.generate.return_value = Mock(data=[mock_image_data])

        # Mock HTTP download
        mock_response = Mock()
        mock_response.content = b"\x89PNG\r\n\x1a\nFAKEIMAGEDATA"
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response

        from image_generator import ImageGenerator
        gen = ImageGenerator()

        save_path = str(tmp_path / "output.png")
        result = gen.generate_image("A cat reporting news", save_path=save_path)

        assert result == save_path
        # Verify the file was written
        assert os.path.exists(save_path)
        with open(save_path, "rb") as f:
            assert f.read() == b"\x89PNG\r\n\x1a\nFAKEIMAGEDATA"

        # Verify API was called with correct parameters
        mock_client.images.generate.assert_called_once_with(
            model="grok-imagine-image",
            prompt="A cat reporting news",
            n=1,
            extra_body={"aspect_ratio": "16:9"},
        )

    @patch("image_generator.OpenAI")
    def test_generate_image_api_error_returns_none(self, mock_openai_cls, image_gen_env):
        """generate_image returns None when the API call fails."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.images.generate.side_effect = Exception("API timeout")

        from image_generator import ImageGenerator
        gen = ImageGenerator()

        result = gen.generate_image("prompt text")
        assert result is None

    @patch("image_generator.requests.get")
    @patch("image_generator.OpenAI")
    def test_generate_image_download_error_returns_none(
        self, mock_openai_cls, mock_requests_get, image_gen_env
    ):
        """generate_image returns None when image download fails."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_image_data = Mock()
        mock_image_data.url = "https://example.com/image.png"
        mock_client.images.generate.return_value = Mock(data=[mock_image_data])

        mock_requests_get.side_effect = Exception("Connection reset")

        from image_generator import ImageGenerator
        gen = ImageGenerator()

        result = gen.generate_image("prompt")
        assert result is None

    @patch("image_generator.requests.get")
    @patch("image_generator.OpenAI")
    def test_generate_image_default_save_path(self, mock_openai_cls, mock_requests_get,
                                               image_gen_env):
        """generate_image uses 'temp_image.png' as default save path."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_image_data = Mock()
        mock_image_data.url = "https://example.com/img.png"
        mock_client.images.generate.return_value = Mock(data=[mock_image_data])

        mock_response = Mock()
        mock_response.content = b"image_bytes"
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response

        from image_generator import ImageGenerator
        gen = ImageGenerator()

        # Use a patched open so we don't write to real filesystem
        with patch("builtins.open", mock_open()):
            result = gen.generate_image("A cat with a microphone")

        assert result == "temp_image.png"


# =========================================================================
# Content Generator Tests
# =========================================================================

class TestContentGenerator:
    """Tests for ContentGenerator tweet/content generation."""

    @pytest.fixture
    def generator(self, anthropic_env, sample_config_yaml):
        """Create a ContentGenerator with mocked Anthropic client."""
        with patch("src.content_generator.Anthropic") as mock_cls:
            from src.content_generator import ContentGenerator
            gen = ContentGenerator(config_path=sample_config_yaml)
            gen.client = MagicMock()
            yield gen

    def test_generate_tweet_basic(self, generator):
        """generate_tweet returns dict with tweet, needs_source_reply, and story_metadata."""
        mock_response = Mock()
        mock_response.content = [Mock(text="Breaking mews from the perch!")]
        generator.client.messages.create.return_value = mock_response

        result = generator.generate_tweet(topic="stock market volatility")
        assert "tweet" in result
        assert "needs_source_reply" in result
        assert result["needs_source_reply"] is False
        assert "story_metadata" in result

    def test_generate_tweet_with_story_metadata(self, generator):
        """generate_tweet sets needs_source_reply=True when story_metadata provided."""
        mock_response = Mock()
        mock_response.content = [Mock(text="Cat news about politics!")]
        generator.client.messages.create.return_value = mock_response

        story = {
            "title": "Big political scandal",
            "source": "Reuters",
            "article_content": "The scandal involved many officials.",
            "url": "https://example.com/scandal",
        }
        result = generator.generate_tweet(
            trending_topic="political scandal", story_metadata=story
        )
        assert result["needs_source_reply"] is True
        assert result["story_metadata"] == story

    def test_generate_tweet_removes_quotes(self, generator):
        """generate_tweet strips wrapping quotes from Claude output."""
        mock_response = Mock()
        mock_response.content = [Mock(text='"Quoted tweet text"')]
        generator.client.messages.create.return_value = mock_response

        result = generator.generate_tweet(topic="tech news")
        assert not result["tweet"].startswith('"')
        assert not result["tweet"].endswith('"')

    def test_generate_tweet_api_error_returns_fallback(self, generator):
        """generate_tweet returns fallback content when Claude API fails."""
        generator.client.messages.create.side_effect = Exception("API down")

        result = generator.generate_tweet(topic="economy")
        assert result is not None
        assert "tweet" in result
        assert "economy" in result["tweet"]
        assert result["needs_source_reply"] is False

    def test_generate_tweet_validation_failure_returns_none(self, generator):
        """generate_tweet returns None when content validation fails."""
        mock_response = Mock()
        # This tweet contains a prohibited meta-commentary pattern
        mock_response.content = [Mock(text="I cannot generate content about this topic")]
        generator.client.messages.create.return_value = mock_response

        result = generator.generate_tweet(
            trending_topic="test",
            story_metadata={"title": "Test", "article_content": "Content", "source": "Src"},
        )
        assert result is None

    def test_validate_tweet_content_blocks_meta_commentary(self, generator):
        """_validate_tweet_content rejects meta-commentary patterns."""
        result = generator._validate_tweet_content("I can't access the article")
        assert result["valid"] is False
        assert "meta-commentary" in result["reason"]

    def test_validate_tweet_content_blocks_contradictions(self, generator):
        """_validate_tweet_content rejects news-contradiction patterns."""
        result = generator._validate_tweet_content("This never happened and is complete fiction")
        assert result["valid"] is False
        assert "contradiction" in result["reason"]

    def test_validate_tweet_content_blocks_temporal_skepticism(self, generator):
        """_validate_tweet_content rejects temporal skepticism patterns."""
        result = generator._validate_tweet_content("The date says 2025 but that's a typo")
        assert result["valid"] is False

    def test_validate_tweet_content_allows_valid_tweet(self, generator):
        """_validate_tweet_content passes a normal news cat tweet."""
        result = generator._validate_tweet_content(
            "Breaking mews from this cat's perch: stocks are volatile today."
        )
        assert result["valid"] is True
        assert result["reason"] is None

    def test_generate_source_reply_with_url(self, generator):
        """generate_source_reply returns just the URL when available."""
        metadata = {
            "title": "Breaking Story",
            "url": "https://example.com/story",
            "source": "Reuters",
        }
        reply = generator.generate_source_reply("Original tweet", metadata)
        assert reply == "https://example.com/story"

    def test_generate_source_reply_without_url(self, generator):
        """generate_source_reply builds text fallback without URL."""
        metadata = {
            "title": "Breaking Story",
            "source": "Reuters",
            "context": "Story context here",
        }
        reply = generator.generate_source_reply("Original tweet", metadata)
        assert "Breaking Story" in reply
        assert "Reuters" in reply

    def test_generate_reply_success(self, generator):
        """generate_reply returns a cat-reporter-style reply."""
        mock_response = Mock()
        mock_response.content = [Mock(text="This cat agrees, great point!")]
        generator.client.messages.create.return_value = mock_response

        reply = generator.generate_reply("Original post about tech")
        assert "This cat agrees" in reply

    def test_generate_reply_api_error_returns_fallback(self, generator):
        """generate_reply returns fallback text when Claude API fails."""
        generator.client.messages.create.side_effect = Exception("Error")

        reply = generator.generate_reply("Some tweet")
        assert "reporter" in reply.lower() or "breaking" in reply.lower()

    def test_generate_image_prompt_success(self, generator):
        """generate_image_prompt returns a prompt for Grok."""
        mock_response = Mock()
        mock_response.content = [Mock(text="Cat reporter at desk with breaking news")]
        generator.client.messages.create.return_value = mock_response

        prompt = generator.generate_image_prompt("politics", "A tweet about politics")
        assert "Cat reporter" in prompt

    def test_generate_image_prompt_truncated_to_200_chars(self, generator):
        """generate_image_prompt truncates output to 200 chars for Grok."""
        mock_response = Mock()
        mock_response.content = [Mock(text="X" * 300)]
        generator.client.messages.create.return_value = mock_response

        prompt = generator.generate_image_prompt("topic", "tweet text")
        assert len(prompt) <= 200

    def test_generate_image_prompt_api_error_returns_fallback(self, generator):
        """generate_image_prompt returns fallback on API error."""
        generator.client.messages.create.side_effect = Exception("Error")

        prompt = generator.generate_image_prompt("economy", "tweet about economy")
        assert "cat" in prompt.lower() or "detective" in prompt.lower()
        assert "economy" in prompt

    def test_vocab_selection_matches_topic(self, generator):
        """_select_vocab_for_story returns topic-matched phrases."""
        result = generator._select_vocab_for_story("President signs new bill")
        # Should match "politics" category due to "president" keyword
        assert isinstance(result, str)
        assert len(result) > 0

    def test_vocab_selection_no_match_uses_universal(self, generator):
        """_select_vocab_for_story falls back to universal phrases."""
        result = generator._select_vocab_for_story("Obscure topic with no keyword matches")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_analyze_media_framing_no_content(self, generator):
        """analyze_media_framing returns no issues when article_content is missing."""
        result = generator.analyze_media_framing({"title": "Test"})
        assert result["has_issues"] is False

    def test_analyze_media_framing_api_error(self, generator):
        """analyze_media_framing returns no issues on API error."""
        generator.client.messages.create.side_effect = Exception("Error")
        result = generator.analyze_media_framing({
            "title": "Test",
            "article_content": "Content here",
            "source": "Src",
        })
        assert result["has_issues"] is False


class TestTruncateAtSentence:
    """Tests for the _truncate_at_sentence utility function."""

    def test_short_text_unchanged(self):
        """Text under max_length is returned as-is."""
        from content_generator import _truncate_at_sentence
        assert _truncate_at_sentence("Short text.", 100) == "Short text."

    def test_truncates_at_sentence_boundary(self):
        """Text is cut at the last complete sentence within limit."""
        from content_generator import _truncate_at_sentence
        text = "First sentence. Second sentence. Third sentence that is very long."
        result = _truncate_at_sentence(text, 35)
        assert result == "First sentence. Second sentence."

    def test_truncates_at_exclamation(self):
        """Truncation works with ! sentence endings."""
        from content_generator import _truncate_at_sentence
        text = "Breaking mews! This is huge! More details coming soon in an update."
        result = _truncate_at_sentence(text, 30)
        assert result.endswith("!")

    def test_falls_back_to_space(self):
        """Falls back to word boundary when no sentence boundary is found."""
        from content_generator import _truncate_at_sentence
        text = "Thisisaverylongwordwithoutspaces but then more words"
        result = _truncate_at_sentence(text, 45)
        assert len(result) <= 45


# =========================================================================
# Configuration Loading Tests
# =========================================================================

class TestConfigurationLoading:
    """Tests for config.yaml loading and structure."""

    def test_config_file_exists(self):
        """config.yaml exists at project root."""
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        assert os.path.exists(config_path)

    def test_config_loads_valid_yaml(self):
        """config.yaml parses as valid YAML with expected top-level keys."""
        import yaml
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        assert "bot" in config
        assert "content" in config
        assert "safety" in config
        assert "scheduling" in config
        assert "deduplication" in config

    def test_config_content_section(self):
        """config.yaml content section has required fields."""
        import yaml
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        content = config["content"]
        assert "persona" in content
        assert "topics" in content
        assert isinstance(content["topics"], list)
        assert len(content["topics"]) > 0
        assert "style" in content
        assert "max_length" in content
        assert "model" in content
        assert content["max_length"] > 0

    def test_config_deduplication_section(self):
        """config.yaml deduplication section has required fields."""
        import yaml
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        dedup = config["deduplication"]
        assert dedup["enabled"] is True
        assert "topic_cooldown_hours" in dedup
        assert "topic_similarity_threshold" in dedup
        assert "url_deduplication" in dedup
        assert "max_history_days" in dedup
        assert "update_keywords" in dedup
        assert isinstance(dedup["update_keywords"], list)

    def test_config_safety_section(self):
        """config.yaml safety section has avoid_topics."""
        import yaml
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        safety = config["safety"]
        assert "avoid_topics" in safety
        assert isinstance(safety["avoid_topics"], list)

    def test_config_cat_vocabulary_structure(self):
        """config.yaml has structured cat_vocabulary_by_topic with keywords and phrases."""
        import yaml
        config_path = os.path.join(_PROJECT_ROOT, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        vocab = config["content"]["cat_vocabulary_by_topic"]
        assert isinstance(vocab, dict)
        assert len(vocab) > 0
        # Each category should have keywords and phrases
        for category, data in vocab.items():
            assert "keywords" in data, f"Category '{category}' missing keywords"
            assert "phrases" in data, f"Category '{category}' missing phrases"
            assert isinstance(data["keywords"], list)
            assert isinstance(data["phrases"], list)
            assert len(data["keywords"]) > 0
            assert len(data["phrases"]) > 0


# =========================================================================
# Post Tracker / Deduplication Tests
# =========================================================================

class TestPostTracker:
    """Tests for PostTracker deduplication logic."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create a PostTracker with an empty temp history file."""
        from post_tracker import PostTracker
        history_file = str(tmp_path / "test_history.json")
        config = {
            "enabled": True,
            "topic_cooldown_hours": 72,
            "topic_similarity_threshold": 0.40,
            "content_cooldown_hours": 72,
            "content_similarity_threshold": 0.65,
            "url_deduplication": True,
            "max_history_days": 30,
            "allow_updates": True,
            "update_keywords": ["update", "breaking"],
        }
        return PostTracker(history_file=history_file, config=config)

    def test_empty_history_no_duplicates(self, tracker):
        """No duplicates detected with empty history."""
        story = {"title": "New Story", "url": "https://example.com/new"}
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False
        assert result["is_update"] is False

    def test_exact_url_duplicate_detected(self, tracker):
        """Exact URL match is flagged as duplicate."""
        story = {
            "title": "Original Story",
            "url": "https://example.com/story1",
            "source": "Reuters",
        }
        tracker.record_post(story, post_content="Original post content")

        # Same URL should be duplicate
        story2 = {
            "title": "Different Title Same URL",
            "url": "https://example.com/story1",
            "source": "CNN",
        }
        result = tracker.check_story_status(story2)
        assert result["is_duplicate"] is True

    def test_different_url_not_duplicate(self, tracker):
        """Different URL is not flagged as duplicate."""
        story1 = {
            "title": "Federal Reserve raises interest rates amid inflation concerns",
            "url": "https://example.com/alpha",
            "source": "Reuters",
        }
        tracker.record_post(story1, post_content="Fed raises rates amid inflation")

        story2 = {
            "title": "SpaceX launches Starship rocket on maiden voyage to Mars",
            "url": "https://example.com/beta",
            "source": "CNN",
        }
        result = tracker.check_story_status(story2)
        assert result["is_duplicate"] is False

    def test_record_post_persists(self, tracker):
        """record_post saves to disk and is readable on next load."""
        story = {
            "title": "Persisted Story",
            "url": "https://example.com/persist",
            "source": "AP",
        }
        tracker.record_post(
            story,
            post_content="Content here",
            tweet_id="t123",
            bluesky_uri="at://did:plc:abc/app.bsky.feed.post/456",
        )

        # Re-load from same file
        from post_tracker import PostTracker
        tracker2 = PostTracker(
            history_file=tracker.history_file, config=tracker.config
        )
        assert len(tracker2.posts) == 1
        assert tracker2.posts[0]["url"] == "https://example.com/persist"
        assert tracker2.posts[0]["x_tweet_id"] == "t123"
        assert tracker2.posts[0]["bluesky_uri"] == "at://did:plc:abc/app.bsky.feed.post/456"

    def test_is_update_story_detection(self, tracker):
        """_is_update_story detects update keywords in titles."""
        assert tracker._is_update_story("BREAKING: New details emerge") is True
        assert tracker._is_update_story("Update on the investigation") is True
        assert tracker._is_update_story("Stocks rise on Monday") is False

    def test_dedup_disabled_passes_everything(self, tmp_path):
        """When enabled=False, nothing is flagged as duplicate."""
        from post_tracker import PostTracker
        tracker = PostTracker(
            history_file=str(tmp_path / "h.json"),
            config={"enabled": False},
        )
        story = {"title": "Any Story", "url": "https://example.com"}
        tracker.record_post(story, post_content="content")

        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False


# =========================================================================
# Main Pipeline Integration Tests
# =========================================================================

class TestMainPipeline:
    """Tests for the main.py orchestration pipeline."""

    def test_main_entry_point_scheduled_mode(self, all_env):
        """main() in 'scheduled' mode calls post_scheduled_tweet."""
        with patch("src.main.post_scheduled_tweet", return_value=True) as mock_post, \
             patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py", "scheduled"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        mock_post.assert_called_once()
        assert exc_info.value.code == 0

    def test_main_entry_point_reply_mode(self, all_env):
        """main() in 'reply' mode calls reply_to_mentions."""
        with patch("src.main.reply_to_mentions", return_value=True) as mock_reply, \
             patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py", "reply"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        mock_reply.assert_called_once()
        assert exc_info.value.code == 0

    def test_main_entry_point_both_mode(self, all_env):
        """main() in 'both' mode calls both post and reply."""
        with patch("src.main.post_scheduled_tweet", return_value=True) as mock_post, \
             patch("src.main.reply_to_mentions", return_value=True) as mock_reply, \
             patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py", "both"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        mock_post.assert_called_once()
        mock_reply.assert_called_once()
        assert exc_info.value.code == 0

    def test_main_failure_exits_nonzero(self, all_env):
        """main() exits with code 1 when posting fails."""
        with patch("src.main.post_scheduled_tweet", return_value=False) as mock_post, \
             patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py", "scheduled"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        assert exc_info.value.code == 1

    def test_main_unknown_mode_exits(self, all_env):
        """main() exits with code 1 for unknown mode."""
        with patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py", "invalidmode"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        assert exc_info.value.code == 1

    def test_main_defaults_to_scheduled_via_env(self, all_env):
        """main() defaults to 'scheduled' mode from BOT_MODE env var."""
        with patch.dict(os.environ, {"BOT_MODE": "scheduled"}), \
             patch("src.main.post_scheduled_tweet", return_value=True) as mock_post, \
             patch("src.main.load_dotenv"), \
             patch("sys.argv", ["main.py"]), \
             pytest.raises(SystemExit) as exc_info:
            from src.main import main
            main()
        mock_post.assert_called_once()
        assert exc_info.value.code == 0


class TestPostScheduledTweet:
    """Tests for the post_scheduled_tweet pipeline function."""

    @pytest.fixture
    def mock_all_deps(self, all_env, sample_config):
        """Patch all dependencies used by post_scheduled_tweet."""
        import yaml

        config_yaml = yaml.dump(sample_config)

        with patch("src.main.ContentGenerator") as mock_gen_cls, \
             patch("src.main.TwitterBot") as mock_tw_cls, \
             patch("src.main.BlueskyBot") as mock_bs_cls, \
             patch("src.main.NewsFetcher") as mock_nf_cls, \
             patch("src.main.ImageGenerator") as mock_ig_cls, \
             patch("src.main.PostTracker") as mock_pt_cls, \
             patch("builtins.open", mock_open(read_data=config_yaml)), \
             patch("src.main.yaml.safe_load", return_value=sample_config):

            mock_gen = MagicMock()
            mock_tw = MagicMock()
            mock_bs = MagicMock()
            mock_nf = MagicMock()
            mock_ig = MagicMock()
            mock_pt = MagicMock()

            mock_gen_cls.return_value = mock_gen
            mock_tw_cls.return_value = mock_tw
            mock_bs_cls.return_value = mock_bs
            mock_nf_cls.return_value = mock_nf
            mock_ig_cls.return_value = mock_ig
            mock_pt_cls.return_value = mock_pt

            # Set up news_categories on the fetcher
            mock_nf.news_categories = ["politics", "tech"]

            yield {
                "generator": mock_gen,
                "twitter": mock_tw,
                "bluesky": mock_bs,
                "news_fetcher": mock_nf,
                "image_gen": mock_ig,
                "tracker": mock_pt,
            }

    def test_successful_post_to_both_platforms(self, mock_all_deps):
        """post_scheduled_tweet posts to both X and Bluesky on success."""
        deps = mock_all_deps

        # Setup: news fetcher returns articles
        article = {
            "title": "Big Story",
            "url": "https://example.com/big",
            "source": "Reuters",
            "description": "A big story",
        }
        deps["news_fetcher"].get_top_stories.return_value = [article]
        deps["news_fetcher"].get_articles_for_topic.return_value = []
        deps["news_fetcher"].fetch_article_content.return_value = "Full article content here."

        # Tracker says not duplicate
        deps["tracker"].check_story_status.return_value = {
            "is_duplicate": False,
            "is_update": False,
            "previous_posts": [],
            "cluster_info": None,
        }

        # Content generator returns valid tweet
        deps["generator"].generate_tweet.return_value = {
            "tweet": "Breaking mews!",
            "needs_source_reply": True,
            "story_metadata": article,
        }
        deps["generator"].generate_image_prompt.return_value = "cat reporter prompt"
        deps["generator"].generate_source_reply.return_value = "https://example.com/big"

        # Image generator returns path
        deps["image_gen"].generate_image.return_value = "/tmp/image.png"

        # Twitter post succeeds
        deps["twitter"].post_tweet_with_image.return_value = {"id": "x_123"}
        deps["twitter"].reply_to_tweet.return_value = {"id": "x_reply_123"}

        # Bluesky post succeeds
        deps["bluesky"].post_skeet_with_image.return_value = {
            "uri": "at://did:plc:abc/app.bsky.feed.post/bs_123",
            "cid": "cid_bs_123",
        }
        deps["bluesky"].reply_to_skeet.return_value = {
            "uri": "at://did:plc:abc/app.bsky.feed.post/bs_reply_123",
            "cid": "cid_bs_reply_123",
        }

        from src.main import post_scheduled_tweet
        result = post_scheduled_tweet()
        assert result is True

        # Verify posts were made
        deps["twitter"].post_tweet_with_image.assert_called_once()
        deps["bluesky"].post_skeet_with_image.assert_called_once()
        # Verify post was recorded
        deps["tracker"].record_post.assert_called_once()

    def test_returns_false_when_no_valid_articles(self, mock_all_deps):
        """post_scheduled_tweet returns False when all articles are duplicates."""
        deps = mock_all_deps

        deps["news_fetcher"].get_top_stories.return_value = []
        deps["news_fetcher"].get_articles_for_topic.return_value = []

        from src.main import post_scheduled_tweet
        result = post_scheduled_tweet()
        assert result is False

    def test_continues_without_bluesky(self, mock_all_deps):
        """post_scheduled_tweet continues if Bluesky connection fails."""
        deps = mock_all_deps

        # Make BlueskyBot constructor raise
        with patch("src.main.BlueskyBot", side_effect=Exception("Bluesky down")):
            article = {
                "title": "Story",
                "url": "https://example.com/s",
                "source": "AP",
                "description": "desc",
            }
            deps["news_fetcher"].get_top_stories.return_value = [article]
            deps["news_fetcher"].fetch_article_content.return_value = "Content."
            deps["tracker"].check_story_status.return_value = {
                "is_duplicate": False, "is_update": False,
                "previous_posts": [], "cluster_info": None,
            }
            deps["generator"].generate_tweet.return_value = {
                "tweet": "Cat news!",
                "needs_source_reply": False,
                "story_metadata": None,
            }
            deps["twitter"].post_tweet.return_value = {"id": "x_only"}

            from src.main import post_scheduled_tweet
            result = post_scheduled_tweet()
            # Should still succeed with X-only
            assert result is True

    def test_post_without_image(self, mock_all_deps):
        """post_scheduled_tweet uses text-only post when image generation fails."""
        deps = mock_all_deps

        article = {
            "title": "Story",
            "url": "https://example.com/s",
            "source": "AP",
            "description": "desc",
        }
        deps["news_fetcher"].get_top_stories.return_value = [article]
        deps["news_fetcher"].fetch_article_content.return_value = "Content."
        deps["tracker"].check_story_status.return_value = {
            "is_duplicate": False, "is_update": False,
            "previous_posts": [], "cluster_info": None,
        }
        deps["generator"].generate_tweet.return_value = {
            "tweet": "Cat news!",
            "needs_source_reply": False,
            "story_metadata": None,
        }
        deps["generator"].generate_image_prompt.side_effect = Exception("Image gen failed")
        deps["twitter"].post_tweet.return_value = {"id": "x_no_img"}
        deps["bluesky"].post_skeet.return_value = {
            "uri": "at://did:plc:abc/post/1", "cid": "cid1"
        }

        from src.main import post_scheduled_tweet
        result = post_scheduled_tweet()
        assert result is True
        # Should call text-only methods, not image methods
        deps["twitter"].post_tweet.assert_called_once()
        deps["twitter"].post_tweet_with_image.assert_not_called()


class TestReplyToMentions:
    """Tests for the reply_to_mentions pipeline function."""

    def test_no_mentions_returns_true(self, all_env):
        """reply_to_mentions returns True when there are no mentions."""
        with patch("src.main.ContentGenerator") as mock_gen_cls, \
             patch("src.main.TwitterBot") as mock_tw_cls:
            mock_tw = MagicMock()
            mock_tw_cls.return_value = mock_tw
            mock_tw.get_mentions.return_value = []

            from src.main import reply_to_mentions
            result = reply_to_mentions()
            assert result is True

    def test_replies_to_each_mention(self, all_env):
        """reply_to_mentions generates and posts a reply for each mention."""
        with patch("src.main.ContentGenerator") as mock_gen_cls, \
             patch("src.main.TwitterBot") as mock_tw_cls:
            mock_gen = MagicMock()
            mock_tw = MagicMock()
            mock_gen_cls.return_value = mock_gen
            mock_tw_cls.return_value = mock_tw

            mention = Mock(
                id="mention_1",
                text="@mewscast what do you think?",
                author_id="author_1",
            )
            mock_tw.get_mentions.return_value = [mention]
            mock_gen.generate_reply.return_value = "Great question!"
            mock_tw.reply_to_tweet.return_value = {"id": "reply_1"}

            from src.main import reply_to_mentions
            result = reply_to_mentions()
            assert result is True
            mock_gen.generate_reply.assert_called_once()
            mock_tw.reply_to_tweet.assert_called_once_with("mention_1", "Great question!")


# =========================================================================
# Platform Differences Tests
# =========================================================================

class TestPlatformDifferences:
    """Tests verifying platform-specific behavior (X vs Bluesky)."""

    def test_bluesky_character_limit_is_300(self, bluesky_env):
        """BlueskyBot enforces 300-char limit (not X's 280)."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

        # 295 chars should pass without truncation
        text_295 = "A" * 295
        mock_client.send_post.return_value = Mock(uri="at://test", cid="cid")
        bot.post_skeet(text_295)
        # The text should be sent as-is (under 300)
        sent_text = mock_client.send_post.call_args[1]["text"]
        assert sent_text == text_295

    def test_twitter_character_limit_is_280(self, twitter_env):
        """TwitterBot enforces 280-char limit."""
        with patch("twitter_bot.tweepy.API"), \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from twitter_bot import TwitterBot
            bot = TwitterBot()

        # 285 chars should be truncated
        text_285 = "Word. " * 48  # > 280 chars
        mock_client.create_tweet.return_value = Mock(data={"id": "1"})
        bot.post_tweet(text_285)
        sent_text = mock_client.create_tweet.call_args[1]["text"]
        assert len(sent_text) <= 280

    def test_bluesky_image_uses_send_image(self, bluesky_env, tmp_path):
        """BlueskyBot uses client.send_image (not separate upload + post)."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)
        mock_client.send_image.return_value = Mock(uri="at://test", cid="cid")

        bot.post_skeet_with_image("Text", str(img_file))
        mock_client.send_image.assert_called_once()

    def test_twitter_image_uses_v1_upload_then_v2_post(self, twitter_env, tmp_path):
        """TwitterBot uploads via v1.1 API then posts via v2 API."""
        with patch("twitter_bot.tweepy.API") as mock_api_cls, \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_client_cls:
            mock_api_v1 = MagicMock()
            mock_client = MagicMock()
            mock_api_cls.return_value = mock_api_v1
            mock_client_cls.return_value = mock_client
            from twitter_bot import TwitterBot
            bot = TwitterBot()

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG" + b"\x00" * 50)

        mock_api_v1.media_upload.return_value = Mock(media_id=555)
        mock_client.create_tweet.return_value = Mock(data={"id": "t1"})

        bot.post_tweet_with_image("Text", str(img_file))

        # v1.1 upload happens first
        mock_api_v1.media_upload.assert_called_once_with(filename=str(img_file))
        # v2 tweet uses the media_id from v1.1
        mock_client.create_tweet.assert_called_once_with(
            text="Text", media_ids=[555]
        )

    def test_twitter_rate_limit_reraises(self, twitter_env):
        """TwitterBot re-raises TooManyRequests (for CI/CD fast-fail)."""
        import tweepy

        with patch("twitter_bot.tweepy.API"), \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from twitter_bot import TwitterBot
            bot = TwitterBot()

        mock_client.create_tweet.side_effect = tweepy.TooManyRequests(
            _make_rate_limit_response()
        )

        with pytest.raises(tweepy.TooManyRequests):
            bot.post_tweet("Test")

    def test_bluesky_rate_limit_returns_none(self, bluesky_env):
        """BlueskyBot returns None on API error (does not re-raise)."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

        mock_client.send_post.side_effect = Exception("Rate limited")
        result = bot.post_skeet("Test")
        assert result is None


# =========================================================================
# Error Handling / Edge Case Tests
# =========================================================================

class TestErrorHandling:
    """Tests for error handling and edge cases across the pipeline."""

    def test_content_generator_handles_empty_topic_list(self, anthropic_env, tmp_path):
        """ContentGenerator handles missing topics gracefully."""
        import yaml
        config = {
            "content": {
                "topics": [],
                "cat_vocabulary_by_topic": {},
                "cat_vocabulary_universal": ["mews"],
                "engagement_hooks": [],
                "time_of_day": {},
                "cat_humor": [],
                "editorial_guidelines": [],
                "style": "test",
                "max_length": 250,
                "model": "test-model",
            },
            "safety": {"avoid_topics": []},
            "post_angles": {"framing_chance": 0.0},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        with patch("src.content_generator.Anthropic"):
            from src.content_generator import ContentGenerator
            gen = ContentGenerator(config_path=str(config_file))
            gen.client = MagicMock()

            mock_response = Mock()
            mock_response.content = [Mock(text="A test tweet")]
            gen.client.messages.create.return_value = mock_response

            # Should not raise even with empty topics (provide explicit topic)
            result = gen.generate_tweet(topic="test topic")
            assert result is not None

    def test_bluesky_bot_skeet_with_exactly_300_chars(self, bluesky_env):
        """BlueskyBot posts text that is exactly at the 300-char limit."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

        text_300 = "A" * 300
        mock_client.send_post.return_value = Mock(uri="at://test", cid="cid")
        result = bot.post_skeet(text_300)
        assert result is not None
        # Should send as-is (exactly 300 is allowed)
        sent = mock_client.send_post.call_args[1]["text"]
        assert len(sent) == 300

    def test_twitter_bot_tweet_with_exactly_280_chars(self, twitter_env):
        """TwitterBot posts text that is exactly at the 280-char limit."""
        with patch("twitter_bot.tweepy.API"), \
             patch("twitter_bot.tweepy.OAuth1UserHandler"), \
             patch("twitter_bot.tweepy.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from twitter_bot import TwitterBot
            bot = TwitterBot()

        text_280 = "A" * 280
        mock_client.create_tweet.return_value = Mock(data={"id": "exact"})
        result = bot.post_tweet(text_280)
        assert result is not None
        sent = mock_client.create_tweet.call_args[1]["text"]
        assert len(sent) == 280

    def test_post_tracker_corrupt_history_file(self, tmp_path):
        """PostTracker handles corrupt JSON history file gracefully."""
        history_file = tmp_path / "bad_history.json"
        history_file.write_text("NOT VALID JSON {{{{")

        from post_tracker import PostTracker
        tracker = PostTracker(history_file=str(history_file))
        # Should start with empty history
        assert tracker.posts == []

    def test_post_tracker_cleanup_old_posts(self, tmp_path):
        """PostTracker removes posts older than max_history_days."""
        from post_tracker import PostTracker
        from datetime import datetime, timezone, timedelta

        tracker = PostTracker(
            history_file=str(tmp_path / "h.json"),
            config={"enabled": True, "max_history_days": 7},
        )

        # Add an old post (10 days ago)
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        tracker.posts.append({
            "timestamp": old_time,
            "topic": "Old Story",
            "url": "https://old.com",
            "source": "Old",
        })

        # Add a recent post
        recent_time = datetime.now(timezone.utc).isoformat()
        tracker.posts.append({
            "timestamp": recent_time,
            "topic": "Recent Story",
            "url": "https://recent.com",
            "source": "Recent",
        })

        tracker.cleanup_old_posts()
        assert len(tracker.posts) == 1
        assert tracker.posts[0]["topic"] == "Recent Story"

    def test_bluesky_reply_to_skeet_with_link_google_news_url_skip(self, bluesky_env):
        """reply_to_skeet_with_link skips Google News URLs > 300 chars."""
        with patch("bluesky_bot.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

        long_google_url = "https://news.google.com/" + "a" * 300
        parent_uri = "at://did:plc:abc/app.bsky.feed.post/parent"
        result = bot.reply_to_skeet_with_link(parent_uri, long_google_url)
        assert result is None

    def test_image_generator_handles_http_error(self, image_gen_env):
        """ImageGenerator returns None when HTTP download returns error status."""
        with patch("image_generator.OpenAI") as mock_openai, \
             patch("image_generator.requests.get") as mock_get:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            mock_img = Mock()
            mock_img.url = "https://example.com/img.png"
            mock_client.images.generate.return_value = Mock(data=[mock_img])

            import requests
            mock_get.side_effect = requests.exceptions.HTTPError("404")

            from image_generator import ImageGenerator
            gen = ImageGenerator()
            result = gen.generate_image("prompt")
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
