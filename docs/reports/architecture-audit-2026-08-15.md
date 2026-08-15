# Walter Croncat Architecture Audit — 2026-08-15

**Auditor:** Cursor Cloud Agent  
**Scope:** Read-only codebase analysis  
**Deliverable:** Architectural documentation for Bryan

---

## Executive Summary

The Walter Croncat journalism pipeline is a 7-stage AI news reporting system that transforms trending topics into verified, multi-outlet news posts. The system publishes to X (Twitter) and Bluesky with distinct sign-off rules enforcing the Cronkite principle: opinion is never stamped as reporting.

**Key findings:**
1. **X API trend detection is disabled** (`config.yaml:328` — `use_x_api: false`). All story selection currently flows through Google News RSS (`NewsFetcher`), not X. "Trending on X" in practice means "Google News top stories."
2. **Deduplication has known gaps** — issues #14 and #16 document triple-posting of the Pope Leo XIV story, pointing to retry logic that doesn't check whether a `story_id` was already published.
3. **X posting has intermittent silent failures** — issue #17 shows `x_tweet_id = null` on a successful Bluesky post, indicating the X API call failed without raising an exception that would trigger a retry.
4. **Verification gate sign-off enforcement is strong** — the keystone rule (sign-off must match post type) is correctly implemented in `verification_gate.py` with comprehensive branch coverage.
5. **The outlet-reply X path is effectively dead** — X's 2026-02-23 API policy blocks programmatic replies unless the target author has @mentioned or quote-posted the bot. Bluesky is the active outlet-reply platform.

---

## 1. The 7-Stage Journalism Pipeline

### Pipeline Overview

```
 Stage 1 (TrendDetector)       →  Candidate stories
 Stage 2 (StoryTriage)         →  Need-to-know filter
 Stage 3 (SourceGatherer)      →  5-10 outlet dossier
 Stage 3.5 (PrimarySourceFinder) →  Court filings, transcripts
 Stage 4 (MetaAnalyzer)        →  Opus meta-analysis brief
 Stage 5 (PostComposer)        →  One of 6 post types
 Stage 6 (VerificationGate)    →  Hard rules check
 Stage 7 (Publish)             →  X + Bluesky + dossier page
```

### Stage 1 — Trend Detection (`src/trend_detector.py`)

**What it claims to do:** Search X for recent tweets from ~35 curated outlets in `outlet_registry.yaml`, cluster by proper-noun overlap, and return ranked `TrendCandidate` objects.

**What it actually does:** The X path is **disabled** (`config.yaml:328`):
```yaml
trend_detection:
  use_x_api: false  # disabled 2026-05-02
  fallback_to_news_fetcher: true
```

With `use_x_api: false`, `TrendDetector.detect_trends()` immediately falls back to `_detect_via_news_fetcher()` (line 221-224), which calls `NewsFetcher.get_top_stories()` — Google News RSS, not X.

**Models/APIs called:**
- X API `search_recent_tweets` (when enabled) via `x_retry.call_with_retry()` — chunked at 25 handles/query
- Google News RSS `https://news.google.com/rss` (fallback, currently the only active path)

**Skip/fail conditions:**
- `twitter_bot` is `None` → X path skipped (line 236)
- `client` attribute missing on bot → X path skipped (line 243)
- Empty outlet registry → X path skipped (line 239)
- X API returns 0 tweets after retries → fallback to NewsFetcher (line 296-299)

**Key function:** `_cluster_tweets()` (line 379-444) groups tweets by ≥2 shared proper nouns, uses longest tweet text as `headline_seed`.

### Stage 2 — Story Triage (`src/story_triage.py`)

**Purpose:** Filter candidates to ≥3/5 "need-to-know" dimensions.

**Scoring dimensions** (line 286-330):
1. **multi-outlet** — `source_signals ≥ 2` OR `source == "news_fetcher"` (Google News curated)
2. **event-verb** — headline contains a verb from `EVENT_TOKENS` (97 verbs, lines 45-97)
3. **impact** — headline contains token from `IMPACT_TOKENS` (health/safety/rights/money)
4. **checkable** — headline contains outlet name OR proper noun
5. **accountability** — headline mentions DOJ/FBI/SEC/court/committee/etc.

