"""
Post and pin the mewscast explainer tweet.
Used by post-pin-explainer.yml GitHub Action.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from twitter_bot import TwitterBot

EXPLAINER_TEXT = """This desk does not treat a story as confirmed on one source.

We require at least three independent outlets. We say what is still in dispute. The receipts are in the thread.

The sign-off is reserved for a straight report. That will not change."""


def main():
    bot = TwitterBot()

    timeline = bot.get_timeline(max_results=50)
    for tweet in timeline:
        if tweet.text.strip() == EXPLAINER_TEXT.strip():
            tweet_id = tweet.id
            print(f"[IDEMPOTENT] Explainer already posted: {tweet_id}")
            print(f"X_TWEET_ID={tweet_id}")
            print(f"X_TWEET_URL=https://x.com/mewscast/status/{tweet_id}")
            print("[PIN] Attempting to pin existing tweet...")
            if bot.pin_tweet(str(tweet_id)):
                print("[OK] Pin succeeded")
                sys.exit(0)
            else:
                print("[FAIL] Pin failed")
                sys.exit(1)

    print("[POST] Posting explainer tweet...")
    result = bot.post_tweet(EXPLAINER_TEXT)
    if not result:
        print("[FAIL] Post failed")
        sys.exit(1)

    tweet_id = result['id']
    tweet_url = f"https://x.com/mewscast/status/{tweet_id}"
    print(f"X_TWEET_ID={tweet_id}")
    print(f"X_TWEET_URL={tweet_url}")

    print("[PIN] Attempting to pin new tweet...")
    if bot.pin_tweet(str(tweet_id)):
        print("[OK] Pin succeeded")
        sys.exit(0)
    else:
        print(f"[FAIL] Pin failed for {tweet_url}")
        sys.exit(1)


if __name__ == "__main__":
    main()
