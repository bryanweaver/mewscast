"""
Google Trends integration for fetching real trending topics
"""
from pytrends.request import TrendReq
import feedparser
import random
from typing import List, Dict, Optional
import time


class NewsFetcher:
    """Fetches real trending topics from Google Trends"""

    def __init__(self):
        """Initialize Google Trends client"""
        self.pytrends = TrendReq(hl='en-US', tz=360)

    def get_trending_topics(self, count: int = 5, categories: List[str] = None) -> List[Dict]:
        """
        Fetch trending topics from Google Trends

        Args:
            count: Number of trending topics to fetch
            categories: List of categories to focus on (e.g., ['politics', 'national'])

        Returns:
            List of dictionaries with 'title' and 'context' for each trending topic
        """
        try:
            # Fetch real-time trending searches for United States
            trending = self.pytrends.trending_searches(pn='united_states')

            if trending is not None and not trending.empty:
                # Get top trending topics
                topics = trending[0].tolist()[:count * 2]  # Get more to filter

                # Filter for news-worthy topics (avoid celebrity gossip, sports scores, etc)
                filtered_topics = []
                for topic in topics:
                    topic_lower = topic.lower()
                    # Focus on political, national, economic topics
                    if any(keyword in topic_lower for keyword in [
                        'president', 'senate', 'house', 'congress', 'bill', 'law',
                        'election', 'vote', 'policy', 'government', 'trump', 'biden',
                        'economy', 'inflation', 'jobs', 'market', 'crisis', 'war',
                        'protest', 'strike', 'court', 'supreme', 'federal', 'state'
                    ]):
                        # Try to fetch actual article for this topic
                        article = self.get_article_for_topic(topic)

                        if article:
                            # Use real article data
                            filtered_topics.append({
                                'title': article['title'],
                                'context': article['description'][:200],  # Limit description length
                                'url': article['url'],
                                'source': article['source']
                            })
                        else:
                            # Fallback to just the trending topic
                            filtered_topics.append({
                                'title': topic,
                                'context': f"Currently trending on Google Trends",
                                'source': 'Google Trends US'
                            })

                        if len(filtered_topics) >= count:
                            break

                # If we filtered too much, use original topics with articles
                if len(filtered_topics) < count:
                    for topic in topics[:count]:
                        if topic not in [t['title'] for t in filtered_topics]:
                            # Try to fetch article
                            article = self.get_article_for_topic(topic)

                            if article:
                                filtered_topics.append({
                                    'title': article['title'],
                                    'context': article['description'][:200],
                                    'url': article['url'],
                                    'source': article['source']
                                })
                            else:
                                filtered_topics.append({
                                    'title': topic,
                                    'context': f"Currently trending on Google Trends",
                                    'source': 'Google Trends US'
                                })

                            if len(filtered_topics) >= count:
                                break

                print(f"✓ Fetched {len(filtered_topics)} trending topics with articles")
                return filtered_topics[:count]

        except Exception as e:
            print(f"✗ Error fetching Google Trends: {e}")

        # Fallback to general topics if Google Trends fails
        print("ℹ️  Using fallback topics (Google Trends unavailable)")
        fallback = [
            {'title': 'economy and inflation', 'context': 'General topic', 'source': 'Fallback', 'url': None},
            {'title': 'political landscape', 'context': 'General topic', 'source': 'Fallback', 'url': None},
            {'title': 'technology innovation', 'context': 'General topic', 'source': 'Fallback', 'url': None},
            {'title': 'national policy', 'context': 'General topic', 'source': 'Fallback', 'url': None},
            {'title': 'cultural trends', 'context': 'General topic', 'source': 'Fallback', 'url': None}
        ]
        return random.sample(fallback, min(count, len(fallback)))

    def get_topic_context(self, topic: str) -> Optional[Dict]:
        """
        Get additional context about a trending topic

        Args:
            topic: The trending topic to get context for

        Returns:
            Dictionary with topic details or None
        """
        try:
            # Build interest over time
            self.pytrends.build_payload([topic], timeframe='now 1-d')

            # Get related queries
            related = self.pytrends.related_queries()

            context = {
                'title': topic,
                'related_queries': [],
                'source': 'Google Trends'
            }

            if topic in related and related[topic]['top'] is not None:
                top_queries = related[topic]['top']['query'].tolist()[:5]
                context['related_queries'] = top_queries

            return context

        except Exception as e:
            print(f"Note: Could not fetch context for '{topic}': {e}")
            return None

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
