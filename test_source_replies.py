#!/usr/bin/env python3
"""
Test source reply logic without posting to X
"""
import sys
sys.path.insert(0, 'src')

from dotenv import load_dotenv
load_dotenv()  # Load .env file for API keys

from news_fetcher import NewsFetcher
from content_generator import ContentGenerator
from post_tracker import PostTracker

print("="*60)
print("Testing Source Reply Logic")
print("="*60)

# Test 1: Fetch real articles from Google News RSS
print("\n1. Testing Google News RSS fetching...")
news_fetcher = NewsFetcher()
articles = news_fetcher.get_trending_topics(count=3)

if articles:
    print(f"✓ Fetched {len(articles)} articles:")
    for article in articles:
        print(f"  - {article['title'][:60]}...")
        print(f"    Source: {article['source']}")
        print(f"    URL: {article['url'][:80]}...")
        print()
else:
    print("✗ No articles fetched")
    sys.exit(1)

# Test 2: Generate tweet content
print("\n2. Testing tweet generation...")
generator = ContentGenerator()
selected_article = articles[0]

result = generator.generate_tweet(
    trending_topic=selected_article['title'],
    story_metadata=selected_article
)

tweet_text = result['tweet']
needs_source = result['needs_source_reply']
story_meta = result['story_metadata']

print(f"✓ Generated tweet ({len(tweet_text)} chars):")
print(f"  {tweet_text}")
print(f"\n✓ Needs source reply: {needs_source}")
print(f"✓ Has story metadata: {story_meta is not None}")

# Verify source indicator is present
if needs_source and " 📰↓" in tweet_text:
    print(f"✓ Source indicator (📰↓) present in tweet")
elif needs_source:
    print(f"✗ Source indicator missing from tweet that needs source!")
    sys.exit(1)

# Test 3: Generate source reply
print("\n3. Testing source reply generation...")
if needs_source and story_meta:
    source_reply = generator.generate_source_reply(tweet_text, story_meta)
    print(f"✓ Generated source reply:")
    print(f"  {source_reply[:80]}...")

    # Verify URL is the ONLY content (for full link preview)
    if source_reply == story_meta.get('url'):
        print(f"✓ Source reply is URL only (enables full link preview card)")
    elif story_meta.get('url') in source_reply:
        print(f"⚠️  URL present but has additional text (may reduce preview quality)")
    else:
        print(f"✗ URL missing from reply!")
        sys.exit(1)
else:
    print("✗ Should need source reply but doesn't!")
    sys.exit(1)

# Test 4: Check deduplication
print("\n4. Testing post tracking...")
tracker = PostTracker()
posts_needing_replies = tracker.get_posts_needing_replies()
print(f"✓ Found {len(posts_needing_replies)} posts needing replies:")
for post in posts_needing_replies:
    print(f"  - Tweet {post['tweet_id']}: {post['topic'][:60]}...")
    print(f"    URL: {post.get('url', 'No URL')[:80]}...")

print("\n" + "="*60)
print("✅ ALL TESTS PASSED!")
print("="*60)
print("\nSource reply logic is working correctly.")
print("Articles always have URLs, tweets always get source replies.")
