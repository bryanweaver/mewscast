"""
Scrape public X (Twitter) profile data using Playwright.
No login required - only scrapes publicly visible data.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def parse_count(text: str) -> int:
    """Parse counts like '1.2K' or '15M' to integers."""
    if not text:
        return 0
    text = text.strip().upper().replace(',', '')
    try:
        if 'K' in text:
            return int(float(text.replace('K', '')) * 1000)
        elif 'M' in text:
            return int(float(text.replace('M', '')) * 1_000_000)
        else:
            return int(text)
    except (ValueError, TypeError):
        return 0


async def scrape_x_profile(username: str = "mewscast") -> dict:
    """Scrape public profile data from X."""
    from playwright.async_api import async_playwright

    print(f"Scraping X profile: @{username}")

    result = {
        "username": username,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "followers": 0,
        "following": 0,
        "tweets": []
    }

    async with async_playwright() as p:
        # Use Firefox as it's less likely to be detected
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
        )
        page = await context.new_page()

        try:
            # Navigate to profile
            url = f"https://x.com/{username}"
            print(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for profile to load
            await page.wait_for_timeout(3000)

            # Get follower/following counts from the profile header
            # These are usually in links like "/username/followers"
            try:
                # Try to find follower count
                follower_link = page.locator(f'a[href="/{username}/verified_followers"], a[href="/{username}/followers"]')
                if await follower_link.count() > 0:
                    follower_text = await follower_link.first.inner_text()
                    # Extract number from text like "1,234 Followers"
                    match = re.search(r'([\d,.]+[KMB]?)', follower_text)
                    if match:
                        result["followers"] = parse_count(match.group(1))
                        print(f"Found followers: {result['followers']}")

                # Try to find following count
                following_link = page.locator(f'a[href="/{username}/following"]')
                if await following_link.count() > 0:
                    following_text = await following_link.first.inner_text()
                    match = re.search(r'([\d,.]+[KMB]?)', following_text)
                    if match:
                        result["following"] = parse_count(match.group(1))
                        print(f"Found following: {result['following']}")

            except Exception as e:
                print(f"Error getting follower counts: {e}")

            # Scroll to load tweets
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(2000)

            # Get tweet metrics from the timeline
            # Look for tweet articles
            tweets = page.locator('article[data-testid="tweet"]')
            tweet_count = await tweets.count()
            print(f"Found {tweet_count} tweets on page")

            for i in range(min(tweet_count, 20)):  # Limit to 20 tweets
                try:
                    tweet = tweets.nth(i)

                    # Get tweet link (contains tweet ID)
                    tweet_link = tweet.locator('a[href*="/status/"]').first
                    if await tweet_link.count() > 0:
                        href = await tweet_link.get_attribute('href')
                        tweet_id_match = re.search(r'/status/(\d+)', href or '')
                        if not tweet_id_match:
                            continue
                        tweet_id = tweet_id_match.group(1)

                        # Get engagement metrics
                        # These are in the action bar at the bottom of each tweet
                        metrics = {"tweet_id": tweet_id, "likes": 0, "retweets": 0, "replies": 0, "views": 0}

                        # Reply count
                        reply_btn = tweet.locator('[data-testid="reply"]')
                        if await reply_btn.count() > 0:
                            reply_text = await reply_btn.inner_text()
                            metrics["replies"] = parse_count(reply_text)

                        # Retweet count
                        retweet_btn = tweet.locator('[data-testid="retweet"]')
                        if await retweet_btn.count() > 0:
                            retweet_text = await retweet_btn.inner_text()
                            metrics["retweets"] = parse_count(retweet_text)

                        # Like count
                        like_btn = tweet.locator('[data-testid="like"]')
                        if await like_btn.count() > 0:
                            like_text = await like_btn.inner_text()
                            metrics["likes"] = parse_count(like_text)

                        # Views (if visible)
                        view_el = tweet.locator('a[href*="/analytics"]')
                        if await view_el.count() > 0:
                            view_text = await view_el.inner_text()
                            metrics["views"] = parse_count(view_text)

                        result["tweets"].append(metrics)
                        print(f"  Tweet {tweet_id}: {metrics['likes']} likes, {metrics['retweets']} RTs, {metrics['replies']} replies")

                except Exception as e:
                    print(f"Error parsing tweet {i}: {e}")
                    continue

        except Exception as e:
            print(f"Error scraping profile: {e}")
        finally:
            await browser.close()

    print(f"Scraped {len(result['tweets'])} tweets, {result['followers']} followers")
    return result


def update_analytics_with_x_data(x_data: dict, history_path: str = "analytics_history.json"):
    """Update analytics history with scraped X data."""
    # Load existing history
    if os.path.exists(history_path):
        with open(history_path, 'r') as f:
            history = json.load(f)
    else:
        history = {"posts": {}, "follower_history": {"x": [], "bluesky": []}}

    # Ensure follower_history exists
    if "follower_history" not in history:
        history["follower_history"] = {"x": [], "bluesky": []}

    # Add follower snapshot
    history["follower_history"]["x"].append({
        "timestamp": x_data["timestamp"],
        "followers": x_data["followers"],
        "following": x_data["following"]
    })

    # Keep only last 90 days of follower history
    cutoff = datetime.now(timezone.utc).timestamp() - (90 * 24 * 60 * 60)
    history["follower_history"]["x"] = [
        s for s in history["follower_history"]["x"]
        if datetime.fromisoformat(s["timestamp"].replace('Z', '+00:00')).timestamp() > cutoff
    ]

    # Update tweet metrics
    for tweet in x_data["tweets"]:
        key = f"x:{tweet['tweet_id']}"
        if key in history["posts"]:
            # Add snapshot with scraped data
            history["posts"][key]["snapshots"].append({
                "timestamp": x_data["timestamp"],
                "likes": tweet["likes"],
                "retweets": tweet["retweets"],
                "replies": tweet["replies"],
                "views": tweet.get("views", 0),
                "source": "scraper"
            })

    # Save updated history
    with open(history_path, 'w') as f:
        json.dump(history, f, indent=2)

    print(f"Updated {history_path}")
    return history


async def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Scrape X public profile data")
    parser.add_argument("--username", default="mewscast", help="X username to scrape")
    parser.add_argument("--output", default="x_scrape_result.json", help="Output file for raw data")
    parser.add_argument("--update-analytics", action="store_true", help="Update analytics_history.json")
    args = parser.parse_args()

    # Run scraper
    data = await scrape_x_profile(args.username)

    # Save raw output
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Saved raw data to {args.output}")

    # Update analytics if requested
    if args.update_analytics:
        update_analytics_with_x_data(data)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