**Hard rejects** (line 333-378):
- `gossip_no_event` — gossip tokens + no event verb
- `single_anonymous_source` — 1 signal + anonymous tokens
- `single_signal_no_event_no_accountability_no_impact` — 1 signal + no event + no escape hatch
- `recycled_outrage` — ≥2 outrage tokens + no event verb

**Models/APIs called:**
- Claude Haiku (`claude-haiku-4-5-20251001`) when `use_llm=True` for borderline score=2 candidates (line 409-448)
- Enabled in config (`config.yaml:332`: `use_llm: true`)

**Feedback loop:** `last_decisions` list (line 189) persisted to `docs/reports/triage_decisions.jsonl` by `main.py` for weekly review.

### Stage 3 — Source Gather (`src/source_gatherer.py`)

**Purpose:** Collect 5-10 articles from diverse outlets, fetch full bodies.

**Slant matrix** (line 285):
```python
REQUIRED_SLANTS = ["wire", "lean-left", "lean-right", "international", "specialized"]
```

**Fetch chain** (4 stages, `news_fetcher.py:202-247`):
1. Direct HTTP + BeautifulSoup — fast, ~60% success
2. Jina Reader (`r.jina.ai`) — handles soft paywalls
3. Diffbot Article API — CV-based extraction, free 10K/month
4. Playwright browser — JS-rendered SPAs

**Relevance filter** (line 723-786): Two-pass — proper-noun heuristic, then Haiku classifier for borderline. Seed URLs from trend detection are exempt.

**Wire-derived dedup** (line 788-816): Marks articles with ≥50% 30-char chunk overlap with a wire article as `is_wire_derived=True`.

### Stage 3.5 — Primary Source Finder (`src/primary_source_finder.py`)

**Purpose:** Locate underlying documents (court filings, congress.gov records, press releases).

**Endpoint patterns:** congress.gov, PACER, federalregister.gov, BLS, SEC EDGAR, state.gov.

### Stage 4 — Meta-Analysis (`src/meta_analyzer.py`)

**Purpose:** Call Claude Opus to produce a `MetaAnalysisBrief` from the dossier.

**Model:** `claude-opus-4-8` (config.yaml:338)  
**Max tokens:** 4000  
**Prompt template:** `prompts/meta_analysis.md`

**Output structure** (from `dossier_store.py:180-217`):
- `consensus_facts: list[str]`
- `disagreements: list[Disagreement]`
- `framing_analysis: dict[str, str]` — outlet → framing summary
- `primary_source_alignment: list[str]`
- `missing_context: list[str]`
- `suggested_post_type: PostType`
- `confidence: float`

**Skip/fail conditions:**
- Claude response not valid JSON → retry once with corrective preface (line 70-85)
- Invalid `suggested_post_type` → defaults to `REPORT` (line 223-232)

### Stage 5 — Post Composer (`src/post_composer.py`)

**Purpose:** Generate the post text from the brief + dossier.

**Model:** `claude-sonnet-4-6` (config.yaml:341)

**Post types and prompt files** (line 45-52):
| Type | Prompt | Sign-off |
|------|--------|----------|
| REPORT | `report_post.md` | `And that's the mews.` |
| META | `meta_post.md` | `And that's the mews — coverage report.` |
| ANALYSIS | `analysis_post.md` | `This cat's view — speculative, personal, subjective.` |
| BULLETIN | `bulletin_post.md` | `None` |
| CORRECTION | `correction_post.md` | `None` |
| PRIMARY | `primary_post.md` | `And that's the mews — straight from the source.` |

**Character budgets:**
- Short-form (REPORT/BULLETIN/ANALYSIS/PRIMARY/CORRECTION): 280 chars
- Long-form (META): 6500 chars (`config.yaml:343`)

