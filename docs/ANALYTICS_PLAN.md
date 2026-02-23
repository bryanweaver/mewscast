# Mewscast Analytics MVP Plan

## Goal
Build an analytics system to measure Walter Croncat's effectiveness across X/Twitter and Bluesky, tracking engagement metrics over time to inform content strategy and future experiments.

## User Requirements
- Track views, likes, follows over time
- Compare platform performance
- MVP first, extensible for future A/B testing
- **Storage**: SQLite database
- **Visualization**: Streamlit web dashboard
- **Collection frequency**: Once daily (Bluesky), manual/monthly (X)

---

## Critical Constraint: X API Free Tier Limits

**X Free Tier = ~100 READS/month total**

This means:
- Automated daily X metrics collection is **not viable**
- Each `get_tweet` call with metrics consumes 1 read
- 210 posts/month x daily collection would exhaust quota in 1 day

**Strategy:**
- **Bluesky**: Automated daily collection via GitHub Actions
- **X/Twitter**: Manual CLI collection ~monthly (conserve quota)
- Dashboard shows X data when available, gracefully handles gaps

---

## New File Structure

```
mewscast/
├── analytics/                    # NEW
│   ├── __init__.py
│   ├── schema.sql               # Database schema
│   ├── database.py              # DB connection helpers
│   ├── collector.py             # Metrics collection
│   └── aggregator.py            # Daily aggregates
│
├── dashboard/                   # NEW
│   ├── app.py                   # Streamlit entry point
│   ├── pages/
│   │   ├── 01_overview.py
│   │   ├── 02_post_performance.py
│   │   ├── 03_platform_comparison.py
│   │   └── 04_growth.py
│   └── components/
│       └── charts.py
│
├── data/                        # NEW
│   └── mewscast_analytics.db    # SQLite database
│
├── scripts/
│   ├── collect_metrics.py       # NEW: CLI (--bluesky auto, --x manual)
│   └── migrate_history.py       # NEW: One-time migration
│
└── .github/workflows/
    └── collect-analytics.yml    # NEW: Daily Bluesky only
```

---

## SQLite Schema (Key Tables)

### `posts` - Normalized post data
- `id`, `post_uuid`, `timestamp`, `topic`, `source`, `content`
- `x_tweet_id`, `bluesky_uri` (platform identifiers)
- `experiment_id`, `variant` (future A/B testing)

### `post_metrics` - Daily engagement snapshots
- `post_id`, `collected_at`
- X: `x_likes`, `x_retweets`, `x_replies`, `x_impressions`
- Bluesky: `bsky_likes`, `bsky_reposts`, `bsky_replies`
- `total_engagement` (computed column)

### `profile_metrics` - Daily follower counts
- `collected_at`
- X: `x_followers`, `x_following`, `x_tweets_count`
- Bluesky: `bsky_followers`, `bsky_following`, `bsky_posts_count`
- `x_followers_delta`, `bsky_followers_delta`

### `experiments` (future extensibility)
- `experiment_id`, `name`, `status`, `config` (JSON)

---

## Implementation Steps

### Phase 1: Database Foundation
1. Create `analytics/` directory and `__init__.py`
2. Create `analytics/schema.sql` with table definitions
3. Create `analytics/database.py` with:
   - `init_database()` - create tables from schema
   - `get_connection()` - return SQLite connection
4. Create `scripts/migrate_history.py`:
   - Read `posts_history.json`
   - Insert all posts into `posts` table

### Phase 2: Metrics Collection
5. Create `analytics/collector.py` with `MetricsCollector` class:
   - `collect_bluesky_metrics()` - automated daily collection
   - `collect_x_metrics()` - manual monthly collection (quota-aware)
   - `fetch_bluesky_metrics(uri)` - get likes, reposts via atproto
   - `fetch_x_metrics(tweet_id)` - get likes, retweets via tweepy
   - `fetch_bluesky_profile()` / `fetch_x_profile()` - follower counts
6. Create `scripts/collect_metrics.py` - CLI with platform flags:
   ```bash
   # Daily automated (Bluesky only)
   python scripts/collect_metrics.py --bluesky

   # Monthly manual (X only - conserve quota)
   python scripts/collect_metrics.py --x --limit 50
   ```

### Phase 3: GitHub Actions (Bluesky Only)
7. Create `.github/workflows/collect-analytics.yml`:
   - Schedule: `cron: '0 23 * * *'` (11 PM UTC daily)
   - **Bluesky metrics only** (X excluded due to API limits)
   - Steps: checkout, setup Python, install deps, run Bluesky collector
   - Commit `data/mewscast_analytics.db` changes

### Phase 4: Streamlit Dashboard
8. Create `dashboard/app.py` - main entry with sidebar nav
9. Create `dashboard/pages/01_overview.py`:
   - Quick stats row (total posts, followers, avg engagement)
   - Engagement trend line chart
10. Create `dashboard/pages/02_post_performance.py`:
    - Post selector dropdown
    - Side-by-side X vs Bluesky metrics
11. Create `dashboard/pages/03_platform_comparison.py`:
    - Overall platform stats comparison
    - Bar charts comparing engagement
12. Create `dashboard/pages/04_growth.py`:
    - Follower growth line chart (dual platform)
    - Growth rate metrics

### Phase 5: Polish
13. Create `analytics/aggregator.py` for daily summary computation
14. Add `requirements-dashboard.txt`:
    ```
    streamlit>=1.28.0
    plotly>=5.18.0
    pandas>=2.0.0
    ```
15. Update `.gitignore` to track `data/*.db`

---

## Critical Files to Reference

| File | Purpose |
|------|---------|
| `scripts/analytics.py` | Existing metric fetch patterns to reuse |
| `src/twitter_bot.py` | Tweepy client, `get_tweet` with `public_metrics` |
| `src/bluesky_bot.py` | Atproto `get_post_thread` for metrics |
| `src/post_tracker.py` | Post history patterns, JSON handling |
| `.github/workflows/engage-cats-bluesky.yml` | Workflow pattern for DB commits |

---

## API Rate Limit Strategy

### X/Twitter Free Tier (SEVERE LIMITS)
- **~100 READS/month total** - not per endpoint, TOTAL
- Automated collection is **not possible**
- Manual CLI collection ~monthly to conserve quota
- Collect only most recent posts to maximize value from limited reads

### Bluesky (Generous Limits)
- AT Protocol has much more generous limits
- Daily automated collection is viable
- No known hard caps for reading post metrics

### Collection Approach
| Platform | Frequency | Method | Quota Impact |
|----------|-----------|--------|--------------|
| Bluesky | Daily (automated) | GitHub Action | Negligible |
| X/Twitter | Monthly (manual) | CLI script | ~50-100 reads |
| X Profile | Monthly (manual) | CLI script | 1 read |

---

## Future Extensibility (Not in MVP)

The schema includes `experiments` table and `posts.experiment_id`/`variant` columns for future A/B testing:
- Different personalities per platform
- Content style experiments
- Multi-platform expansion

---

## Running the Dashboard

```bash
# Local development
cd mewscast
streamlit run dashboard/app.py

# Or with specific port
streamlit run dashboard/app.py --server.port 8501
```

---

## Success Criteria

- [ ] SQLite database stores post and profile metrics
- [ ] Daily GitHub Action collects **Bluesky** metrics automatically
- [ ] Manual CLI works for **X** metrics collection (~monthly)
- [ ] Dashboard shows engagement trends over time
- [ ] Dashboard gracefully handles sparse X data
- [ ] Platform comparison view works (with available data)
- [ ] Follower growth tracking works
