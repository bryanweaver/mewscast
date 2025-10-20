"""
Rebuild posts_history.json from X timeline
Fetches all bot posts and reconstructs the history file for deduplication
"""
import sys
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, 'src')

from twitter_bot import TwitterBot

def rebuild_history_from_x():
    """Fetch bot's timeline and rebuild posts_history.json"""
    print("\n" + "=" * 70)
    print("Rebuilding Post History from X Timeline")
    print("=" * 70 + "\n")

    # Load environment variables
    load_dotenv()

    # Initialize Twitter bot
    print("🔗 Connecting to X API...")
    bot = TwitterBot()

    # Get @mewscast user ID
    mewscast_user = bot.client.get_user(username='mewscast')
    mewscast_user_id = mewscast_user.data.id
    print(f"✓ Connected to X API")
    print(f"✓ Found @mewscast user ID: {mewscast_user_id}\n")

    # Fetch all tweets from the bot's timeline
    print("📥 Fetching all posts from timeline...")

    all_tweets = []
    pagination_token = None

    # Fetch multiple pages to get all tweets
    while True:
        response = bot.client.get_users_tweets(
            id=mewscast_user_id,
            max_results=100,  # Maximum allowed by API
            tweet_fields=['created_at', 'text', 'conversation_id'],
            exclude=['retweets'],  # Get main posts and their replies
            pagination_token=pagination_token
        )

        if response.data:
            all_tweets.extend(response.data)
            print(f"  Fetched {len(response.data)} tweets (total: {len(all_tweets)})")

        # Check if there are more pages
        if hasattr(response, 'meta') and 'next_token' in response.meta:
            pagination_token = response.meta['next_token']
        else:
            break

    tweets = type('obj', (object,), {'data': all_tweets})()

    if not tweets.data:
        print("⚠️  No tweets found!")
        return

    print(f"✓ Found {len(tweets.data)} posts\n")

    # Build history records
    history_records = []

    for tweet in reversed(tweets.data):  # Process oldest first
        print(f"Processing tweet {tweet.id}...")
        print(f"  Posted: {tweet.created_at}")
        print(f"  Text: {tweet.text[:80]}...\n")

        # Try to find the source reply (conversation thread)
        source_url = None
        source_text = None
        reply_tweet_id = None

        try:
            # Get conversation replies to find source citation
            replies = bot.client.get_users_tweets(
                id=my_user_id,
                max_results=10,
                tweet_fields=['created_at', 'text', 'in_reply_to_user_id', 'conversation_id'],
            )

            # Find replies in this conversation
            for reply in (replies.data or []):
                if hasattr(reply, 'conversation_id') and reply.conversation_id == tweet.id:
                    # This is a reply to our tweet
                    if reply.text.startswith('http'):
                        source_url = reply.text.strip()
                        source_text = reply.text
                        reply_tweet_id = reply.id
                        print(f"  ✓ Found source reply: {source_url[:60]}...")
                        break

        except Exception as e:
            print(f"  ⚠️  Could not fetch replies: {e}")

        # Extract story title from tweet (first line, remove source indicator)
        lines = tweet.text.split('\n')
        title = lines[0].replace(' 📰↓', '').strip()

        # Create history record
        record = {
            'timestamp': tweet.created_at.isoformat() if tweet.created_at else datetime.now(timezone.utc).isoformat(),
            'topic': title,
            'url': source_url if source_url else None,
            'source': 'Unknown',  # Can't determine from tweet alone
            'content': tweet.text,  # Store full tweet for content deduplication
            'x_tweet_id': str(tweet.id),
            'x_reply_tweet_id': str(reply_tweet_id) if reply_tweet_id else None,
            'bluesky_uri': None,  # Don't have Bluesky history
            'bluesky_reply_uri': None
        }

        history_records.append(record)

    # Save to posts_history.json
    history_data = {'posts': history_records}

    with open('posts_history.json', 'w') as f:
        json.dump(history_data, f, indent=2)

    print("=" * 70)
    print(f"✅ SUCCESS! Rebuilt history with {len(history_records)} posts")
    print(f"📄 Saved to: posts_history.json")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    rebuild_history_from_x()
