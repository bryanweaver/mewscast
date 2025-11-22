"""
Fetch analytics for @mewscast posts from X and Bluesky

Usage: python scripts/analytics.py
(Run from repository root)
"""
import sys
import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from twitter_bot import TwitterBot
from bluesky_bot import BlueskyBot

def load_posts_history():
    """Load posts history"""
    history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'posts_history.json')
    with open(history_path, 'r') as f:
        return json.load(f)

def fetch_x_analytics(twitter_bot, posts):
    """Fetch analytics from X/Twitter for recent posts"""
    print("\n📊 X/Twitter Analytics")
    print("=" * 70)

    # Get recent posts with X tweet IDs (last 10)
    recent_x_posts = [p for p in posts if p.get('x_tweet_id')][-10:]

    if not recent_x_posts:
        print("❌ No X posts found in history")
        return

    total_likes = 0
    total_retweets = 0
    total_replies = 0
    total_impressions = 0

    print(f"📈 Fetching metrics for {len(recent_x_posts)} recent posts...\n")

    for post in recent_x_posts:
        tweet_id = post['x_tweet_id']

        try:
            # Fetch tweet with public metrics
            tweet = twitter_bot.client.get_tweet(
                tweet_id,
                tweet_fields=['public_metrics', 'created_at']
            )

            if tweet.data:
                metrics = tweet.data.public_metrics

                likes = metrics.get('like_count', 0)
                retweets = metrics.get('retweet_count', 0)
                replies = metrics.get('reply_count', 0)
                impressions = metrics.get('impression_count', 0)  # May not be available on free tier

                total_likes += likes
                total_retweets += retweets
                total_replies += replies
                if impressions:
                    total_impressions += impressions

                # Show top performing
                if likes + retweets > 2:  # Any engagement
                    print(f"💬 {likes}❤️  {retweets}🔁  {replies}💭")
                    print(f"   {post.get('content', '')[:80]}...")
                    if impressions:
                        print(f"   👁️  {impressions:,} impressions")
                    print()

        except Exception as e:
            print(f"⚠️  Could not fetch metrics for tweet {tweet_id}: {e}")

    # Summary
    avg_likes = total_likes / len(recent_x_posts) if recent_x_posts else 0
    avg_retweets = total_retweets / len(recent_x_posts) if recent_x_posts else 0
    avg_replies = total_replies / len(recent_x_posts) if recent_x_posts else 0

    print("\n📊 X Analytics Summary (Last 10 Posts):")
    print(f"   Total Engagement: {total_likes + total_retweets + total_replies}")
    print(f"   ❤️  Likes: {total_likes} (avg: {avg_likes:.1f})")
    print(f"   🔁 Retweets: {total_retweets} (avg: {avg_retweets:.1f})")
    print(f"   💭 Replies: {total_replies} (avg: {avg_replies:.1f})")
    if total_impressions:
        print(f"   👁️  Impressions: {total_impressions:,}")

def fetch_bluesky_analytics(bluesky_bot, posts):
    """Fetch analytics from Bluesky for recent posts"""
    print("\n\n📊 Bluesky Analytics")
    print("=" * 70)

    # Get recent posts with Bluesky URIs (last 10)
    recent_bsky_posts = [p for p in posts if p.get('bluesky_uri')][-10:]

    if not recent_bsky_posts:
        print("❌ No Bluesky posts found in history")
        return

    total_likes = 0
    total_reposts = 0
    total_replies = 0

    print(f"📈 Fetching metrics for {len(recent_bsky_posts)} recent posts...\n")

    for post in recent_bsky_posts:
        uri = post['bluesky_uri']

        try:
            # Fetch post thread to get metrics
            post_thread = bluesky_bot.client.app.bsky.feed.get_post_thread({'uri': uri})

            if post_thread and post_thread.thread:
                post_data = post_thread.thread.post

                likes = post_data.like_count or 0
                reposts = post_data.repost_count or 0
                replies = post_data.reply_count or 0

                total_likes += likes
                total_reposts += reposts
                total_replies += replies

                # Show top performing
                if likes + reposts > 2:  # Any engagement
                    print(f"💬 {likes}❤️  {reposts}🔁  {replies}💭")
                    print(f"   {post.get('content', '')[:80]}...")
                    print()

        except Exception as e:
            print(f"⚠️  Could not fetch metrics for post: {e}")

    # Summary
    avg_likes = total_likes / len(recent_bsky_posts) if recent_bsky_posts else 0
    avg_reposts = total_reposts / len(recent_bsky_posts) if recent_bsky_posts else 0
    avg_replies = total_replies / len(recent_bsky_posts) if recent_bsky_posts else 0

    print("\n📊 Bluesky Analytics Summary (Last 10 Posts):")
    print(f"   Total Engagement: {total_likes + total_reposts + total_replies}")
    print(f"   ❤️  Likes: {total_likes} (avg: {avg_likes:.1f})")
    print(f"   🔁 Reposts: {total_reposts} (avg: {avg_reposts:.1f})")
    print(f"   💭 Replies: {total_replies} (avg: {avg_replies:.1f})")

def analyze_posting_frequency(posts):
    """Analyze posting frequency and patterns"""
    print("\n\n📅 Posting Frequency Analysis")
    print("=" * 70)

    if not posts:
        print("❌ No posts found")
        return

    # Get timestamps
    timestamps = []
    for post in posts:
        try:
            ts = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            timestamps.append(ts)
        except:
            continue

    if len(timestamps) < 2:
        print("⚠️  Not enough posts to analyze")
        return

    # Calculate date range
    first_post = min(timestamps)
    last_post = max(timestamps)
    days_active = (last_post - first_post).days + 1

    # Posts per day
    posts_per_day = len(timestamps) / days_active if days_active > 0 else 0

    # Recent activity (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_posts = [ts for ts in timestamps if ts > week_ago]

    print(f"📊 Overall Stats:")
    print(f"   Total Posts: {len(posts)}")
    print(f"   Days Active: {days_active}")
    print(f"   Average Posts/Day: {posts_per_day:.1f}")
    print(f"   First Post: {first_post.strftime('%Y-%m-%d')}")
    print(f"   Last Post: {last_post.strftime('%Y-%m-%d')}")
    print(f"\n📈 Recent Activity (Last 7 Days):")
    print(f"   Posts: {len(recent_posts)}")
    print(f"   Average/Day: {len(recent_posts)/7:.1f}")

def main():
    """Main analytics function"""
    print("\n" + "=" * 70)
    print("📊 MEWSCAST ANALYTICS REPORT")
    print("=" * 70)

    # Load environment
    load_dotenv()

    # Load posts history
    print("\n📂 Loading posts history...")
    history = load_posts_history()
    posts = history.get('posts', [])
    print(f"✓ Loaded {len(posts)} posts")

    # Analyze posting frequency
    analyze_posting_frequency(posts)

    # Fetch X analytics
    try:
        print("\n🔗 Connecting to X/Twitter...")
        twitter_bot = TwitterBot()
        fetch_x_analytics(twitter_bot, posts)
    except Exception as e:
        print(f"❌ Error connecting to X: {e}")

    # Fetch Bluesky analytics
    try:
        print("\n🦋 Connecting to Bluesky...")
        bluesky_bot = BlueskyBot()
        fetch_bluesky_analytics(bluesky_bot, posts)
    except Exception as e:
        print(f"❌ Error connecting to Bluesky: {e}")

    print("\n" + "=" * 70)
    print("✅ Analytics report complete!")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
