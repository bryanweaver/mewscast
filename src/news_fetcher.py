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

                    # Try multiple URL extraction patterns
                    url_patterns = [
                        r'https?://(?!news\.google\.com)(?!www\.google\.com)[^\s"\'\x00-\x1f\x80-\xff]+',
                        r'https?://[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}[^\s"\'\x00-\x1f\x80-\xff]*',
                    ]

                    for pattern in url_patterns:
                        urls = re.findall(pattern, decoded)
                        # Filter out Google URLs
                        non_google_urls = [u for u in urls if 'google.com' not in u and 'google.co' not in u]

                        if non_google_urls:
                            # Clean the URL - remove any trailing junk
                            actual_url = non_google_urls[0].split('\x00')[0].split('\x08')[0].rstrip('\x00\x08')

                            # Validate URL structure
                            if actual_url.startswith('http') and '.' in actual_url:
                                print(f"   ✓ Decoded URL: {actual_url[:80]}...")
                                return actual_url

                except Exception as decode_error:
                    print(f"   ⚠️  Base64 decode failed: {decode_error}")

            # Method 2: Try to extract URL from redirect chain
            print(f"   Trying redirect method...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }

            # First, try HEAD request (faster)
            try:
                response = requests.head(
                    google_url,
                    allow_redirects=True,
                    timeout=5,
                    headers=headers
                )
                if response.url and 'google.com' not in response.url and 'google.co' not in response.url:
                    print(f"   ✓ Resolved via HEAD redirect: {response.url[:80]}...")
                    return response.url
            except:
                pass  # Fall through to GET method

            # Fall back to GET request
            response = requests.get(
                google_url,
                allow_redirects=True,
                timeout=10,
                headers=headers
            )

            # Check final URL
            if response.url and 'google.com' not in response.url and 'google.co' not in response.url:
                print(f"   ✓ Resolved via GET redirect: {response.url[:80]}...")
                return response.url

            # Method 3: Try to extract URL from HTML response
            if response.text:
                # Look for canonical URL in meta tags
                canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', response.text)
                if canonical_match:
                    canonical_url = canonical_match.group(1)
                    if 'google.com' not in canonical_url:
                        print(f"   ✓ Extracted canonical URL: {canonical_url[:80]}...")
                        return canonical_url

                # Look for og:url meta tag
                og_url_match = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', response.text)
                if og_url_match:
                    og_url = og_url_match.group(1)
                    if 'google.com' not in og_url:
                        print(f"   ✓ Extracted og:url: {og_url[:80]}...")
                        return og_url

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
