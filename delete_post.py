"""
Script to delete incorrect posts
"""
import sys
import os
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from twitter_bot import TwitterBot
from bluesky_bot import BlueskyBot

# Load environment variables
load_dotenv()

def main():
    # IDs from the incorrect post
    x_tweet_id = "1991857135693734158"
    x_reply_id = "1991857145290354776"
    bluesky_uri = "at://did:plc:c6zobiwguxel3fcov34h46pw/app.bsky.feed.post/3m65ebwbkni2a"
    bluesky_reply_uri = "at://did:plc:c6zobiwguxel3fcov34h46pw/app.bsky.feed.post/3m65ebz532v23"

    print("🗑️  Deleting incorrect posts...")
    print()

    # Delete from X
    print("Deleting from X...")
    try:
        twitter_bot = TwitterBot()

        # Delete reply first
        if twitter_bot.delete_tweet(x_reply_id):
            print(f"   ✓ Deleted X reply: {x_reply_id}")

        # Then delete main tweet
        if twitter_bot.delete_tweet(x_tweet_id):
            print(f"   ✓ Deleted X tweet: {x_tweet_id}")

        print()
    except Exception as e:
        print(f"   ✗ Error deleting from X: {e}")
        print()

    # Delete from Bluesky
    print("Deleting from Bluesky...")
    try:
        bluesky_bot = BlueskyBot()

        # Delete reply first
        if bluesky_bot.delete_post(bluesky_reply_uri):
            print(f"   ✓ Deleted Bluesky reply")

        # Then delete main post
        if bluesky_bot.delete_post(bluesky_uri):
            print(f"   ✓ Deleted Bluesky post")

        print()
    except Exception as e:
        print(f"   ✗ Error deleting from Bluesky: {e}")
        print()

    print("✅ Deletion complete!")

if __name__ == "__main__":
    main()
