#!/usr/bin/env python3
"""
Headline vs Reality — Walter Croncat's manual mismatch detector.

Checks whether a news article's headline accurately represents what
the article body actually says. When a gap is found, generates a
formatted "HEADLINE vs REALITY" post for Bluesky and/or X.

Usage:
    # URL mode (auto-fetches article)
    python src/headline_reality_post.py --url "https://example.com/article"

    # Paste mode (enter headline + article text interactively)
    python src/headline_reality_post.py --paste

    # Dry run (show generated post but don't publish)
    python src/headline_reality_post.py --url "https://example.com/article" --dry-run

    # Post to a specific platform only
    python src/headline_reality_post.py --url "..." --platform bluesky
    python src/headline_reality_post.py --url "..." --platform x
    python src/headline_reality_post.py --url "..." --platform both
"""
import argparse
import json
import os
import sys
from typing import Dict, Optional, Tuple

import requests
import yaml
from anthropic import Anthropic
from bs4 import BeautifulSoup

# Allow running as: python src/headline_reality_post.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_generator import _strip_quotes, _truncate_at_sentence
from prompt_loader import get_prompt_loader

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLUESKY_LIMIT = 300
X_LIMIT = 280
TARGET_LIMIT = 280  # Keep under X limit so the post works on both platforms

JINA_BASE_URL = "https://r.jina.ai/"
JINA_HEADERS = {"Accept": "text/markdown", "X-Return-Format": "markdown"}

# Higher char limit than the normal pipeline (1500) — we need the full article
# to catch headline contradictions buried deeper in the text
BS_MAX_CHARS = 8000

# CSS selectors for article content extraction (mirrors news_fetcher.py)
ARTICLE_SELECTORS = [
    'article',
    '[role="main"]',
    '.article-body',
    '.article-content',
    '.story-body',
    '.post-content',
    '#article-body',
    '.entry-content',
    '.content-body',
    '.story-content',
    'main article',
    '.article__body',
    '.article-text',
    '.story-text',
    '.body-content',
    '[itemprop="articleBody"]',
    '.post-body',
    '.news-body',
]


# ---------------------------------------------------------------------------
# HeadlineRealityChecker
# ---------------------------------------------------------------------------

