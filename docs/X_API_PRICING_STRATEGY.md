# X API Pricing & Engagement Strategy

**Version:** 1.0
**Date:** April 8, 2026
**Author:** Research report for mewscast
**Scope:** X.com API pricing landscape (2026) and how mewscast can exploit it for maximum engagement

---

## TL;DR

- **The free tier is dead.** As of February 2026, X replaced its fixed tiers with
  pay-per-use as the default for new developers. Legacy Basic ($200/mo) and Pro
  ($5,000/mo) remain only for existing subscribers.
- **Pay-per-use is a win for mewscast.** At our current posting volume (~5
  posts/day, minimal reads), the new model costs roughly **$1.50–$5 per month**
  instead of $200, a ~97% reduction vs. the old Basic tier.
- **Write is cheap, reach is not.** The bottleneck for engagement is no longer
  API cost — it is the algorithm, which in 2026 aggressively boosts Premium
  accounts and punishes external links.
- **Highest-leverage moves:** subscribe to X Premium ($8/mo) for the 2–10x reach
  multiplier, shift link citations to reply threads, optimize for the first
  30-minute reply window, and reinvest API savings into an engagement loop that
  seeds early-window replies on our own posts.

---

## 1. The New X API Pricing Landscape (April 2026)

### 1.1 Pay-Per-Use (default for all new developers)

X launched pay-per-use pricing on **February 6, 2026**, making it the default
for new developers. Credits are prepaid in the Developer Console and deducted
per request.

| Action                | Cost           | Notes                                          |
| --------------------- | -------------- | ---------------------------------------------- |
| Post created (write)  | **$0.01**      | Each original post, reply, or quote            |
| Post read (lookup)    | **$0.005**     | De-duplicated within a 24h UTC window          |
| Monthly read cap      | **2M reads**   | Above this, Enterprise contract required       |
| Minimum subscription  | **$0**         | No floor — pure usage-based                    |
| xAI credit rebate     | **up to 20%**  | 10% default, 15% at $500 spend, 20% at $1,000+ |

Legacy Free users who were recently active were auto-migrated to Pay-Per-Use
with a one-time $10 voucher.

### 1.2 Legacy Tiers (existing subscribers only)

| Tier       | Price        | Posts/mo cap       | Typical use                 |
| ---------- | ------------ | ------------------ | --------------------------- |
| Basic      | $200/mo      | ~3,000 writes      | Small apps, content bots    |
| Pro        | $5,000/mo    | ~300k writes       | SaaS, high-traffic apps     |
| Enterprise | $50,000+/mo  | Negotiated         | Data firehose, SLAs         |

New sign-ups **cannot** purchase Basic or Pro — they are grandfathered only.
Existing subscribers can opt in to Pay-Per-Use at any time.

### 1.3 What mewscast currently costs under each model

Current posting profile from `config.yaml`:
- `max_posts_per_day: 5` on X
- Low read volume (mention checking + `check-mentions.yml` ~4x/day)
- Source-citation reply = 1 extra write per post (2 writes/story)

| Model                    | Writes/mo   | Reads/mo  | Monthly cost         |
| ------------------------ | ----------- | --------- | -------------------- |
| Legacy Basic (current)   | ~300        | ~400      | **$200.00** (fixed)  |
| Pay-Per-Use (projected)  | ~300        | ~400      | **$5.00**            |
| Pay-Per-Use + 2x engage  | ~600        | ~2,000    | **$16.00**           |
| Pay-Per-Use + search     | ~600        | ~20,000   | **$106.00**          |

**Bottom line:** unless we start scraping timelines or doing heavy analytics
reads, the write side of mewscast fits comfortably under $20/month on
Pay-Per-Use. The xAI rebate effectively rebates Grok image-generation costs, so
the marginal cost of a post is close to the $0.01 write credit alone.

---

## 2. The 2026 X Algorithm: What Actually Drives Reach

Understanding where the algorithm gives and takes is non-negotiable, because
spending $200/mo on the API is pointless if the posts get throttled.

### 2.1 Signals the algorithm now weights heavily

1. **Replies > Likes > Reposts.** Replies are reported to be worth ~150x a
   like. The goal of every post should be to earn a reply in the first 30
   minutes.
2. **First-hour velocity.** The ranker watches engagement velocity in the first
   30–60 minutes more than total engagement. 10 replies in 15 minutes beats 10
   replies over 24 hours.
3. **Grok-powered transformer.** Since January 2026, X's For You ranker is a
   multi-modal transformer that reads full post text and watches video. Thin,
   keyword-stuffed, or templated posts get demoted.
4. **Premium boost.** Premium ($8/mo) subscribers see roughly **2x–10x more
   impressions** per post, and their replies are pinned to the top of other
   people's reply threads.
5. **Text-first posts.** Plain text outperforms video by ~30% in engagement.
   Images and polls still help; external links hurt badly.

### 2.2 Signals that now hurt reach

