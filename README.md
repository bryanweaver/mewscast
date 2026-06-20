# Mewscast / Walter Croncat

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

AI journalism bot (as a cat) that posts to X/Twitter and Bluesky. Fetches real news, generates commentary with full article context, and posts automatically with source citations. The core pipeline is modeled on Walter Cronkite's journalism methods — multi-outlet sourcing, strict report/opinion separation, and a mechanical sign-off rule enforced in code.

## Table of Contents

- [Quick Start](#quick-start)
- [Walter Croncat Journalism Pipeline](#walter-croncat-journalism-pipeline)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Quick Start

### Prerequisites

- Python 3.11+
- X/Twitter Developer Account
- Bluesky Account (with app password)
- Anthropic API key
- X AI API key (for Grok image generation)

### Local Setup

```bash
git clone https://github.com/YOUR_USERNAME/mewscast.git
cd mewscast
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API credentials
```

### Run Locally

```bash
# Legacy scheduled post
python src/main.py scheduled

# Journalism pipeline (one cycle)
python src/main.py journalism

# Journalism dry-run (writes draft to drafts/, no publish)
python src/main.py journalism --dry-run
```

### Deploy to GitHub Actions

1. Push to GitHub
2. Add secrets under repo Settings → Secrets and variables → Actions:

| Secret | Description |
|--------|-------------|
| `X_API_KEY` | X API key |
| `X_API_SECRET` | X API secret |
| `X_ACCESS_TOKEN` | X access token |
| `X_ACCESS_TOKEN_SECRET` | X access token secret |
| `X_BEARER_TOKEN` | X bearer token |
| `BLUESKY_USERNAME` | Bluesky handle (e.g. `yourname.bsky.social`) |
| `BLUESKY_PASSWORD` | Bluesky app password |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `X_AI_API_KEY` | X AI API key (Grok image generation) |

3. Go to Actions tab, enable workflows. `post-tweet.yml` runs on schedule automatically.

## Walter Croncat Journalism Pipeline

A 7-stage pipeline that replaces single-article summarization with real multi-outlet journalism.

### The 7 stages

| Stage | Module | Purpose |
|-------|--------|---------|
| 1 — Trend detection | `src/trend_detector.py` | X search over curated outlet watchlist, Google News fallback |
| 2 — Story triage | `src/story_triage.py` | Need-to-know heuristic filter |
| 3 — Source gather | `src/source_gatherer.py` + `src/primary_source_finder.py` | Slant-diverse multi-outlet fetch + primary source pattern matching |
| 4 — Meta-analysis | `src/meta_analyzer.py` | Claude Opus call → structured `MetaAnalysisBrief` |
| 5 — Post composition | `src/post_composer.py` | Dispatches to one of 6 post-type prompts |
| 6 — Verification gate | `src/verification_gate.py` | Hard rules enforcing journalism discipline |
| 7 — Publish / dry-run | `src/main.py::post_journalism_cycle` | Publish to X and Bluesky, or write draft to `drafts/` |

### The 6 post types

| Post type | Sign-off | Purpose |
|-----------|----------|---------|
| `REPORT` | `And that's the mews.` | Straight news — the default (~70% of posts) |
| `META` | `And that's the mews — coverage report.` | Coverage analysis across outlets; forceable via CLI, normalized from auto-suggested META to REPORT |
| `ANALYSIS` | `This cat's view — speculative, personal, subjective.` | Labeled opinion, used sparingly |
| `BULLETIN` | *(none)* | Single-source breaking news, must contain hedge phrase |
| `CORRECTION` | *(none)* | Self-correction, pinned after publishing |
| `PRIMARY` | `And that's the mews — straight from the source.` | Primary-document spotlight |

### The keystone rule

Walter Cronkite omitted "And that's the way it is" on nights he editorialized — the sign-off was the seal of a straight report. Walter Croncat enforces this mechanically in `src/verification_gate.py::_check_signoff_matches_type`: sign-off must match post type exactly, and BULLETIN/CORRECTION posts must not contain any sign-off phrase anywhere in the body.

### Master switch

```yaml
# config.yaml
pipelines:
  legacy:
    enabled: false   # legacy single-article pipeline
  journalism:
    enabled: true    # Walter Croncat journalism pipeline
```

`--dry-run` is always allowed regardless of the switch.

### CLI reference

```bash
# One journalism cycle (pipeline picks post type)
python src/main.py journalism

# Dry-run — writes draft to drafts/<story_id>_<post_type>.md
python src/main.py journalism --dry-run

# Force a specific post type
python src/main.py journalism brief [--dry-run]       # REPORT
python src/main.py journalism meta [--dry-run]        # META
python src/main.py journalism analysis [--dry-run]    # ANALYSIS
python src/main.py journalism bulletin [--dry-run]    # BULLETIN
python src/main.py journalism correction [--dry-run]  # CORRECTION
python src/main.py journalism primary [--dry-run]     # PRIMARY

# Force a specific topic (skips trend detection)
python src/main.py journalism --topic "US tariffs on China" --dry-run

# Republish a saved dry-run draft
python src/main.py republish <story_id>

# Offline smoke test (stubs X, Google News, and Claude calls)
python scripts/journalism_dry_run.py --mock
```

Rejected drafts (verification gate failures after one retry) land in `drafts/rejected/`.

### Story dossiers

Every pipeline run produces a `StoryDossier` + `MetaAnalysisBrief` written to `dossiers/<story_id>.json` (gitignored). Dossier HTML viewer pages are generated and committed to `docs/dossiers/` by the GHA workflow.

## Project Structure

```
mewscast/
├── .github/workflows/
│   ├── post-tweet.yml              # Legacy scheduled posts
│   ├── journalism-publish.yml      # Journalism pipeline (scheduled)
│   ├── journalism-dry-run.yml      # Dry-run (manual trigger)
│   ├── journalism-republish.yml    # Republish a saved draft
│   ├── post-correction.yml         # Manual correction post
│   ├── x-engage.yml                # X engagement automation
│   ├── bluesky-engage.yml          # Bluesky engagement automation
│   ├── engage-cats-bluesky.yml     # Cat community engagement (Bluesky)
│   ├── outlet-reply.yml            # X outlet reply bot
│   ├── bluesky-outlet-reply.yml    # Bluesky outlet reply bot
│   ├── check-mentions.yml          # X mention replies
│   ├── triage-review.yml           # Triage decision logging
│   ├── track-analytics.yml         # Engagement analytics
│   └── rebuild-history.yml         # Rebuild post history from X
├── src/
│   ├── main.py                     # Entry point (legacy + journalism modes)
│   ├── twitter_bot.py              # X/Twitter API integration
│   ├── bluesky_bot.py              # Bluesky API integration
│   ├── bluesky_client.py           # Low-level Bluesky client
│   ├── content_generator.py        # Legacy content generation
│   ├── image_generator.py          # AI image generation (Grok)
│   ├── image_qc.py                 # Image quality checks
│   ├── news_fetcher.py             # Google News RSS fetching
│   ├── post_tracker.py             # Deduplication & history
│   ├── prompt_loader.py            # Prompt template loader
│   ├── engagement_bot.py           # X engagement automation
│   ├── x_engagement_bot.py         # X engagement bot (newer)
│   ├── bluesky_engagement_bot.py   # Bluesky engagement bot
│   ├── outlet_reply_bot.py         # X outlet reply bot
│   ├── bluesky_outlet_reply.py     # Bluesky outlet reply bot
│   ├── x_retry.py                  # X API retry helpers
│   ├── positive_news_post.py       # Positive news posts (WIP)
│   ├── draft_analyzer.py           # Draft analysis helpers
│   ├── vocab_report.py             # Vocabulary reporting utility
│   │
│   ├── # Walter Croncat journalism pipeline (Stages 1–7)
│   ├── trend_detector.py           # Stage 1 — X search + watchlist
│   ├── story_triage.py             # Stage 2 — need-to-know filter
│   ├── source_gatherer.py          # Stage 3 — multi-outlet gather
│   ├── primary_source_finder.py    # Stage 3 — primary source pattern matcher
│   ├── meta_analyzer.py            # Stage 4 — Claude Opus meta-analysis
│   ├── post_composer.py            # Stage 5 — dispatcher across 6 post types
│   ├── verification_gate.py        # Stage 6 — hard rules incl. keystone sign-off rule
│   ├── dossier_store.py            # Data classes, SIGN_OFFS, JSON persistence
│   ├── dossier_renderer.py         # Renders dossier HTML viewer pages
│   └── field_notes.py              # Field-notes reply composer
├── prompts/                        # Claude prompt templates
│   ├── tweet_generation.md         # Legacy tweet prompt
│   ├── meta_analysis.md            # Stage 4 meta-analysis prompt
│   ├── report_post.md              # REPORT post type
│   ├── meta_post.md                # META post type
│   ├── analysis_post.md            # ANALYSIS post type
│   ├── bulletin_post.md            # BULLETIN post type
│   ├── correction_post.md          # CORRECTION post type
│   ├── primary_post.md             # PRIMARY post type
│   └── journalism_image.md         # Journalism image prompt
├── tests/                          # 864 tests across 21 test files
├── scripts/                        # Utility scripts
│   ├── journalism_dry_run.py       # End-to-end smoke test (--mock)
│   ├── rebuild_history.py          # Rebuild post history from X
│   ├── filter_history.py           # Clean up post history
│   ├── analytics.py                # Analytics collection
│   └── triage_review.py            # Triage review tooling
├── docs/                           # Documentation (see docs/README.md)
├── dossiers/                       # Story dossiers (gitignored)
├── drafts/                         # Dry-run drafts (gitignored)
├── outlet_registry.yaml            # 30-outlet curated watchlist
├── config.yaml                     # Bot configuration
├── posts_history.json              # Post deduplication history
├── requirements.txt
├── .env.example
└── LICENSE
```

## Configuration

Key sections in `config.yaml`:

```yaml
pipelines:
  legacy:
    enabled: false      # legacy single-article pipeline
  journalism:
    enabled: true       # Walter Croncat journalism pipeline

journalism:
  enabled: true
  meta_analyzer:
    model: claude-opus-4-8
  post_composer:
    model: claude-sonnet-4-6

content:
  model: "claude-sonnet-4-6"   # legacy pipeline model
```

Cost at 2x/day journalism posts: ~$13/month (Opus meta-analysis is the largest cost). See `docs/COST_ANALYSIS.md` for full breakdown.

## Testing

```bash
pip install pytest
pytest tests/
pytest tests/test_verification_gate.py -v
pytest tests/ --cov=src --cov-report=html
```

**864 tests across 21 files**, all green in a single `pytest tests/` run.

| Test file | Tests | Coverage area |
|-----------|-------|---------------|
| `test_bots.py` | 118 | Bluesky + X bot posting pipeline |
| `test_engagement.py` | 95 | Engagement bot behavior |
| `test_content_generator.py` | 95 | Legacy content generation |
| `test_outlet_reply.py` | 62 | X outlet reply bot |
| `test_x_engagement.py` | 61 | X engagement bot |
| `test_field_notes.py` | 49 | Field-notes reply composer |
| `test_source_gatherer.py` | 41 | Stage 3: slant-diverse fetch |
| `test_deduplication.py` | 70 | Post deduplication logic |
| `test_verification_gate.py` | 58 | Stage 6: keystone sign-off matrix + all hard rules |
| `test_post_composer.py` | 22 | Stage 5: per-type prompt dispatch |
| `test_dossier_renderer.py` | 22 | Dossier HTML renderer |
| `test_dossier_store.py` | 28 | Data classes + JSON persistence |
| `test_trend_detector.py` | 23 | Stage 1: watchlist query + clustering |
| `test_story_triage.py` | 25 | Stage 2: heuristic scoring |
| `test_primary_source_finder.py` | 18 | Stage 3: primary source pattern matching |
| `test_meta_analyzer.py` | 14 | Stage 4: prompt, JSON parsing, retry |
| `test_image_generator.py` | 16 | Image generation |
| `test_bluesky_outlet_reply.py` | 20 | Bluesky outlet reply bot |
| `test_dossier_reply_compose.py` | 12 | Dossier reply composition |
| `test_x_retry.py` | 9 | X API retry helpers |
| `test_image_qc.py` | 6 | Image quality checks |

**Test isolation note:** `conftest.py` eagerly pre-imports `bs4`, `bluesky_client`, `content_generator`, and `twitter_bot` before test collection. Module-level `sys.modules.setdefault(...)` stubs in individual test files are silently bypassed for those four names. Mock at the call site instead (e.g. `instance.attr = Mock()`).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Missing Twitter API credentials" | Check `.env` has all 5 X credentials; verify GitHub Secrets match |
| "Rate limit exceeded" | X free tier: ~1,500 posts/month (50/day). Wait for reset or reduce frequency |
| "Content generation failed" | Check Anthropic API key; verify credits at console.anthropic.com |
| GitHub Actions not running | Confirm workflows are enabled; check secrets are set |
| Both pipelines disabled error | Flip `pipelines.legacy.enabled` or `pipelines.journalism.enabled` to `true` in `config.yaml` |

## License

MIT License — Copyright (c) 2025 Bryan Weaver. See [LICENSE](LICENSE).
