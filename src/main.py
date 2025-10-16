"""
Mewscast - AI-powered X news reporter cat bot
Main entry point for scheduled posts and automation
"""
import os
import sys
import random
import time
from datetime import datetime
from dotenv import load_dotenv

from content_generator import ContentGenerator
from twitter_bot import TwitterBot
from news_fetcher import NewsFetcher


def post_scheduled_tweet():
    """Generate and post a scheduled news cat tweet with Google Trends"""
    print(f"\n{'='*60}")
    print(f"Mewscast - News Reporter Cat")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        # Initialize components
        print("🐱 Initializing news cat reporter...")
        generator = ContentGenerator()

        print("📡 Connecting to X...")
        bot = TwitterBot()

        print("📰 Fetching trending topics from Google Trends...")
        news_fetcher = NewsFetcher()

        # Fetch real trending topics
        trending_stories = news_fetcher.get_trending_topics(count=5)

        # Pick a random trending story
        selected_story = random.choice(trending_stories) if trending_stories else None

        if selected_story:
            print(f"📰 Selected: {selected_story['title']}")
            print(f"   Source: {selected_story['source']}\n")

        # Generate cat news content with story metadata
        result = generator.generate_tweet(
            trending_topic=selected_story['title'] if selected_story else None,
            story_metadata=selected_story
        )

        tweet_text = result['tweet']
        needs_source = result['needs_source_reply']
        story_meta = result['story_metadata']

        # Post main tweet to X
        print(f"📤 Filing news report to X...")
        print(f"   Content: \"{tweet_text}\"\n")
        post_result = bot.post_tweet(tweet_text)

        if post_result:
            tweet_id = post_result['id']
            print(f"✅ Tweet posted! ID: {tweet_id}")

            # If it's a specific story, auto-reply with source
            if needs_source and story_meta:
                print(f"\n📎 Posting source citation reply...")
                time.sleep(2)  # Brief pause before reply

                source_reply = generator.generate_source_reply(tweet_text, story_meta)
                reply_result = bot.reply_to_tweet(tweet_id, source_reply)

                if reply_result:
                    print(f"✅ Source reply posted! ID: {reply_result['id']}")
                else:
                    print(f"⚠️  Main tweet posted but source reply failed")

            print(f"\n{'='*60}")
            print(f"✅ SUCCESS! News report filed.")
            print(f"{'='*60}\n")
            return True
        else:
            print(f"\n{'='*60}")
            print(f"❌ FAILED to post tweet.")
            print(f"{'='*60}\n")
            return False

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")
        return False


def reply_to_mentions():
    """Check mentions and reply as news cat reporter"""
    print(f"\n{'='*60}")
    print(f"Mewscast - Checking Mentions")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        generator = ContentGenerator()
        bot = TwitterBot()

        print("📨 Fetching recent mentions...")
        mentions = bot.get_mentions(max_results=5)

        if not mentions:
            print("No new mentions found.")
            return True

        print(f"Found {len(mentions)} mention(s)\n")

        for mention in mentions:
            print(f"Processing mention from @{mention.author_id}...")
            print(f"   Text: {mention.text[:100]}...\n")

            # Generate reply
            reply_text = generator.generate_reply(mention.text)

            # Post reply
            bot.reply_to_tweet(mention.id, reply_text)
            print()

        print(f"\n{'='*60}")
        print(f"✅ Processed {len(mentions)} mention(s)")
        print(f"{'='*60}\n")
        return True

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        print(f"{'='*60}\n")
        return False


def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()

    # Check mode from environment or argument
    mode = os.getenv("BOT_MODE", "scheduled")

    if len(sys.argv) > 1:
        mode = sys.argv[1]

    print(f"\n🚀 Starting Mewscast in '{mode}' mode...\n")

    if mode == "scheduled" or mode == "post":
        success = post_scheduled_tweet()
    elif mode == "reply":
        success = reply_to_mentions()
    elif mode == "both":
        success1 = post_scheduled_tweet()
        success2 = reply_to_mentions()
        success = success1 and success2
    else:
        print(f"❌ Unknown mode: {mode}")
        print("Available modes: scheduled, reply, both")
        sys.exit(1)

    # Exit with appropriate code for CI/CD
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
