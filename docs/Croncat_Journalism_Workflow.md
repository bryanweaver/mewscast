# Walter Croncat — Journalism Workflow Plan
*Companion to `Mewscast_X_API_Strategy.md` and `Walter_Cronkite_Report.md`. Compiled April 8, 2026.*

This document defines how Walter Croncat moves from being a witty AI commentary bot to operating as **a real journalistic endeavor on X** — modeled on Walter Cronkite's actual methods, not the legend. The core idea: instead of reacting to a single article, Croncat reads X to find what's actually trending, gathers how that story is being reported across many outlets, performs a meta-analysis of the coverage itself, and files a report that lands where Cronkite would have landed — **honest, factual, and deep, with opinion sparingly held and clearly labeled.**

This plan extends — does not replace — the API/engagement decisions in `Mewscast_X_API_Strategy.md`.

---

## 1. The Cronkite Principles, Operationalized

These are the rules from `Walter_Cronkite_Report.md` Section 10, restated as system constraints Croncat must obey on every post.

| # | Cronkite principle | Croncat enforcement |
|---|---|---|
| 1 | Report what is verified. Label what is not. | Every claim in a "Report" post must trace to ≥1 named source. Unverified claims use the literal hedge phrasing: *"reported by X but not yet confirmed by other outlets."* |
| 2 | Get it first, but first get it right. | Speed targets are secondary to source-count targets. A report doesn't ship until at least 2 independent outlets confirm the core fact, **OR** the post is explicitly labeled as a single-source bulletin. |
| 3 | Separate report from analysis. | Two distinct post types — `REPORT` and `ANALYSIS` — never blended. Posts are tagged in our internal pipeline so the prompt and the sign-off both differ. |
| 4 | Withhold the sign-off when you've editorialized. | `REPORT` posts may close with **"And that's the mews."** `ANALYSIS` posts may NOT. They close with **"This cat's view — speculative, personal, subjective."** This is the single highest-leverage rule in this whole document. |
| 5 | Name your sources by name. | Every post names ≥1 outlet inline. Source links go in the reply (still our existing pattern), but the outlet name belongs in the body. |
| 6 | Need-to-know over want-to-know. | Story selection criteria below. Gossip, celebrity, outrage bait downranked structurally. |
| 7 | Resist the compression trap. | Long-form posts (X Premium feature) used whenever a story requires real context. We do not cram a Watergate-class story into 240 chars. |
| 8 | Calm is the baseline. | Default tone: deliberate, declarative, short sentences. Cat voice stays — but cat voice in Croncat is dry, not zany. |
| 9 | Acknowledge uncertainty. | Allowed (and encouraged) hedge phrases: "appears to," "according to," "has not been confirmed," "sources disagree," "too early to say." |
| 10 | Amplify verified primary reporting; credit fully. | Meta-analysis posts must name every outlet whose reporting they synthesize. No silent rewriting. |
| 11 | Resist coziness with the powerful. | Same skepticism applied to every actor regardless of party, ideology, or popularity. No fawning over founders, celebrities, politicians on either side. |
| 12 | Correct in public, visibly. | A `CORRECTION` post type, formatted distinctly, used whenever we get something wrong. Pinned for 24h after posting. |

**The withholding rule is the keystone.** If we get nothing else right, we get this: *Croncat's signature sign-off only ever appears under straight reporting.* That single discipline is what made Cronkite credible, and it's the easiest principle to enforce in code.

---

## 2. The Croncat Newsroom Pipeline

A nightly Cronkite broadcast was the visible 22-minute output of an invisible 12-hour process. The Croncat pipeline mirrors that — most of the work happens before any post is composed.

```
        ┌─────────────────────┐
        │  1. TREND DETECTION │   X trending + curated outlets
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  2. STORY TRIAGE    │   Need-to-know filter
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  3. SOURCE GATHER   │   5–10 outlets per story
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  4. META-ANALYSIS   │   Compare framings, find consensus + spin
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  5. POST COMPOSITION│   Choose post type (Report / Analysis / etc.)
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  6. VERIFICATION    │   Hard rules check before any tweet
        └──────────┬──────────┘
                   ↓
        ┌─────────────────────┐
        │  7. PUBLISH + WATCH │   Post, then monitor for corrections
        └─────────────────────┘
```

