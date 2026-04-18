"""
Twitter/X bot integration using tweepy
"""
import os
import tweepy
from typing import Optional
from content_generator import _truncate_at_sentence


class TwitterBot:
    """Handles all Twitter/X API interactions"""

    def __init__(self):
        """Initialize X API client with credentials from environment"""
        self.api_key = os.getenv("X_API_KEY")
        self.api_secret = os.getenv("X_API_SECRET")
        self.access_token = os.getenv("X_ACCESS_TOKEN")
        self.access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")
        self.bearer_token = os.getenv("X_BEARER_TOKEN")

        # Validate credentials
        if not all([self.api_key, self.api_secret, self.access_token,
                    self.access_token_secret, self.bearer_token]):
            raise ValueError("Missing X API credentials. Check your .env file.")

        # Initialize tweepy client (v2 API)
        # wait_on_rate_limit=False so GitHub Actions fail fast instead of waiting
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=False  # Fail fast on rate limits (important for CI/CD)
        )

        # Initialize v1.1 API for media upload
        auth = tweepy.OAuth1UserHandler(
            self.api_key,
            self.api_secret,
            self.access_token,
            self.access_token_secret
        )
        self.api_v1 = tweepy.API(auth)

    def post_tweet(self, text: str) -> Optional[dict]:
        """
        Post a tweet to your timeline

        Args:
            text: The tweet content (max 280 characters)

        Returns:
            Tweet data if successful, None if failed
        """
        try:
            if len(text) > 280:
                print(f"Warning: Tweet too long ({len(text)} chars). Truncating...")
                text = _truncate_at_sentence(text, 280)

            response = self.client.create_tweet(text=text)
            print(f"✓ Tweet posted successfully! ID: {response.data['id']}")
            return response.data
        except tweepy.TooManyRequests as e:
            print(f"✗ Rate limit exceeded! Free tier: 50 posts/24hrs")
            print(f"   Wait until rate limit resets and try again")
            print(f"   Error: {e}")
            raise  # Re-raise to make GitHub Actions fail
        except tweepy.TweepyException as e:
            print(f"✗ Error posting tweet: {e}")
            # Print more details for debugging
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response status: {e.response.status_code}")
                print(f"   Response text: {e.response.text}")
            return None

    def post_tweet_with_image(self, text: str, image_path: str) -> Optional[dict]:
        """
        Post a tweet with an attached image

        Args:
            text: The tweet content (max 280 characters)
            image_path: Path to the image file to attach

        Returns:
            Tweet data if successful, None if failed
        """
        try:
            if len(text) > 280:
                print(f"Warning: Tweet too long ({len(text)} chars). Truncating...")
                text = _truncate_at_sentence(text, 280)

            # Upload media using v1.1 API
            print(f"📤 Uploading image: {image_path}")
            media = self.api_v1.media_upload(filename=image_path)
            media_id = media.media_id

            print(f"✓ Image uploaded! Media ID: {media_id}")

            # Post tweet with media using v2 API
            response = self.client.create_tweet(
                text=text,
                media_ids=[media_id]
            )

            print(f"✓ Tweet with image posted successfully! ID: {response.data['id']}")
            return response.data

        except tweepy.TooManyRequests as e:
            print(f"✗ Rate limit exceeded! Free tier: 50 posts/24hrs")
            print(f"   Wait until rate limit resets and try again")
            print(f"   Error: {e}")
            raise  # Re-raise to make GitHub Actions fail
        except tweepy.TweepyException as e:
            print(f"✗ Error posting tweet with image: {e}")
            # Print more details for debugging
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response status: {e.response.status_code}")
                print(f"   Response text: {e.response.text}")
            return None
        except FileNotFoundError:
            print(f"✗ Error: Image file not found: {image_path}")
            return None

    def reply_to_tweet(self, tweet_id: str, text: str) -> Optional[dict]:
        """
        Reply to a specific tweet

        Args:
            tweet_id: ID of the tweet to reply to
            text: Reply content

        Returns:
            Tweet data if successful, None if failed
        """
        try:
            if len(text) > 280:
                text = _truncate_at_sentence(text, 280)

            response = self.client.create_tweet(
                text=text,
                in_reply_to_tweet_id=tweet_id
            )
            print(f"✓ Reply posted successfully! ID: {response.data['id']}")
            return response.data
        except tweepy.TooManyRequests as e:
            print(f"✗ Rate limit exceeded! Free tier: 50 posts/24hrs")
            print(f"   Wait until rate limit resets and try again")
            print(f"   Error: {e}")
            raise  # Re-raise to make GitHub Actions fail
        except tweepy.TweepyException as e:
            print(f"✗ Error posting reply: {e}")
            # Log the full X API response so the caller can see the real
            # underlying reason (tier/scope/reply-controls/anti-spam) —
            # the short exception message often collapses distinct causes
            # into the same "reply not allowed" wording.
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response status: {e.response.status_code}")
                print(f"   Response body: {e.response.text}")
            return None

    def reply_to_tweet_with_image(self, tweet_id: str, text: str, image_path: str) -> Optional[dict]:
        """Reply to a tweet with an attached image."""
        try:
            if len(text) > 280:
                text = _truncate_at_sentence(text, 280)

            media = self.api_v1.media_upload(filename=image_path)
            response = self.client.create_tweet(
                text=text,
                in_reply_to_tweet_id=tweet_id,
                media_ids=[media.media_id],
            )
            print(f"✓ Reply with image posted! ID: {response.data['id']}")
            return response.data
        except tweepy.TooManyRequests as e:
            print(f"✗ Rate limit exceeded: {e}")
            raise
        except tweepy.TweepyException as e:
            print(f"✗ Error posting reply with image: {e}")
            return None
        except FileNotFoundError:
            print(f"✗ Image not found: {image_path}")
            return None

    def follow_user_by_handle(self, handle: str) -> bool:
        """Follow an X user by their @handle.

        Experimental: Walter following the outlet does NOT directly
        satisfy X's "People you follow" reply-restriction rule (that
        rule is from the AUTHOR's perspective — the outlet would have
        to follow Walter). But following may incrementally soften X's
        anti-automation heuristics over time, so we try it best-effort
        before reply attempts on verified accounts.

        Idempotent — X returns a success-shaped response when already
        following. Never raises for the caller to handle; always returns
        True on ok/already-following and False on failure — including
        non-tweepy errors like TypeError from param validation (raised
        by tweepy v4.8+ when access tokens are missing) or
        AttributeError from malformed response objects.
        """
        try:
            user_resp = self.client.get_user(username=handle)
            if not user_resp or not getattr(user_resp, 'data', None):
                print(f"   Could not resolve @{handle} for follow")
                return False
            user_id = user_resp.data.id
            response = self.client.follow_user(target_user_id=user_id)
            data = getattr(response, 'data', None) or {}
            following = data.get('following') if isinstance(data, dict) else getattr(data, 'following', None)
            if following:
                print(f"   ✓ Now following @{handle}")
                return True
            print(f"   Follow @{handle} returned unexpected payload: {data}")
            return False
        except tweepy.TooManyRequests as e:
            # Don't fail the whole reply cycle on a follow rate-limit —
            # the reply attempt itself is what matters.
            print(f"   Follow @{handle} rate-limited: {e}")
            return False
        except tweepy.TweepyException as e:
            print(f"   Follow @{handle} failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"     Response: {e.response.status_code} {e.response.text[:200]}")
            return False
        except Exception as e:
            # Tweepy v4.8+ raises TypeError for param validation (e.g.
            # access token not set), and malformed responses can raise
            # AttributeError. The docstring promises "never raises";
            # honor it with a final broad catch so no non-tweepy
            # exception propagates out of the experiment.
            print(f"   Follow @{handle} errored: {type(e).__name__}: {e}")
            return False

    def quote_tweet(self, tweet_id: str, text: str) -> Optional[dict]:
        """
        Quote-retweet a specific tweet with commentary.

        Args:
            tweet_id: ID of the tweet to quote
            text: Commentary text (max 280 characters)

        Returns:
            Tweet data if successful, None if failed
        """
        try:
            if len(text) > 280:
                text = _truncate_at_sentence(text, 280)

            response = self.client.create_tweet(
                text=text,
                quote_tweet_id=tweet_id
            )
            print(f"✓ Quote tweet posted successfully! ID: {response.data['id']}")
            return response.data
        except tweepy.TooManyRequests as e:
            print(f"✗ Rate limit exceeded! Free tier: 50 posts/24hrs")
            print(f"   Error: {e}")
            raise
        except tweepy.TweepyException as e:
            print(f"✗ Error posting quote tweet: {e}")
            return None

    def delete_tweet(self, tweet_id: str) -> bool:
        """
        Delete a tweet

        Args:
            tweet_id: ID of the tweet to delete

        Returns:
            True if successful, False if failed
        """
        try:
            self.client.delete_tweet(tweet_id)
            print(f"✓ Tweet deleted successfully! ID: {tweet_id}")
            return True
        except tweepy.TweepyException as e:
            print(f"✗ Error deleting tweet: {e}")
            return False

    def get_mentions(self, max_results: int = 10) -> list:
        """
        Get recent mentions of your account

        Args:
            max_results: Number of mentions to retrieve (max 100)

        Returns:
            List of mention objects
        """
        try:
            user = self.client.get_me()
            mentions = self.client.get_users_mentions(
                id=user.data.id,
                max_results=min(max_results, 100)
            )
            return mentions.data if mentions.data else []
        except tweepy.TweepyException as e:
            print(f"✗ Error fetching mentions: {e}")
            return []

    def get_timeline(self, max_results: int = 10) -> list:
        """
        Get your own recent tweets

        Args:
            max_results: Number of tweets to retrieve (max 100)

        Returns:
            List of tweet objects
        """
        try:
            user = self.client.get_me()
            tweets = self.client.get_users_tweets(
                id=user.data.id,
                max_results=min(max_results, 100)
            )
            return tweets.data if tweets.data else []
        except tweepy.TweepyException as e:
            print(f"✗ Error fetching timeline: {e}")
            return []

    def get_trending_topics(self, count: int = 5) -> list:
        """
        Get trending topics from X

        Tries multiple methods:
        1. Search recent popular tweets for hashtags (Free tier: 96/day)
        2. Fallback to general news topics

        Args:
            count: Number of trending topics to retrieve

        Returns:
            List of trending topic strings
        """
        # Method 1: Search recent tweets for popular hashtags
        # Free tier: 1 request/15min = plenty for our use case
        try:
            # Search for highly engaged recent tweets
            search_query = "lang:en -is:retweet min_faves:1000"
            response = self.client.search_recent_tweets(
                query=search_query,
                max_results=10,
                tweet_fields=['public_metrics', 'entities']
            )

            if response.data:
                # Extract hashtags and keywords from popular tweets
                keywords = set()
                for tweet in response.data:
                    if hasattr(tweet, 'entities') and tweet.entities:
                        # Get hashtags
                        if 'hashtags' in tweet.entities:
                            for hashtag in tweet.entities['hashtags']:
                                keywords.add(hashtag['tag'])
                        # Get cashtags (stock symbols - often trending)
                        if 'cashtags' in tweet.entities:
                            for cashtag in tweet.entities['cashtags']:
                                keywords.add(f"${cashtag['tag']}")

                trends = list(keywords)[:count]
                if trends:
                    print(f"✓ Extracted {len(trends)} trending topics from popular tweets")
                    return trends

        except tweepy.TweepyException as e:
            print(f"Note: Search trending not available ({e})")

        # Method 2: Fallback to general news topics
        fallback_topics = [
            "breaking news",
            "economy",
            "technology",
            "politics",
            "business"
        ]
        print(f"ℹ️  Using fallback topics (trending API limited on Free tier)")
        return fallback_topics[:count]