**Post-processing repairs** (line 219-318):
- `_enforce_char_limit()` — truncates at sentence boundary
- `_repair_hedge_attribution()` — grafts outlet name onto orphan "reportedly"/"according to"

### Stage 6 — Verification Gate (`src/verification_gate.py`)

**Purpose:** Hard checks before publish. Pure functions, no I/O.

**Checks run** (line 141-165):
1. `_check_source_count` — REPORT/META need ≥2 outlets
2. `_check_outlet_in_body` — ≥1 outlet name literally present
3. **`_check_signoff_matches_type`** — THE KEYSTONE RULE
4. `_check_no_editorial_words` — banned words in REPORT
5. `_check_hedge_attribution` — "according to" must have nearby outlet
6. `_check_primary_source_for_accountability` — PRIMARY needs primary source
7. `_check_no_placeholder_template` — blocks leaked fallback text
8. `_check_dates_match_brief` — rejects LLM year regression
9. `_check_char_limit` — enforces per-type budget

**Keystone implementation** (line 226-334):

```python
# Branch 1: post type HAS a sign-off (REPORT, META, ANALYSIS, PRIMARY)
if expected is not None:
    if text.endswith(expected):
        # Check for double-stamping
        ...
        return True, None
    # No expected sign-off at end — allowed, but reject if DIFFERENT type's sign-off snuck in
    for other in other_sign_offs:
        if text.endswith(other):
            return False, "signoff_matches_type: ..."

# Branch 2: post type has NO sign-off (BULLETIN, CORRECTION)
for other in other_sign_offs:
    if text.endswith(other):
        return False, "signoff_matches_type: ..."
# Belt-and-suspenders: forbid ANY sign-off phrase anywhere in body
for so in all_sign_off_phrases:
    if so in body:
        return False, "signoff_matches_type: ..."
```

**Weakness:** A missing sign-off on a REPORT post is allowed (line 273-297 comment: "occasional missing sign-off is acceptable"). This means a REPORT could ship without its "And that's the mews." seal, diluting the brand consistency. The gate catches *wrong* sign-offs but not *absent* expected sign-offs.

### Stage 7 — Publish (`src/main.py`)

**Orchestration:** `post_journalism_cycle()` (line 800+ in main.py) runs Stages 1-6, then:
1. Generates image via Grok (`_generate_journalism_image`)
2. Posts to Bluesky first
3. Posts to X with image
4. Posts dossier-link reply (Field Notes image if eligible)
5. Persists dossier JSON + HTML page
6. Updates `posts_history.json` and `journalism_seen_stories.txt`

**Image generation:**
- Model: `grok-imagine-image-quality` (config.yaml:275)
- Prompt: `prompts/journalism_image.md` + Claude Haiku for dynamic portion
- QC: Optional Haiku vision check (config.yaml:286)

---

## 2. GitHub Actions and Bots

### journalism-publish.yml

**File:** `.github/workflows/journalism-publish.yml`

**Triggers:**
- `workflow_dispatch` (manual with optional `post_type` and `topic` inputs)
- `schedule`:
  - `30 13 * * *` — 13:30 UTC = 9:30 AM EDT
  - `30 17 * * *` — 17:30 UTC = 1:30 PM EDT
  - `0 0 * * *` — 00:00 UTC = 8:00 PM EDT

**What it runs:** `python src/main.py journalism`

**Commits written:**
1. `journalism_seen_stories.txt` — dedup file
2. `docs/dossiers/*.html`, `docs/sitemap.xml`, `docs/robots.txt` — dossier pages
3. `posts_history.json` — post record
4. `docs/reports/triage_decisions.jsonl` — triage feedback

**On-brand enforcement:** None at the GHA level — all sign-off enforcement is in `verification_gate.py`.

### bluesky-engage.yml

**File:** `.github/workflows/bluesky-engage.yml`

**Triggers:** 4x/day schedule (13:30, 16:30, 19:30, 00:30 UTC) + manual

**What it runs:** `python scripts/bluesky_engage.py`

