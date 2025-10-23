# 🐱 Cat Community Engagement Bot

Automatically finds and engages with cat-related accounts and posts on X to build your community.

## What It Does

### Every 30 Minutes:
1. **Follows 1 cat account** (48/day = 50% of follow limit)
2. **Likes 1 cat post** (48/day = 50% of like limit)

### Smart Filtering:
- **Accounts:** 100-100K followers, cat-related bio, good follow ratio
- **Posts:** 5-10K likes, recent (24hrs), genuine cat content
- **Avoids:** Bots, spam, mega-accounts, duplicates

## API Usage

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

All engagement is logged in `engagement_history.json`:
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

History auto-cleans every 7 days (keeps 90 days).

## Manual Testing

Test the engagement bot locally:
```bash
cd src
python engagement_bot.py
```

Or trigger via GitHub Actions:
```bash
gh workflow run engage-cats.yml
gh run watch $(gh run list --workflow=engage-cats.yml --limit=1 --json databaseId -q '.[0].databaseId')
```

## Expected Results

Over 30 days:
- **Follow:** 1,440 cat accounts
- **Like:** 1,440 cat posts
- **Growth:** 10-30% follow-back rate = 144-432 new followers
- **Visibility:** Thousands of cat lovers see your profile

## Scaling Up (Future)

If you upgrade to paid tier, you could:
- Engage every 15 minutes (double the rate)
- Add quote tweets of cat posts
- Reply to cat posts with news angle
- DM new followers with thank you message
