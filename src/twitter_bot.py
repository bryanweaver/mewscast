"""
Twitter/X bot integration using tweepy
"""
import os
import tweepy
from typing import Optional


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
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )

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
                text = text[:277] + "..."

            response = self.client.create_tweet(text=text)
            print(f"✓ Tweet posted successfully! ID: {response.data['id']}")
            return response.data
        except tweepy.TweepyException as e:
            print(f"✗ Error posting tweet: {e}")
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
                text = text[:277] + "..."

            response = self.client.create_tweet(
                text=text,
                in_reply_to_tweet_id=tweet_id
            )
            print(f"✓ Reply posted successfully! ID: {response.data['id']}")
            return response.data
        except tweepy.TweepyException as e:
            print(f"✗ Error posting reply: {e}")
            return None

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