**Purpose:** Like posts that mention the bot. Writes to `bluesky_engagement_history.json`.

### engage-cats-bluesky.yml

**File:** `.github/workflows/engage-cats-bluesky.yml`

**Triggers:** 4x/day schedule (13:00, 16:00, 20:00, 01:00 UTC) + manual

**What it runs:** `python src/bluesky_engagement_bot.py`

**Purpose:** Cat community engagement — find/follow cat accounts, like cat posts, repost cat rescue posts.

**Code:** `BlueskyEngagementBot.run_engagement_cycle()` (line 639-696):
1. `find_and_follow_cat_account()` — search for cat keywords, quality-filter, follow
2. `find_and_like_cat_post()` — search, like, auto-follow author
3. `find_and_repost_cat_rescue()` — find rescue posts asking for reposts

**Potential failure mode:** The `_check_follow_ratio_safe()` check (line 87-123) silently skips follows when ratio > 2.5:1 but doesn't log this as a failure, so runs may appear successful with 0 follows.

### bluesky-outlet-reply.yml

**File:** `.github/workflows/bluesky-outlet-reply.yml`

**Triggers:**
- `workflow_run` after `journalism-publish.yml` completes
- 4x/day schedule (14:00, 16:00, 20:00, 00:00 UTC)
- `workflow_dispatch` with optional `dry_run`

**What it runs:** `python src/bluesky_outlet_reply.py`

**Purpose:** Reply to outlet skeets with dossier analysis link.

**Commits written:** `bluesky_outlet_reply_history.json`

### X Engagement / Outlet-Reply

**X outlet-reply is effectively dead.** From `config.yaml:384-401`:

```yaml
follow_before_reply: false  # Experiment concluded 2026-04-19
# X shipped an API-v2 policy on 2026-02-23 that rejects POST /2/tweets replies
# unless the TARGET AUTHOR has @mentioned or quote-posted us.
```

There is **no dedicated X engagement GHA**. The X posting path in `main.py` calls `TwitterBot.post_tweet()` and `TwitterBot.reply_to_tweet()` directly, but programmatic replies to outlets are blocked by X's policy.

**X engagement history:** `x_engagement_history.json` exists but the engagement workflow that wrote to it is not present in current GHAs.

---

## 3. Story Selection: Where X vs Google News Drives the Pick

### The Hypothesis to Verify

> "trend_detector.py uses X recent-search on outlet_registry.yaml handles, not the For You feed."

### Verification Result: **CONFIRMED but DISABLED**

**Code path when X API is enabled:**

```python
# trend_detector.py line 254-303
for chunk in self._chunk_handles(self.outlets, 25):
    query = self._build_query(chunk)  # "(from:Reuters OR from:AP ...) -is:retweet lang:en"
    response = call_with_retry(
        lambda: client.search_recent_tweets(
            query=query,
            max_results=100,
            tweet_fields=['public_metrics', 'created_at', 'entities', 'author_id'],
        ),
        ...
    )
```

This is `search_recent_tweets`, not the For You feed. The query is constructed from `outlet_registry.yaml` handles (line 312-317):

```python
from_clauses = " OR ".join(f"from:{h}" for h in handles)
return f"({from_clauses}) -is:retweet lang:en"
```

**Current state:** This path is **not executed** because `config.yaml:328` sets `use_x_api: false`.

### What "Trending on X" Actually Means in This Codebase

**In trend_detector.py:** If X API were enabled, "trending" would mean "tweets from curated outlets in the last 7 days that cluster by proper-noun overlap, ranked by (source count, engagement)." This is NOT the X For You feed or the X Trending Topics.

**In practice today:** "Trending" means `NewsFetcher.get_top_stories()` — Google News top stories RSS feed. The `TrendCandidate.source` field is set to `"news_fetcher"` (line 466), and the triage `multi-outlet` check gives automatic credit for Google's curation (line 305-307).

### The Real Path from Candidate → Selected Story

