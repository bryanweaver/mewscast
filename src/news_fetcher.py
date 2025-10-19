"""
Google News RSS integration for fetching real news articles
"""
import feedparser
import random
import requests
from typing import List, Dict, Optional
import time
import re
import base64


class NewsFetcher:
    """Fetches real news articles from Google News RSS"""

    def __init__(self):
        """Initialize news fetcher with search categories"""
        # News categories to search (aligned with bot's focus)
        self.news_categories = [
            "US politics",
            "Congress",
            "Senate",
            "economy",
            "inflation",
            "business news",
            "technology",
            "innovation",
            "national news",
            "UAP sighting",
            "UFO disclosure",
            "government transparency"
        ]

    def resolve_google_news_url(self, google_url: str) -> str:
        """
        Resolve Google News proxy URL to the actual article URL

        Args:
            google_url: Google News RSS article URL

        Returns:
            Actual article URL, or original URL if resolution fails
        """
        try:
            # Method 1: Decode base64-encoded URL from Google News RSS link
            # Google News URLs look like: https://news.google.com/rss/articles/CBMi...?oc=5
            # The part after "articles/" is a base64-encoded string containing the actual URL

            # Extract the encoded article ID
            match = re.search(r'/articles/([^?]+)', google_url)
            if match:
                encoded_id = match.group(1)

                # Try to decode the base64 (add padding if needed)
                try:
                    # Add padding to make length multiple of 4
                    padding = (4 - len(encoded_id) % 4) % 4
                    encoded_id_padded = encoded_id + ('=' * padding)

                    # Decode base64
                    decoded = base64.urlsafe_b64decode(encoded_id_padded).decode('utf-8', errors='ignore')

                    # Extract URL from decoded string using regex
                    # Look for http/https URLs that are NOT google.com
                    url_pattern = r'https?://(?!.*google\.com)[^\s"\'\x00-\x1f]+'
                    urls = re.findall(url_pattern, decoded)

                    if urls:
                        # Return the first non-Google URL found
                        actual_url = urls[0].rstrip('\x00')  # Remove null bytes
                        print(f"   ✓ Decoded URL: {actual_url[:80]}...")
                        return actual_url

                except Exception as decode_error:
                    print(f"   ⚠️  Base64 decode failed: {decode_error}")

            # Method 2: Follow HTTP redirects as fallback
            print(f"   Trying redirect method...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(
                google_url,
                allow_redirects=True,
                timeout=10,
                headers=headers
            )
            actual_url = response.url

            # If still on Google domain after redirects, extraction failed
            if 'google.com' not in actual_url and 'google.co' not in actual_url:
                print(f"   ✓ Resolved via redirect: {actual_url[:80]}...")
                return actual_url

            print(f"   ⚠️  Could not extract actual URL, using Google News URL")
            return google_url

        except Exception as e:
            print(f"   ⚠️  Could not resolve URL: {e}")
            return google_url  # Fallback to original URL

    def get_trending_topics(self, count: int = 5, categories: List[str] = None) -> List[Dict]:
        """
        Fetch real news articles directly from Google News RSS

        Args:
            count: Number of articles to fetch
            categories: List of categories to search (optional, uses defaults if not provided)

        Returns:
            List of dictionaries with 'title', 'context', 'url', 'source' for each article
        """
        articles = []
        search_categories = categories if categories else random.sample(self.news_categories, min(3, len(self.news_categories)))

        print(f"🔍 Searching Google News RSS for categories: {', '.join(search_categories)}")

        for category in search_categories:
            # Search Google News RSS for this category
            article = self.get_article_for_topic(category)

            if article:
                articles.append({
                    'title': article['title'],
                    'context': article['description'][:200],  # Limit description
                    'url': article['url'],
                    'source': article['source']
                })

            # Stop if we have enough
            if len(articles) >= count:
                break

            # Small delay to be respectful to Google
            time.sleep(0.5)

        # If we still don't have enough, search more categories
        if len(articles) < count:
            remaining_categories = [c for c in self.news_categories if c not in search_categories]
            random.shuffle(remaining_categories)

            for category in remaining_categories[:count - len(articles)]:
                article = self.get_article_for_topic(category)
                if article:
                    articles.append({
                        'title': article['title'],
                        'context': article['description'][:200],
                        'url': article['url'],
                        'source': article['source']
                    })
                time.sleep(0.5)

        if articles:
            print(f"✓ Fetched {len(articles)} articles from Google News RSS")
            return articles

        # Ultimate fallback - should rarely happen
        print("⚠️  Warning: Could not fetch any articles. Using minimal fallback.")
        return [{
            'title': 'Breaking news developments',
            'context': 'Real-time news analysis from multiple sources',
            'url': 'https://news.google.com',
            'source': 'Google News'
        }]

    def get_article_for_topic(self, topic: str) -> Optional[Dict]:
        """
        Fetch actual news article from Google News RSS for a topic

        Args:
            topic: The trending topic to search for

        Returns:
            Dictionary with 'title', 'description', 'url', 'source' or None
        """
        try:
            # Build Google News RSS search URL
            search_query = topic.replace(' ', '+')
            rss_url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"

            print(f"🔍 Searching Google News RSS for: {topic}")

            # Parse RSS feed
            feed = feedparser.parse(rss_url)

            if not feed.entries:
                print(f"   No articles found for '{topic}'")
                return None

            # Filter for reputable US news sources
            preferred_sources = [
                'Reuters', 'Associated Press', 'AP News', 'The New York Times',
                'The Washington Post', 'CNN', 'BBC', 'NPR', 'Bloomberg',
                'Politico', 'The Hill', 'USA Today', 'Fox News', 'NBC News',
                'CBS News', 'ABC News'
            ]

            # Try to find article from preferred source first
            for entry in feed.entries[:10]:  # Check first 10 results
                source = entry.get('source', {}).get('title', 'Unknown')

                # Check if from preferred source
                if any(pref in source for pref in preferred_sources):
                    # Resolve Google News proxy URL to actual article URL
                    actual_url = self.resolve_google_news_url(entry.link)

                    article = {
                        'title': entry.title,
                        'description': entry.get('summary', ''),
                        'url': actual_url,
                        'source': source,
                        'published': entry.get('published', '')
                    }
                    print(f"✓ Found article from {source}")
                    return article

            # If no preferred source found, use first result
            entry = feed.entries[0]

            # Resolve Google News proxy URL to actual article URL
            actual_url = self.resolve_google_news_url(entry.link)

            article = {
                'title': entry.title,
                'description': entry.get('summary', ''),
                'url': actual_url,
                'source': entry.get('source', {}).get('title', 'Google News'),
                'published': entry.get('published', '')
            }
            print(f"✓ Found article from {article['source']}")
            return article

        except Exception as e:
            print(f"✗ Error fetching article for '{topic}': {e}")
            return None
