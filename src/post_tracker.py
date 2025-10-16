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

    def is_duplicate(self, story_metadata: Dict) -> bool:
        """
        Check if story is a duplicate of recently posted content

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'

        Returns:
            True if duplicate, False if original
        """
        if not self.config.get('enabled', True):
            return False

        url = story_metadata.get('url')
        title = story_metadata.get('title', '')

        # Level 1: Exact URL match (HARD BLOCK)
        if url and self.config.get('url_deduplication', True):
            if self._url_posted(url):
                print(f"✗ Duplicate URL detected: {url[:60]}...")
                return True

        # Level 2: Topic similarity check (SOFT BLOCK)
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

    def record_post(self, story_metadata: Dict, tweet_id: str):
        """
        Record a successful post to history

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            tweet_id: Posted tweet ID
        """
        post_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'topic': story_metadata.get('title', 'Unknown'),
            'url': story_metadata.get('url'),
            'tweet_id': tweet_id,
            'source': story_metadata.get('source', 'Unknown')
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