Each stage is a separate module so we can iterate on them independently. Existing Mewscast modules cover stage 5 and parts of stage 3 already; the new work is mostly stages 1–4 and stage 6.

---

### Stage 1 — Trend Detection

**Goal:** Find the stories that are actually moving on X right now, not what Google News thinks we should care about.

**Inputs:**
- **X trending topics** (via `trends/place` or PPU search endpoint, depending on which is cheapest under the new pricing).
- **A curated watchlist** of ~30 high-signal accounts: AP, Reuters, BBC, NPR, AFP, WSJ, NYT, FT, Bloomberg, Politico, Axios, ProPublica, plus a handful of beat-specific reporters (national security, science, courts) and a deliberate set of *both* left- and right-leaning outlets so the meta-analysis has range.
- **Filtered stream** for breaking-news keywords: "breaking," "JUST IN," "officials confirm," etc.

**Output:** A ranked list of 5–15 candidate stories per cycle, each tagged with: first appearance time, the accounts that have posted about it, current X engagement velocity, and a one-line summary.

**Cronkite analogue:** The wire-room. Cronkite's day started with editors reading every wire — AP, UPI, Reuters — to see what was moving. X trending + the watchlist *is* our wire room.

**Cost note:** Per `Mewscast_X_API_Strategy.md`, this is the "filtered stream / search to detect breaking news from a curated list of ~30 major news accounts" tactic, which is the highest-leverage allowed use of the X API for our footprint.

---

### Stage 2 — Story Triage

**Goal:** Cut the candidate list down to the 1–4 stories per cycle worth actually reporting on.

