# Engagement Audit - @mewscast

**Date:** 2025-11-22
**Status:** Active on Bluesky, Limited on X

---

## 📊 Current Engagement Strategy

### **Bluesky** ✅ ACTIVE
**Schedule:** Every 30 minutes
**Status:** Running smoothly
**Actions:**
- Follows cat-related accounts
- Likes cat posts
- Tracks engagement history

**Why it works:**
- ✅ Generous rate limits
- ✅ Growing platform (fast user growth)
- ✅ Tech-savvy audience appreciates AI/open source
- ✅ Less competition (fewer bots)

### **X/Twitter** ⚠️ PAUSED
**Schedule:** Disabled (monthly search cap exceeded)
**Status:** Manual trigger only
**Issue:** X Free tier has very limited search/engagement API calls

**Rate Limits Hit:**
- Monthly search cap exceeded
- Need to wait for reset or upgrade tier

---

## 📈 Analytics Available

### **API Endpoints Available:**

**X/Twitter API v2:**
```
GET /2/tweets/:id
  - public_metrics: like_count, retweet_count, reply_count, quote_count
  - impression_count (may not be available on free tier)
```

**Bluesky AT Protocol:**
```
app.bsky.feed.getPostThread
  - like_count, repost_count, reply_count
  - More detailed metrics available
```

### **Analytics Script Created:**

Location: `scripts/analytics.py`

**What it fetches:**
- ✅ Last 10 posts from each platform
- ✅ Likes, retweets/reposts, replies
- ✅ Top performing posts
- ✅ Average engagement rates
- ✅ Posting frequency analysis
- ✅ Impressions (if available)

**Usage:**
```bash
python scripts/analytics.py
```

---

## 🎯 Recommendations

### **1. Double Down on Bluesky** ⭐ HIGH PRIORITY

**Why:**
- Platform is growing faster than X
- Better audience alignment (tech, open source, news)
- More generous API limits
- Less saturated with bots
- Your transparency strategy works better there

**Actions:**
- ✅ Already running engagement every 30 min
- Consider: Increase engagement actions per cycle
- Consider: Post frequency (currently 7/day on both)
- Consider: Bluesky-specific content strategies

### **2. X Strategy Adjustment**

**Current issue:** Free tier limits hit

**Options:**

**A) Stay on Free Tier (Current)**
- ✅ Cost: $0
- ❌ Limited engagement automation
- ✅ Can still post (7x/day working fine)
- Manual engagement only

**B) Upgrade to X API Basic ($100/month)**
- ✅ Higher rate limits
- ✅ Better analytics access
- ❌ Cost: $100/month
- ⚠️  ROI unclear for a bot account

**C) Reduce X Engagement, Focus on Bluesky**
- ✅ Cost: $0
- ✅ Focus resources where growth is happening
- Post to X, but don't auto-engage
- Manually engage occasionally

**Recommendation:** Option C - Focus on Bluesky

### **3. Analytics Improvements**

**Implement:**
- [ ] Track engagement metrics over time
- [ ] Identify best performing content types
- [ ] Analyze optimal posting times
- [ ] A/B test different commentary styles
- [ ] Monitor follower growth rate

**Create dashboard showing:**
- Engagement rate trends
- Platform comparison (X vs Bluesky)
- Best performing topics
- ROI on posting frequency

### **4. Content Strategy Optimization**

**Test these on Bluesky (better engagement):**
- Threads (multi-post stories)
- More direct audience questions
- Behind-the-scenes (how the bot works)
- Fact-check corrections (transparency++)
- Cat community engagement (reply to cat posts)

---

## 📊 Current Metrics Snapshot

**Run this to get current metrics:**
```bash
python scripts/analytics.py
```

**Expected output:**
- Total posts across platforms
- Average engagement per post
- Recent performance (last 7 days)
- Top performing posts
- Platform comparison

---

## 🚀 Action Items

**Immediate:**
- [ ] Run analytics script to get baseline metrics
- [ ] Review Bluesky engagement history (285KB file!)
- [ ] Decide on X engagement strategy (pause vs manual)

**Short-term:**
- [ ] Optimize Bluesky bio with GitHub link
- [ ] Monitor Bluesky growth weekly
- [ ] Test content variations on Bluesky
- [ ] Set up weekly analytics review

**Long-term:**
- [ ] Build analytics dashboard
- [ ] Implement A/B testing framework
- [ ] Consider Bluesky-exclusive features
- [ ] Evaluate X API upgrade vs. Bluesky focus

---

## 💡 Key Insights

**Platform Comparison:**

| Metric | X/Twitter | Bluesky |
|--------|-----------|---------|
| Growth | Stable/declining | Rapid growth ⭐ |
| Engagement automation | Paused (limits) | Active ✅ |
| Posting | 7x/day ✅ | 7x/day ✅ |
| API limits | Restrictive ❌ | Generous ✅ |
| Audience fit | Mixed | Excellent ⭐ |
| Bot tolerance | Low | Higher |
| Open source appreciation | Medium | High ⭐ |

**Verdict:** Prioritize Bluesky growth while maintaining X presence for visibility.

---

## 📝 Notes

- Bluesky engagement history is 285KB (lots of activity!)
- X engagement paused due to API limits
- Both platforms get 7 posts/day
- Analytics script ready to use for data-driven decisions

**Next Review:** Check analytics weekly to track growth trends
