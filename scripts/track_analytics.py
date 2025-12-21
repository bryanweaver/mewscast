"""
Track analytics over time for @mewscast posts

Stores engagement snapshots in analytics_history.json and generates
a Markdown report showing trends. Designed to run daily via GitHub Actions.

Usage: uv run --with tweepy --with atproto --with python-dotenv --with pyyaml python scripts/track_analytics.py
"""
import sys
import os
import json
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
HISTORY_FILE = os.path.join(REPO_ROOT, 'analytics_history.json')
REPORT_FILE = os.path.join(REPO_ROOT, 'docs', 'ANALYTICS.md')
DASHBOARD_FILE = os.path.join(REPO_ROOT, 'docs', 'index.html')
TRAILING_DAYS = 30


def load_analytics_history():
    """Load existing analytics history or create empty structure"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"posts": {}, "last_updated": None}


def save_analytics_history(history):
    """Save analytics history to JSON file"""
    history["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def load_posts_history():
    """Load posts history"""
    history_path = os.path.join(REPO_ROOT, 'posts_history.json')
    with open(history_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_posts_in_window(posts, days=TRAILING_DAYS):
    """Get posts from the last N days"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for post in posts:
        try:
            ts = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
            if ts > cutoff:
                recent.append(post)
        except:
            continue
    return recent


def fetch_bluesky_metrics(posts):
    """Fetch current metrics from Bluesky"""
    try:
        from bluesky_bot import BlueskyBot
        bot = BlueskyBot()
        print("Connected to Bluesky")
    except Exception as e:
        print(f"Could not connect to Bluesky: {e}")
        return {}

    metrics = {}
    for post in posts:
        uri = post.get('bluesky_uri')
        if not uri:
            continue

        try:
            thread = bot.client.app.bsky.feed.get_post_thread({'uri': uri})
            if thread and thread.thread:
                post_data = thread.thread.post
                metrics[uri] = {
                    "likes": post_data.like_count or 0,
                    "reposts": post_data.repost_count or 0,
                    "replies": post_data.reply_count or 0,
                }
        except Exception as e:
            print(f"Could not fetch Bluesky post: {e}")

    return metrics


def fetch_x_metrics(posts):
    """Fetch current metrics from X (graceful failure)"""
    try:
        from twitter_bot import TwitterBot
        bot = TwitterBot()
        print("Connected to X")
    except Exception as e:
        print(f"Could not connect to X (continuing without): {e}")
        return {}

    metrics = {}
    for post in posts:
        tweet_id = post.get('x_tweet_id')
        if not tweet_id:
            continue

        try:
            tweet = bot.client.get_tweet(
                tweet_id,
                tweet_fields=['public_metrics', 'created_at']
            )
            if tweet.data:
                m = tweet.data.public_metrics
                metrics[tweet_id] = {
                    "likes": m.get('like_count', 0),
                    "retweets": m.get('retweet_count', 0),
                    "replies": m.get('reply_count', 0),
                    "impressions": m.get('impression_count', 0),
                }
        except Exception as e:
            print(f"Could not fetch X tweet {tweet_id}: {e}")

    return metrics


def update_history(history, posts, bluesky_metrics, x_metrics):
    """Add new snapshot to history for each post"""
    now = datetime.now(timezone.utc).isoformat()

    for post in posts:
        # Extract source and topic
        source = post.get('source', 'Unknown')
        topic = post.get('topic', '')

        # Bluesky
        uri = post.get('bluesky_uri')
        if uri and uri in bluesky_metrics:
            if uri not in history["posts"]:
                history["posts"][uri] = {
                    "content": post.get('content', '')[:100],
                    "posted_at": post.get('timestamp'),
                    "platform": "bluesky",
                    "source": source,
                    "topic": topic,
                    "linked_x_id": post.get('x_tweet_id'),
                    "snapshots": []
                }
            history["posts"][uri]["snapshots"].append({
                "timestamp": now,
                **bluesky_metrics[uri]
            })

        # X
        tweet_id = post.get('x_tweet_id')
        if tweet_id and tweet_id in x_metrics:
            key = f"x:{tweet_id}"
            if key not in history["posts"]:
                history["posts"][key] = {
                    "content": post.get('content', '')[:100],
                    "posted_at": post.get('timestamp'),
                    "platform": "x",
                    "source": source,
                    "topic": topic,
                    "linked_bluesky_uri": post.get('bluesky_uri'),
                    "snapshots": []
                }
            history["posts"][key]["snapshots"].append({
                "timestamp": now,
                **x_metrics[tweet_id]
            })

    return history


