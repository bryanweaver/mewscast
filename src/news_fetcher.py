"""
Google News RSS integration for fetching real news articles
"""
import feedparser
import random
import requests
from typing import List, Dict, Optional
import time
import re
from googlenewsdecoder import gnewsdecoder


class NewsFetcher:
    """Fetches real news articles from Google News RSS"""

    def __init__(self):
        """Initialize news fetcher with search categories"""
        # News categories to search (aligned with bot's focus)
        # SPICY TOPICS that people actually care about
        self.news_categories = [
            "Trump indictment",
            "Biden scandal",
            "Congress chaos",
            "Supreme Court ruling",
            "stock market crash",
            "Bitcoin surge",
            "Elon Musk",
            "AI breakthrough",
            "UFO Pentagon disclosure",
            "FBI investigation",
            "corruption scandal",
            "tech layoffs",
            "Silicon Valley drama",
            "celebrity controversy",
            "viral news",
            "breaking international crisis"
        ]

    def resolve_google_news_url(self, google_url: str) -> str:
        """
        Resolve Google News proxy URL to the actual article URL using googlenewsdecoder

        Args:
            google_url: Google News RSS article URL

        Returns:
            Actual article URL, or original URL if resolution fails
        """
        try:
            # Use googlenewsdecoder library (updated Jan 2025)
            print(f"   📡 Decoding Google News URL...")
            result = gnewsdecoder(google_url, interval=1)

            if result.get("status"):
                decoded_url = result["decoded_url"]
                print(f"   ✓ Decoded URL: {decoded_url[:80]}...")
                return decoded_url
            else:
                error_msg = result.get("message", "Unknown error")
                print(f"   ⚠️  Decoder failed: {error_msg}")
                print(f"   Using original Google News URL as fallback")
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

    def get_articles_for_topic(self, topic: str, max_articles: int = 10) -> List[Dict]:
        """
        Fetch multiple news articles from Google News RSS for a topic

        Args:
            topic: The trending topic to search for
            max_articles: Maximum number of articles to return (default 10)

        Returns:
            List of article dictionaries with 'title', 'description', 'url', 'source'
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
                return []

            # Filter for MAJOR news sources only (no local/college papers!)
            # Prioritize sources that cover big, national/international stories
            preferred_sources = [
                # Top Tier - Breaking news & major stories
                'Reuters', 'Associated Press', 'AP News', 'Bloomberg',
                'The Wall Street Journal', 'Financial Times',

                # Major National Papers
                'The New York Times', 'The Washington Post', 'USA Today',

                # TV News (high engagement)
                'CNN', 'Fox News', 'NBC News', 'CBS News', 'ABC News', 'MSNBC',

                # Political Coverage
                'Politico', 'The Hill', 'Axios', 'Punchbowl News',

                # Tech & Business
                'TechCrunch', 'The Verge', 'Ars Technica', 'CNBC', 'Business Insider',

                # International
                'BBC', 'The Guardian', 'Al Jazeera',

                # Entertainment/Viral (high engagement)
                'TMZ', 'Variety', 'Hollywood Reporter', 'People'
            ]

            # BLACKLIST: Never use these boring sources
            blacklist_sources = [
                'Daily Pennsylvanian', 'Idaho Press', 'College', 'University',
                'Local', 'Gazette', 'Tribune', 'Herald', 'Observer',
                'Community News', 'Patch', 'Town', 'City Council'
            ]

            # Collect multiple articles from preferred sources
            articles = []
            for entry in feed.entries[:30]:  # Check first 30 results for more depth
                if len(articles) >= max_articles:
                    break

                source = entry.get('source', {}).get('title', 'Unknown')

                # Skip blacklisted sources (boring local news)
                if any(bad in source for bad in blacklist_sources):
                    continue

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
                    articles.append(article)

            if articles:
                print(f"✓ Found {len(articles)} articles from major sources")
            return articles

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
