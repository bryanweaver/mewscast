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

    def __init__(self, history_file: str = None, config: Dict = None):
        """
        Initialize post tracker

        Args:
            history_file: Path to JSON file storing post history (defaults to ../posts_history.json from src/)
            config: Configuration dict with deduplication settings
        """
        # Default to project root (parent directory of src/)
        if history_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir)
            history_file = os.path.join(project_root, "posts_history.json")

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

    def check_story_status(self, story_metadata: Dict, post_content: str = None) -> Dict:
        """
        Check if story is related to recent posts and return context

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            post_content: The generated post text to check for similarity

        Returns:
            Dictionary with:
                - 'is_duplicate': True if exact duplicate (BLOCK)
                - 'is_update': True if update to existing story (ALLOW with context)
                - 'previous_posts': List of related previous posts
                - 'cluster_info': Information about the story cluster
        """
        if not self.config.get('enabled', True):
            return {'is_duplicate': False, 'is_update': False, 'previous_posts': [], 'cluster_info': None}

        url = story_metadata.get('url')
        title = story_metadata.get('title', '')

        # Level 1: Exact URL match (HARD BLOCK)
        if url and self.config.get('url_deduplication', True):
            if self._url_posted(url):
                print(f"✗ Duplicate URL detected: {url[:60]}...")
                return {'is_duplicate': True, 'is_update': False, 'previous_posts': [], 'cluster_info': None}

        # Level 2: Content similarity check (HARD BLOCK) - check actual post text
        content_cooldown_hours = self.config.get('content_cooldown_hours', 72)  # Default 3 days
        if post_content and self._similar_content_posted(post_content, hours=content_cooldown_hours):
            print(f"✗ Similar content posted recently")
            return {'is_duplicate': True, 'is_update': False, 'previous_posts': [], 'cluster_info': None}

        # Level 3: Story cluster check - find related posts
        cluster_result = self._find_story_cluster(title)

        if cluster_result['related_posts']:
            # Check if this is an update (has update keywords) or just a repeat
            if self._is_update_story(title):
                print(f"✓ Update to existing story - will require differentiation")
                return {
                    'is_duplicate': False,
                    'is_update': True,
                    'previous_posts': cluster_result['related_posts'],
                    'cluster_info': cluster_result['cluster_info']
                }
            else:
                # Related story without update indicators - might be too similar
                # Use stricter threshold
                similarity = cluster_result['cluster_info'].get('max_similarity', 0)
                threshold = self.config.get('topic_similarity_threshold', 0.40)

                if similarity >= threshold:
                    print(f"✗ Similar topic posted recently: {title[:60]}...")
                    return {'is_duplicate': True, 'is_update': False, 'previous_posts': [], 'cluster_info': None}

        return {'is_duplicate': False, 'is_update': False, 'previous_posts': [], 'cluster_info': None}

    def is_duplicate(self, story_metadata: Dict, post_content: str = None) -> bool:
        """
        Check if story is a duplicate of recently posted content

        DEPRECATED: Use check_story_status() for richer context
        This method maintained for backward compatibility

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            post_content: The generated post text to check for similarity

        Returns:
            True if duplicate, False if original
        """
        result = self.check_story_status(story_metadata, post_content)
        return result['is_duplicate']

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

    def _is_update_story(self, title: str) -> bool:
        """
        Check if story title contains update indicators

        Args:
            title: Article title to check

        Returns:
            True if title contains update keywords
        """
        # Default update keywords if not configured
        default_keywords = [
            'update', 'updates', 'updated',
            'breaking', 'developing',
            'now', 'just', 'latest',
            'reaction', 'responds', 'respond', 'response', 'reacts',
            'after', 'following',
            'says', 'claims', 'denies',
            'walkback', 'reversal', 'u-turn',
            'backlash', 'fallout', 'aftermath',
            'shocked', 'surprise', 'surprising',
            'announces', 'announcement',
            'hits back', 'fires back', 'claps back'
        ]

        update_keywords = self.config.get('update_keywords', default_keywords)
        title_lower = title.lower()

        # Check for update keywords with word boundaries to avoid false matches
        # (e.g., "now" shouldn't match "known", "after" shouldn't match "afternoon")
        import re
        for keyword in update_keywords:
            # Use word boundaries to match whole words only
            if re.search(r'\b' + re.escape(keyword) + r'\b', title_lower):
                return True

        return False

    def _find_story_cluster(self, title: str, hours: int = 48) -> Dict:
        """
        Find posts related to the same story cluster

        Args:
            title: Article title to check
            hours: Lookback period in hours (default 48)

        Returns:
            Dictionary with:
                - 'related_posts': List of related post records
                - 'cluster_info': Dict with similarity scores and entities
        """
        if not title:
            return {'related_posts': [], 'cluster_info': None}

        # Extract keywords and entities from title
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be'}

        title_words = set(title.lower().split()) - stop_words
        title_nouns = self._extract_proper_nouns(title)

        if len(title_words) < 2:
            return {'related_posts': [], 'cluster_info': None}

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        related_posts = []
        max_similarity = 0.0

        for post in self.posts:
            # Check timestamp
            post_time = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if post_time < cutoff_time:
                continue  # Too old

            # Extract keywords from historical post
            post_title = post.get('topic', '')
            post_words = set(post_title.lower().split()) - stop_words
            post_nouns = self._extract_proper_nouns(post_title)

            if len(post_words) < 2:
                continue

            # Check entity overlap (proper nouns)
            common_nouns = title_nouns & post_nouns

            # Calculate keyword similarity with stem matching
            common_words = title_words & post_words

            # Add stem matching for better keyword detection
            stem_matches = 0
            for tw in title_words:
                for pw in post_words:
                    if tw not in common_words and pw not in common_words:
                        # Check if words share significant prefix (stem matching)
                        if len(tw) >= 4 and len(pw) >= 4:
                            if tw[:5] == pw[:5] or tw[:6] == pw[:6]:
                                stem_matches += 0.5  # Partial credit for stem match

            effective_overlap = len(common_words) + stem_matches
            overlap_ratio = effective_overlap / max(len(title_words), len(post_words))

            # Boost similarity if proper nouns match
            if len(common_nouns) >= 2:
                # Multiple entities match - strong signal
                similarity_score = max(overlap_ratio + 0.3, 0.8)
            elif len(common_nouns) == 1 and len(title_nouns) >= 1:
                # One entity matches - moderate signal
                similarity_score = overlap_ratio + 0.2
            else:
                similarity_score = overlap_ratio

            # Consider it related if similarity is high enough
            # Use lower threshold here (25%) to catch more potential updates
            if similarity_score >= 0.25:
                related_posts.append({
                    'post': post,
                    'similarity': similarity_score,
                    'common_entities': list(common_nouns)
                })
                max_similarity = max(max_similarity, similarity_score)

        # Sort by similarity (most similar first)
        related_posts.sort(key=lambda x: x['similarity'], reverse=True)

        cluster_info = {
            'max_similarity': max_similarity,
            'num_related': len(related_posts),
            'entities': list(title_nouns)
        }

        return {
            'related_posts': related_posts[:3],  # Return top 3 most similar
            'cluster_info': cluster_info
        }

    def _extract_proper_nouns(self, text: str) -> set:
        """
        Extract likely proper nouns (capitalized words) from text
        These are weighted more heavily as they identify specific stories

        Args:
            text: Text to extract from

        Returns:
            Set of lowercase proper nouns
        """
        import re
        # Find words that start with capital letters (but not sentence starts)
        words = text.split()
        proper_nouns = set()

        for i, word in enumerate(words):
            # Clean punctuation
            clean_word = re.sub(r'[^\w]', '', word)

            # Skip if empty, single char, or common stop words
            if len(clean_word) <= 1 or clean_word.lower() in {'the', 'a', 'an'}:
                continue

            # If word starts with capital
            if clean_word[0].isupper():
                # Skip common sentence starters
                if clean_word in {'The', 'A', 'An', 'This', 'That', 'These', 'Those', 'It', 'He', 'She'}:
                    continue
                proper_nouns.add(clean_word.lower())

        return proper_nouns

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

        # Extract proper nouns for entity-based matching (e.g., "Cupertino", "Trump")
        title_nouns = self._extract_proper_nouns(title)

        if len(title_words) < 2:
            return False  # Title too short to compare

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get threshold from config (default 40%)
        threshold = self.config.get('topic_similarity_threshold', 0.40)

        for post in self.posts:
            # Check timestamp
            post_time = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if post_time < cutoff_time:
                continue  # Too old, outside cooldown period

            # Extract keywords from historical post
            post_title = post.get('topic', '')
            post_words = set(post_title.lower().split()) - stop_words
            post_nouns = self._extract_proper_nouns(post_title)

            if len(post_words) < 2:
                continue

            # LEVEL 1: Check if 2+ significant proper nouns match (high confidence duplicate)
            # This catches cases like "Cupertino" where the core entity is the same
            # even if surrounding details differ
            common_nouns = title_nouns & post_nouns
            if len(common_nouns) >= 2 and len(title_nouns) >= 2:
                # Multiple specific entities match = same story
                print(f"   Entity match: {list(common_nouns)[:3]} in '{post_title[:60]}...'")
                print(f"   Strong indicator of duplicate story")
                # Still check for update keywords
                if self._is_update_story(title):
                    print(f"   ✓ But story contains update indicators - allowing as new development")
                    return False
                return True

            # LEVEL 2: Calculate keyword overlap with improved matching
            common_words = title_words & post_words

            # Also check for word stems (deploy/deployment, etc.)
            stem_matches = 0
            for tw in title_words:
                for pw in post_words:
                    if tw not in common_words and pw not in common_words:
                        # Check if words share significant prefix (stem matching)
                        if len(tw) >= 4 and len(pw) >= 4:
                            if tw[:4] == pw[:4] or tw[:5] == pw[:5]:
                                stem_matches += 0.5  # Partial credit for stem match

            effective_overlap = len(common_words) + stem_matches
            overlap_ratio = effective_overlap / max(len(title_words), len(post_words))

            # Use configurable threshold (default 40%)
            if overlap_ratio >= threshold:
                # Check if this is an update to a previous story
                if self._is_update_story(title):
                    print(f"   Topic similarity: {overlap_ratio:.1%} with '{post_title[:60]}...'")
                    print(f"   ✓ But story contains update indicators - allowing as new development")
                    return False  # Allow updates through
                else:
                    print(f"   Topic similarity: {overlap_ratio:.1%} with '{post_title[:60]}...'")
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

            # Get threshold from config (default 65%)
            threshold = self.config.get('content_similarity_threshold', 0.65)

            if overlap_ratio >= threshold:
                print(f"   Content similarity: {overlap_ratio:.1%} with post from {post_time.strftime('%Y-%m-%d')}")
                return True

        return False

    def record_post(self, story_metadata: Dict, post_content: str = None, tweet_id: str = None,
                    reply_tweet_id: str = None, bluesky_uri: str = None, bluesky_reply_uri: str = None,
                    image_prompt: str = None):
        """
        Record a successful post to history

        Args:
            story_metadata: Story dict with 'title', 'url', 'source'
            post_content: The actual text content of the post
            tweet_id: Posted tweet ID (X/Twitter)
            reply_tweet_id: Optional reply tweet ID (X/Twitter)
            bluesky_uri: Posted skeet URI (Bluesky)
            bluesky_reply_uri: Optional reply skeet URI (Bluesky)
            image_prompt: The prompt used to generate the image
        """
        post_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'topic': story_metadata.get('title', 'Unknown'),
            'url': story_metadata.get('url'),
            'source': story_metadata.get('source', 'Unknown'),
            'content': post_content,  # Store actual post text for better deduplication
            'image_prompt': image_prompt,  # Store image generation prompt
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
            # Check both 'reply_tweet_id' (old format) and 'x_reply_tweet_id' (current format)
            if post.get('url') and not (post.get('reply_tweet_id') or post.get('x_reply_tweet_id')):
                posts_needing_replies.append(post)

        return posts_needing_replies
