"""
Google News RSS integration for fetching real news articles
"""
import feedparser
import random
from typing import List, Dict, Optional
import time


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
                    article = {
                        'title': entry.title,
                        'description': entry.get('summary', ''),
                        'url': entry.link,
                        'source': source,
                        'published': entry.get('published', '')
                    }
                    print(f"✓ Found article from {source}")
                    return article

            # If no preferred source found, use first result
            entry = feed.entries[0]
            article = {
                'title': entry.title,
                'description': entry.get('summary', ''),
                'url': entry.link,
                'source': entry.get('source', {}).get('title', 'Google News'),
                'published': entry.get('published', '')
            }
            print(f"✓ Found article from {article['source']}")
            return article

        except Exception as e:
            print(f"✗ Error fetching article for '{topic}': {e}")
            return None
