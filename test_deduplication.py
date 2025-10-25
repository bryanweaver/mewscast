"""
Test script to verify improved deduplication logic catches known duplicates
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from post_tracker import PostTracker
from datetime import datetime, timezone

# Test configuration with new thresholds
test_config = {
    'enabled': True,
    'topic_cooldown_hours': 72,
    'topic_similarity_threshold': 0.40,
    'content_cooldown_hours': 72,
    'content_similarity_threshold': 0.65,
    'source_cooldown_hours': 2160,
    'url_deduplication': True,
    'max_history_days': 90,
    'allow_updates': True,
    'update_keywords': [
        'update', 'breaking', 'just', 'now', 'latest', 'new',
        'charged', 'convicted', 'arrested', 'released', 'sentenced',
        'announced', 'confirmed', 'denied', 'reverses', 'overturned',
        'escalates', 'responds', 'fires back', 'doubles down',
        'backs down', 'resigns', 'appointed', 'elected', 'voted',
        'passes', 'fails', 'after', 'following', 'amid', 'in wake of'
    ]
}

# Initialize tracker with test config
tracker = PostTracker(config=test_config)

# Test Case 1: Portland National Guard duplicate (no update keywords)
print("="*60)
print("Test Case 1: Portland National Guard stories (Oct 20 & 22)")
print("="*60)

story1 = {
    'title': '9th Circuit rules that National Guard can deploy to Portland',
    'url': 'https://www.npr.org/test1',
    'source': 'NPR'
}

story2 = {
    'title': 'Appeals court allows Trump\'s deployment of National Guard in Portland',
    'url': 'https://www.nbcnews.com/test2',
    'source': 'NBC News'
}

# Simulate first story posted
tracker.record_post(story1, post_content="First story about National Guard")

# Check if second story is duplicate
is_dup = tracker._similar_topic_posted(story2['title'], hours=72)
print(f"\nStory 1: {story1['title']}")
print(f"Story 2: {story2['title']}")
print(f"Is duplicate? {is_dup}")
print(f"Expected: True (should be caught as duplicate - no update keywords)")
print()

# Test Case 1b: Same story but WITH update keyword
print("="*60)
print("Test Case 1b: Portland update (should be ALLOWED)")
print("="*60)

story2_update = {
    'title': 'Breaking: Appeals court reverses ruling on National Guard in Portland',
    'url': 'https://www.nbcnews.com/test2b',
    'source': 'NBC News'
}

is_update = tracker._is_update_story(story2_update['title'])
is_dup_update = tracker._similar_topic_posted(story2_update['title'], hours=72)

print(f"\nStory 1: {story1['title']}")
print(f"Story 2: {story2_update['title']}")
print(f"Is update? {is_update}")
print(f"Is duplicate? {is_dup_update}")
print(f"Expected: Is update=True, Is duplicate=False (update keywords allow it through)")
print()

# Test Case 2: UFO stories
print("="*60)
print("Test Case 2: UFO Congressional testimony (Oct 17 & 18)")
print("="*60)

# Reset tracker
tracker = PostTracker(config=test_config)

story3 = {
    'title': 'Witness tells Congress UFO came \'right for us\' in dramatic testimony',
    'url': 'https://www.cnn.com/test3',
    'source': 'CNN'
}

story4 = {
    'title': 'Witness tells Congress UFO came \'right for us\' in new hearings',
    'url': None,
    'source': 'CNN'
}

# First story posted
tracker.record_post(story3, post_content="First UFO story")

# Check source cooldown
source_blocked = tracker._source_posted('CNN', hours=2160)
print(f"\nStory 1: {story3['title']}")
print(f"Story 2: {story4['title']}")
print(f"Source blocked? {source_blocked}")
print(f"Expected: True (same source CNN within 90 days)")

# Also check topic similarity
topic_dup = tracker._similar_topic_posted(story4['title'], hours=72)
print(f"Topic duplicate? {topic_dup}")
print(f"Expected: True (nearly identical topics)")
print()

# Test Case 3: Different stories (should NOT be blocked)
print("="*60)
print("Test Case 3: Unrelated stories (should NOT be blocked)")
print("="*60)

# Reset tracker
tracker = PostTracker(config=test_config)

story5 = {
    'title': 'Stock market crashes amid inflation fears',
    'url': 'https://www.reuters.com/test5',
    'source': 'Reuters'
}

story6 = {
    'title': 'Elon Musk announces new AI breakthrough',
    'url': 'https://www.bloomberg.com/test6',
    'source': 'Bloomberg'
}

tracker.record_post(story5, post_content="Stock market story")

topic_dup = tracker._similar_topic_posted(story6['title'], hours=72)
source_dup = tracker._source_posted(story6['source'], hours=2160)

print(f"\nStory 1: {story5['title']}")
print(f"Story 2: {story6['title']}")
print(f"Topic duplicate? {topic_dup}")
print(f"Source duplicate? {source_dup}")
print(f"Expected: Both False (completely different stories and sources)")
print()

print("="*60)
print("Test Case 4: Cupertino CBS show (Oct 23-24 actual duplicate)")
print("="*60)

# Reset tracker
tracker = PostTracker(config=test_config)

story_cupertino1 = {
    'title': "Silicon Valley Drama 'Cupertino' Lands CBS Series Pickup for 2026-27 - The Hollywood Reporter",
    'url': 'https://www.hollywoodreporter.com/test1',
    'source': 'The Hollywood Reporter'
}

story_cupertino2 = {
    'title': "CBS Orders Silicon Valley Legal Drama 'Cupertino' From Robert and Michelle King With Mike Colter Starring - Variety",
    'url': 'https://variety.com/test2',
    'source': 'Variety'
}

# First story posted
tracker.record_post(story_cupertino1, post_content="CBS orders Cupertino show")

# Check if second story is duplicate (should catch with entity matching)
print(f"\nStory 1: {story_cupertino1['title'][:80]}...")
print(f"Story 2: {story_cupertino2['title'][:80]}...")

# Extract proper nouns to see what we're matching
nouns1 = tracker._extract_proper_nouns(story_cupertino1['title'])
nouns2 = tracker._extract_proper_nouns(story_cupertino2['title'])
common = nouns1 & nouns2

print(f"\nProper nouns in Story 1: {sorted(nouns1)}")
print(f"Proper nouns in Story 2: {sorted(nouns2)}")
print(f"Common proper nouns: {sorted(common)} ({len(common)} matches)")

is_dup = tracker._similar_topic_posted(story_cupertino2['title'], hours=72)
print(f"\nIs duplicate? {is_dup}")
print(f"Expected: True (2+ entity matches: Cupertino, CBS, Silicon, Valley)")
print()

print("="*60)
print("Test completed!")
print("="*60)
