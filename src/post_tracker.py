"""
Post tracking and deduplication system
Prevents posting duplicate stories or repeating topics too frequently
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


class PostTracker:
    """Tracks posted stories to prevent duplicates"""

    def __init__(self, history_file: str = "posts_history.json", config: Dict = None):
        """
        Initialize post tracker

        Args:
            history_file: Path to JSON file storing post history
            config: Configuration dict with deduplication settings
        """
        self.history_file = history_file
        self.config = config or {
            'enabled': True,
            'topic_cooldown_hours': 48,
            'url_deduplication': True,
            'max_history_days': 7
        }
        self.posts = self._load_history()

    def _load_history(self) -> List[Dict]:
        """Load post history from JSON file"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    return data.get('posts', [])
            return []
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️  Could not load post history: {e}")
            print(f"   Starting with empty history")
            return []

    def _save_history(self):
        """Save post history to JSON file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump({'posts': self.posts}, f, indent=2)
        except IOError as e:
            print(f"⚠️  Could not save post history: {e}")

    def is_duplicate(self, story_metadata: Dict, post_content: str = None) -> bool:
        """
        Check if story is a duplicate of recently posted content

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            post_content: The generated post text to check for similarity

        Returns:
            True if duplicate, False if original
        """
        if not self.config.get('enabled', True):
            return False

        url = story_metadata.get('url')
        title = story_metadata.get('title', '')
        source = story_metadata.get('source', '')

        # Level 1: Exact URL match (HARD BLOCK)
        if url and self.config.get('url_deduplication', True):
            if self._url_posted(url):
                print(f"✗ Duplicate URL detected: {url[:60]}...")
                return True

        # Level 2: Source deduplication (HARD BLOCK) - never use same source twice
        source_cooldown_hours = self.config.get('source_cooldown_hours', 168)  # Default 7 days
        if source and self._source_posted(source, hours=source_cooldown_hours):
            print(f"✗ Source already used recently: {source}")
            return True

        # Level 3: Content similarity check (HARD BLOCK) - check actual post text
        content_cooldown_hours = self.config.get('content_cooldown_hours', 72)  # Default 3 days
        if post_content and self._similar_content_posted(post_content, hours=content_cooldown_hours):
            print(f"✗ Similar content posted recently")
            return True

        # Level 4: Topic similarity check (SOFT BLOCK)
        cooldown_hours = self.config.get('topic_cooldown_hours', 48)
        if self._similar_topic_posted(title, hours=cooldown_hours):
            print(f"✗ Similar topic posted recently: {title[:60]}...")
            return True

        return False

    def _url_posted(self, url: str) -> bool:
        """Check if URL was already posted"""
        for post in self.posts:
            if post.get('url') == url:
                return True
        return False

    def _source_posted(self, source: str, hours: int = 168) -> bool:
        """
        Check if source was already posted within cooldown period

        Args:
            source: News source name to check
            hours: Cooldown period in hours (default 7 days)

        Returns:
            True if source found within cooldown period
        """
        if not source:
            return False

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        for post in self.posts:
            # Check timestamp
            post_time = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if post_time < cutoff_time:
                continue  # Too old, outside cooldown period

            # Check if same source
            post_source = post.get('source', '')
            if post_source == source:
                return True

        return False

    def _similar_topic_posted(self, title: str, hours: int = 48) -> bool:
        """
        Check if similar topic was posted within cooldown period

        Args:
            title: Article title to check
            hours: Cooldown period in hours

        Returns:
            True if similar topic found within cooldown period
        """
        if not title:
            return False

        # Extract keywords from title (lowercase, remove common words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be'}

        title_words = set(title.lower().split()) - stop_words

        if len(title_words) < 2:
            return False  # Title too short to compare

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        for post in self.posts:
            # Check timestamp
            post_time = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if post_time < cutoff_time:
                continue  # Too old, outside cooldown period

            # Extract keywords from historical post
            post_title = post.get('topic', '')
            post_words = set(post_title.lower().split()) - stop_words

            if len(post_words) < 2:
                continue

            # Calculate keyword overlap
            common_words = title_words & post_words
            overlap_ratio = len(common_words) / max(len(title_words), len(post_words))

            # If >60% keyword overlap, consider it similar
            if overlap_ratio > 0.6:
                return True

        return False

    def _similar_content_posted(self, content: str, hours: int = 72) -> bool:
        """
        Check if similar content was posted within cooldown period

        Args:
            content: Post content text to check
            hours: Cooldown period in hours (default 3 days)

        Returns:
            True if similar content found within cooldown period
        """
        if not content:
            return False

        # Extract keywords from content (lowercase, remove common words and cat phrases)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be',
                      'this', 'that', 'it', 'can', 'will', 'cat', 'mews', 'purr', 'paws',
                      'fur', 'whisker', 'perch', 'meow'}

        # Clean content: remove hashtags, URLs, and source indicator
        import re
        clean_content = re.sub(r'#\w+', '', content)  # Remove hashtags
        clean_content = re.sub(r'http\S+', '', clean_content)  # Remove URLs
        clean_content = re.sub(r'📰↓', '', clean_content)  # Remove source indicator

        content_words = set(clean_content.lower().split()) - stop_words

        if len(content_words) < 3:
            return False  # Content too short to compare meaningfully

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        for post in self.posts:
            # Check timestamp
            post_time = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if post_time < cutoff_time:
                continue  # Too old, outside cooldown period

            # Extract keywords from historical post content
            post_content = post.get('content', '')
            if not post_content:
                continue  # No content stored (old format)

            # Clean historical content same way
            clean_post_content = re.sub(r'#\w+', '', post_content)
            clean_post_content = re.sub(r'http\S+', '', clean_post_content)
            clean_post_content = re.sub(r'📰↓', '', clean_post_content)

            post_words = set(clean_post_content.lower().split()) - stop_words

            if len(post_words) < 3:
                continue

            # Calculate keyword overlap
            common_words = content_words & post_words
            overlap_ratio = len(common_words) / max(len(content_words), len(post_words))

            # Higher threshold for content (70%) than topic (60%)
            # because content is more specific
            if overlap_ratio > 0.70:
                print(f"   Content similarity: {overlap_ratio:.1%} with post from {post_time.strftime('%Y-%m-%d')}")
                return True

        return False

    def record_post(self, story_metadata: Dict, post_content: str = None, tweet_id: str = None,
                    reply_tweet_id: str = None, bluesky_uri: str = None, bluesky_reply_uri: str = None):
        """
        Record a successful post to history

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            post_content: The actual text content of the post
            tweet_id: Posted tweet ID (X/Twitter)
            reply_tweet_id: Optional reply tweet ID (X/Twitter)
            bluesky_uri: Posted skeet URI (Bluesky)
            bluesky_reply_uri: Optional reply skeet URI (Bluesky)
        """
        post_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'topic': story_metadata.get('title', 'Unknown'),
            'url': story_metadata.get('url'),
            'source': story_metadata.get('source', 'Unknown'),
            'content': post_content,  # Store actual post text for better deduplication
            'x_tweet_id': tweet_id,  # X/Twitter
            'x_reply_tweet_id': reply_tweet_id,
            'bluesky_uri': bluesky_uri,  # Bluesky
            'bluesky_reply_uri': bluesky_reply_uri
        }

        self.posts.append(post_record)

        # Cleanup old posts to keep file small
        self.cleanup_old_posts()

        # Save to disk
        self._save_history()

        print(f"✓ Post recorded to history (total: {len(self.posts)} posts tracked)")

    def cleanup_old_posts(self):
        """Remove posts older than max_history_days"""
        max_days = self.config.get('max_history_days', 7)
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=max_days)

        original_count = len(self.posts)

        self.posts = [
            post for post in self.posts
            if datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00')) >= cutoff_time
        ]

        removed = original_count - len(self.posts)
        if removed > 0:
            print(f"🧹 Cleaned up {removed} old posts from history")

    def filter_duplicates(self, stories: List[Dict]) -> List[Dict]:
        """
        Filter out duplicate stories from a list

        Args:
            stories: List of story dicts

        Returns:
            List of unique stories only
        """
        if not self.config.get('enabled', True):
            return stories

        unique_stories = []

        for story in stories:
            if not self.is_duplicate(story):
                unique_stories.append(story)
            else:
                print(f"   Skipping duplicate: {story.get('title', '')[:60]}...")

        print(f"✓ Filtered {len(stories)} stories → {len(unique_stories)} unique")
        return unique_stories

    def get_posts_needing_replies(self) -> List[Dict]:
        """
        Get posts that have URLs but no source reply yet

        Returns:
            List of post records that need source replies
        """
        posts_needing_replies = []

        for post in self.posts:
            # Has URL but no reply posted yet
            if post.get('url') and not post.get('reply_tweet_id'):
                posts_needing_replies.append(post)

        return posts_needing_replies
