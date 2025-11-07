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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


class NewsFetcher:
    """Fetches real news articles from Google News RSS"""

    def __init__(self):
        """Initialize news fetcher with search categories"""
        # News categories to search (aligned with bot's focus)
        # GENERIC TOPICS covering all major news areas
        self.news_categories = [
            # Politics (12)
            "presidential controversy",
            "Congressional scandal",
            "Supreme Court decision",
            "White House crisis",
            "political corruption charges",
            "election interference",
            "government shutdown",
            "Senate filibuster battle",
            "campaign finance violation",
            "political resignation",
            "executive order backlash",
            "impeachment proceedings",

            # Economy/Finance (10)
            "stock market volatility",
            "cryptocurrency crash",
            "Federal Reserve rates",
            "corporate bankruptcy",
            "CEO ousted scandal",
            "major company layoffs",
            "inflation report shock",
            "gas prices spike",
            "recession warning",
            "bank collapse",

            # Tech (8)
            "Big Tech antitrust",
            "major data breach",
            "social media controversy",
            "AI safety concerns",
            "tech billionaire scandal",
            "platform censorship battle",
            "ransomware attack",
            "tech monopoly lawsuit",

            # International (8)
            "international military conflict",
            "diplomatic crisis",
            "trade war escalation",
            "border security crisis",
            "terrorism threat",
            "foreign election interference",
            "international sanctions",
            "nuclear weapons threat",

            # Crime/Justice (8)
            "high-profile arrest",
            "FBI raid investigation",
            "mass shooting incident",
            "police brutality case",
            "celebrity criminal charges",
            "organized crime bust",
            "domestic terrorism plot",
            "cartel drug bust",

            # Business/Labor (6)
            "merger blocked antitrust",
            "labor union strike",
            "corporate fraud scandal",
            "insider trading charges",
            "massive product recall",
            "whistleblower lawsuit",

            # Culture/Sports (6)
            "celebrity arrest scandal",
            "viral social media controversy",
            "sports betting investigation",
            "athlete doping scandal",
            "streaming service drama",
            "influencer exposed fraud",

            # UAP/UFO & Disclosure (6)
            "UFO Pentagon disclosure",
            "UAP Congressional hearing",
            "alien technology claims",
            "military UFO encounter",
            "government UFO coverup",
            "extraterrestrial evidence",

            # Space (6)
            "NASA mission breakthrough",
            "SpaceX launch incident",
            "astronaut emergency",
            "space station crisis",
            "asteroid threat warning",
            "Mars discovery announcement",

            # Science/Health (8)
            "pandemic outbreak warning",
            "vaccine controversy",
            "medical breakthrough",
            "climate crisis report",
            "environmental disaster",
            "nuclear accident",
            "disease outbreak",
            "scientific fraud exposed"
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
            # CRITICAL: Only get recent news (last 3 days max)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=3)
            articles = []

            for entry in feed.entries[:30]:  # Check first 30 results for more depth
                if len(articles) >= max_articles:
                    break

                # Check article date FIRST - skip old news
                published_str = entry.get('published', '')
                if published_str:
                    try:
                        published_date = parsedate_to_datetime(published_str)
                        if published_date < cutoff_date:
                            # Skip articles older than 3 days
                            continue
                    except Exception as e:
                        # If we can't parse the date, skip the article to be safe
                        print(f"   ⚠️  Could not parse date for article, skipping")
                        continue

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
                        'published': published_str,
                        'published_date': published_date.isoformat() if published_str else None
                    }
                    articles.append(article)

            if articles:
                print(f"✓ Found {len(articles)} articles from major sources")
            return articles

        except Exception as e:
            print(f"✗ Error fetching articles for '{topic}': {e}")
            return []

    def get_top_stories(self, max_stories: int = 20) -> List[Dict]:
        """
        Fetch current top stories from Google News main feed
        This shows what's ACTUALLY trending right now

        Args:
            max_stories: Maximum number of top stories to fetch

        Returns:
            List of article dictionaries with 'title', 'description', 'url', 'source', 'published'
        """
        try:
            # Google News Top Stories RSS feed (US)
            rss_url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"

            print(f"🔥 Fetching TOP STORIES from Google News (what's trending NOW)...")

            # Parse RSS feed
            feed = feedparser.parse(rss_url)

            if not feed.entries:
                print(f"   ⚠️  No top stories found")
                return []

            # Get top stories from major sources
            articles = []

            # Preferred sources (same as get_articles_for_topic)
            preferred_sources = [
                'Reuters', 'Associated Press', 'AP News', 'Bloomberg',
                'The Wall Street Journal', 'Financial Times',
                'The New York Times', 'The Washington Post', 'USA Today',
                'CNN', 'BBC', 'NBC News', 'CBS News', 'ABC News', 'NPR',
                'Fox News', 'MSNBC', 'Politico', 'The Hill',
                'CNBC', 'Forbes', 'Business Insider', 'MarketWatch',
                'The Guardian', 'The Atlantic', 'Time', 'Newsweek',
                'Axios', 'ProPublica', 'The Independent',
                'Al Jazeera', 'The Economist'
            ]

            for entry in feed.entries[:max_stories]:
                # Extract source from entry
                source = entry.get('source', {}).get('title', 'Unknown')

                # Get published date
                published_str = entry.get('published', '')
                published_date = None
                if published_str:
                    try:
                        published_date = parsedate_to_datetime(published_str)
                    except:
                        pass

                # Prioritize major sources
                if any(pref in source for pref in preferred_sources):
                    actual_url = self.resolve_google_news_url(entry.link)

                    article = {
                        'title': entry.title,
                        'description': entry.get('summary', ''),
                        'url': actual_url,
                        'source': source,
                        'published': published_str,
                        'published_date': published_date.isoformat() if published_date else None
                    }
                    articles.append(article)

            if articles:
                print(f"✓ Found {len(articles)} top stories from major sources")
                for i, article in enumerate(articles[:5], 1):
                    print(f"   {i}. {article['source']}: {article['title'][:60]}...")

            return articles

        except Exception as e:
            print(f"✗ Error fetching top stories: {e}")
            return []

    def extract_trending_topics(self, top_stories: List[Dict]) -> List[str]:
        """
        Extract trending topics/keywords from top story headlines
        This identifies what's actually news-worthy RIGHT NOW

        Args:
            top_stories: List of top story articles

        Returns:
            List of trending topic strings (most frequent keywords/entities)
        """
        import re
        from collections import Counter

        if not top_stories:
            return []

        # Extract all words from headlines
        all_words = []
        proper_nouns = []

        # Common stop words to ignore
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be',
            'this', 'that', 'these', 'those', 'it', 'can', 'will', 'says', 'after',
            'has', 'have', 'had', 'not', 'what', 'who', 'why', 'how', 'new'
        }

        for story in top_stories:
            title = story.get('title', '')

            # Split into words
            words = re.findall(r'\b[a-zA-Z]+\b', title)

            for word in words:
                word_lower = word.lower()

                # Skip stop words and short words
                if word_lower in stop_words or len(word) < 3:
                    continue

                # If capitalized, it's likely a proper noun (person, place, organization)
                if word[0].isupper():
                    proper_nouns.append(word)

                all_words.append(word_lower)

        # Count frequency of terms
        word_counts = Counter(all_words)
        noun_counts = Counter(proper_nouns)

        # Prioritize proper nouns (specific entities) and frequent keywords
        trending = []

        # Add top proper nouns (people, places, orgs - these are specific stories)
        for noun, count in noun_counts.most_common(10):
            if count >= 2:  # Appeared in 2+ headlines = trending
                trending.append(noun)

        # Add top keywords (general topics)
        for word, count in word_counts.most_common(10):
            if count >= 2 and word not in [t.lower() for t in trending]:
                trending.append(word)

        return trending[:15]  # Top 15 trending topics