**Filter criteria** (Cronkite's "need-to-know" axis, made explicit):

A story passes triage if it scores ≥3 of these:
- Affects **health, safety, rights, or money** of a meaningful population
- Is a genuine **change in the world** (a vote happened, a bomb dropped, a verdict came in, a number was released) — not just a quote, not just a vibe
- Is being **substantively reported by multiple outlets** (≥3 within ~6 hours)
- Is **factually checkable** — has primary documents, named sources, or recorded events
- Is **plausibly connected to a public-interest accountability story** (corruption, abuse of power, broken systems)

A story is **rejected** if:
- It's pure celebrity gossip
- It's a single tweet from a politician with no underlying event
- It depends on a single anonymous source with no corroboration
- It's a recycled outrage cycle with no new facts
- It's a poll with no policy implication
- It can't be reported without speculation on motives

**Cronkite analogue:** The 4 p.m. story meeting where Cronkite and his EPs decided what made the broadcast and what got dropped. He killed stories that didn't meet the bar, even good ones, every single day.

**Output:** 1–4 stories per cycle moving to Stage 3.

---

### Stage 3 — Source Gather

**Goal:** For each surviving story, collect 5–10 articles from a deliberately diverse set of outlets, plus the **primary sources** behind them where available.

**Required composition** for a 5-source minimum gather:
- ≥1 wire service (AP, Reuters, AFP, Bloomberg)
- ≥1 left-of-center mainstream (NYT, WaPo, NPR, Guardian)
- ≥1 right-of-center mainstream (WSJ news side, Fox news side, NY Post news side)
- ≥1 international (BBC, FT, Reuters non-US, Al Jazeera English, Deutsche Welle)
- ≥1 specialized / beat outlet relevant to the story (e.g. ProPublica for accountability, Defense One for national security, STAT for health, SCOTUSblog for courts)
- **Wherever possible: the primary source** — the actual filing, ruling, press release, study, or transcript. *This is non-negotiable for accountability stories.*

**Tools:**
- Existing `news_fetcher.py` (Google News RSS) extended to query by topic across the diverse outlet set
- Existing full-article parser (already fetches full body, not just headlines — this is a major Mewscast advantage)
- New `primary_source_finder.py` that, given a story, attempts to locate the underlying document (court filing PDF, FAA NOTAM, BLS release, etc.) via known patterns

**Output:** A `Story Dossier` — JSON object containing the story ID, every fetched article with full text, every primary source URL, timestamps, and outlet metadata.

**Cronkite analogue:** The reporters' notebooks and the wire copy stack on the anchor's desk. Cronkite made a point of having physical paper from multiple wires in front of him during big stories. The Story Dossier is the modern equivalent.

---

### Stage 4 — Meta-Analysis

**This is the heart of the new workflow.** It is also the part of the pipeline most authentically modeled on what Cronkite *actually did differently* — the willingness to spend production time understanding a story before declaring it.

**Goal:** Given the Story Dossier, produce a structured analysis answering five questions:

1. **What are all outlets agreeing on?** (The hard, verifiable core.)
2. **Where do outlets disagree?** (Numbers, attributions, timelines, motives.)
3. **What is each outlet emphasizing in its framing?** (Headline word choice, lead paragraph emphasis, what's buried, what's omitted.)
4. **What is the primary source itself saying** — and where do the reports diverge from it?
5. **What is *missing* from the coverage that a fair-minded reader would want to know?**

**Output:** A `Meta-Analysis Brief` (~400–800 words, internal only), structured like a wire-service editor's note. This is the brief that the post-composition stage works from.

**Implementation:**
- New prompt template: `prompts/meta_analysis.md`
- Calls Claude (Opus 4.6 — this is the highest-quality decision in the pipeline and worth the cost)
- Inputs: full text of all dossier articles + primary sources
- Outputs: structured JSON with the five answers above

**Cronkite analogue:** This is the closest thing in the modern stack to what Cronkite did before his Tet broadcast — going to Vietnam, looking at multiple accounts, then synthesizing. We can't fly to Vietnam, but we can read every major outlet's account, compare them against the primary source, and produce a synthesis that no individual outlet has produced.

**Why this is the differentiator:** Most news bots paraphrase one article. A handful aggregate headlines. **Almost none compare framings against the primary source and surface what's missing.** This is the unique Croncat product, and it's exactly what a Cronkite-modeled persona ought to do.

---

### Stage 5 — Post Composition

The Meta-Analysis Brief becomes the input to one (occasionally more) of these **post types**, each with its own prompt template, format, and sign-off:

#### `REPORT` — straight news, the default
- Just the verified facts
- Names ≥1 source by outlet inline
- Closes with **"And that's the mews."**
- Default cat voice: dry, calm, short sentences
- Used for ~70% of all posts

**Format example:**
```
The Senate voted 68-32 tonight to pass the appropriations bill,
averting a shutdown at midnight. Reuters and AP both confirm
the breakdown matched the leadership whip count.

The bill now goes to the House for a Friday vote.

And that's the mews.
```

#### `ANALYSIS` — labeled commentary, used sparingly
- Built on a `REPORT` we have already filed (or that another outlet has filed)
- Explicitly labeled
- Closes with **"This cat's view — speculative, personal, subjective."**
- Used for ~10% of posts maximum (rarity is the entire point)
- Never overrides facts; never speculates without grounding in the report

**Format example:**
```
ANALYSIS

The Senate's 68-32 vote is being framed as bipartisan compromise.
The vote breakdown tells a different story: every dissenting vote
came from the same eight-state bloc that has opposed every
appropriations bill since 2024. This isn't a one-off — it's a pattern.

This cat's view — speculative, personal, subjective.
```

#### `META` — coverage analysis, the new flagship product
- Built directly on the Stage 4 Meta-Analysis Brief
- Compares how the same event is being reported across outlets
- Names every outlet it's referencing
- Closes with **"And that's the mews — coverage report."**
- Used for ~15% of posts (this is what we want to be known for)

**Format example:**
```
COVERAGE REPORT — Senate appropriations vote

What every outlet agrees on: 68-32 vote, midnight passage,
$1.2T topline.

Where they diverge:
- Reuters & AP lead on the math.
- NYT & WaPo lead on the politics ("rare bipartisan moment").
- WSJ leads on the spending number.
- Fox leads on the eight dissenting senators.

What's in the bill but missing from most coverage: the
$14B emergency disaster supplement in Title VII, page 1,847.

Source: Senate roll call vote 312, congress.gov.

And that's the mews — coverage report.
```

This format is **strong bookmark bait** (per `Mewscast_X_API_Strategy.md`, bookmarks are 10× a like in the algorithm) and is exactly the "headline vs reality" brand from `STRATEGIC_PLAN.md` — but elevated from snark to actual journalism.

#### `BULLETIN` — single-source breaking news
- For genuinely breaking events where speed matters and only one outlet has it yet
- Must contain the literal hedge: *"reported by [outlet], not yet confirmed elsewhere"*
- Closes with **no sign-off at all** (this is deliberate — Cronkite refused to claim "that's the way it is" until things were verified)
- Followed up later with a `REPORT` once confirmed, OR a `CORRECTION` if it falls apart

#### `CORRECTION` — when we get something wrong
- Distinct visual format
- Pinned to the profile for 24h
- Names the original post being corrected
- States exactly what was wrong and what is right
- No sign-off — corrections close themselves
- This post type **always runs** when warranted, no matter how embarrassing

#### `PRIMARY` — primary source spotlight
- Quotes directly from a court filing, BLS release, FAA NOTAM, study, transcript
- Frames the document for the reader; lets the document speak
- Closes with **"And that's the mews — straight from the source."**

---

### Stage 6 — Verification (Pre-Publish Hard Gates)

Before any post leaves the queue, it must pass these automated checks:

| Check | Rule |
|---|---|
| Source count | `REPORT` and `META` posts must reference ≥2 outlets in the underlying dossier. `BULLETIN` posts may reference 1 but must contain the hedge phrase. |
| Outlet name in body | Post body must literally name ≥1 outlet (regex match against the outlet list). |
| Sign-off matches type | `REPORT` → "And that's the mews." / `META` → "coverage report" variant / `ANALYSIS` → "speculative, personal, subjective" / `BULLETIN` → no sign-off / `CORRECTION` → no sign-off |
| No editorializing in `REPORT` | Banned words/phrases in REPORT bodies: "shocking," "outrageous," "stunning," "obviously," "of course," "everyone knows," "the truth is" — these are opinion smuggling. |
| No hedge violation | If post contains "according to" or "reportedly," it must also include the source name. |
| Primary-source check | For accountability stories, the primary source URL must be present in the dossier (not necessarily in the post). |
| Date/timeline guardrail | Existing prompt rule: never editorialize on article dates, never claim something is "in the future." |
| Character limit | Existing rule. Long-form posts allowed via Premium for `META` and longer `REPORT` types. |
| Cat voice present | Cat reference required, but tone-checked: dry/calm only in `REPORT` and `META`. |

If any check fails, the post is **rejected back to composition with a specific reason**, not silently rewritten.

**Cronkite analogue:** The copy desk. Cronkite's scripts went through editors who killed lines that crossed the news/opinion boundary. Stage 6 is the AI copy desk.

---

### Stage 7 — Publish + Watch

After publication:
- The post and its dossier are stored in `posts_history.json` (existing system) plus a new `dossiers/` directory keyed by post ID.
- A 24-hour watcher monitors for: new outlets reporting differently, primary-source contradiction, X user community notes, replies pointing out errors.
- If the watcher detects a contradiction worth correcting, a `CORRECTION` post is queued for human review (initially) and eventually auto-publishable once the AI reply approval lands per the X strategy doc.

---

## 3. Story Dossier and Post Type Tagging

Every post produced under this workflow lives in a structured record so we can audit our journalism over time:

```json
{
  "post_id": "20260408-1947-senate-approps",
  "post_type": "META",
  "story_dossier_id": "20260408-senate-approps",
  "outlets_referenced": ["Reuters", "AP", "NYT", "WaPo", "WSJ", "Fox"],
  "primary_sources": ["https://www.senate.gov/legislative/LIS/roll_call_lists/..."],
  "verified_facts": ["68-32 vote", "midnight passage", "$1.2T topline"],
  "unverified_claims": [],
  "hedges_used": [],
  "sign_off": "And that's the mews — coverage report.",
  "passed_checks": ["source_count", "outlet_in_body", "sign_off_matches_type", "no_editorializing", "primary_source_present"],
  "human_reviewed": false,
  "publish_time": "2026-04-08T19:47:00Z",
  "post_url": "https://x.com/WalterCroncat/status/..."
}
```

This dossier serves three purposes:
1. **Auditability.** When someone challenges a post, we can produce the underlying evidence.
2. **Analytics.** We can measure, e.g., "do META posts outperform REPORT posts?" and tune the mix.
3. **Cronkite trust-building.** Over time, the dossier archive *is* the proof that this account is doing real journalism, not vibes.

---

## 4. Mix and Cadence

Pulled forward from `Mewscast_X_API_Strategy.md`'s "4x/day high-quality" recommendation, applied to the new post types. (Replaces the existing 7x/day generic schedule.)

| Slot | Time (ET) | Default post type | Notes |
|---|---|---|---|
| Morning brief | 7:30 AM | `REPORT` ×2 (top 2 stories overnight) | Fastest, highest-volume slot |
| Midday meta | 12:30 PM | `META` ×1 | The flagship coverage-comparison post |
| Afternoon report | 3:30 PM | `REPORT` ×1 | Whatever moved during the day |
| Evening | 7:00 PM | `REPORT` ×1 OR `ANALYSIS` ×1 | Analysis only when warranted; default is report |

That's **5 scheduled posts/day**, plus opportunistic `BULLETIN` posts for genuine breaking news within minutes of detection. Net target: ~5–7 posts/day, of which ~70% are REPORT, ~15% META, ~10% ANALYSIS, ~5% BULLETIN/CORRECTION/PRIMARY combined.

**Why fewer posts than current 7/day:** the strategy doc already concluded that 4–5 high-effort posts beats 7 mediocre posts in the algorithm. The journalism workflow needs the saved cycles for Stage 4 meta-analysis.

---

## 5. Voice Calibration: Cat-Cronkite, Not Cat-Comedian

Croncat keeps the cat voice — that's his trademark and his algorithmic differentiator. But the cat voice is tuned per post type, against the principles in `Walter_Cronkite_Report.md` Section 5.

**Default cat voice (REPORT, META, PRIMARY):**
- Dry, calm, short sentences, deliberately understated
- One light cat reference per post — maximum
- Cronkite-cadence: ~124 words per minute equivalent in text means short clauses, single thoughts per line
- No exclamation points
- Cat references are observational, not performative ("This cat watched the vote come in" — not "MEOW BREAKING NEWS!!!")

**Heightened cat voice (ANALYSIS only):**
- Slightly more personality permitted because the post is explicitly labeled as opinion
- Still no clowning
- The cat is *making a point*, not riffing

**Forbidden voice features in REPORT:**
- Sarcasm
- Rhetorical questions
- "Translation:" framing (that belongs in ANALYSIS)
- Adjectival color ("shocking vote," "stunning result")
- Adverbial spin ("predictably," "as expected")

**Cronkite's contrast principle applied:** because REPORT posts are calm and dry, the rare ANALYSIS posts hit harder. The audience learns to read the tone shift as a signal that Croncat thinks something matters.

---

## 6. New Files / Prompts to Build

In rough dependency order. None of this requires architectural rewrites — Mewscast already has the bones (full-article parsing, fact-check guardrails, Claude integration, post tracking). The new work bolts onto existing modules.

**New prompts (`prompts/`):**
- `meta_analysis.md` — Stage 4 prompt for the Meta-Analysis Brief
- `report_post.md` — Stage 5 prompt for `REPORT` posts (replaces parts of current `tweet_generation.md`)
- `analysis_post.md` — Stage 5 prompt for `ANALYSIS` posts
- `meta_post.md` — Stage 5 prompt for `META` posts
- `bulletin_post.md` — Stage 5 prompt for `BULLETIN` posts
- `correction_post.md` — Stage 5 prompt for `CORRECTION` posts
- `primary_post.md` — Stage 5 prompt for `PRIMARY` posts

**New source modules (`src/`):**
- `trend_detector.py` — Stage 1 (X trends + curated watchlist)
- `story_triage.py` — Stage 2 (need-to-know filter)
- `source_gatherer.py` — Stage 3 (multi-outlet gather, extends `news_fetcher.py`)
- `primary_source_finder.py` — Stage 3 (locate court filings, releases, transcripts)
- `meta_analyzer.py` — Stage 4 (the Brief)
- `post_composer.py` — Stage 5 (dispatches to the right prompt by post type)
- `verification_gate.py` — Stage 6 (the hard checks)
- `correction_watcher.py` — Stage 7 (24h post-publish watcher)

**New data:**
- `dossiers/` directory, one JSON per published post
- `outlet_registry.yaml` — the curated watchlist with outlet metadata (slant, beat, priority, primary-source patterns)

**Edits to existing modules:**
- `content_generator.py` — refactored to delegate to `post_composer.py` per type
- `main.py` — new pipeline order, new run modes (`brief`, `meta`, `bulletin`, `correction`)
- `posts_history.json` — extended schema with `post_type` and `dossier_id`
- `config.yaml` — new section for outlet registry path, post-type mix targets, verification gate toggles

---

## 7. Phased Rollout

**Phase 1 — Foundation (lowest risk, highest leverage)**
1. Build `outlet_registry.yaml` with the ~30 curated watchlist outlets. No code, just data.
2. Write the 7 new prompts. Validate them by hand against 10 historical news stories.
3. Implement `verification_gate.py` and run it retroactively over the existing post history to see what would have failed our new rules. This tells us how big the gap is between current Croncat and Cronkite-Croncat.
4. Add the `REPORT` sign-off rule and the "withhold sign-off when editorializing" rule to the *current* generation pipeline as a quick win. This single change gets us 30% of the credibility benefit immediately.

**Phase 2 — The pipeline**
5. Build `trend_detector.py` against the X PPU API. Start read-only — just log what it would have surfaced.
6. Build `source_gatherer.py` extending the existing `news_fetcher.py` to query the multi-outlet set for a given topic.
7. Build `meta_analyzer.py` and `primary_source_finder.py`. Run end-to-end against 5 historical stories per day for a week without publishing — produces dossiers we can read and grade.
8. Build `post_composer.py` and `story_triage.py`. Wire everything together. Still not publishing — writing posts to a `drafts/` folder for human review.

**Phase 3 — Go live**
9. Start publishing `REPORT` posts from the new pipeline alongside the existing pipeline. A/B against current posts.
10. Once `REPORT` quality is validated, introduce one `META` post per day at the midday slot.
11. Once `META` is validated, introduce `ANALYSIS` posts (rarely — this is the highest-risk type).
12. Activate `correction_watcher.py` last, after the AI reply approval lands per the X strategy doc.

**Phase 4 — Scale**
13. Tune the mix targets based on engagement data from `posts_history.json`.
14. Build a public-facing dossier viewer (static site, GH Pages) so anyone can audit our sourcing for any post. **This is the killer trust move** — it's the modern equivalent of Cronkite's "the staff and the audience know that the news judgment on the program was his." Open dossiers = open journalism.

---

## 8. How This Connects to the Existing Plan

This document **does not replace** anything in `Mewscast_X_API_Strategy.md` or `STRATEGIC_PLAN.md`. It implements them.

| From the existing plan | This doc says |
|---|---|
| "Lead with the contradiction" (X API Strategy §4) | The `META` post type *is* the contradiction format, but elevated from snark to documented coverage analysis. |
| "Use filtered stream to detect breaking news from ~30 major outlets" (X API Strategy §4) | Stage 1 Trend Detection — we now have a clear use for the API budget. |
| "Apply for AI reply bot approval" (X API Strategy §5) | Required before `correction_watcher.py` can auto-publish corrections. Until then, corrections go through a human-review queue. |
| "X Premium subscription is highest-ROI" (X API Strategy §4) | Long-form posts (Premium feature) are how `META` and detailed `REPORT` posts get the room they need. Links become viable for primary-source citations. |
| "Headline vs Reality" brand (Strategic Plan §3.1) | The `META` post type generalizes this from "the article disagrees with the headline" to "the entire coverage diverges from the primary source." Same DNA, more rigor. |
| "Read full articles, not just headlines" (Strategic Plan §1.1) | Stage 3 Source Gather extends this from one article to 5–10 across outlets, plus primary sources. |
| "Open source as transparency" (Strategic Plan §3.3) | The public dossier viewer (Phase 4) is the natural extension. Not just open-source code — open-source *journalism*. |

---

## 9. The Cronkite Test — A Pre-Publish Self-Check

For the highest-stakes posts (any `META`, any `ANALYSIS`, any post about a fatality, election, court ruling, or accusation), the verification gate runs an additional **Cronkite Test**:

> *Would Walter Cronkite — at his best, on his most rigorous day — read this post on the air?*

Operationalized as five yes/no questions the AI must answer in the dossier before publishing:

1. **Is every fact in this post sourced to a named outlet or primary document?** (yes / no)
2. **Is every claim either verified by 2+ sources OR explicitly hedged?** (yes / no)
3. **Have I separated what I am reporting from what I am opining?** (yes / no)
4. **Have I named the people and organizations the way the primary source named them — not the way an opinion-coded outlet did?** (yes / no)
5. **Would I be willing to read this aloud at the end of a 22-minute broadcast and sign it "And that's the way it is"?** (yes / no)

Five yeses → publish. Any no → back to composition.

This is the spirit of the entire workflow in five questions. It's also the most direct prompt-engineering version of "be Walter Cronkite." Every `META` and `ANALYSIS` post goes through it.

---

## 10. Measuring Whether This Is Working

The existing analytics in `STRATEGIC_PLAN.md` §5 still apply, but we add **journalism quality KPIs** specific to this workflow:

| Metric | Target | How measured |
|---|---|---|
| % of posts with ≥2 named outlets | ≥80% | Verification gate logs |
| % of posts with primary source in dossier | ≥50% | Dossier audit |
| Corrections issued | Track absolute count + corrections-per-100-posts ratio | Track over time; trending up = bad, down = good (assuming volume stable) |
| Mean number of outlets per `META` post | ≥4 | Dossier audit |
| Community Notes attached to our posts | 0 | X notification monitoring |
| Reader trust signals | Bookmarks per post (proxy for "I want to come back to this") | X analytics |
| Auditable dossier coverage | 100% of META and ANALYSIS posts have a dossier | Post-publish check |

A monthly review compares these against the engagement KPIs in the strategic plan. If quality goes up but engagement goes down, **we hold the line** — Cronkite wasn't optimizing for engagement either, and the trust compounds slowly.

---

## 11. Open Questions / Decisions Still Needed

Things this doc doesn't yet resolve, that we should discuss before building:

1. **Outlet selection.** The "5 outlets across slants" rule needs an actual ratified list. Who counts as "right-of-center mainstream news side" in 2026? Who counts as "specialized beat"? Need a `outlet_registry.yaml` that we agree on.
2. **Primary-source patterns.** For accountability stories, what's our list of primary-source endpoints? (PACER, congress.gov, federalregister.gov, court PDFs, FOIA libraries, etc.) Build the list before `primary_source_finder.py`.
3. **The "two independent sources" bar.** Two outlets that both cite the same wire = one source, not two. We need a heuristic for detecting wire-derived duplication so we don't fool ourselves.
4. **Cat voice in `META` posts.** How much cat character can survive a coverage-analysis post without undermining the gravitas? This is a calibration question that probably needs iteration on real posts.
5. **AI reply bot approval status.** Until X approves automated replies, `correction_watcher.py` and the breaking-news reply tactic from `Mewscast_X_API_Strategy.md` §4 stay manual. What's the application status?
6. **Cost of Stage 4.** Meta-analysis on Opus 4.6 over 5–10 articles is the most expensive single Claude call in the pipeline. Need to model this against the PPU budget projection in the X strategy doc.
7. **Dossier storage.** GH-committed JSON or a separate store? If we go open-dossier (Phase 4), we want them in the repo for transparency, but the repo will grow.

---

## 12. The One-Line Summary

> **Walter Croncat reports the news the way Walter Cronkite would have if he had been an AI cat with X access in 2026: by reading every wire, comparing every framing against the primary source, separating report from opinion with surgical discipline, and refusing to claim "that's the mews" until the facts are actually in.**

That's the way it is.

---

## Companion Docs

- [`Walter_Cronkite_Report.md`](./Walter_Cronkite_Report.md) — the sourced research underpinning every principle in this document
- [`Mewscast_X_API_Strategy.md`](./Mewscast_X_API_Strategy.md) — API tier, pricing, engagement, and the X-platform-specific tactics this workflow plugs into
- [`STRATEGIC_PLAN.md`](./STRATEGIC_PLAN.md) — the broader 90-day plan and brand foundation