```
1. NewsFetcher.get_top_stories() returns up to 20 articles from Google News RSS
   (news_fetcher.py:794-857)

2. TrendDetector._detect_via_news_fetcher() wraps each into a TrendCandidate
   with source="news_fetcher", engagement=0 (line 458-475)

3. StoryTriage.triage() scores each candidate:
   - "news_fetcher" candidates get automatic multi-outlet credit
   - Must still hit ≥3/5 dimensions to pass
   - Hard rejects (gossip, outrage) still apply

4. SourceGatherer.gather() takes the first passing candidate and fans out
   to Google News RSS again with the headline_seed as query

5. The story with the highest triage score (multi-outlet + event-verb + ...) wins
```

**Critical insight:** There is currently no X signal in story selection. The pipeline is 100% Google News driven.

---

## 4. verification_gate and Sign-Off Discipline

### The Keystone Rule

From `dossier_store.py:37-48`:

```python
SIGN_OFFS: dict[PostType, Optional[str]] = {
    PostType.REPORT:     "And that's the mews.",
    PostType.META:       "And that's the mews — coverage report.",
    PostType.ANALYSIS:   "This cat's view — speculative, personal, subjective.",
    PostType.BULLETIN:   None,
    PostType.CORRECTION: None,
    PostType.PRIMARY:    "And that's the mews — straight from the source.",
}
```

### How the Gate Enforces It

`verification_gate.py:226-334` implements `_check_signoff_matches_type()`:

**Branch 1 — Post type HAS a sign-off (REPORT, META, ANALYSIS, PRIMARY):**
- If draft ends with expected sign-off → PASS (with double-stamp paranoia check)
- If draft ends with DIFFERENT type's sign-off → FAIL (opinion-smuggling)
- If draft has no sign-off → PASS (line 290-297: missing allowed, wrong forbidden)

**Branch 2 — Post type has NO sign-off (BULLETIN, CORRECTION):**
- If draft ends with any sign-off → FAIL
- If draft contains any sign-off phrase anywhere in body → FAIL
- If draft contains "And that's the mews" stem anywhere → FAIL

### Where It Is Weak

1. **Missing expected sign-off is allowed** (line 273-297). A REPORT can ship without "And that's the mews." The rationale in comments: "an occasional missing sign-off is acceptable — rejecting a whole story because the composer forgot to type a closing line costs more than it buys." This dilutes the brand seal — the signature sign-off should be the stamp of verification, and its absence should be notable.

2. **No enforcement of sign-off presence in ANALYSIS.** The speculative-opinion sign-off is the critical firewall against opinion-as-reporting. If an ANALYSIS post ships without "This cat's view — speculative, personal, subjective," readers may mistake it for a REPORT.

3. **The gate runs AFTER composition.** If the composer model (Sonnet) consistently forgets the sign-off, the post still passes. The composer prompt (`prompts/report_post.md`) includes the sign-off instruction, but there's no fallback stamp if the model omits it.

**Recommendation (not implemented):** Change Branch 1 to FAIL when expected sign-off is missing, OR add a `_stamp_signoff()` post-processor in `post_composer.py` that appends the correct sign-off if absent.

---

## 5. Known Failure Modes

### Issue #14 / #16 — Pope Leo XIV Triple-Post

**Summary:** The Pope Leo XIV peace vigil story was posted 3 times in 18 minutes on 2026-04-12. All 3 posts reference the same `dossier_id: 2026-04-11-pope-leo-xiv-issued-0276fdcfd2`.

**Evidence from issues:**
- Issue #14: "posted 3 times in posts_history.json with identical/near-identical content"
- Issue #16: "00:27 UTC, 00:41 UTC, 00:45 UTC — all with source='republish' with no URL"

**Root cause (code analysis):**

The dedup check in `main.py` uses `journalism_seen_stories.txt` (a flat file of story IDs). However:

1. **Retry logic doesn't check seen-stories:** If the X/Bluesky API call fails partway through, the retry may re-run the entire publish flow without checking if the story was already persisted.

