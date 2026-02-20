"""
Positive News Special Report

Searches for uplifting, heartwarming, or hopeful news stories and generates
a Walter Croncat "good news" post for followers.

Usage:
    python src/main.py special positive              # Auto-search for positive stories
    python src/main.py special positive "topic here"  # Search for positive news on a topic
"""
import os
import random
import yaml
import feedparser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

from news_fetcher import NewsFetcher
from content_generator import ContentGenerator, _truncate_at_sentence
from prompt_loader import get_prompt_loader


class PositiveNewsGenerator:
    """Generates 'Positive News' special report posts"""

    # Search queries designed to surface uplifting stories
    POSITIVE_SEARCH_QUERIES = [
        "community volunteers help",
        "hero saves",
        "breakthrough discovery",
        "record-breaking achievement",
        "neighbors help rebuild",
        "students raise money charity",
        "rescue mission success",
        "medical breakthrough treatment",
        "teacher inspires students",
        "veteran honored community",
        "animal rescue heartwarming",
        "good samaritan helps stranger",
        "community comes together",
        "nonprofit milestone achievement",
        "uplifting story today",
        "feel good news",
        "positive news today",
        "acts of kindness",
        "environmental restoration success",
        "clean energy milestone",
        "scientific discovery hope",
        "firefighter rescue",
        "reunion found family",
        "scholarship surprise student",
        "small town rallies together",
    ]

    def __init__(self):
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        positive_config = self.config.get('special_posts', {}).get('positive_news', {})
        self.max_length = positive_config.get('max_length', 280)
        self.news_fetcher = NewsFetcher()
        self.content_generator = ContentGenerator()
        self.prompts = get_prompt_loader()

    def find_positive_story(self, topic: str = None) -> Optional[Dict]:
        """
        Search for an uplifting news story.

        Args:
            topic: Optional specific topic to search for positive news about.
                   If None, searches using built-in positive news queries.

        Returns:
            Dict with 'article', 'topic' or None if nothing found.
        """
        if topic:
            # User specified a topic - search for positive angle on it
            queries = [
                f"{topic} good news",
                f"{topic} success",
                f"{topic} breakthrough",
                f"{topic} heartwarming",
                f"{topic} hero",
            ]
        else:
            # Auto-search using positive news queries
            queries = list(self.POSITIVE_SEARCH_QUERIES)
            random.shuffle(queries)

        print(f"🌟 Searching for positive news stories...")

        for query in queries[:10]:  # Try up to 10 queries
            print(f"\n   🔍 Trying: '{query}'")
            article = self._search_positive_news(query)
            if article:
                return {
                    'article': article,
                    'topic': topic or query
                }

        print("❌ Could not find a suitable positive news story")
        return None

    def _search_positive_news(self, query: str) -> Optional[Dict]:
        """
        Search Google News RSS for positive stories matching the query.
        Filters for recent articles from reputable sources.
        """
        try:
            search_query = query.replace(' ', '+')
            rss_url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"

            feed = feedparser.parse(rss_url)

            if not feed.entries:
                return None

            # Only consider recent articles (last 5 days for positive news - wider window)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=5)

            # Preferred sources
            preferred_sources = [
                'Reuters', 'Associated Press', 'AP News',
                'The New York Times', 'The Washington Post', 'USA Today',
                'CNN', 'BBC', 'NBC News', 'CBS News', 'ABC News', 'NPR',
                'Fox News', 'CNBC', 'Forbes',
                'The Guardian', 'Time', 'Newsweek',
                'People', 'Good Morning America',
                'Today', 'PBS',
            ]

            for entry in feed.entries[:15]:
                published_str = entry.get('published', '')
                if published_str:
                    try:
                        published_date = parsedate_to_datetime(published_str)
                        if published_date < cutoff_date:
                            continue
                    except Exception:
                        continue

                source = entry.get('source', {}).get('title', 'Unknown')

                # Prefer major sources but be more flexible for positive news
                is_preferred = any(pref in source for pref in preferred_sources)
                if not is_preferred:
                    continue

                # Skip obviously negative headlines
                title_lower = entry.title.lower()
                negative_indicators = [
                    'killed', 'murder', 'dead', 'dies', 'death',
                    'shooting', 'crash', 'scandal', 'fraud', 'arrest',
                    'war', 'attack', 'bomb', 'terror', 'crisis',
                    'collapse', 'disaster', 'tragedy', 'victim',
                ]
                if any(neg in title_lower for neg in negative_indicators):
                    continue

                # Resolve URL and fetch content
                actual_url = self.news_fetcher.resolve_google_news_url(entry.link)
                content = self.news_fetcher.fetch_article_content(actual_url)

                if not content:
                    continue

                print(f"   ✅ Found: {source} - {entry.title[:60]}...")

                return {
                    'title': entry.title,
                    'description': entry.get('summary', ''),
                    'url': actual_url,
                    'source': source,
                    'published': published_str,
                    'article_content': content,
                }

            return None

        except Exception as e:
            print(f"   ⚠️  Error searching: {e}")
            return None

    def generate_positive_post(self, story_data: Dict) -> Optional[Dict]:
        """
        Generate Walter Croncat's positive news post.

        Uses a multi-pass approach:
        1. Generate initial post
        2. Verify claims against source article
        3. If verification finds issues, regenerate with corrections

        Returns dict with 'post_text' and 'source_url'.
        """
        article = story_data['article']
        topic = story_data['topic']

        # Get topic-matched vocab
        cat_vocab_str = self.content_generator._select_vocab_for_story(
            article['title'],
            article.get('article_content', '')[:300]
        )

        content = article.get('article_content', '')[:800]

        # Build the positive news prompt
        prompt = self.prompts.load("positive_news.md",
            topic=topic,
            source=article['source'],
            title=article['title'],
            content=content,
            cat_vocab_str=cat_vocab_str,
            max_length=self.max_length,
        )

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            model = self.config['content']['model']

            # === PASS 1: Generate initial post ===
            print("   📝 Pass 1: Generating positive news post...")
            message = client.messages.create(
                model=model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            post_text = message.content[0].text.strip()

            # Clean up quotes if present
            if post_text.startswith('"') and post_text.endswith('"'):
                post_text = post_text[1:-1]
            if post_text.startswith("'") and post_text.endswith("'"):
                post_text = post_text[1:-1]

            print(f"   Draft ({len(post_text)} chars): {post_text[:80]}...")

            # === PASS 2: Verify accuracy against source ===
            print("   🔍 Pass 2: Verifying claims against source article...")
            verification = self._verify_post(
                client, model, post_text,
                article['source'], article['title'], content
            )

            if verification['has_issues']:
                print(f"   ⚠️  Verification found issues: {verification['issues']}")
                print(f"   📝 Pass 3: Regenerating with corrections...")

                corrected_prompt = (
                    f"{prompt}\n\n"
                    f"## IMPORTANT CORRECTIONS FROM FACT-CHECK\n"
                    f"A previous draft had these problems:\n"
                    f"Draft: {post_text}\n"
                    f"Issues found: {verification['issues']}\n\n"
                    f"Fix these issues in your new version. Be accurate about what the article actually says."
                )

                message = client.messages.create(
                    model=model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": corrected_prompt}]
                )

                post_text = message.content[0].text.strip()
                if post_text.startswith('"') and post_text.endswith('"'):
                    post_text = post_text[1:-1]
                if post_text.startswith("'") and post_text.endswith("'"):
                    post_text = post_text[1:-1]

                print(f"   Corrected ({len(post_text)} chars): {post_text[:80]}...")
            else:
                print(f"   ✅ Verification passed - claims are accurate!")

            # Enforce length
            if len(post_text) > self.max_length:
                post_text = _truncate_at_sentence(post_text, self.max_length)

            # Track vocab usage
            self.content_generator._record_used_phrase(post_text)

            print(f"✅ Positive news post generated ({len(post_text)} chars)")

            return {
                'post_text': post_text,
                'article': article,
                'topic': topic,
            }

        except Exception as e:
            print(f"❌ Error generating positive news post: {e}")
            return None

    def _verify_post(self, client, model: str, post_text: str,
                     source: str, title: str, content: str) -> Dict:
        """
        Verify a positive news post's claims against the source article.
        """
        verification_prompt = (
            f"You are a fact-checker reviewing a social media post about a positive news story. "
            f"Check whether the post accurately represents what the source article says.\n\n"
            f"## THE POST TO VERIFY:\n{post_text}\n\n"
            f"## SOURCE: {source}\n"
            f"Headline: {title}\n"
            f"Content: {content}\n\n"
            f"## CHECK FOR:\n"
            f"1. Does the post accurately describe what happened?\n"
            f"2. Does the post fabricate any details not in the article?\n"
            f"3. Are any facts stated in the post contradicted by the article?\n"
            f"4. Does the post exaggerate the positive aspects beyond what the article says?\n\n"
            f"Respond in this exact format:\n"
            f"ACCURATE: yes/no\n"
            f"ISSUES: [describe specific issues, or 'none' if accurate]\n"
        )

        try:
            message = client.messages.create(
                model=model,
                max_tokens=300,
                messages=[{"role": "user", "content": verification_prompt}]
            )

            response = message.content[0].text.strip().lower()

            has_issues = 'accurate: no' in response or 'accurate:no' in response
            issues = ''
            if 'issues:' in response:
                issues = response.split('issues:', 1)[1].strip()
                if issues == 'none' or issues == 'none.':
                    has_issues = False
                    issues = ''

            return {'has_issues': has_issues, 'issues': issues}

        except Exception as e:
            print(f"   ⚠️  Verification call failed: {e}")
            return {'has_issues': False, 'issues': 'verification unavailable'}
