# Quick Setup Guide - Get Your Credentials

## Step 1: Get Twitter/X API Credentials

### Navigate to Developer Portal
1. Go to https://developer.twitter.com/en/portal/dashboard
2. Click on your app/project name

### Get Your Credentials

#### A. API Keys (in "Keys and Tokens" tab)

**Consumer Keys:**
- **API Key** - looks like: `xvz1evFS4wEEPTGEFPHBog`
- **API Key Secret** - looks like: `L8qq9PZyRg6ieKGEKhZolGC0vJWLw8iEJ88DRdyOg`
- ⚠️ Secret only shows once - copy it immediately!

**Bearer Token:**
- Scroll down to find it
- Looks like: `AAAAAAAAAAAAAAAAAAAAABcDEF%2F...` (very long)

#### B. Access Token & Secret

1. Scroll to "Authentication Tokens" section
2. Click **"Generate"** button next to "Access Token and Secret"
3. Copy both:
   - **Access Token** - looks like: `1234567890-aBcDeFgHiJkLmNoPqRsTuVwXyZ`
   - **Access Token Secret** - looks like: `AbCdEfGhIjKlMnOpQrStUvWxYz1234567890AbCdEf`
4. ⚠️ Only shown once - save them!

### Set Permissions (CRITICAL!)

1. Go to "Settings" tab in your app
2. Find "App permissions" section
3. Must be set to: **"Read and Write"**
4. If it says "Read only":
   - Click "Edit"
   - Change to "Read and Write"
   - Save
   - Go back and **regenerate** your Access Token & Secret

## Step 2: Get Anthropic API Key

1. Go to https://console.anthropic.com/
2. Sign up/login
3. Click "API Keys" in sidebar
4. Click "Create Key"
5. Copy the key - looks like: `sk-ant-api03-...`
6. Add credits: Settings → Billing → Add at least $5

## Step 3: Configure Your Bot

### Create .env file:

```bash
cd /Users/bryanweaver/Documents/mewscast
cp .env.example .env
nano .env  # or use any text editor
```

### Fill in your .env:

```bash
# Twitter/X API Credentials
TWITTER_API_KEY=your_api_key_here
TWITTER_API_SECRET=your_api_secret_here
TWITTER_ACCESS_TOKEN=your_access_token_here
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret_here
TWITTER_BEARER_TOKEN=your_bearer_token_here

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-api03-...

# Bot Configuration
BOT_MODE=scheduled
POST_FREQUENCY=daily
```

## Step 4: Test Locally

```bash
./test_local.sh
```

If successful, you'll see:
```
✓ Generated tweet (XXX chars)
✓ Tweet posted successfully! ID: 1234567890
```

## Step 5: Deploy to GitHub

### Push to GitHub:
```bash
git init
git add .
git commit -m "Initial mewscast setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mewscast.git
git push -u origin main
```

### Add GitHub Secrets:
1. Go to your repo: `https://github.com/YOUR_USERNAME/mewscast`
2. Click: Settings → Secrets and variables → Actions
3. Click: "New repository secret"
4. Add each of these (one at a time):

| Name | Value |
|------|-------|
| `TWITTER_API_KEY` | Your API Key |
| `TWITTER_API_SECRET` | Your API Secret |
| `TWITTER_ACCESS_TOKEN` | Your Access Token |
| `TWITTER_ACCESS_TOKEN_SECRET` | Your Access Token Secret |
| `TWITTER_BEARER_TOKEN` | Your Bearer Token |
| `ANTHROPIC_API_KEY` | Your Anthropic Key |

### Enable Actions:
1. Go to "Actions" tab
2. Enable workflows if prompted
3. Click "Post Scheduled Tweet"
4. Click "Run workflow" to test

## Free Tier Rate Limits - What You Can Do

✅ **What works great:**
- Post 1 tweet/day (limit: 17/day)
- Post 2-3 times/day (still well under limit)
- Fetch your profile info (limit: 25/day)

⚠️ **What's restricted:**
- Checking mentions: 1 request/15min (96/day max)
- Better to check once daily or skip for now

💡 **Recommendation:** Stick with 1-2 scheduled posts/day. Skip auto-replies until you have more followers (or upgrade to Basic tier later).

## Troubleshooting

### "Missing Twitter API credentials"
- Check all 5 credentials are in .env
- No spaces around the = sign
- No quotes needed around values

### "403 Forbidden" or "Read-only application"
- App permissions must be "Read and Write"
- Regenerate Access Token after changing permissions

### "401 Unauthorized"
- Check credentials are correct
- Make sure you copied the full tokens (they're long!)

### "Rate limit exceeded"
- Free tier: 17 tweets/24hrs
- Wait until tomorrow or reduce posting frequency

### GitHub Action fails
- Verify all 6 secrets are added to repo
- Check secret names match exactly (case-sensitive)
- Look at Actions tab → Failed run → View logs for details

## Next Steps

Once running:
1. Let it post for a week
2. Customize topics in `config.yaml` based on engagement
3. Monitor costs at console.anthropic.com
4. Consider 2x/day posting if 1x is working well

Your estimated monthly cost: **$2-5** (just Anthropic API)

Questions? Check main README.md or open an issue.
