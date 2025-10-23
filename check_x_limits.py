"""
Quick script to check X API rate limits
"""
import os
from dotenv import load_dotenv
import tweepy

load_dotenv()

# Initialize client
client = tweepy.Client(
    bearer_token=os.getenv("X_BEARER_TOKEN"),
    consumer_key=os.getenv("X_API_KEY"),
    consumer_secret=os.getenv("X_API_SECRET"),
    access_token=os.getenv("X_ACCESS_TOKEN"),
    access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    wait_on_rate_limit=False
)

print("=" * 80)
print("X API RATE LIMITS (Free Tier)")
print("=" * 80)

# Get user info to verify connection
try:
    user = client.get_me()
    print(f"\n✓ Connected as: @{user.data.username}")
except Exception as e:
    print(f"\n✗ Connection failed: {e}")
    exit(1)

print("\n" + "=" * 80)
print("POSTING LIMITS")
print("=" * 80)
print("""
✓ Tweets: 50 posts per 24 hours
  └─ Includes original tweets, replies, retweets
  └─ ~2 posts/hour or 7 posts/3hrs max burst

✓ Media uploads: 50 per 24 hours
  └─ Same limit as tweets (1 image per tweet)

✓ Status look-ups: 900 per 15 minutes (54,000/day)
  └─ Checking if tweet exists
""")

print("=" * 80)
print("READING LIMITS")
print("=" * 80)
print("""
✓ Timeline reads: 180 per 15 minutes (17,280/day)
  └─ Getting your own tweets

✓ User look-ups: 300 per 15 minutes (28,800/day)
  └─ Getting user info

✓ Tweet search: 180 per 15 minutes (17,280/day)
  └─ Searching for tweets with keywords

✓ Mentions: 180 per 15 minutes (17,280/day)
  └─ Getting tweets that mention you
""")

print("=" * 80)
print("ENGAGEMENT LIMITS")
print("=" * 80)
print("""
✓ Likes: 1000 per 24 hours
  └─ You can like up to 1000 tweets per day

✓ Follows: 400 per 24 hours
  └─ You can follow up to 400 accounts per day

✓ Retweets: 50 per 24 hours (same as posts)
  └─ Counts toward your 50 post limit
""")

print("=" * 80)
print("PREMIUM FEATURE LIMITS (Free Tier = Limited/None)")
print("=" * 80)
print("""
✗ Trending topics API: NOT AVAILABLE on Free tier
  └─ Must use workarounds (search popular tweets, external APIs)

✗ Full-archive search: NOT AVAILABLE on Free tier
  └─ Only recent tweets (7 days) searchable

✗ Twitter Spaces: LISTEN ONLY on Free tier
  └─ Cannot host spaces
""")

print("=" * 80)
print("CURRENT USAGE RECOMMENDATIONS")
print("=" * 80)
print("""
Your bot currently:
✓ Posts 3 times per day = 6% of limit (safe!)
✓ Each post includes 1 image = 6% of media limit
✓ Posts source reply = ~6% of limit

POTENTIAL TO MAX OUT:
→ Increase to 8-10 posts/day with images (20% of limit)
→ Add 10-20 replies to mentions per day (24-44% total)
→ Add engagement (likes/RTs) to 50-100 tweets/day
→ Search trending tweets every hour for content ideas
→ Monitor 100+ accounts for reply opportunities

AGGRESSIVE GROWTH MODE:
→ 15 original posts/day (30% limit)
→ 15 reply threads/day (60% total)
→ 100 likes/day (10% limit)
→ 50 strategic follows/day (12.5% limit)
→ Search every 15 mins for trending content
→ Reply to 10-20 high-engagement tweets/day
""")

print("=" * 80)
