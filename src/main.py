"""
Mewscast - AI-powered X news reporter cat bot
Main entry point for scheduled posts and automation
"""
import os
import sys
import random
import time
import yaml
from datetime import datetime
from dotenv import load_dotenv

from content_generator import ContentGenerator
from twitter_bot import TwitterBot
from news_fetcher import NewsFetcher
from image_generator import ImageGenerator
from post_tracker import PostTracker


def post_scheduled_tweet():
    """Generate and post a scheduled news cat tweet with Google Trends"""
    print(f"\n{'='*60}")
    print(f"Mewscast - News Reporter Cat")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        # Load config for deduplication settings
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Initialize components
        print("🐱 Initializing news cat reporter...")
        generator = ContentGenerator()

        print("📡 Connecting to X...")
        bot = TwitterBot()

        print("📰 Fetching trending topics from Google Trends...")
        news_fetcher = NewsFetcher()

        # Initialize post tracker for deduplication
        dedup_config = config.get('deduplication', {})
        tracker = PostTracker(config=dedup_config)

        # Fetch real trending topics
        trending_stories = news_fetcher.get_trending_topics(count=5)

        # Filter out duplicates
        print("🔍 Checking for duplicate stories...")
        unique_stories = tracker.filter_duplicates(trending_stories)

        # If all were duplicates, fetch more stories
        if not unique_stories and trending_stories:
            print("⚠️  All stories were duplicates, fetching more...")
            more_stories = news_fetcher.get_trending_topics(count=10)
            unique_stories = tracker.filter_duplicates(more_stories)

        # Pick a random unique story
        selected_story = random.choice(unique_stories) if unique_stories else None

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

        # Try to generate image (with graceful fallback)
        image_path = None
        try:
            print(f"🎨 Attempting to generate image with Grok...")
            img_generator = ImageGenerator()

            # Generate image prompt using Claude
            image_prompt = generator.generate_image_prompt(selected_story['title'] if selected_story else "news", tweet_text)

            # Generate image using Grok
            image_path = img_generator.generate_image(image_prompt)

        except Exception as e:
            print(f"⚠️  Image generation failed: {e}")
            print(f"   Continuing without image...")

        # Post main tweet to X (with or without image)
        print(f"📤 Filing news report to X...")
        print(f"   Content: \"{tweet_text}\"")

        if image_path:
            print(f"   Image: {image_path}\n")
            post_result = bot.post_tweet_with_image(tweet_text, image_path)
        else:
            print(f"   (No image attached)\n")
            post_result = bot.post_tweet(tweet_text)

        if post_result:
            tweet_id = post_result['id']
            print(f"✅ Tweet posted! ID: {tweet_id}")

            reply_tweet_id = None

            # If it's a specific story, auto-reply with source
            if needs_source and story_meta:
                print(f"\n📎 Posting source citation reply...")
                time.sleep(2)  # Brief pause before reply

                source_reply = generator.generate_source_reply(tweet_text, story_meta)
                reply_result = bot.reply_to_tweet(tweet_id, source_reply)

                if reply_result:
                    reply_tweet_id = reply_result['id']
                    print(f"✅ Source reply posted! ID: {reply_tweet_id}")
                else:
                    print(f"⚠️  Main tweet posted but source reply failed")

            # Record post to history for deduplication (with reply ID if posted)
            if selected_story:
                tracker.record_post(selected_story, tweet_id, reply_tweet_id)

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
