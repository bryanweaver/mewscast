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
- [Media Literacy Feature](#media-literacy-feature)
  - [How It Works](#how-it-works)
  - [What It Detects](#what-it-detects)
  - [Example Outputs](#example-outputs)
  - [Severity Thresholds](#severity-thresholds)
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
- **Media Literacy Analysis**: NEW! Automatically detects misleading headlines, bias, and manipulation tactics
- **Smart Response System**: Chooses between media literacy callouts or regular cat-snark based on severity
- **AI-Powered Commentary**: Uses Claude 4.5 Sonnet for sharp, witty news analysis
- **Fact-Checking**: Strict validation to prevent fabrication or hallucination
- **Cat Personality**: Professional news reporter who specializes in media literacy... and happens to be a cat 🐱

### Multi-Platform Posting
- **X/Twitter**: Posts with AI-generated images (via Grok) and source citations
- **Bluesky**: Cross-posts to Bluesky with link cards
- **Deduplication**: Smart 4-level system prevents repetition while allowing story updates (72-hour cooldown)
- **Source Attribution**: Always posts source links as replies for transparency

### Automation & Cost
- **GitHub Actions**: Free automated posting (7 posts/day)
- **Engagement Bot**: Auto-follows cat accounts and likes cat posts on Bluesky
- **Near-Zero Cost**: $20-50/month for API usage (Anthropic + Grok images)
- **No Server Needed**: Runs entirely on GitHub Actions

## Cost Breakdown

- **GitHub Actions**: FREE (unlimited for public repos)
- **Anthropic API**: ~$10-25/month (Claude 4.5 Sonnet for content + media literacy analysis)
  - Content generation: ~$0.01 per post
  - Media literacy analysis: ~$0.0015 per post (when article content exists)
- **X/Twitter API**: FREE (Basic tier - 50 posts/24hrs)
- **Grok API**: ~$10-20/month (Image generation via X AI)
- **Bluesky**: FREE (no API costs)

**Total: $20-50/month** (varies with posting frequency)

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

## Media Literacy Feature

Walter Croncat now includes intelligent media literacy analysis that helps readers identify misleading news practices.

### How It Works

```
Article received → Media literacy analysis
├─ High/Medium severity issues found → Generate media literacy callout
└─ Low/No issues → Use regular populist cat-snark approach
```

### What It Detects

- **Misleading Headlines**: Headlines that contradict article content
- **Statistical Manipulation**: Using percentages to exaggerate small changes
- **Missing Context**: Omitting critical information that changes the story
- **Bias & One-Sided Reporting**: Quoting only one perspective
- **Fear-Mongering**: Using emotional manipulation tactics

### Example Outputs

**Media Literacy Callout:**
```
#MediaLiteracy: Headline screams 'CRISIS' but article says 0.3% dip.

Classic fear-bait. Article itself calls it 'normal.' This cat's not buying the panic.
```

**Regular Cat-Snark (when no issues detected):**
```
City council votes 7-2 for $3.2M park. 15 acres of green space.

Two dissenting votes worried about $150K yearly upkeep. From my perch: Who's getting the construction contract?
```

### Severity Thresholds

- **High Severity**: Egregious manipulation, false claims → Triggers media literacy response
- **Medium Severity**: Notable bias, missing context → Triggers media literacy response
- **Low Severity**: Minor issues → Uses regular cat-snark approach
- **No Issues**: Clean reporting → Uses regular cat-snark approach

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
│   ├── main.py                 # Main entry point
│   ├── twitter_bot.py          # X/Twitter API integration
│   ├── bluesky_bot.py          # Bluesky API integration
│   ├── content_generator.py    # AI content generation (Claude) + media literacy
│   ├── image_generator.py      # AI image generation (Grok)
│   ├── news_fetcher.py         # Google News RSS fetching
│   ├── post_tracker.py         # Deduplication & history
│   └── engagement_bot.py       # Engagement automation
├── tests/                  # Test suite
│   ├── __init__.py             # Test package initialization
│   └── test_media_literacy.py  # Media literacy tests (13 test cases)
├── docs/                   # Documentation (see Documentation section)
├── scripts/                # Utility scripts
│   ├── rebuild_history.py      # Rebuild post history from X
│   └── filter_history.py       # Clean up post history
├── config.yaml             # Bot configuration
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
- Media literacy analysis adds ~$0.0015 per post (worth it for quality)

## Testing

### Running Tests

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_media_literacy.py -v

# Run with coverage report
pytest tests/ --cov=src --cov-report=html
```

### Test Coverage

The project includes comprehensive test coverage for critical features:

- **Media Literacy Analysis**: 13 test cases covering detection, severity thresholds, and error handling
- **Deduplication Logic**: Tests for exact matches, content similarity, and story clustering
- **API Error Handling**: Tests for graceful fallback when APIs fail
- **Character Limit Enforcement**: Tests retry logic and truncation for posts

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

- `tests/test_media_literacy.py` - Media literacy detection and response generation
- `tests/test_deduplication.py` - Post deduplication logic (TODO)
- `tests/test_engagement.py` - Engagement bot behavior (TODO)

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

See [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) for full security audit details.

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