class HeadlineRealityChecker:
    """
    Checks whether news headlines match what articles actually say.
    Generates HEADLINE vs REALITY posts for Walter Croncat.
    """

    def __init__(self):
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Missing ANTHROPIC_API_KEY. Check your .env file.")

        self.client = Anthropic(api_key=api_key)
        self.model = self.config['content']['model']
        self.prompts = get_prompt_loader()

    # -----------------------------------------------------------------------
    # Article fetching — three-tier fallback chain
    # -----------------------------------------------------------------------

    def fetch_via_jina(self, url: str) -> Optional[str]:
        """
        Fetch article using Jina Reader API (prepends https://r.jina.ai/).
        Returns clean markdown, or None on failure.
        """
        try:
            print(f"   🌐 Trying Jina Reader API...")
            response = requests.get(
                JINA_BASE_URL + url,
                headers=JINA_HEADERS,
                timeout=30,
            )
            response.raise_for_status()

            text = response.text.strip()
            if len(text) < 200:
                print(f"   ⚠️  Jina returned too little content ({len(text)} chars)")
                return None

            print(f"   ✓ Jina extracted {len(text)} chars of clean markdown")
            return text

        except Exception as e:
            print(f"   ⚠️  Jina Reader failed: {e}")
            return None

    def fetch_via_trafilatura(self, url: str) -> Optional[str]:
        """
        Fetch article using trafilatura — purpose-built for news article extraction.
        Returns clean text, or None on failure.
        """
        try:
            import trafilatura
            print(f"   🔄 Trying trafilatura extraction...")
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                print(f"   ⚠️  trafilatura: could not download page")
                return None

            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if not text or len(text) < 200:
                print(f"   ⚠️  trafilatura: content too short or empty")
                return None

            # Apply same high char limit
            text = _truncate_at_sentence(text, BS_MAX_CHARS)
            print(f"   ✓ trafilatura extracted {len(text)} chars")
            return text

        except ImportError:
            print(f"   ⚠️  trafilatura not installed, skipping")
            return None
        except Exception as e:
            print(f"   ⚠️  trafilatura failed: {e}")
            return None

    def fetch_via_beautifulsoup(self, url: str) -> Optional[str]:
        """
        Fetch article using BeautifulSoup — mirrors news_fetcher.py logic
        but with a much higher char limit (8000 vs 1500) to catch
        headline contradictions buried deeper in the article.
        Returns extracted text, or None on failure.
        """
        try:
            print(f"   🔄 Trying BeautifulSoup extraction...")
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',
                'Connection': 'keep-alive',
            }
            response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Remove boilerplate
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            # Try common article container selectors
            article_content = None
            for selector in ARTICLE_SELECTORS:
                element = soup.select_one(selector)
                if element:
                    article_content = element.get_text()
                    break

            # Fallback: collect paragraphs
            if not article_content:
                paragraphs = soup.find_all('p')
                if paragraphs:
                    article_content = ' '.join(p.get_text() for p in paragraphs[:40])

            if not article_content or len(article_content.strip()) < 200:
                print(f"   ⚠️  BeautifulSoup: could not extract meaningful content")
                return None

            # Clean whitespace and apply high char limit
            article_content = ' '.join(article_content.split())
            article_content = _truncate_at_sentence(article_content, BS_MAX_CHARS)

            print(f"   ✓ BeautifulSoup extracted {len(article_content)} chars")
            return article_content

        except Exception as e:
            print(f"   ⚠️  BeautifulSoup failed: {e}")
            return None

    def get_article_content(self, url: str) -> Tuple[Optional[str], str]:
        """
        Fetch article content with a three-tier fallback chain:
            1. Jina Reader API     (best — clean markdown, bypasses paywalls/JS)
            2. trafilatura         (purpose-built news extraction)
            3. BeautifulSoup       (last resort, higher char limit than normal pipeline)

        Returns:
            (content, method) where method is "jina", "trafilatura",
            "beautifulsoup", or "failed".
        """
        print(f"\n📄 Fetching article: {url[:80]}...")

        content = self.fetch_via_jina(url)
        if content:
            return content, "jina"

        content = self.fetch_via_trafilatura(url)
        if content:
            return content, "trafilatura"

        content = self.fetch_via_beautifulsoup(url)
        if content:
            return content, "beautifulsoup"

        return None, "failed"

    # -----------------------------------------------------------------------
    # Phase 1 — Structured mismatch analysis
    # -----------------------------------------------------------------------

    def analyze_mismatch(self, headline: str, article_text: str) -> Optional[Dict]:
        """
        Send headline + full article to Claude for structured analysis.
        Returns dict with has_mismatch, headline_claims, article_actually_says,
        mismatch_description, severity — or None on failure.
        """
        print(f"\n🔍 Analyzing: does the headline match the article?")

        prompt = self.prompts.load(
            "headline_vs_reality_analysis.md",
            headline=headline,
            article_text=article_text,
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Strip code fences if Claude wrapped the JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()

            result = json.loads(response_text)

            if result.get('has_mismatch'):
                severity = result.get('severity', 'unknown')
                print(f"   🚨 Mismatch found! Severity: {severity}")
                print(f"   Headline claims: {str(result.get('headline_claims', ''))[:80]}")
            else:
                print(f"   ✅ No mismatch — headline appears accurate")

            return result

        except json.JSONDecodeError as e:
            print(f"   ✗ Failed to parse analysis response as JSON: {e}")
            return None
        except Exception as e:
            print(f"   ✗ Analysis call failed: {e}")
            return None

    # -----------------------------------------------------------------------
    # Phase 2 — Post generation
    # -----------------------------------------------------------------------

    def generate_post(self, headline: str, analysis: Dict) -> Optional[str]:
        """
        Generate the formatted HEADLINE vs REALITY post from analysis results.
        Enforces TARGET_LIMIT characters. Returns post text or None on failure.
        """
        print(f"\n✍️  Generating HEADLINE vs REALITY post...")

        prompt = self.prompts.load(
            "headline_vs_reality.md",
            headline=headline,
            headline_claims=analysis.get('headline_claims', ''),
            article_actually_says=analysis.get('article_actually_says', ''),
            mismatch_description=analysis.get('mismatch_description', ''),
            severity=analysis.get('severity', 'moderate'),
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            post_text = message.content[0].text.strip()
            post_text = _strip_quotes(post_text)

            if len(post_text) > TARGET_LIMIT:
                print(f"   ⚠️  Post too long ({len(post_text)} chars). Trimming to {TARGET_LIMIT}...")
                post_text = _truncate_at_sentence(post_text, TARGET_LIMIT)

            print(f"   ✓ Post ready ({len(post_text)} chars)")
            return post_text

        except Exception as e:
            print(f"   ✗ Post generation failed: {e}")
            return None

    # -----------------------------------------------------------------------
    # Platform posting
    # -----------------------------------------------------------------------

    def post_to_bluesky(self, post_text: str, url: Optional[str]) -> Optional[dict]:
        """Post to Bluesky. If a URL is provided, replies with it as a source card."""
        try:
            from bluesky_bot import BlueskyBot
            bot = BlueskyBot()

            print(f"\n🦋 Posting to Bluesky...")
            result = bot.post_skeet(post_text)

            if result and url:
                print(f"   📎 Replying with source URL...")
                bot.reply_to_skeet_with_link(result['uri'], url)

            return result

        except Exception as e:
            print(f"   ✗ Bluesky post failed: {e}")
            return None

    def post_to_x(self, post_text: str, url: Optional[str]) -> Optional[dict]:
        """Post to X/Twitter. If a URL is provided, replies with it as a source."""
        try:
            from twitter_bot import TwitterBot
            bot = TwitterBot()

            # X is stricter than Bluesky
            x_text = post_text
            if len(x_text) > X_LIMIT:
                x_text = _truncate_at_sentence(x_text, X_LIMIT)

            print(f"\n🐦 Posting to X/Twitter...")
            result = bot.post_tweet(x_text)

            if result and url:
                tweet_id = result.get('id')
                if tweet_id:
                    print(f"   📎 Replying with source URL...")
                    bot.reply_to_tweet(tweet_id, url)

            return result

        except Exception as e:
            print(f"   ✗ X/Twitter post failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Paste mode helper
# ---------------------------------------------------------------------------

def get_paste_input() -> Tuple[str, str]:
    """
    Interactively prompt the user for headline and article text.
    Two consecutive blank lines (or Ctrl-D / Ctrl-Z) ends the article input.
    Returns (headline, article_text).
    """
    print("\n📋 PASTE MODE — enter article details below")
    print("=" * 50)

    print("\nHeadline (press Enter when done):")
    headline = input("> ").strip()
    if not headline:
        print("✗ Headline cannot be empty.")
        sys.exit(1)

    print(f"\nArticle text (paste it below).")
    print("End with two blank lines or Ctrl-D (Unix) / Ctrl-Z (Windows):")
    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
            # Two consecutive blank lines = done
            if len(lines) >= 2 and lines[-1] == "" and lines[-2] == "":
                break
    except EOFError:
        pass

    article_text = '\n'.join(lines).strip()
    if not article_text:
        print("✗ Article text cannot be empty.")
        sys.exit(1)

    print(f"\n✓ Got headline ({len(headline)} chars) and article ({len(article_text)} chars)")
    return headline, article_text


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Walter Croncat's HEADLINE vs REALITY checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python src/headline_reality_post.py --url "https://example.com/article"\n'
            '  python src/headline_reality_post.py --paste\n'
            '  python src/headline_reality_post.py --url "https://..." --dry-run\n'
            '  python src/headline_reality_post.py --url "https://..." --platform bluesky\n'
            '  python src/headline_reality_post.py --url "https://..." --platform x\n'
            '  python src/headline_reality_post.py --url "https://..." --platform both\n'
        ),
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="Article URL to fetch and analyze")
    input_group.add_argument(
        "--paste", action="store_true",
        help="Enter headline and article text manually via stdin",
    )

    parser.add_argument(
        "--platform", choices=["bluesky", "x", "both"], default="both",
        help="Platform(s) to post to (default: both)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate the post but do not publish it",
    )
    parser.add_argument(
        "--headline",
        help="Headline override for URL mode (skips auto-detection prompt)",
    )

    args = parser.parse_args()

    # Load .env for local development (no-op in CI where vars are already set)
    try:
        from dotenv import load_dotenv
        dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        load_dotenv(dotenv_path)
    except ImportError:
        pass

    # ---- Initialize checker ------------------------------------------------
    try:
        checker = HeadlineRealityChecker()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        sys.exit(1)

    # ---- Get headline + article text ----------------------------------------
    article_url: Optional[str] = None

    if args.url:
        article_url = args.url
        content, method = checker.get_article_content(args.url)

        if content is None:
            print(f"\n✗ Could not extract article content from URL.")
            print(f"   Tried: Jina Reader → trafilatura → BeautifulSoup")
            print(f"\n   Try paste mode instead:")
            print(f"   python src/headline_reality_post.py --paste")
            sys.exit(1)

        print(f"   (Extracted via: {method})")

        # Determine headline
        if args.headline:
            headline = args.headline
        else:
            # Try to auto-detect from first non-empty line of extracted content
            first_line = ""
            for line in content.split('\n'):
                stripped = line.lstrip('#').strip()
                if stripped:
                    first_line = stripped
                    break

            if 10 < len(first_line) < 250:
                print(f"\n📰 Auto-detected headline:")
                print(f"   {first_line}")
                confirm = input("   Use this as the headline? (y/n): ").strip().lower()
                if confirm == 'y':
                    headline = first_line
                else:
                    print("   Enter the correct headline:")
                    headline = input("> ").strip()
            else:
                print(f"\n⚠️  Could not auto-detect headline. Enter it manually:")
                headline = input("> ").strip()

        if not headline:
            print("✗ Headline cannot be empty.")
            sys.exit(1)

        article_text = content

    else:
        # Paste mode
        headline, article_text = get_paste_input()

    # ---- Phase 1: Structured analysis ---------------------------------------
    analysis = checker.analyze_mismatch(headline, article_text)
    if analysis is None:
        print(f"\n✗ Analysis failed. Cannot continue.")
        sys.exit(1)

    if not analysis.get('has_mismatch'):
        print(f"\n✅ HEADLINE IS ACCURATE")
        print(f"   The headline accurately represents what the article says.")
        print(f"   No HEADLINE vs REALITY post needed.")
        print(f"   Walter Croncat approves of this journalism.")
        sys.exit(0)

    # ---- Phase 2: Generate post --------------------------------------------
    post_text = checker.generate_post(headline, analysis)
    if post_text is None:
        print(f"\n✗ Post generation failed. Cannot continue.")
        sys.exit(1)

    # ---- Display the generated post ----------------------------------------
    print(f"\n{'=' * 60}")
    print("📰 GENERATED POST:")
    print(f"{'=' * 60}")
    print(post_text)
    print(f"{'=' * 60}")
    print(f"Length: {len(post_text)} chars  |  Bluesky limit: {BLUESKY_LIMIT}  |  X limit: {X_LIMIT}")

    if len(post_text) > BLUESKY_LIMIT:
        print(f"⚠️  WARNING: Post exceeds Bluesky character limit ({BLUESKY_LIMIT})")
    if len(post_text) > X_LIMIT:
        print(f"ℹ️  Note: Post is over X limit ({X_LIMIT}) — will be trimmed when posting to X")

    # ---- Dry run: stop here ------------------------------------------------
    if args.dry_run:
        print(f"\n🔍 DRY RUN — post not published")
        sys.exit(0)

    # ---- Confirmation prompt ------------------------------------------------
    platform_label = args.platform
    source_label = f"  Source URL: {article_url}" if article_url else ""
    print(f"\nReady to post to: {platform_label}")
    if source_label:
        print(source_label)
    confirm = input("\nPublish this post? (y/n): ").strip().lower()
    if confirm != 'y':
        print("✗ Cancelled — post not published")
        sys.exit(0)

    # ---- Post to platform(s) ------------------------------------------------
    posted_bluesky = None
    posted_x = None

    if args.platform in ("bluesky", "both"):
        posted_bluesky = checker.post_to_bluesky(post_text, article_url)

    if args.platform in ("x", "both"):
        posted_x = checker.post_to_x(post_text, article_url)

    # ---- Summary -----------------------------------------------------------
    print(f"\n{'=' * 60}")
    if posted_bluesky or posted_x:
        print("✅ DONE")
    else:
        print("⚠️  No posts were successfully published")

    if posted_bluesky:
        print(f"   Bluesky: {posted_bluesky.get('uri', 'posted')}")
    if posted_x:
        print(f"   X/Twitter: {posted_x.get('id', 'posted')}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
