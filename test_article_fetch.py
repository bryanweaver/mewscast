"""
Test script to verify article fetching and content generation improvements
"""
import sys
import os
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from news_fetcher import NewsFetcher
from content_generator import ContentGenerator

# Load environment variables
load_dotenv()

def main():
    print("="*60)
    print("Testing Article Fetch and Content Generation")
    print("="*60)
    print()

    # Test with the NPR article about Mamdani
    test_url = "https://www.npr.org/2025/11/21/nx-s1-5615169/trump-mamdani-oval-office-communist-socialist"
    test_title = "After calling him a 'communist,' Trump will meet Mamdani in the Oval Office Friday - NPR"

    print(f"📰 Test Article:")
    print(f"   Title: {test_title}")
    print(f"   URL: {test_url}")
    print()

    # Initialize components
    news_fetcher = NewsFetcher()
    content_generator = ContentGenerator()

    # Fetch full article content
    print("📄 Fetching article content...")
    article_content = news_fetcher.fetch_article_content(test_url)

    if article_content:
        print(f"✓ Fetched {len(article_content)} characters")
        print()
        print("Article Preview:")
        print("-" * 60)
        print(article_content[:500] + "...")
        print("-" * 60)
        print()
    else:
        print("✗ Failed to fetch article content")
        print()

    # Create story metadata
    story_metadata = {
        'title': test_title,
        'source': 'NPR',
        'url': test_url,
        'context': 'Trump to meet with political figure he previously called communist',
        'article_content': article_content
    }

    # Generate content
    print("🐱 Generating cat news commentary...")
    print()

    result = content_generator.generate_tweet(
        trending_topic=test_title,
        story_metadata=story_metadata
    )

    tweet_text = result['tweet']

    print("Generated Tweet:")
    print("="*60)
    print(tweet_text)
    print("="*60)
    print()

    # Check for common errors
    print("🔍 Checking for accuracy...")
    errors = []

    if 'Virginia' in tweet_text or 'virginia' in tweet_text:
        errors.append("❌ ERROR: Mentions Virginia (should be New York/NYC)")

    if 'Mayor' in tweet_text or 'mayor' in tweet_text:
        if article_content and 'Mayor' in article_content:
            print("✓ Correctly mentions Mayor (found in article)")
        else:
            errors.append("⚠️  WARNING: Mentions Mayor - verify this is in article")

    if 'NYC' in tweet_text or 'New York' in tweet_text:
        print("✓ Correctly mentions New York/NYC")

    if errors:
        print()
        for error in errors:
            print(error)
    else:
        print("✓ No obvious factual errors detected!")

    print()
    print("="*60)
    print("Test Complete")
    print("="*60)

if __name__ == "__main__":
    main()