- **External links in the main post.** Confirmed reach reduction of 50–90%.
  Since March 2026, non-Premium accounts posting links see near-zero median
  engagement on those posts.
- **3+ hashtags.** 1–2 hashtags get ~21% more engagement than 3+.
- **Unanswered replies on your own post.** If you don't reply to the first few
  commenters within ~2–3 hours, the velocity signal dies.
- **Duplicate/near-duplicate posts** (Grok ranker detects semantic dupes, not
  just string dupes — relevant to our deduplication system).

---

## 3. Strategic Implications for Mewscast

Map each API/algorithm fact to a concrete lever we can pull.

### 3.1 Migrate to Pay-Per-Use (or confirm we're already on it)

- **Action:** Check our X Developer Console. If we are still on Basic ($200),
  opt in to Pay-Per-Use immediately. Estimated savings: **~$195/month.**
- **Redirect savings:** Use ~$10/mo of the savings to subscribe to X Premium
  for the account. That is by far the highest-ROI single decision available.

### 3.2 Subscribe the @mewscast account to X Premium ($8/mo)

- Justified purely by the 2–10x reach multiplier — at our current ~5 posts/day,
  that is the equivalent of posting 10–50/day without Premium.
- Unlocks eligibility for the Creator Revenue Share program once we cross 500
  verified followers + 5M 3-month impressions. The algorithm boost accelerates
  the path to both thresholds.
- Premium replies get pinned in other conversations — perfect for our
  engagement bot, which already replies to news/cat accounts.

### 3.3 Restructure posts to avoid the external-link penalty

Current behavior (from README and `twitter_bot.py`): source link is posted as a
**reply** to the main tweet. That is correct — **keep doing this**. Audit any
remaining codepaths that embed URLs directly in the main post body and move
them to the reply. Specifically check:

- `src/twitter_bot.py` — verify link reply logic.
- `src/battle_post.py` — battle posts are a thread; confirm sources are in
  reply-2, not in post-1.
- `src/positive_news_post.py` — same audit.

If any part of the pipeline still puts a raw URL in post-1, we are voluntarily
burning 50–90% of our reach.

### 3.4 Exploit the first 30-minute window

This is where the cost savings from Pay-Per-Use get reinvested. A post's fate
is decided in minutes, not days, so we should concentrate API spend there.

**Proposed engagement loop (runs 5–30 minutes after each post):**

1. Mewscast posts a news item at T+0.
2. At T+5min, the engagement bot searches for 2–3 real accounts that posted
   about the same story and leaves a substantive reply (not a like) from
   @mewscast. Those accounts are likely to reply back, which counts as
   first-window engagement on our profile.
3. At T+15min, the bot checks for any replies on our own post and responds
   within 1–2 minutes. Reply velocity on our own thread is a ranker signal.
4. At T+30min, the bot quotes-or-replies to one top-of-topic account to extend
   the conversation.

**Budget impact:** 5 extra writes + ~20 reads per post × 5 posts/day × 30 days
= ~750 writes + 3,000 reads ≈ **$22.50/month** on top of base cost. Still a
fraction of the old Basic tier.

### 3.5 Content format changes the algorithm now rewards

- **Lead with a claim, not a headline.** "Fed just cut rates. Here's who
  actually benefits." outperforms "Fed cuts rates." The claim format
  gets replies because people want to argue.
- **End every post with one engagement hook** (we already have these in
  `config.yaml` → `engagement_hooks`). Enforce a 100% usage rate for posts
  under 240 chars, since replies are the #1 ranked signal.
- **Drop to 1 hashtag max.** Audit `prompts/tweet_generation_x.md` — if it ever
  adds multiple hashtags, cap at one.
- **Keep it text-first.** Images help, but don't require them. Grok image cost
  can be reserved for posts we expect to go viral (breaking news, battle posts).
- **Threads are underused.** Battle posts are already a thread; extend thread
  support to any story where we have a framing angle + populist angle + source
  citation. Each reply in our own thread is another shot at the ranker.

### 3.6 Read-side optimizations (to stay under read budget)

- Use `since_id` for `check-mentions.yml` to avoid re-reading the same mention
  window — the 24h dedup window already helps but explicit `since_id` is
  cheaper mentally and guarantees one read per new mention.
- Cache any user lookups done by the engagement bot; X's dedup only covers
  post reads, not user reads.
- For analytics (`scripts/track_analytics.py`), pull metrics once per day in
  one batched call, not per-post.

---

## 4. Cost Model: Before / After

Assumes recommended configuration: Pay-Per-Use + Premium + engagement loop.

| Item                             | Monthly cost  |
| -------------------------------- | ------------- |
| X API writes (~900 writes)       | $9.00         |
| X API reads (~4,000 reads)       | $20.00        |
| X Premium subscription           | $8.00         |
| xAI credit rebate (−10%)         | −$2.90        |
| **Subtotal: X platform**         | **$34.10**    |
| Anthropic (Claude) content gen   | $10–25        |
| Grok image generation            | $10–20        |
| GitHub Actions                   | $0            |
| **Total monthly cost**           | **$54–79**    |

