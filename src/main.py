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
from bluesky_bot import BlueskyBot
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
        twitter_bot = TwitterBot()

        print("🦋 Connecting to Bluesky...")
        try:
            bluesky_bot = BlueskyBot()
        except Exception as e:
            print(f"⚠️  Bluesky connection failed: {e}")
            print(f"   Continuing with X only...")
            bluesky_bot = None

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

        # Post to X (with or without image)
        print(f"📤 Filing news report to X...")
        print(f"   Content: \"{tweet_text}\"")

        tweet_id = None
        reply_tweet_id = None
        x_success = False

        if image_path:
            print(f"   Image: {image_path}\n")
            x_result = twitter_bot.post_tweet_with_image(tweet_text, image_path)
        else:
            print(f"   (No image attached)\n")
            x_result = twitter_bot.post_tweet(tweet_text)

        if x_result:
            tweet_id = x_result['id']
            print(f"✅ X post successful! ID: {tweet_id}")
            x_success = True

            # Post source reply on X
            if needs_source and story_meta:
                print(f"📎 Posting source citation reply on X...")
                time.sleep(2)  # Brief pause before reply

                source_reply = generator.generate_source_reply(tweet_text, story_meta)
                x_reply_result = twitter_bot.reply_to_tweet(tweet_id, source_reply)

                if x_reply_result:
                    reply_tweet_id = x_reply_result['id']
                    print(f"✅ X source reply posted! ID: {reply_tweet_id}")
                else:
                    print(f"⚠️  X source reply failed")
        else:
            print(f"❌ X post failed")

        # Post to Bluesky (with or without image)
        bluesky_uri = None
        bluesky_reply_uri = None
        bluesky_success = False

        if bluesky_bot:
            print(f"\n🦋 Filing news report to Bluesky...")
            print(f"   Content: \"{tweet_text}\"")

            if image_path:
                print(f"   Image: {image_path}\n")
                bluesky_result = bluesky_bot.post_skeet_with_image(tweet_text, image_path)
            else:
                print(f"   (No image attached)\n")
                bluesky_result = bluesky_bot.post_skeet(tweet_text)

            if bluesky_result:
                bluesky_uri = bluesky_result['uri']
                print(f"✅ Bluesky post successful! URI: {bluesky_uri}")
                bluesky_success = True

                # Post source reply on Bluesky
                if needs_source and story_meta:
                    print(f"📎 Posting source citation reply on Bluesky...")
                    time.sleep(2)  # Brief pause before reply

                    source_reply = generator.generate_source_reply(tweet_text, story_meta)
                    bluesky_reply_result = bluesky_bot.reply_to_skeet(bluesky_uri, source_reply)

                    if bluesky_reply_result:
                        bluesky_reply_uri = bluesky_reply_result['uri']
                        print(f"✅ Bluesky source reply posted! URI: {bluesky_reply_uri}")
                    else:
                        print(f"⚠️  Bluesky source reply failed")
            else:
                print(f"❌ Bluesky post failed")

        # Record post to history (with IDs from both platforms)
        if selected_story and (x_success or bluesky_success):
            tracker.record_post(
                selected_story,
                tweet_id=tweet_id,
                reply_tweet_id=reply_tweet_id,
                bluesky_uri=bluesky_uri,
                bluesky_reply_uri=bluesky_reply_uri
            )

        # Determine overall success
        if x_success or bluesky_success:
            print(f"\n{'='*60}")
            platforms_posted = []
            if x_success:
                platforms_posted.append("X")
            if bluesky_success:
                platforms_posted.append("Bluesky")
            print(f"✅ SUCCESS! News report filed to: {', '.join(platforms_posted)}")
            print(f"{'='*60}\n")
            return True
        else:
            print(f"\n{'='*60}")
            print(f"❌ FAILED to post to any platform.")
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
