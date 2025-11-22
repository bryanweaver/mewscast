# 🐱 Cat Community Engagement Bots

Automatically finds and engages with cat-related accounts and posts on **X/Twitter** and **Bluesky** to build your community.

## What It Does

### X/Twitter - Every 30 Minutes:
1. **Follows 1 cat account** (48/day = 50% of follow limit)
2. **Likes 1 cat post** (48/day = 50% of like limit)

### Bluesky - Every 30 Minutes:
1. **Follows 1 cat account** (48/day - generous limits)
2. **Likes 1 cat post** (48/day - generous limits)

### Smart Filtering:
- **Accounts:** 100-100K followers, cat-related bio, good follow ratio
- **Posts:** 5-10K likes, recent (24hrs), genuine cat content
- **Avoids:** Bots, spam, mega-accounts, duplicates

## API Usage

### X/Twitter (Free Tier - Strict Limits)
```
Searches: 48/day (50% of 96/day limit)
Follows: 48/day (50% of 96/day limit)
Likes: 48/day (50% of 96/day limit)
```

Combined with your 7 posts/day, you're using:
- **Posts:** 14/17 per day (82%)
- **Searches:** 48/96 per day (50%)
- **Follows:** 48/96 per day (50%)
- **Likes:** 48/96 per day (50%)

### Bluesky (Generous Limits)
```
Searches: 48/day (well within limits)
Follows: 48/day (well within limits)
Likes: 48/day (well within limits)
```

Bluesky's AT Protocol has much more generous rate limits than X!

## How It Works

### Finding Cat Accounts
Searches for:
- "cat owner"
- "cat dad" / "cat mom"
- "#catsoftwitter"
- "my cat"

Filters for:
- 100-100K followers (quality range)
- Cat-related bio
- Not verified (they don't follow back)
- Good follow ratio (not spammers)

### Finding Cat Posts
Searches for:
- "cute cat"
- "look at my cat"
- "#caturday"
- "adopted a cat"

Filters for:
- 5-10K likes (quality but not mega-viral)
- Recent (last 24 hours)
- Not already engaged with

## Tracking

### X/Twitter engagement logged in `engagement_history.json`:
```json
{
  "followed_users": [
    {
      "user_id": "123456",
      "username": "catdad",
      "timestamp": "2025-10-23T13:00:00"
    }
  ],
  "liked_tweets": [
    {
      "tweet_id": "987654",
      "author": "cutecats",
      "timestamp": "2025-10-23T13:30:00"
    }
  ]
}
```

### Bluesky engagement logged in `bluesky_engagement_history.json`:
```json
{
  "followed_users": [
    {
      "did": "did:plc:abc123",
      "handle": "catdad.bsky.social",
      "timestamp": "2025-10-23T13:00:00"
    }
  ],
  "liked_posts": [
    {
      "uri": "at://did:plc:xyz789/app.bsky.feed.post/abc",
      "author": "cutecats.bsky.social",
      "timestamp": "2025-10-23T13:30:00"
    }
  ]
}
```

Both histories auto-clean every 7 days (keep 90 days).

## Manual Testing

### Test X/Twitter engagement bot:
```bash
cd src
python engagement_bot.py
```

Or trigger via GitHub Actions:
```bash
gh workflow run engage-cats.yml
gh run watch $(gh run list --workflow=engage-cats.yml --limit=1 --json databaseId -q '.[0].databaseId')
```

### Test Bluesky engagement bot:
```bash
cd src
python bluesky_engagement_bot.py
```

Or trigger via GitHub Actions:
```bash
gh workflow run engage-cats-bluesky.yml
gh run watch $(gh run list --workflow=engage-cats-bluesky.yml --limit=1 --json databaseId -q '.[0].databaseId')
```

## Expected Results

### Over 30 Days (Combined X + Bluesky):
- **Follow:** 2,880 cat accounts (1,440 per platform)
- **Like:** 2,880 cat posts (1,440 per platform)
- **Growth:** 10-30% follow-back rate = 288-864 new followers total
- **Visibility:** Thousands of cat lovers see your profile on both platforms

### Platform Breakdown:
**X/Twitter:**
- 1,440 follows → 144-432 new followers
- Larger platform, more competitive

**Bluesky:**
- 1,440 follows → 144-432 new followers
- Smaller platform, easier to stand out
- Higher engagement rates typically

## Scaling Up (Future)

If you upgrade to paid tier, you could:
- Engage every 15 minutes (double the rate)
- Add quote tweets of cat posts
- Reply to cat posts with news angle
- DM new followers with thank you message