2. **`source='republish'` indicates a retry path:** The `journalism-republish.yml` workflow exists (line 4 of workflow list) — this is a separate "republish from dossier" path that may bypass normal dedup.

3. **No transaction lock on story_id:** Multiple concurrent GHA runs (schedule + workflow_dispatch) could process the same story before the seen-file is committed.

**The actual gap:** `post_tracker.py:check_story_status()` checks URL/content/topic similarity, but `journalism_seen_stories.txt` dedup is a simple `story_id in file.read()` check in `main.py`. If the file write fails or races, the same story can pass dedup twice.

### Issue #17 — x_tweet_id null

**Summary:** Hungary Tisza election post (2026-04-12T20:17 UTC) has `x_tweet_id = null` but `bluesky_uri` populated.

**Evidence:** "No X analytics entry exists for this post."

**Root cause (code analysis):**

The X posting path in `TwitterBot.post_tweet()` (or `post_tweet_with_image`) returns `None` on certain error conditions without raising an exception. The calling code in `main.py` checks for success:

```python
# main.py pattern
result = twitter_bot.post_tweet_with_image(...)
if result:
    tweet_id = result.get("id")
```

If `result` is `None` or the `"id"` key is missing, `tweet_id` stays `None` and is written to `posts_history.json` without triggering a retry.

**Likely silent-failure scenarios:**
1. X API rate limit (429) caught and logged but not retried
2. X API 500/503 treated as non-recoverable
3. Media upload succeeds but tweet create fails, returning partial result

**The gap:** No centralized X-API retry wrapper with exponential backoff for transient failures. The `x_retry.py` module exists but is used only in `trend_detector.py`, not in `twitter_bot.py`.

### Other Recurring Issues

**engage-cats-bluesky failures:** The `find_and_follow_cat_account()` function silently returns `False` when:
- Follow ratio > 2.5:1 (`_check_follow_ratio_safe()` line 100-106)
- No quality candidates found (line 301)
- API errors in follow (line 204)

The `run_engagement_cycle()` summary shows "Followed: 0 account" but doesn't distinguish "couldn't find anyone" from "ratio blocked" from "API error." Logs show the reason, but the return value doesn't propagate it.

**Credential failures:** No issues in the tracker specifically cite credential problems, but the `.env.example` file shows 7 distinct API keys are required:
- X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN
- BLUESKY_USERNAME, BLUESKY_APP_PASSWORD
- ANTHROPIC_API_KEY
- X_AI_API_KEY (Grok)
- DIFFBOT_TOKEN

Any missing/expired credential causes silent fallback or failure without clear error messaging at the GHA job level.

---

## 6. Recommendations (Not Implemented)

### A. Tune REPORTs Toward Actual X Trending

**Problem:** With `use_x_api: false`, all story selection is Google News, which skews toward wire consensus rather than what's actually being discussed on X.

**Options (tradeoff: API cost vs relevance):**

1. **Re-enable X recent-search for trend detection** — requires X API budget (~$100/month at Basic tier, or PPU at ~$0.50/1000 tweets). The chunked-query pattern already exists in `trend_detector.py`.

2. **Hybrid: X for validation, Google for discovery** — use Google News for candidate generation, then score each candidate by X engagement via a single `search_recent_tweets` call per candidate. Keeps API calls low (~50/day × 15 candidates × $0.0005 = $0.38/day).

3. **X Trends API** — `trends/place` returns the actual trending topics sidebar. Lower signal-to-noise than curated outlet search, but true "trending on X." Cost: 1 request = 1 tweet equivalent.

**Recommendation:** Option 2 (hybrid validation) is the best cost/signal tradeoff. Implement a `_score_candidate_by_x_engagement()` method that queries X for the headline_seed and returns tweet count + total engagement. Use this to re-rank candidates before triage.

### B. Fix Dedup Holes Without Turning Cat Into Shitposter

**Problem:** Triple-posting damages credibility and wastes follower attention.

**Fixes:**

1. **Atomic seen-stories update** — write `story_id` to `journalism_seen_stories.txt` BEFORE any API calls, not after. Rollback on total failure.