def prune_old_posts(history, days=TRAILING_DAYS):
    """Remove posts older than the trailing window"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    to_remove = []
    for post_id, post_data in history["posts"].items():
        try:
            posted_at = datetime.fromisoformat(post_data["posted_at"].replace('Z', '+00:00'))
            if posted_at < cutoff:
                to_remove.append(post_id)
        except:
            continue

    for post_id in to_remove:
        del history["posts"][post_id]

    if to_remove:
        print(f"Pruned {len(to_remove)} posts older than {days} days")

    return history


def calculate_growth(snapshots):
    """Calculate engagement growth between snapshots"""
    if len(snapshots) < 2:
        return None

    latest = snapshots[-1]
    previous = snapshots[-2]

    return {
        "likes": latest.get("likes", 0) - previous.get("likes", 0),
        "reposts": latest.get("reposts", latest.get("retweets", 0)) - previous.get("reposts", previous.get("retweets", 0)),
        "replies": latest.get("replies", 0) - previous.get("replies", 0),
    }


def generate_markdown_report(history):
    """Generate Markdown report with trends"""
    now = datetime.now(timezone.utc)

    # Separate by platform
    bluesky_posts = {k: v for k, v in history["posts"].items() if v["platform"] == "bluesky"}
    x_posts = {k: v for k, v in history["posts"].items() if v["platform"] == "x"}

    # Calculate totals
    def sum_latest(posts, field):
        total = 0
        for p in posts.values():
            if p["snapshots"]:
                total += p["snapshots"][-1].get(field, 0)
        return total

    def sum_growth(posts, field):
        total = 0
        for p in posts.values():
            growth = calculate_growth(p["snapshots"])
            if growth:
                total += growth.get(field, 0)
        return total

    # Build report
    lines = [
        "# Mewscast Analytics",
        "",
        f"*Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"Tracking engagement for posts from the last {TRAILING_DAYS} days.",
        "",
        "---",
        "",
        "## Summary",
        "",
    ]

    # Bluesky summary
    if bluesky_posts:
        bsky_likes = sum_latest(bluesky_posts, "likes")
        bsky_reposts = sum_latest(bluesky_posts, "reposts")
        bsky_replies = sum_latest(bluesky_posts, "replies")
        bsky_likes_growth = sum_growth(bluesky_posts, "likes")
        bsky_reposts_growth = sum_growth(bluesky_posts, "reposts")

        lines.extend([
            "### Bluesky",
            "",
            f"| Metric | Total | Since Last Run |",
            f"|--------|-------|----------------|",
            f"| Posts tracked | {len(bluesky_posts)} | - |",
            f"| Likes | {bsky_likes} | {'+' if bsky_likes_growth >= 0 else ''}{bsky_likes_growth} |",
            f"| Reposts | {bsky_reposts} | {'+' if bsky_reposts_growth >= 0 else ''}{bsky_reposts_growth} |",
            f"| Replies | {bsky_replies} | - |",
            "",
        ])

    # X summary
    if x_posts:
        x_likes = sum_latest(x_posts, "likes")
        x_retweets = sum_latest(x_posts, "retweets")
        x_replies = sum_latest(x_posts, "replies")
        x_likes_growth = sum_growth(x_posts, "likes")

        lines.extend([
            "### X (Twitter)",
            "",
            f"| Metric | Total | Since Last Run |",
            f"|--------|-------|----------------|",
            f"| Posts tracked | {len(x_posts)} | - |",
            f"| Likes | {x_likes} | {'+' if x_likes_growth >= 0 else ''}{x_likes_growth} |",
            f"| Retweets | {x_retweets} | - |",
            f"| Replies | {x_replies} | - |",
            "",
        ])
    elif not x_posts:
        lines.extend([
            "### X (Twitter)",
            "",
            "*No X data collected (API unavailable or rate limited)*",
            "",
        ])

    # Top performers
    lines.extend([
        "---",
        "",
        "## Top Performers",
        "",
    ])

    # Sort by total engagement
    def total_engagement(post_data):
        if not post_data["snapshots"]:
            return 0
        latest = post_data["snapshots"][-1]
        return (latest.get("likes", 0) +
                latest.get("reposts", latest.get("retweets", 0)) +
                latest.get("replies", 0))

    all_posts = list(history["posts"].items())
    all_posts.sort(key=lambda x: total_engagement(x[1]), reverse=True)

    for post_id, post_data in all_posts[:5]:
        if not post_data["snapshots"]:
            continue
        latest = post_data["snapshots"][-1]
        platform = post_data["platform"].upper()
        content = post_data["content"][:80]
        likes = latest.get("likes", 0)
        reposts = latest.get("reposts", latest.get("retweets", 0))

        lines.extend([
            f"**[{platform}]** {likes} likes, {reposts} reposts",
            f"> {content}...",
            "",
        ])

    # Footer
    lines.extend([
        "---",
        "",
        f"*Data snapshots: {sum(len(p['snapshots']) for p in history['posts'].values())} total across {len(history['posts'])} posts*",
    ])

    return "\n".join(lines)


def generate_dashboard(history):
    """Generate HTML dashboard with embedded analytics data"""
    import re

    # Read the HTML template
    with open(DASHBOARD_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    # Embed the analytics data
    data_json = json.dumps(history, ensure_ascii=False)

    # Replace the placeholder with actual data
    # Use re.DOTALL so .*? matches across newlines (in case of previously corrupted data)
    # Use lambda to prevent re.sub from interpreting \n in JSON as backreferences
    pattern = r'/\* ANALYTICS_DATA_PLACEHOLDER \*/.*?/\* END_ANALYTICS_DATA \*/'
    replacement = f'/* ANALYTICS_DATA_PLACEHOLDER */ {data_json} /* END_ANALYTICS_DATA */'
    html = re.sub(pattern, lambda m: replacement, html, flags=re.DOTALL)

    # Write the updated HTML
    with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    print("=" * 60)
    print("MEWSCAST ANALYTICS TRACKER")
    print("=" * 60)

    load_dotenv()

    # Load data
    print("\nLoading posts history...")
    posts_history = load_posts_history()
    posts = posts_history.get('posts', [])

    print("\nLoading analytics history...")
    analytics_history = load_analytics_history()

    # Get posts in trailing window
    recent_posts = get_posts_in_window(posts, TRAILING_DAYS)
    print(f"Found {len(recent_posts)} posts in last {TRAILING_DAYS} days")

    # Fetch current metrics
    print("\nFetching Bluesky metrics...")
    bluesky_metrics = fetch_bluesky_metrics(recent_posts)
    print(f"Got metrics for {len(bluesky_metrics)} Bluesky posts")

    print("\nFetching X metrics...")
    x_metrics = fetch_x_metrics(recent_posts)
    print(f"Got metrics for {len(x_metrics)} X posts")

    # Update history
    print("\nUpdating history...")
    analytics_history = update_history(analytics_history, recent_posts, bluesky_metrics, x_metrics)
    analytics_history = prune_old_posts(analytics_history, TRAILING_DAYS)

    # Save history
    save_analytics_history(analytics_history)
    print(f"Saved to {HISTORY_FILE}")

    # Generate report
    print("\nGenerating Markdown report...")
    report = generate_markdown_report(analytics_history)

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Saved to {REPORT_FILE}")

    # Generate HTML dashboard
    print("\nGenerating HTML dashboard...")
    generate_dashboard(analytics_history)
    print(f"Saved to {DASHBOARD_FILE}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