Compared to the current ~$20–50/mo quoted in the README (which assumed a $0
free X tier that no longer exists), this is a ~$30/mo increase for what should
be **5–10x the reach** and a clear path to Creator Revenue Share monetization.

---

## 5. 30/60/90-Day Action Plan

### Days 0–30: Migrate and instrument

- [ ] Confirm X API billing model in Developer Console; opt into Pay-Per-Use if
  still on Basic.
- [ ] Subscribe @mewscast to X Premium; update profile, enable 2FA and verified
  email (required for Creator Revenue Share eligibility).
- [ ] Audit `twitter_bot.py`, `battle_post.py`, `positive_news_post.py` to
  confirm URLs are only in replies, never in post-1.
- [ ] Add API cost telemetry: log per-request credit spend to
  `analytics_history.json`.
- [ ] Cap hashtags to ≤1 in `prompts/tweet_generation_x.md`.

### Days 31–60: Ship the engagement loop

- [ ] New workflow `x-first-window-engage.yml` that runs 5, 15, and 30 minutes
  after each scheduled post.
- [ ] Extend `engagement_bot.py` with a `seed_replies(post_id)` method that
  replies to 2–3 same-topic accounts.
- [ ] Extend `engagement_bot.py` with a `respond_to_own_thread(post_id)` method
  that answers the first 1–2 replies within 2 minutes.
- [ ] Track reply-time and first-window engagement in `track_analytics.py`.

### Days 61–90: Optimize on data

- [ ] Compare first-window engagement rate pre- and post-Premium; confirm 2–10x
  lift exists for us specifically.
- [ ] A/B the "claim-led" vs. "headline-led" post openings and promote the
  winner into the default prompt.
- [ ] Re-evaluate the 5 posts/day cap against impression quality — if Premium
  lift is real, fewer, better-timed posts may beat more, mediocre posts.
- [ ] If we are within 20% of 500 verified followers, pause on new features and
  push for the threshold to unlock monetization.

---

## 6. Open Questions / Risks

1. **Does the xAI rebate count toward Grok image generation credits?** The
   announcement language says "xAI API credits" — needs verification in the
   Developer Console before we bake it into cost math.
2. **Does replying to our own posts from the same account count for the
   velocity signal?** The Grok ranker likely discounts self-replies. The
   engagement loop should focus on *other* accounts' replies, not
   self-replies, except for the formal source-citation reply.
3. **Rate-limit windows.** Pay-Per-Use still has per-15-minute rate caps. The
   engagement loop (5/15/30-minute bursts) has to stay under those. Verify in
   Developer Console before shipping the workflow.
4. **ToS on automated replies.** X's automation policy has tightened in 2026;
   verify the engagement-seed behavior (replying to news accounts about the
   same story) is still within their automation rules for Premium accounts.
5. **Monetization qualification churn.** The 5M impressions/3-month bar is
   higher than it sounds. Premium's 2–10x lift is the fastest lever to get
   there.

---

## 7. Sources

- [X API Pricing in 2026: Every Tier Explained (And the New Pay-As-You-Go Option)](https://www.wearefounders.uk/the-x-api-price-hike-a-blow-to-indie-hackers/)
- [Twitter/X API Pricing 2026: All Tiers ($0 to $42K) Compared](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/)
- [X (Twitter) API Pricing in 2026: All Tiers | Postproxy](https://postproxy.dev/blog/x-api-pricing-2026/)
- [Announcing the Launch of X API Pay-Per-Use Pricing — X Developer Community](https://devcommunity.x.com/t/announcing-the-launch-of-x-api-pay-per-use-pricing/256476)
- [X Revamps Developer API Pricing, Shifts To Pay-Per-Use Model — Medianama](https://www.medianama.com/2026/02/223-x-developer-api-pricing-pay-per-use-model/)
- [Pricing — X Developer Docs](https://docs.x.com/x-api/getting-started/pricing)
- [How the Twitter Algorithm Works in 2026 — Sprout Social](https://sproutsocial.com/insights/twitter-algorithm/)
- [How the Twitter/X Algorithm Works in 2026 (Complete Breakdown) — OpenTweet](https://opentweet.io/blog/how-twitter-x-algorithm-works-2026)
- [Twitter Algorithm 2026: Technical Deep Dive and Optimization Guide — Teract](https://www.teract.ai/resources/twitter-algorithm-2026)
- [X Creator Revenue Sharing Program Requirements 2026](https://www.xpayoutcalculator.com/updates/x-creator-revenue-sharing-requirements-2026-complete-guide/)
- [X Updates Revenue-Sharing Rules for Ad Creators — EmitPost](https://emitpost.com/x-revenue-sharing-criteria/)
