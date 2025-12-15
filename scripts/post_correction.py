"""
Post correction reply to a post on X and/or Bluesky
Used by post-correction.yml GitHub Action
"""
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from twitter_bot import TwitterBot
from bluesky_bot import BlueskyBot


def main():
    x_tweet_id = os.environ.get('X_TWEET_ID')
    bluesky_uri = os.environ.get('BLUESKY_URI')
    correction = os.environ.get('CORRECTION_TEXT')
    post_to_x = os.environ.get('POST_TO_X', 'true').lower() == 'true'
    post_to_bluesky = os.environ.get('POST_TO_BLUESKY', 'true').lower() == 'true'

    print(f"Posting correction ({len(correction)} chars):")
    print("---")
    print(correction)
    print("---")
    print()

    success = True

    if post_to_x:
        print(f"[X] Posting correction as reply to tweet {x_tweet_id}...")
        try:
            twitter_bot = TwitterBot()
            x_result = twitter_bot.reply_to_tweet(x_tweet_id, correction)
            if x_result:
                print(f"[OK] X correction posted! ID: {x_result['id']}")
            else:
                print("[FAIL] X correction failed")
                success = False
        except Exception as e:
            print(f"[FAIL] X error: {e}")
            success = False
    else:
        print("[SKIP] X posting disabled")

    print()

    if post_to_bluesky:
        print(f"[BSKY] Posting correction as reply to {bluesky_uri}...")
        try:
            bluesky_bot = BlueskyBot()
            bsky_result = bluesky_bot.reply_to_skeet(bluesky_uri, correction)
            if bsky_result:
                print(f"[OK] Bluesky correction posted! URI: {bsky_result['uri']}")
            else:
                print("[FAIL] Bluesky correction failed")
                success = False
        except Exception as e:
            print(f"[FAIL] Bluesky error: {e}")
            success = False
    else:
        print("[SKIP] Bluesky posting disabled")

    print()
    if success:
        print("[DONE] Correction posting complete!")
    else:
        print("[WARN] Some corrections failed - check logs above")
        sys.exit(1)


if __name__ == "__main__":
    main()