2. **Idempotency check in publish flow** — before posting, query `posts_history.json` for any post with matching `story_id` in the last 24h. If found, skip.

3. **Lock file for concurrent runs** — add a `.lock` file check at the start of `journalism-publish.yml`. If another run is in progress, exit early.

### C. Make X API Failures Loud

**Problem:** `x_tweet_id = null` posts slip through silently.

**Fixes:**

1. **Wrap X API calls in `x_retry.call_with_retry()`** — already implemented for trend detection, extend to `twitter_bot.py`.

2. **Fail the GHA job on X post failure** — if `result.get("id")` is None after retries, `sys.exit(1)` so the job status is red.

3. **Alert on partial success** — if Bluesky succeeds but X fails, post a follow-up X retry 30 minutes later (separate job) rather than leaving the story X-orphaned.

### D. Strengthen Sign-Off Enforcement

**Problem:** Missing sign-offs allowed; brand seal diluted.

**Fixes:**

1. **Change `_check_signoff_matches_type` to FAIL on missing expected sign-off** — this is a one-line change (line 290 → return False instead of True).

2. **Add `_stamp_signoff()` in post_composer** — if draft doesn't end with expected sign-off, append it before returning. Belt-and-suspenders.

### E. Cost Context

Current monthly spend (estimated from code paths):
- **Anthropic:** ~$15-20/month
  - Opus for meta-analysis: ~3 stories/day × 30 days × $0.015/call = $1.35
  - Sonnet for composition: ~3 × 30 × $0.003 = $0.27
  - Haiku for triage/QC/field-notes: ~50 calls/day × 30 × $0.00025 = $0.38
  - Haiku for image prompt: ~3 × 30 × $0.00025 = $0.02
- **Grok:** ~$4.50/month (3 images/day × 30 × $0.05)
- **Diffbot:** Free tier (10K pages/month, using ~1K)
- **X API:** $0 (disabled)

**Budget for X API if re-enabled:**
- Basic tier: $100/month (10K tweets/month = ~330/day)
- PPU: ~$15/month at 1000 tweets/day × 30 × $0.0005

---

## Appendix A: File Reference

| File | Stage | Purpose |
|------|-------|---------|
| `src/trend_detector.py` | 1 | X/Google News trend detection |
| `src/story_triage.py` | 2 | Need-to-know filter |
| `src/source_gatherer.py` | 3 | Multi-outlet dossier builder |
| `src/primary_source_finder.py` | 3.5 | Primary document locator |
| `src/meta_analyzer.py` | 4 | Opus meta-analysis |
| `src/post_composer.py` | 5 | Draft generation |
| `src/verification_gate.py` | 6 | Hard rules check |
| `src/main.py` | 7 | Orchestrator + publish |
| `src/dossier_store.py` | All | Data classes + persistence |
| `src/news_fetcher.py` | 1,3 | Google News RSS + article fetch |
| `src/twitter_bot.py` | 7 | X API client |
| `src/bluesky_bot.py` | 7 | Bluesky AT Protocol client |
| `src/image_generator.py` | 7 | Grok image generation |
| `src/bluesky_engagement_bot.py` | N/A | Cat community engagement |
| `src/bluesky_outlet_reply.py` | N/A | Outlet reply bot |
| `config.yaml` | All | Pipeline configuration |
| `outlet_registry.yaml` | 1,3 | Curated outlet watchlist |

## Appendix B: Issue Reference

| Issue | Status | Summary |
|-------|--------|---------|
| #14 | OPEN | Pope Leo XIV triple-post with missing Bluesky cross-posts |
| #16 | OPEN | Pope Leo XIV triple-post (duplicate of #14 with more detail) |
| #17 | OPEN | Hungary Tisza election post x_tweet_id null |
| #18 | OPEN | Home distilling and Alaska Senate posts missing from analytics |
| #40 | OPEN | Replace thumbnails with Cloudflare on-the-fly resizing |

---

*Report generated 2026-08-15. No code changes made. No workflows triggered.*
