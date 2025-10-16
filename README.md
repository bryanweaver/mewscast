# Mewscast

AI-powered Twitter/X automation bot that posts scheduled content using Claude AI. Built for developers who want a cheap, low-maintenance way to maintain an active Twitter presence.

## Features

- Automated scheduled posts using GitHub Actions (free!)
- AI-generated content using Anthropic's Claude
- Twitter/X API v2 integration
- Reply automation (optional)
- Configurable topics, style, and posting schedule
- Near-zero cost operation ($2-10/month for API usage only)

## Cost Breakdown

- **GitHub Actions**: FREE (2,000 minutes/month for private repos, unlimited for public)
- **Anthropic API**: ~$1-5/month (Claude 3.5 Sonnet at $3 per million tokens)
- **Twitter API**: FREE (with approved developer account)

**Total: $2-10/month**

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Twitter Developer Account
- Anthropic API key
- GitHub account (for free hosting)

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
   - Add these secrets:
     - `TWITTER_API_KEY`
     - `TWITTER_API_SECRET`
     - `TWITTER_ACCESS_TOKEN`
     - `TWITTER_ACCESS_TOKEN_SECRET`
     - `TWITTER_BEARER_TOKEN`
     - `ANTHROPIC_API_KEY`

3. Enable GitHub Actions:
   - Go to Actions tab
   - Enable workflows if prompted

4. That's it! Your bot will now post automatically based on the schedule in `.github/workflows/post-tweet.yml`

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
│   └── workflows/
│       └── post-tweet.yml      # GitHub Actions workflow
├── src/
│   ├── main.py                 # Main entry point
│   ├── twitter_bot.py          # Twitter API integration
│   └── content_generator.py   # AI content generation
├── config.yaml                 # Bot configuration
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variables template
└── README.md
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

## License

MIT License - feel free to fork and customize!

## Contributing

PRs welcome! Some ideas:

- Analytics dashboard
- Multiple AI provider support
- Content scheduling calendar
- Image generation integration
- Thread support

## Support

- Issues: [GitHub Issues](https://github.com/YOUR_USERNAME/mewscast/issues)
- Twitter: Share your bot and tag your experience!

---

Built with by developers, for developers. Now go build your Twitter presence while you sleep!
