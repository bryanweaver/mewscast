# Mewscast / Walter Croncat — X API & Engagement Strategy Report
*Compiled April 7, 2026*

This report summarizes X (Twitter) API pricing as of April 2026, recent platform changes, current engagement best practices, and concrete recommendations for the Walter Croncat / Mewscast AI news bot account.

---

## 1. Current X API Pricing (April 2026)

On **February 6, 2026**, X replaced its tiered subscription model with **Pay-Per-Use (PPU)** as the default for all new developers. The legacy fixed tiers (Basic/Pro) remain available to existing customers who prefer predictable billing, and Enterprise continues as a custom contract tier. New signups are directed exclusively to PPU.

| Tier | Monthly Cost | Posts / mo | Reads / mo | v1.1 | v2 | Streaming | Media | Notes |
|---|---|---|---|---|---|---|---|---|
| **Free** | $0 | ~1,500 posts/mo (write-only, app-level) | None | Limited | Limited | ❌ | Basic | New signups only get this as a test sandbox; effectively no read access |
| **Pay-Per-Use** (default 2026) | Variable, credits-based | Metered per call | Capped at **2M reads/mo** before forced Enterprise | ✅ | ✅ | Filtered stream metered | Standard | No flat fee; buy credits, pay per endpoint call. Similar to AWS billing |
| **Basic** (legacy, closed to new signups) | **$100/mo** | 10,000 posts | 10,000 reads | ✅ | ✅ | ❌ | Standard | Still the cheapest predictable plan for existing customers |
| **Pro** (legacy) | **$5,000/mo** | 1,000,000 posts | 1,000,000 reads | ✅ | ✅ | ✅ Filtered stream | Full | Full search archive, higher rate limits |
| **Enterprise** | **$42,000+/mo** | Custom | Custom | ✅ | ✅ | ✅ Full firehose | Full | Required above 2M reads/mo PPU ceiling |

**Key takeaway:** A small bot posting 7x/day (~210 posts/mo) and doing light reading fits comfortably inside either the legacy Basic tier or a very cheap PPU footprint. The $5,000 Pro tier is dramatically oversized for Mewscast's needs.

---

## 2. Recent Changes (Past 6–12 Months)

- **Nov 2025:** Closed beta of usage-based pricing launched.
- **Feb 6, 2026:** PPU became the default pricing model for all new developers. Fixed Basic/Pro no longer available to new signups.
- **March 2026 link-reach change:** Non-Premium accounts posting links now see ~zero median engagement — link posts from non-Premium accounts are effectively invisible in the timeline. Premium accounts posting links still see reduced-but-viable engagement.
- **AI reply bots now require prior written approval from X.** Automated reply bots built on AI/LLMs must be explicitly approved before deployment.
- **Bot disclosure required:** Automated accounts must clearly identify themselves as bots in the profile bio and label the responsible operator.
- **Engagement farming banned:** Automated likes, reposts, bookmarks, follow/unfollow loops, and auto-DMs are all explicitly prohibited and subject to suspension.
- **Developer Agreement** still requires compliance with the Automation Rules, Display Requirements, API Restricted Uses, and X Rules.

---

## 3. Engagement Best Practices on X (2026)

**Engagement weighting (approximate algorithm multipliers):**
- Repost ≈ **20× a like**
- Reply ≈ **13.5× a like**
- Bookmark ≈ **10× a like** ("silent like")
- Like = 1× baseline

A post with modest likes but strong reposts + bookmarks will dramatically out-rank a post that only gets likes.

**Time decay is steep:** A post loses roughly half its potential visibility every ~6 hours. Responding to early engagement within the first 2–3 hours is critical.

**Premium reach boost:** X Premium subscribers see a **2–4× reach multiplier** vs non-Premium, and Premium replies are pinned to the top of conversation threads. For any link-posting strategy, Premium is effectively mandatory since March 2026.

**Content formats that perform best in 2026:**
- Native media (images, short vertical video) dramatically outperforms text-only.
- Screenshots of text (e.g. article headlines with commentary) beat raw links.
- Threads still work, but single strong posts with media now win the algorithm more often.
- Long-form posts (Premium feature) convert very well for commentary/analysis content — exactly the Walter Croncat format.
- Hashtags have near-zero ranking benefit and can slightly *hurt* reach; use sparingly (0–1 max).

**Reply strategy:** Replying early (first 5 minutes) to large accounts in your niche is still the single best organic growth tactic. For a news bot, being first-to-comment on a breaking-news tweet from a major outlet is high-leverage.

**Community Notes:** News-adjacent content is monitored aggressively. Factual accuracy and citing primary sources matters more than ever — a Community Note will tank reach.

**Best posting times:** Weekdays 9–11am and 7–9pm ET perform best for news content. Weekends are lower volume but less competition.

---

## 4. Strategic Recommendations for Mewscast

### API tier
At ~210 posts/mo and light reading, **PPU is the obvious fit** — estimated cost **under $10/mo** for Walter's current usage. Do NOT upgrade to Pro ($5K/mo) — it would be ~100× oversized. If grandfathered into legacy Basic at $100/mo, stay there only if PPU modeling shows it's cheaper to switch.

**Action:** Model one week of Walter's actual API calls against the PPU credit pricing sheet before migrating. If you're still on Free, apply for PPU now — Free tier reads are essentially unusable for a news-reaction bot.

