# Walter Croncat Journalism Pipeline — Cost Analysis & Scheduling Strategy
*April 2026*

---

## Part 1: Cost Analysis by Post Type

### API Pricing (April 2026)

Per [Anthropic's current pricing](https://platform.claude.com/docs/en/about-claude/pricing):

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Used for |
|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | Stage 4: Meta-analysis |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Stage 5: Post composition |
| Claude Haiku 4.5 | $1.00 | $5.00 | Draft analysis + image prompt |

Other costs:
- Grok image generation: ~$0.02-0.05 per image (publish mode only)
- X API (PPU): ~$0.001 per search call (Stage 1 trend detection)
- Google News RSS: Free
- Jina Reader: Free tier (rate-limited)
- GitHub Actions: Free (public repo)

### Per-Cycle Cost Breakdown

Each journalism cycle runs Stages 1-7. Here's what each stage costs:

| Stage | What runs | Typical tokens | Cost per cycle |
|---|---|---|---|
| **Stage 1** — Trend Detection | X API search OR Google News RSS | n/a | ~$0.001 |
| **Stage 2** — Triage | Pure heuristic (no LLM) | 0 | $0.00 |
| **Stage 3** — Source Gather | HTTP fetches (direct + Jina fallback) | 0 | $0.00 |
| **Stage 4** — Meta-Analysis | **Claude Opus**: ~15-25K input, ~1.5K output | 20K in / 1.5K out | **$0.14** |
| **Stage 5** — Composition | **Claude Sonnet**: ~5K input, ~0.5-2K output | 5K in / 1K out | **$0.03** |
| **Stage 5 retry** | Sonnet again (if verification gate rejects) | 5K in / 1K out | $0.03 |
| **Stage 6** — Verification | Pure logic (no LLM) | 0 | $0.00 |
| **Draft Analysis** | **Claude Haiku**: ~3K input, ~200 output | 3K in / 200 out | **$0.004** |
| **Image prompt** | **Claude Haiku**: ~2K input, ~150 output | 2K in / 150 out | $0.003 |
| **Image generation** | **Grok**: 1 image | n/a | ~$0.03 |
| | | **Total (dry-run):** | **~$0.17** |
| | | **Total (publish with image):** | **~$0.21** |

### Cost by Post Type

Different post types don't change the pipeline cost much — the same stages run regardless. The main variable is whether Opus produces a long or short brief:

| Post type | Opus input tokens | Opus output | Sonnet output | Total cycle cost |
|---|---|---|---|---|
| **META** (flagship) | ~25K (7 article bodies) | ~2K (detailed brief) | ~2K (long-form post) | ~$0.22 |
| **REPORT** | ~20K (5-7 articles, some headline-only) | ~1K (shorter brief) | ~300 tokens (280 chars) | ~$0.16 |
| **BULLETIN** | ~10K (1-3 article bodies) | ~500 (minimal brief) | ~200 tokens | ~$0.10 |
| **ANALYSIS** | ~25K (same as META) | ~2K | ~1K | ~$0.21 |
| **PRIMARY** | ~15K | ~1K | ~500 | ~$0.14 |
| **CORRECTION** | ~5K (references original) | ~500 | ~300 | ~$0.08 |

### Monthly Cost Projections

| Schedule | Posts/day | Monthly cost (publish) | Monthly cost (dry-run) |
|---|---|---|---|
| **1x/day** (conservative start) | 1 | **~$6** | ~$5 |
| **2x/day** (recommended) | 2 | **~$13** | ~$10 |
| **3x/day** (moderate) | 3 | **~$19** | ~$15 |
| **4x/day** (aggressive) | 4 | **~$25** | ~$20 |
| **5x/day** (max recommended) | 5 | **~$32** | ~$25 |

### Comparison to Current Legacy Pipeline

The existing `post_scheduled_tweet` pipeline costs:
- ~$0.01-0.02 per post (Sonnet for content + Grok for image)
- At 7x/day: ~$3-4/month

**The journalism pipeline is ~10-15x more expensive per post** because of the Opus meta-analysis call. But the output quality is incomparably higher — Opus produces real multi-outlet coverage comparison that Sonnet alone cannot.

### Cost Optimization Opportunities

1. **Batch API (50% off):** If posts are scheduled in advance (not real-time), the Batch API gives a flat 50% discount. A 2x/day schedule would drop to ~$6.50/month.

2. **Prompt caching (90% off cache hits):** The meta_analysis.md prompt template is the same every cycle (~2K tokens). Caching it would save ~$0.01/cycle. Small but free.

3. **Downgrade BULLETIN to Sonnet:** BULLETIN posts are single-source reports with minimal analysis. Skipping Opus for BULLETIN-destined stories and going straight from Stage 3 to Stage 5 (Sonnet) would save ~$0.10 per BULLETIN cycle. Worth doing when most cycles produce BULLETINs.

4. **Cap article body length:** Currently bodies are truncated at 6,000 chars. Reducing to 3,000 chars would halve Opus input tokens for dense dossiers, saving ~$0.03-0.05 per cycle.

### Total All-In Monthly Budget

| Component | Cost/month |
|---|---|
| Legacy scheduled posts (7x/day) | $3-4 |
| Journalism pipeline (2x/day recommended) | $13 |
| X API (PPU, both pipelines) | <$5 |
| X Premium (if subscribed) | $8-16 |
| Grok image generation | $2-3 |
| **Total** | **~$35-45/month** |

This is within the $40-75/month range estimated in the X API Strategy doc.

---

## Part 2: Scheduling Strategy

### Current State

The legacy `post_scheduled_tweet` pipeline runs 7x/day on this cron schedule:
```
2 AM, 6 AM, 10 AM, 1 PM, 4 PM, 7 PM, 10 PM UTC
(10 PM, 2 AM, 6 AM, 9 AM, 12 PM, 3 PM, 6 PM ET)
```

The journalism pipeline has not been scheduled yet (master switch off, dry-run only via manual Actions trigger).

### Recommended Scheduling Strategy

**Phase 1: Validation (first 2 weeks)**

Keep legacy pipeline unchanged. Add journalism dry-runs on a daily schedule to build a track record of drafts to review:

```yaml
# journalism-dry-run.yml — uncomment the schedule
schedule:
  - cron: '0 13 * * *'   # 1x/day at 1 PM UTC (9 AM ET)
```

Review the drafts daily in the GitHub Actions artifacts. Tune prompts if needed.

**Phase 2: Soft Launch (weeks 3-4)**

Flip `journalism.enabled: true`. Add the journalism pipeline as a SECOND workflow alongside the legacy pipeline. Start with 1x/day:

```yaml
# journalism-publish.yml (new workflow)
schedule:
  - cron: '30 17 * * *'   # 1x/day at 5:30 PM UTC (1:30 PM ET)
```

1:30 PM ET is the afternoon engagement peak per the X strategy doc. This is the single highest-value timeslot for a journalism post — people are checking news during their afternoon break.

Keep the legacy pipeline at 7x/day. The journalism post supplements (not replaces) the regular posts. Total: 8 posts/day, one of which is journalism-grade.

**Phase 3: Ramp Up (weeks 5-8)**

If the journalism posts outperform the legacy posts in engagement:

```yaml
schedule:
  - cron: '30 14 * * *'   # 10:30 AM ET (morning prime)
  - cron: '30 20 * * *'   # 4:30 PM ET (afternoon prime)
```

2x/day journalism at the two peak engagement windows. Reduce legacy from 7x to 5x to compensate (drop the 2 AM and 6 AM slots — lowest engagement, just overnight filler).

**Phase 4: Full Transition (month 3+)**

If journalism quality + engagement justifies it, consider:

```yaml
schedule:
  - cron: '0 14 * * *'    # 10 AM ET — morning report
  - cron: '0 17 * * *'    # 1 PM ET — midday meta
  - cron: '0 20 * * *'    # 4 PM ET — afternoon report
  - cron: '0 1 * * *'     # 9 PM ET — evening wrap
```

4x/day journalism, reduce legacy to 3x/day (overnight filler only). The journalism posts take the prime slots; legacy fills the gaps.

### Post-Type Mix by Time Slot

Not all timeslots should produce the same post type. The news cycle has a rhythm:

| Time (ET) | Best post type | Why |
|---|---|---|
| **Morning (9-11 AM)** | REPORT | Lead with what happened overnight. Straight news, fresh, fast. |
| **Midday (12-2 PM)** | META | By midday, multiple outlets have covered the morning's news differently. This is when coverage comparison has the most material. |
| **Afternoon (3-5 PM)** | REPORT | Catch the afternoon news cycle (court rulings, market close, press conferences). |
| **Evening (7-9 PM)** | META or ANALYSIS | The day's stories have been fully reported by now. Evening is for deeper comparison or the rare opinion post. |

The pipeline already has forced-type support (`python src/main.py journalism meta`, `journalism brief`, etc.). The workflow can pass the forced type based on the cron slot:

```yaml
jobs:
  morning:
    if: github.event.schedule == '0 14 * * *'
    steps:
      - run: python src/main.py journalism brief  # REPORT

  midday:
    if: github.event.schedule == '0 17 * * *'
    steps:
      - run: python src/main.py journalism meta   # META
```

### Key Timing Principles

1. **Offset from the legacy schedule.** Don't publish a journalism post at the same time as a legacy post — they'll compete with each other in followers' feeds. The legacy cron hits on the hour (2, 6, 10, 13, 16, 19, 22 UTC); the journalism cron should hit at :30 past.

2. **Random delay stays.** The existing 1-15 minute random delay in post-tweet.yml makes posts look more human. Apply the same to journalism publishes.

3. **Weekend cadence can be lighter.** Weekday news cycles are denser than weekends. Consider: 2x/day weekdays, 1x/day weekends once in Phase 3+.

4. **The META post is the premium slot.** META posts have the highest engagement potential (bookmarks are 10x likes in the algorithm per the X strategy doc). Scheduling META for the midday peak maximizes its algorithmic lift.

### Dedup Interaction with Scheduling

The `journalism_seen_stories.txt` dedup file ensures no story repeats across cycles within a 14-day window. With 2x/day scheduling:
- Morning cycle picks the top trending story → marks it seen
- Midday cycle picks the NEXT trending story (morning's pick is already seen)
- This naturally produces variety across the day without manual intervention

At 4x/day, the dedup file grows by 4 entries/day = ~56 entries in a 14-day window. The 14-day prune keeps it bounded.

### Summary

| Phase | When | Journalism posts/day | Legacy posts/day | Monthly journalism cost |
|---|---|---|---|---|
| **Validation** | Weeks 1-2 | 1 (dry-run only) | 7 | ~$5 (dry-run) |
| **Soft Launch** | Weeks 3-4 | 1 (publishing) | 7 | ~$6 |
| **Ramp Up** | Weeks 5-8 | 2 | 5 | ~$13 |
| **Full Transition** | Month 3+ | 4 | 3 | ~$25 |

Total all-in budget stays within the $40-75/month range from the X API Strategy doc at every phase.

---

## Sources

- [Anthropic Claude API Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — per-token costs for Opus 4.6, Sonnet 4.6, Haiku 4.5
- [Claude API Pricing Full Breakdown](https://www.metacto.com/blogs/anthropic-api-pricing-a-full-breakdown-of-costs-and-integration) — batch API and caching optimization details
- `docs/Mewscast_X_API_Strategy.md` — X engagement windows, posting best practices, total budget targets
- `docs/Croncat_Journalism_Workflow.md` — pipeline stages, post types, cadence targets
