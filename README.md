# Mewscast

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: anthropic](https://img.shields.io/badge/AI-Claude%204.5-purple.svg)](https://www.anthropic.com)

AI-powered news reporter bot (as a cat 🐱) that posts to X/Twitter and Bluesky using Claude AI. Fetches real news from Google News, generates witty commentary with full article context, and posts automatically with proper source citations.

## Table of Contents

- [Features](#features)
  - [Content Generation](#content-generation)
  - [Multi-Platform Posting](#multi-platform-posting)
  - [Automation & Cost](#automation--cost)
- [Cost Breakdown](#cost-breakdown)
- [Quick Start](#quick-start)
  - [Prerequisites](#1-prerequisites)
  - [Get API Credentials](#2-get-api-credentials)
  - [Local Setup](#3-local-setup)
  - [Configure Your Bot](#4-configure-your-bot)
  - [Test Locally](#5-test-locally)
  - [Deploy to GitHub Actions](#6-deploy-to-github-actions-free-hosting)
- [Usage](#usage)
  - [Run Modes](#run-modes)
  - [Manual Trigger](#manual-trigger-github)
  - [Customize Schedule](#customize-schedule)
- [Media Framing Analysis](#media-framing-analysis)
- [Configuration Options](#configuration-options)
- [Project Structure](#project-structure)
- [Tips for Growth](#tips-for-growth)
  - [Getting to 500 Followers](#getting-to-500-followers-for-x-creator-program)
  - [Monetization Strategy](#monetization-strategy)
  - [Cost Optimization](#cost-optimization)
- [Testing](#testing)
  - [Running Tests](#running-tests)
  - [Test Coverage](#test-coverage)
  - [Writing New Tests](#writing-new-tests)
  - [Test Files](#test-files)
- [Troubleshooting](#troubleshooting)
- [Scaling Up](#scaling-up)
- [Security](#security)
- [License](#license)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Support](#support)

## Features

### Content Generation
- **Real News Sourcing**: Fetches trending stories from Google News RSS (top stories + category fallback)
- **Full Article Parsing**: Reads complete articles (not just headlines) for accurate commentary
- **Media Framing Analysis**: Occasionally analyzes how media frames stories and adds commentary on notable framing angles
- **AI-Powered Commentary**: Uses Claude 4.5 Sonnet for sharp, witty news analysis
- **Fact-Checking**: Strict validation to prevent fabrication or hallucination
- **Cat Personality**: Professional news reporter who happens to be a cat

### Multi-Platform Posting
- **X/Twitter**: Posts with AI-generated images (via Grok) and source citations
- **Bluesky**: Cross-posts to Bluesky with link cards
- **Deduplication**: Smart 4-level system prevents repetition while allowing story updates (72-hour cooldown)
- **Source Attribution**: Always posts source links as replies for transparency

### In-Progress Features
- **Positive Mews** (needs minor fixes): Dedicated positive/uplifting news posts to balance out the regular news cycle
- **Walter Croncat Journalism Workflow** (shipped behind a master switch — see below): a 7-stage Cronkite-modeled pipeline that reads X for trending stories, gathers coverage across multiple outlets plus primary sources, runs a meta-analysis, and files a journalism-grade post. Currently runnable in dry-run mode. The legacy `battle_post` feature has been removed and replaced by the `META` post type inside this pipeline.

### Automation & Cost
- **GitHub Actions**: Free automated posting (7 posts/day)
- **Engagement Bot**: Auto-follows cat accounts and likes cat posts on Bluesky
- **Near-Zero Cost**: $20-50/month for API usage (Anthropic + Grok images)
- **No Server Needed**: Runs entirely on GitHub Actions

## Cost Breakdown

- **GitHub Actions**: FREE (unlimited for public repos)
- **Anthropic API**: ~$10-25/month (Claude 4.5 Sonnet for content generation)
  - Content generation: ~$0.01 per post
- **X/Twitter API**: FREE (Basic tier - 50 posts/24hrs)
- **Grok API**: ~$10-20/month (Image generation via X AI)
- **Bluesky**: FREE (no API costs)

**Total: $20-50/month** (varies with posting frequency)

## Walter Croncat Journalism Workflow

A Cronkite-modeled journalism pipeline that turns Walter Croncat from a generic AI news bot into a real journalistic endeavor. Instead of reacting to a single article, Croncat reads X for what's trending, gathers how the same event is being reported across 5–10 outlets plus the primary source, performs a meta-analysis of the coverage, and files a post modeled on Cronkite's actual methods.

The full design is in [`docs/Croncat_Journalism_Workflow.md`](docs/Croncat_Journalism_Workflow.md) and the underlying research on Cronkite's journalism is in [`docs/Walter_Cronkite_Report.md`](docs/Walter_Cronkite_Report.md).

### The 7 stages

1. **Trend detection** (`src/trend_detector.py`) — X `search_recent_tweets` over a curated outlet watchlist, with Google News fallback.
2. **Story triage** (`src/story_triage.py`) — need-to-know heuristic filter.
3. **Source gather** (`src/source_gatherer.py` + `src/primary_source_finder.py`) — slant-diverse multi-outlet fetch plus primary source pattern matching (congress.gov, SCOTUS, federalregister.gov, SEC filings, .gov PDFs).
4. **Meta-analysis** (`src/meta_analyzer.py`) — Claude Opus call producing a structured `MetaAnalysisBrief` comparing how outlets are framing the same event.
5. **Post composition** (`src/post_composer.py`) — dispatcher across 6 post types, each with its own prompt.
6. **Verification gate** (`src/verification_gate.py`) — hard rules enforcing journalism discipline, including the keystone sign-off rule.
7. **Publish / dry-run** (`src/main.post_journalism_cycle`) — publish to X and Bluesky, or write a draft to `drafts/` under `--dry-run`.

### The 6 post types and their sign-offs

| Post type | Sign-off | Purpose |
|---|---|---|
| `REPORT` | `And that's the mews.` | Straight news, the default |
| `META` | `And that's the mews — coverage report.` | Coverage analysis comparing how outlets are reporting the same event (the flagship — replaces `battle_post`) |
| `ANALYSIS` | `This cat's view — speculative, personal, subjective.` | Rare, explicitly labeled commentary |
| `BULLETIN` | *(no sign-off)* | Single-source breaking news — deliberately unsigned per Cronkite's practice |
| `CORRECTION` | *(no sign-off)* | Self-correction, pinned after publishing |
| `PRIMARY` | `And that's the mews — straight from the source.` | Primary-document spotlight |

### The keystone rule

Walter Cronkite omitted "And that's the way it is" on nights he had closed his broadcast with commentary, because the sign-off was the seal of a straight report. Walter Croncat enforces the same discipline mechanically in `src/verification_gate.py::_check_signoff_matches_type` — a post's sign-off must match its post type exactly, and BULLETIN/CORRECTION posts must not contain any sign-off phrase anywhere in the body. This is the single most load-bearing rule in the whole pipeline.

### Master switch

The workflow is off by default. Flip it on in `config.yaml`:

```yaml
journalism:
  enabled: false   # set to true only after a week of dry-run validation
```

`--dry-run` is always allowed regardless of the master switch.

### CLI

```bash
# Run one journalism cycle (uses brief's suggested post type)
python src/main.py journalism

# Dry-run — writes a draft to drafts/<story_id>_<post_type>.md instead of publishing
python src/main.py journalism --dry-run

# Force a specific post type
python src/main.py journalism brief [--dry-run]        # REPORT
python src/main.py journalism meta [--dry-run]         # META (the flagship)
python src/main.py journalism analysis [--dry-run]     # ANALYSIS (use sparingly)
python src/main.py journalism bulletin [--dry-run]     # BULLETIN
python src/main.py journalism correction [--dry-run]   # CORRECTION
python src/main.py journalism primary [--dry-run]      # PRIMARY

# Offline end-to-end smoke test (stubs out the X, Google News, and Claude calls)
python scripts/journalism_dry_run.py --mock
```

Rejected drafts (verification gate failures after one retry) land in `drafts/rejected/`.

### Story dossiers

Every story run through the pipeline produces a `StoryDossier` and a `MetaAnalysisBrief` that are written to `dossiers/<story_id>.json`. The directory is gitignored for now; Phase 4 of the plan will publish these as a public audit trail (open-source journalism, not just open-source code).

## Quick Start

### 1. Prerequisites

- Python 3.11+
- X/Twitter Developer Account (Free tier)
- Bluesky Account (with app password)
- Anthropic API key (Claude 4.5 Sonnet)
- X AI API key (for Grok image generation)
- GitHub account (for free hosting via Actions)

### 2. Get API Credentials

#### Twitter API (Free)
1. Go to [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a new app (if you don't have one)
3. Generate API keys and tokens:
   - API Key and Secret
   - Access Token and Secret
   - Bearer Token
4. Set permissions to "Read and Write"

#### Anthropic API
1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Create an API key
3. Add $5-10 credit to start (will last months)

### 3. Local Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/mewscast.git
cd mewscast

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API credentials
```

### 4. Configure Your Bot

Edit `config.yaml` to customize:
- Topics to tweet about
- Posting style and tone
- Schedule (cron format)
- Content filters

### 5. Test Locally

```bash
# Test tweet generation and posting
cd src
python main.py scheduled
```

### 6. Deploy to GitHub Actions (Free Hosting!)

1. Push your code to GitHub:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mewscast.git
git push -u origin main
```

2. Add secrets to your GitHub repository:
   - Go to your repo → Settings → Secrets and variables → Actions
   - Click "New repository secret" and add each of these:

   **X/Twitter API Credentials:**
   - `X_API_KEY` - Your X API key
   - `X_API_SECRET` - Your X API secret
   - `X_ACCESS_TOKEN` - Your X access token
   - `X_ACCESS_TOKEN_SECRET` - Your X access token secret
   - `X_BEARER_TOKEN` - Your X bearer token

   **Bluesky Credentials:**
   - `BLUESKY_USERNAME` - Your Bluesky handle (e.g., `yourname.bsky.social`)
   - `BLUESKY_PASSWORD` - Your Bluesky app password (from Settings → App Passwords)

   **AI API Keys:**
   - `ANTHROPIC_API_KEY` - Your Anthropic API key (for Claude)
   - `X_AI_API_KEY` - Your X AI API key (for Grok image generation)

3. Enable GitHub Actions:
   - Go to Actions tab
   - Enable workflows if prompted
   - You should see workflows: "Post Scheduled Tweet", "Engage Cats (X)", "Engage Cats (Bluesky)"

4. Test the workflow:
   - Go to Actions tab → "Post Scheduled Tweet"
   - Click "Run workflow" → "Run workflow"
   - Watch it run and check for any errors

5. That's it! Your bot will now:
   - Post automatically 7 times per day (schedule in `.github/workflows/post-tweet.yml`)
   - Auto-engage with cat accounts on X and Bluesky
   - Commit post history after each successful post

## Usage

### Run Modes

```bash
# Post a scheduled tweet
python src/main.py scheduled

# Reply to mentions
python src/main.py reply

# Both
python src/main.py both
```

### Manual Trigger (GitHub)

1. Go to your repo → Actions tab
2. Select "Post Scheduled Tweet" workflow
3. Click "Run workflow"

### Customize Schedule

Edit `.github/workflows/post-tweet.yml`:

```yaml
schedule:
  - cron: '0 14 * * *'  # Daily at 2 PM UTC
  # Examples:
  # - cron: '0 */6 * * *'  # Every 6 hours
  # - cron: '0 9,17 * * *'  # Twice daily at 9 AM and 5 PM UTC
```

Use [crontab.guru](https://crontab.guru/) to create custom schedules.

## Media Framing Analysis

When generating posts from specific news stories, the bot has a configurable chance (default 50%) to analyze how the media frames the story. If notable framing angles are found, the post incorporates that perspective instead of the default cat-snark approach. This is handled by `analyze_media_framing()` in `content_generator.py` and uses the `analyze_framing.md` and `tweet_framing.md` prompt templates.

## Configuration Options

### config.yaml

```yaml
content:
  topics:
    - "software development"
    - "tech trends"
    - "coding tips"
  style: "casual and helpful"
  model: "claude-3-5-sonnet-20241022"

scheduling:
  post_times:
    - "0 14 * * *"  # 2 PM UTC daily

safety:
  avoid_topics:
    - "politics"
    - "religion"
  max_posts_per_day: 3
```

## Project Structure

```
mewscast/
├── .github/
│   └── workflows/          # GitHub Actions workflows
│       ├── post-tweet.yml      # Main posting workflow
│       ├── engage-cats.yml     # X engagement automation
│       └── engage-cats-bluesky.yml  # Bluesky engagement
├── src/                    # Source code
│   ├── main.py                 # Main entry point (legacy + journalism modes)
│   ├── twitter_bot.py          # X/Twitter API integration
│   ├── bluesky_bot.py          # Bluesky API integration
│   ├── content_generator.py    # Legacy content generation (Claude)
│   ├── image_generator.py      # AI image generation (Grok)
│   ├── news_fetcher.py         # Google News RSS fetching
│   ├── post_tracker.py         # Deduplication & history (extended with dossier_id/post_type)
│   ├── engagement_bot.py       # Engagement automation
│   ├── positive_news_post.py   # Positive news posts - WIP
│   │
│   ├── # Walter Croncat journalism workflow (Stages 1–7)
│   ├── trend_detector.py       # Stage 1 — X search + watchlist
│   ├── story_triage.py         # Stage 2 — need-to-know filter
│   ├── source_gatherer.py      # Stage 3 — multi-outlet gather
│   ├── primary_source_finder.py # Stage 3 — primary source pattern matcher
│   ├── meta_analyzer.py        # Stage 4 — Claude Opus meta-analysis
│   ├── post_composer.py        # Stage 5 — dispatcher across 6 post types
│   ├── verification_gate.py    # Stage 6 — hard rules incl. keystone sign-off rule
│   └── dossier_store.py        # Data classes, SIGN_OFFS, JSON persistence
├── prompts/                # Claude prompt templates
│   ├── tweet_generation.md     # Legacy tweet prompt
│   ├── analyze_framing.md      # Legacy framing analysis
│   ├── meta_analysis.md        # Stage 4 meta-analysis prompt
│   ├── report_post.md          # REPORT post type
│   ├── meta_post.md            # META post type (flagship)
│   ├── analysis_post.md        # ANALYSIS post type
│   ├── bulletin_post.md        # BULLETIN post type
│   ├── correction_post.md      # CORRECTION post type
│   └── primary_post.md         # PRIMARY post type
├── tests/                  # Test suite
│   ├── __init__.py             # Test package initialization
│   ├── test_deduplication.py   # Post deduplication logic (71 tests)
│   ├── test_engagement.py      # Engagement bot behavior (95 tests)
│   ├── test_content_generator.py  # Content generation pipeline (114 tests)
│   ├── test_bots.py            # Bot posting pipeline (118 tests)
│   │
│   ├── # Journalism workflow tests
│   ├── test_dossier_store.py       # Data classes + persistence (28 tests)
│   ├── test_verification_gate.py   # Hard rules incl. keystone matrix (40 tests)
│   ├── test_trend_detector.py      # Stage 1 (18 tests)
│   ├── test_story_triage.py        # Stage 2 (15 tests)
│   ├── test_source_gatherer.py     # Stage 3 (9 tests)
│   ├── test_primary_source_finder.py # Stage 3 helper (18 tests)
│   ├── test_meta_analyzer.py       # Stage 4 (14 tests)
│   └── test_post_composer.py       # Stage 5 (21 tests)
├── docs/                   # Documentation (see Documentation section)
├── scripts/                # Utility scripts
│   ├── rebuild_history.py      # Rebuild post history from X
│   ├── filter_history.py       # Clean up post history
│   └── journalism_dry_run.py   # End-to-end smoke test for the journalism pipeline
├── dossiers/               # Story dossiers written by the pipeline (gitignored)
├── drafts/                 # Dry-run drafts (gitignored)
├── outlet_registry.yaml    # 30-outlet curated watchlist for the journalism workflow
├── config.yaml             # Bot configuration (includes `journalism:` section)
├── posts_history.json      # Post deduplication history
├── bluesky_engagement_history.json  # Bluesky follows/likes
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
├── LICENSE                 # MIT License
└── README.md               # This file
```

## Tips for Growth

### Getting to 500 Followers (for X Creator Program)

1. **Consistency**: Post daily (this bot handles that!)
2. **Engagement**: Reply to others (can automate with `reply` mode)
3. **Value**: Share useful tips, insights, and experiences
4. **Authenticity**: Customize the bot's style to match your voice

### Monetization Strategy

- **Phase 1** (Weeks 1-4): Build automation, post daily, grow to 100+ followers
- **Phase 2** (Months 2-3): Hit 300+ followers, increase engagement
- **Phase 3** (Month 4+): Reach 500 followers, apply for X Premium
- **Phase 4**: Enable monetization, revenue covers costs

### Cost Optimization

- Start with daily posts (cheapest)
- Use Claude 3.5 Sonnet (best value)
- Only enable reply mode once you have steady mentions
- Monitor API costs in first month
- Media framing analysis is lightweight and adds minimal cost per post

## Testing

### Running Tests

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_deduplication.py -v

# Run with coverage report
pytest tests/ --cov=src --cov-report=html
```

### Test Coverage

The project includes **562+ tests across 12 test files** covering legacy modules plus the Walter Croncat journalism workflow:

**Legacy modules (398 tests):**
- **Deduplication Logic** (`test_deduplication.py`, 71 tests): URL matching, topic/content similarity, story clustering, update detection, and post history management
- **Engagement Bots** (`test_engagement.py`, 95 tests): Target filtering, history tracking, follow-ratio checks, repost logic, engagement cycle orchestration, and API error handling for both X/Twitter and Bluesky bots
- **Content Generation Pipeline** (`test_content_generator.py`, 114 tests): ContentGenerator, PromptLoader, and NewsFetcher — AI response validation, character limit enforcement, and retry logic
- **Bot Posting Pipeline** (`test_bots.py`, 118 tests): Bluesky bot, Twitter/X bot, image generator, configuration loading, and main pipeline orchestration

**Journalism workflow (164 tests):**
- **Dossier Store** (`test_dossier_store.py`, 28 tests): Dataclass round-trip, SIGN_OFFS lookup, JSON persistence, schema correctness
- **Verification Gate** (`test_verification_gate.py`, 40 tests): The keystone sign-off-matches-type matrix covering every post type + cross-contamination cases, plus source count, outlet-in-body, editorial word filter, hedge attribution, and char limit checks
- **Trend Detector** (`test_trend_detector.py`, 18 tests): Watchlist query construction, tweet clustering, NewsFetcher fallback
- **Story Triage** (`test_story_triage.py`, 15 tests): Heuristic scoring, hard-reject paths, pass-threshold behavior
- **Source Gatherer** (`test_source_gatherer.py`, 9 tests): Slant diversity, wire-derivation, dossier well-formedness
- **Primary Source Finder** (`test_primary_source_finder.py`, 18 tests): Pattern matching for congress.gov, SCOTUS, federalregister.gov, BLS, SEC, White House, generic .gov PDFs
- **Meta-Analyzer** (`test_meta_analyzer.py`, 14 tests): Prompt construction, JSON parsing (clean/fenced/prose), retry logic, graceful failure
- **Post Composer** (`test_post_composer.py`, 21 tests): Per-type prompt dispatch, sign-off metadata, correction_inputs threading, retry_reasons injection

**Note:** Running `pytest tests/` currently reports a small number of failures due to a pre-existing test-isolation bug between `test_bots.py` and `test_content_generator.py` (the former installs a `sys.modules['bs4']` mock at import time that breaks the latter when run in the same process). All files pass cleanly when run individually. This predates the journalism workflow and is tracked as follow-up cleanup.

### Writing New Tests

When adding features, include tests that cover:

1. **Happy Path**: Normal operation with expected inputs
2. **Edge Cases**: Boundary conditions, empty inputs, maximum values
3. **Error Handling**: API failures, network issues, invalid responses
4. **Integration**: How the feature interacts with existing code

Example test structure:
```python
def test_new_feature(generator):
    """Test description of what this validates"""
    # Setup test data
    test_input = {...}

    # Execute the feature
    result = generator.new_feature(test_input)

    # Assert expected behavior
    assert result['success'] == True
    assert 'expected_field' in result
```

### Test Files

- `tests/test_deduplication.py` - Post deduplication logic (71 tests)
- `tests/test_engagement.py` - Engagement bot behavior for X/Twitter and Bluesky (95 tests)
- `tests/test_content_generator.py` - Content generation pipeline including PromptLoader and NewsFetcher (114 tests)
- `tests/test_bots.py` - Bot posting pipeline including image generation and main orchestration (118 tests)

## Troubleshooting

### "Missing Twitter API credentials"
- Check your `.env` file has all 5 Twitter credentials
- Verify they're added as GitHub Secrets (if using Actions)

### "Rate limit exceeded"
- Twitter free tier: 1,500 posts/month (50/day)
- Wait for rate limit reset or reduce posting frequency

### "Content generation failed"
- Check Anthropic API key is valid
- Verify you have credits in your Anthropic account
- Check API usage at console.anthropic.com

### GitHub Actions not running
- Check workflow file is in `.github/workflows/`
- Verify Actions are enabled in repo settings
- Check secrets are properly set

## Scaling Up

Want more features? Consider:

- **Railway/Render**: Migrate to always-on server for reply automation (~$5/month)
- **OpenAI**: Alternative to Claude (similar cost)
- **Multiple accounts**: Run one instance per account
- **Analytics**: Track engagement and optimize content

## Security

This repository has been thoroughly audited for security:
- ✅ No hardcoded credentials or API keys
- ✅ All secrets managed via environment variables and GitHub Secrets
- ✅ No PII or sensitive data in commit history
- ✅ Proper .gitignore configuration



## License

MIT License

Copyright (c) 2025 Bryan Weaver

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

See [LICENSE](LICENSE) file for full license text.

## Documentation

Additional documentation can be found in the `docs/` directory.

## Contributing

PRs welcome! Some ideas:

- Analytics dashboard
- Multiple AI provider support
- Content scheduling calendar
- Thread support
- Multi-account management

## Support

- **Issues**: [GitHub Issues](https://github.com/bryanweaver/mewscast/issues)
- **X/Twitter**: [@mewscast](https://x.com/mewscast)
- **Bluesky**: [@mewscast.bsky.social](https://bsky.app/profile/mewscast.bsky.social)

---

Built with by developers, for developers. Now go build your Twitter presence while you sleep!