### X Premium subscription for @WalterCroncat
**Strongly recommended — this is the single highest-ROI spend available.** For roughly $8–16/mo:
- 2–4× reach multiplier on every post
- Reply prioritization in conversation threads (huge for the "reply to breaking news" strategy below)
- Long-form posts unlocked — perfect for Walter's article-reading commentary format
- Link posts become viable again (non-Premium link posts are dead since March 2026)
- Verified checkmark adds credibility to a news-reporting persona

### Content strategy adjustments
1. **Post screenshots, not links.** Walter should quote the headline + key paragraph as an image (or long-form post), not link out. Links without Premium = dead reach.
2. **Lead with the contradiction.** Walter's core value is "headline vs reality" — structure every post so the spin-vs-truth tension is the first line. That's bookmark-bait (10× multiplier).
3. **Add Grok-generated images more often.** Native media is a major ranking input. A cat-reporter illustration on each post should materially lift reach.
4. **Cut frequency, raise quality.** 7x/day is fine, but the algorithm prefers 3–4 high-signal posts over 7 mediocre ones. Consider 4x/day of high-effort posts + reply activity.
5. **Ask questions / invite disagreement.** Replies are 13.5× likes. Ending with "Am I wrong, humans?" or similar will meaningfully lift the reply rate.

### Using the API for engagement (within the rules)
- **Allowed:** Auto-posting original commentary, reading trending topics, search/filter for breaking news, posting threads.
- **Allowed with approval:** AI-generated replies — requires prior written approval from X. Worth applying for.
- **NOT allowed:** Auto-liking, auto-reposting, auto-following, auto-DMs, follow/unfollow loops.
- **High-leverage allowed tactic:** Use filtered stream / search to detect breaking news from a curated list of ~30 major news accounts, then queue a Walter commentary post within 2–5 minutes of the original. First-mover reply advantage is the single biggest organic growth lever.

### Image generation ROI
Grok image generation is almost certainly worth continuing. Native images are a direct ranking input and the Walter Croncat character is inherently visual. Budget-wise, it's a rounding error vs Premium.

### ROI summary
| Spend | Est. monthly cost | Expected reach impact |
|---|---|---|
| X API (PPU) | <$10 | Neutral (required) |
| X Premium for @WalterCroncat | ~$8–16 | **2–4× reach, link posts viable, long-form unlocked** |
| Grok image gen | existing | Native media boost |
| Anthropic commentary | existing | Quality lever |
| **Total all-in** | **~$40–75/mo** | Meaningful lift vs. current ~$20–50/mo |

The single highest-leverage change is **adding X Premium**. Everything else is optimization.

---

## 5. Action Items

1. **Subscribe @WalterCroncat to X Premium this week.** Highest-ROI action available.
2. **Apply to X for AI reply bot approval** — required before any auto-reply functionality.
3. **Migrate from whatever current API tier to PPU** (model one week of usage first). Avoid Pro.
4. **Refactor posts to lead with the spin-vs-reality contradiction** in the first line.
5. **Switch from link-sharing to screenshot/long-form posts** — non-Premium link reach is dead, and even with Premium, native media outperforms.
6. **Add Grok-generated Walter Croncat character image to every post** where it fits.
7. **Build a curated breaking-news watchlist** (~30 major outlets) and auto-draft Walter commentary within 2–5 minutes of breaking posts, with human review before posting (until AI reply approval lands).
8. **Reduce post frequency to 4x/day high-quality** instead of 7x/day, and redirect the saved cycles into higher-effort media and commentary.
9. **Make sure bot disclosure is in the bio** ("Automated AI cat news reporter, operated by Bryan Weaver") — required by X Automation Rules.
10. **Monitor for Community Notes** on every post; cite primary sources in every commentary to minimize risk.

---

## Sources

- [X API Pricing (official)](https://docs.x.com/x-api/getting-started/pricing)
- [X API Pricing in 2026: Every Tier Explained (We Are Founders)](https://www.wearefounders.uk/the-x-api-price-hike-a-blow-to-indie-hackers/)
- [Twitter/X API Pricing 2026: All Tiers Compared (Xpoz)](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/)
- [X (Twitter) API Pricing in 2026: All Tiers (Postproxy)](https://postproxy.dev/blog/x-api-pricing-2026/)
- [X Updates API Pricing (Social Media Today)](https://www.socialmediatoday.com/news/x-formerly-twitter-launches-usage-based-api-access-charges/803315/)
- [X Automation Rules (X Help)](https://help.x.com/en/rules-and-policies/x-automation)
- [X Developer Agreement and Policy](https://developer.x.com/en/developer-terms/agreement-and-policy)
- [Twitter/X Automation Rules in 2026 (OpenTweet)](https://opentweet.io/blog/twitter-automation-rules-2026)
- [How the Twitter Algorithm Works in 2026 (Sprout Social)](https://sproutsocial.com/insights/twitter-algorithm/)
- [How the Twitter/X Algorithm Works in 2026 (OpenTweet)](https://opentweet.io/blog/how-twitter-x-algorithm-works-2026)
- [X Algorithm Explained 2026 (AutoTweet)](https://www.autotweet.io/blog/x-algorithm-explained-2026)

---

## Companion Docs

- [`Walter_Cronkite_Report.md`](./Walter_Cronkite_Report.md) — sourced research on Walter Cronkite that the persona is built on
- [`Croncat_Journalism_Workflow.md`](./Croncat_Journalism_Workflow.md) — the 7-stage pipeline this strategy supports
- [`../README.md`](../README.md) — project README and CLI reference
