"""
Test script to verify update detection and story clustering
Tests with real examples of duplicate stories
"""
import sys
import os

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from post_tracker import PostTracker
from datetime import datetime, timezone, timedelta

# Simulate the Trump sedition story progression
test_stories = [
    {
        'title': "Trump: Democrats' message to troops seditious behavior, punishable by death - BBC",
        'url': "https://www.bbc.com/news/articles/cx2p2dz9zk2o",
        'source': "BBC",
        'timestamp': datetime.now(timezone.utc) - timedelta(hours=20)
    },
    {
        'title': "'I'm not going to be intimidated': Rep. Crow responds to Trump's sedition threat - NPR",
        'url': "https://www.npr.org/2025/11/21/nx-s1-5615204/trump-sedition-death-threat",
        'source': "NPR",
        'timestamp': datetime.now(timezone.utc) - timedelta(hours=3)
    },
    {
        'title': "Trump says he wasn't threatening Democrats he accused of 'seditious behavior, punishable by death' - NBC News",
        'url': "https://www.nbcnews.com/politics/white-house/trump-democrats-sedition-death-threat-military-rcna245156",
        'source': "NBC News",
        'timestamp': datetime.now(timezone.utc)
    }
]

# Simulate MTG resignation story
mtg_stories = [
    {
        'title': "Marjorie Taylor Greene Says She Will Resign in January, After Break From Trump - The New York Times",
        'url': "https://www.nytimes.com/2025/11/21/us/politics/marjorie-taylor-greene-resigns.html",
        'source': "The New York Times",
        'timestamp': datetime.now(timezone.utc) - timedelta(hours=16)
    },
    {
        'title': "Politicians shocked by Marjorie Taylor Greene's surprise resignation announcement - The Guardian",
        'url': "https://www.theguardian.com/us-news/2025/nov/22/marjorie-taylor-greene-political-reactions",
        'source': "The Guardian",
        'timestamp': datetime.now(timezone.utc)
    }
]

def test_story_clustering():
    """Test that story clustering detects related articles"""
    print("="*60)
    print("Testing Story Clustering and Update Detection")
    print("="*60)

    # Create tracker with test config
    config = {
        'enabled': True,
        'topic_cooldown_hours': 48,
        'url_deduplication': True,
        'content_cooldown_hours': 72,
        'topic_similarity_threshold': 0.40
    }

    # Use a temporary history file
    tracker = PostTracker(history_file='test_history.json', config=config)

    # Clear existing history
    tracker.posts = []

    print("\nTest Case 1: Trump Sedition Story Progression")
    print("-" * 60)

    for i, story in enumerate(test_stories, 1):
        print(f"\n{i}. Checking: {story['title'][:80]}...")
        print(f"   Source: {story['source']}")

        status = tracker.check_story_status(story)

        print(f"   is_duplicate: {status['is_duplicate']}")
        print(f"   is_update: {status['is_update']}")
        print(f"   related_posts: {len(status['previous_posts'])} found")
        if status.get('cluster_info'):
            print(f"   cluster_info: {status['cluster_info']}")

        if status['previous_posts']:
            for j, prev in enumerate(status['previous_posts'], 1):
                prev_post = prev['post']
                print(f"      Related #{j}: {prev_post.get('topic', '')[:60]}...")
                print(f"                  Similarity: {prev['similarity']:.1%}")

        # Simulate posting (record to history)
        if not status['is_duplicate']:
            tracker.record_post(
                story_metadata=story,
                post_content=f"Test post about {story['title'][:50]}..."
            )
            print(f"   ✓ Would post (with {'UPDATE label' if status['is_update'] else 'no label'})")
        else:
            print(f"   ✗ BLOCKED - duplicate")

    print("\n" + "="*60)
    print("Test Case 2: MTG Resignation Story")
    print("-" * 60)

    for i, story in enumerate(mtg_stories, 1):
        print(f"\n{i}. Checking: {story['title'][:80]}...")
        print(f"   Source: {story['source']}")

        status = tracker.check_story_status(story)

        print(f"   is_duplicate: {status['is_duplicate']}")
        print(f"   is_update: {status['is_update']}")
        print(f"   related_posts: {len(status['previous_posts'])} found")
        if status.get('cluster_info'):
            print(f"   cluster_info: {status['cluster_info']}")

        if status['previous_posts']:
            for j, prev in enumerate(status['previous_posts'], 1):
                prev_post = prev['post']
                print(f"      Related #{j}: {prev_post.get('topic', '')[:60]}...")
                print(f"                  Similarity: {prev['similarity']:.1%}")

        # Simulate posting
        if not status['is_duplicate']:
            tracker.record_post(
                story_metadata=story,
                post_content=f"Test post about {story['title'][:50]}..."
            )
            print(f"   ✓ Would post (with {'UPDATE label' if status['is_update'] else 'no label'})")
        else:
            print(f"   ✗ BLOCKED - duplicate")

    print("\n" + "="*60)
    print("✅ Test Complete")
    print("="*60)

    # Cleanup test file
    if os.path.exists('test_history.json'):
        os.remove('test_history.json')

if __name__ == "__main__":
    test_story_clustering()
