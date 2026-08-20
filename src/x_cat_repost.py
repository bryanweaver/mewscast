#!/usr/bin/env python3
"""
X Cat Repost CLI — native retweet (classic RT) of cute cat posts.

Bryan's workflow: dispatch with a tweet_id of a cute cat post from another
account. This bot will retweet it natively (no quote, no commentary).

Usage:
    python src/x_cat_repost.py --tweet-id 1234567890 --dry-run
    python src/x_cat_repost.py --tweet-id 1234567890

Cap: max 2 successful RTs per UTC day. History stored in x_cat_repost_history.json.

Safety:
    - Rejects our own tweets (via get_me check)
    - Rejects tweets containing news/politics keywords (if tweet text is available)
    - Never falls back to quote_tweet on 403
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional

HISTORY_FILE = "x_cat_repost_history.json"
MAX_RTS_PER_DAY = 2

REJECT_KEYWORDS = [
    "breaking news",
    "politics",
    "election",
    "congress",
    "senate",
    "president",
    "trump",
    "biden",
    "democrat",
    "republican",
    "vote",
    "ballot",
    "immigration",
    "border",
    "ukraine",
    "russia",
    "china",
    "war",
    "military",
    "terrorist",
    "shooting",
    "killed",
    "dead",
    "death",
    "murdered",
    "genocide",
]


def load_history() -> dict:
    """Load the repost history from disk."""
    if not os.path.exists(HISTORY_FILE):
        return {"reposts": []}
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"reposts": []}


def save_history(history: dict) -> None:
    """Save the repost history to disk."""
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def count_today_reposts(history: dict) -> int:
    """Count how many successful reposts we've done today (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = 0
    for entry in history.get("reposts", []):
        if entry.get("date") == today and entry.get("success"):
            count += 1
    return count


def is_own_tweet(tweet_id: str) -> bool:
    """Check if the tweet belongs to our authenticated account."""
    try:
        from twitter_bot import TwitterBot
        bot = TwitterBot()
        me = bot.get_me()
        if not me:
            print("⚠ Could not fetch authenticated user; skipping own-tweet check")
            return False

        response = bot.client.get_tweet(tweet_id, expansions=["author_id"])
        if not response or not getattr(response, "data", None):
            print(f"⚠ Could not fetch tweet {tweet_id}; skipping own-tweet check")
            return False

        author_id = str(response.data.author_id)
        my_id = str(me["id"])
        if author_id == my_id:
            print(f"✗ Rejected: tweet {tweet_id} is our own tweet")
            return True
        return False
    except Exception as e:
        print(f"⚠ Error checking tweet ownership: {e}")
        return False


def contains_reject_keywords(tweet_text: Optional[str]) -> bool:
    """Check if tweet text contains news/politics keywords."""
    if not tweet_text:
        return False
    text_lower = tweet_text.lower()
    for kw in REJECT_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
            print(f"✗ Rejected: tweet contains keyword '{kw}'")
            return True
    return False


def get_tweet_text(tweet_id: str) -> Optional[str]:
    """Fetch the tweet text for keyword checking."""
    try:
        from twitter_bot import TwitterBot
        bot = TwitterBot()
        response = bot.client.get_tweet(tweet_id, tweet_fields=["text"])
        if response and getattr(response, "data", None):
            return response.data.text
        return None
    except Exception as e:
        print(f"⚠ Could not fetch tweet text: {e}")
        return None


def do_retweet(tweet_id: str) -> bool:
    """Perform the native retweet. Returns True on success."""
    try:
        from twitter_bot import TwitterBot
        bot = TwitterBot()
        result = bot.retweet(tweet_id)
        return result is not None
    except Exception as e:
        print(f"✗ Retweet failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Native retweet (classic RT) of cute cat posts"
    )
    parser.add_argument(
        "--tweet-id",
        required=True,
        help="ID of the tweet to retweet",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without actually retweeting",
    )
    args = parser.parse_args()

    tweet_id = args.tweet_id.strip()
    dry_run = args.dry_run

    print(f"=== X Cat Repost {'(DRY RUN)' if dry_run else ''} ===")
    print(f"Tweet ID: {tweet_id}")

    history = load_history()
    today_count = count_today_reposts(history)
    print(f"Reposts today: {today_count}/{MAX_RTS_PER_DAY}")

    if today_count >= MAX_RTS_PER_DAY:
        print(f"✓ Daily cap reached ({MAX_RTS_PER_DAY} RTs). Exiting cleanly.")
        sys.exit(0)

    if dry_run:
        print("\n[DRY RUN] Would check if tweet is our own...")
        print("[DRY RUN] Would check for reject keywords...")
        print(f"[DRY RUN] Would retweet {tweet_id}")
        print("[DRY RUN] No action taken.")
        sys.exit(0)

    if is_own_tweet(tweet_id):
        sys.exit(1)

    tweet_text = get_tweet_text(tweet_id)
    if contains_reject_keywords(tweet_text):
        sys.exit(1)

    print(f"\nAttempting native retweet of {tweet_id}...")
    success = do_retweet(tweet_id)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).isoformat()
    history["reposts"].append({
        "tweet_id": tweet_id,
        "date": today,
        "timestamp": timestamp,
        "success": success,
    })
    save_history(history)

    if success:
        print(f"✓ Retweet recorded. Today's count: {today_count + 1}/{MAX_RTS_PER_DAY}")
        sys.exit(0)
    else:
        print("✗ Retweet failed (see above for details). Recorded as failed attempt.")
        sys.exit(1)


if __name__ == "__main__":
    main()
