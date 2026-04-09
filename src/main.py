"""
Mewscast - AI-powered X news reporter cat bot
Main entry point for scheduled posts and automation
"""
import json
import os
import re
import sys
import random
import time
import yaml
from datetime import datetime, timezone
from dotenv import load_dotenv

from content_generator import ContentGenerator
from twitter_bot import TwitterBot
from bluesky_bot import BlueskyBot
from news_fetcher import NewsFetcher
from image_generator import ImageGenerator
from post_tracker import PostTracker

# --- Walter Croncat journalism workflow imports --------------------------
# These modules are pure-Python and import with zero side-effects at module
# level; the whole pipeline is only instantiated inside post_journalism_cycle
# so the existing modes (scheduled/reply/both/special) are unaffected when
# the journalism workflow is disabled.
from dossier_store import DossierStore, DraftPost, PostType, StoryDossier
from trend_detector import TrendDetector, _extract_proper_nouns
from story_triage import StoryTriage
from source_gatherer import _FLUFF_PREFIXES, _SUFFIX_STRIP_RE, SourceGatherer
from primary_source_finder import PrimarySourceFinder
from meta_analyzer import MetaAnalyzer
from post_composer import PostComposer
from verification_gate import VerificationGate, VerificationResult


def _load_config():
    """Load the project config.yaml and return parsed dict."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def post_scheduled_tweet():
    """Generate and post a scheduled news cat tweet with Google Trends"""
    print(f"\n{'='*60}")
    print(f"Mewscast - News Reporter Cat")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        # Load config for deduplication settings
        config = _load_config()

        # Initialize components
        print("🐱 Initializing news cat reporter...")
        generator = ContentGenerator()

        print("📡 Connecting to X...")
        twitter_bot = TwitterBot()

        print("🦋 Connecting to Bluesky...")
        try:
            bluesky_bot = BlueskyBot()
        except Exception as e:
            print(f"⚠️  Bluesky connection failed: {e}")
            print(f"   Continuing with X only...")
            bluesky_bot = None

        print("📰 Initializing news fetcher...")
        news_fetcher = NewsFetcher()

        # Initialize post tracker for deduplication
        dedup_config = config.get('deduplication', {})
        tracker = PostTracker(config=dedup_config)

        # NEW FLOW: Prioritize what's ACTUALLY trending right now
        # This ensures we cover major breaking news (elections, crises, etc.)
        # instead of randomly selecting from static topic list
        #
        # Step 1: Get top stories from Google News (what's breaking NOW)
        # Step 2: If no unique top stories, fall back to category search
        # Step 3: Verify we can fetch article content before selecting (prevent "can't read" tweets)

        # Collect all potential articles first with their status
        candidate_articles = []  # List of (article, status) tuples

        print(f"🔥 Phase 1: Checking TOP STORIES (what's trending NOW)...")
        top_stories = news_fetcher.get_top_stories(max_stories=20)

        # Add unique top stories to candidates
        for article in top_stories:
            status = tracker.check_story_status(article)

            if status['is_duplicate']:
                print(f"   ✗ Duplicate: {article['source']} - {article['title'][:50]}...")
                continue

            # Store article with its status for later use
            candidate_articles.append((article, status))
            if status['is_update']:
                print(f"   ✓ Added UPDATE candidate: {article['source']} - {article['title'][:50]}...")
            else:
                print(f"   ✓ Added candidate: {article['source']} - {article['title'][:50]}...")

        # If we need more candidates, search category-based topics
        if len(candidate_articles) < 10:
            print(f"\n📰 Phase 2: Searching category-based topics for more candidates...")
            topics_to_try = random.sample(news_fetcher.news_categories,
                                         min(20, len(news_fetcher.news_categories)))

            for topic in topics_to_try:
                if len(candidate_articles) >= 20:  # Stop when we have enough candidates
                    break

                articles = news_fetcher.get_articles_for_topic(topic, max_articles=5)

                for article in articles:
                    status = tracker.check_story_status(article)

                    if status['is_duplicate']:
                        print(f"   ✗ Duplicate: {article['source']} - {article['title'][:50]}...")
                        continue

                    # Store article with its status
                    candidate_articles.append((article, status))
                    if status['is_update']:
                        print(f"   ✓ Added UPDATE candidate from {topic}: {article['title'][:50]}...")
                    else:
                        print(f"   ✓ Added candidate from {topic}: {article['title'][:50]}...")

        print(f"\n🔍 Phase 3: Testing {len(candidate_articles)} candidate articles...")

        # Try each candidate until we get valid content AND valid generated tweet
        selected_story = None
        story_status = None
        result = None

        for i, (article, status) in enumerate(candidate_articles, 1):
            print(f"\n📰 Attempting article {i}/{len(candidate_articles)}: {article['title'][:60]}...")
            print(f"   Source: {article['source']}")
            print(f"   URL: {article.get('url', 'N/A')}")

            # Step 1: Try to fetch article content
            if not article.get('url'):
                print(f"   ❌ No URL available - trying next article...")
                continue

            article_content = news_fetcher.fetch_article_content(article['url'])
            if not article_content:
                print(f"   ❌ Could not fetch content - trying next article...")
                continue

            article['article_content'] = article_content
            print(f"   ✅ Fetched {len(article_content)} chars of content")

            # Step 2: Generate tweet and validate
            previous_posts = None
            if status and status.get('is_update'):
                previous_posts = status.get('previous_posts', [])
                print(f"   📋 Providing context from {len(previous_posts)} previous post(s)")

            # Generate for Bluesky first (our primary/working platform)
            result = generator.generate_tweet(
                trending_topic=article['title'],
                story_metadata=article,
                previous_posts=previous_posts
            )

            # Check if generation succeeded (validation passed)
            if result is None:
                print(f"   ❌ Content validation failed - trying next article...")
                continue

            # Step 3: Check for duplicate content
            if not (status and status.get('is_update')):
                content_check = tracker.check_story_status(article, post_content=result['tweet'])
                if content_check['is_duplicate']:
                    print(f"   ❌ Generated content too similar to recent post - trying next article...")
                    continue

            # Success! We have valid content
            selected_story = article
            story_status = status
            print(f"   ✅ Valid tweet generated!")
            break

        if not selected_story or not result:
            print(f"\n{'='*60}")
            print(f"❌ Could not generate valid content for any of {len(candidate_articles)} articles")
            print(f"{'='*60}\n")
            return False

        bluesky_text = result['tweet']
        needs_source = result['needs_source_reply']
        story_meta = result['story_metadata']

        # Use same content for both platforms (single generation)
        x_text = bluesky_text

        # Try to generate image (with graceful fallback)
        image_path = None
        image_prompt = None
        try:
            print(f"🎨 Attempting to generate image with Grok...")
            img_generator = ImageGenerator()

            # Generate image prompt using Claude (with full article for story-specific imagery)
            # Use bluesky text since it's more straightforward
            image_prompt = generator.generate_image_prompt(
                selected_story['title'] if selected_story else "news",
                bluesky_text,
                article_content=selected_story.get('article_content') if selected_story else None
            )

            # Generate image using Grok
            image_path = img_generator.generate_image(image_prompt)

        except Exception as e:
            print(f"⚠️  Image generation failed: {e}")
            print(f"   Continuing without image...")

        # Post to X (with or without image) - uses X-specific tone
        print(f"📤 Filing news report to X...")
        print(f"   Content: \"{x_text}\"")

        tweet_id = None
        reply_tweet_id = None
        x_success = False

        if image_path:
            print(f"   Image: {image_path}\n")
            x_result = twitter_bot.post_tweet_with_image(x_text, image_path)
        else:
            print(f"   (No image attached)\n")
            x_result = twitter_bot.post_tweet(x_text)

        if x_result:
            tweet_id = x_result['id']
            print(f"✅ X post successful! ID: {tweet_id}")
            x_success = True

            # Post source reply on X
            if needs_source and story_meta:
                print(f"📎 Posting source citation reply on X...")
                time.sleep(2)  # Brief pause before reply

                source_reply = generator.generate_source_reply(x_text, story_meta)
                x_reply_result = twitter_bot.reply_to_tweet(tweet_id, source_reply)

                if x_reply_result:
                    reply_tweet_id = x_reply_result['id']
                    print(f"✅ X source reply posted! ID: {reply_tweet_id}")
                else:
                    print(f"⚠️  X source reply failed")
        else:
            print(f"❌ X post failed")

        # Post to Bluesky (with or without image)
        bluesky_uri = None
        bluesky_reply_uri = None
        bluesky_success = False

        if bluesky_bot:
            print(f"\n🦋 Filing news report to Bluesky...")
            print(f"   Content: \"{bluesky_text}\"")

            if image_path:
                print(f"   Image: {image_path}\n")
                bluesky_result = bluesky_bot.post_skeet_with_image(bluesky_text, image_path)
            else:
                print(f"   (No image attached)\n")
                bluesky_result = bluesky_bot.post_skeet(bluesky_text)

            if bluesky_result:
                bluesky_uri = bluesky_result['uri']
                print(f"✅ Bluesky post successful! URI: {bluesky_uri}")
                bluesky_success = True

                # Post source reply on Bluesky
                if needs_source and story_meta:
                    print(f"📎 Posting source citation reply on Bluesky...")
                    time.sleep(2)  # Brief pause before reply

                    source_reply = generator.generate_source_reply(bluesky_text, story_meta)

                    # Check if source reply is just a URL (for link card)
                    is_url_only = bool(re.match(r'^https?://\S+$', source_reply.strip()))

                    if is_url_only:
                        # Use link card method for URL-only replies
                        bluesky_reply_result = bluesky_bot.reply_to_skeet_with_link(bluesky_uri, source_reply.strip())
                    else:
                        # Use regular reply for text content
                        bluesky_reply_result = bluesky_bot.reply_to_skeet(bluesky_uri, source_reply)

                    if bluesky_reply_result:
                        bluesky_reply_uri = bluesky_reply_result['uri']
                        print(f"✅ Bluesky source reply posted! URI: {bluesky_reply_uri}")
                    else:
                        print(f"⚠️  Bluesky source reply failed")
            else:
                print(f"❌ Bluesky post failed")

        # Record post to history (with IDs from both platforms)
        # Use bluesky_text as canonical content since Bluesky is our primary platform
        if selected_story and (x_success or bluesky_success):
            tracker.record_post(
                selected_story,
                post_content=bluesky_text,
                tweet_id=tweet_id,
                reply_tweet_id=reply_tweet_id,
                bluesky_uri=bluesky_uri,
                bluesky_reply_uri=bluesky_reply_uri,
                image_prompt=image_prompt
            )

        # Determine overall success
        if x_success or bluesky_success:
            print(f"\n{'='*60}")
            platforms_posted = []
            if x_success:
                platforms_posted.append("X")
            if bluesky_success:
                platforms_posted.append("Bluesky")
            print(f"✅ SUCCESS! News report filed to: {', '.join(platforms_posted)}")
            print(f"{'='*60}\n")
            return True
        else:
            print(f"\n{'='*60}")
            print(f"❌ FAILED to post to any platform.")
            print(f"{'='*60}\n")
            return False

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")
        return False


def reply_to_mentions():
    """Check mentions and reply as news cat reporter"""
    print(f"\n{'='*60}")
    print(f"Mewscast - Checking Mentions")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        generator = ContentGenerator()
        bot = TwitterBot()

        print("📨 Fetching recent mentions...")
        mentions = bot.get_mentions(max_results=5)

        if not mentions:
            print("No new mentions found.")
            return True

        print(f"Found {len(mentions)} mention(s)\n")

        for mention in mentions:
            print(f"Processing mention from @{mention.author_id}...")
            print(f"   Text: {mention.text[:100]}...\n")

            # Generate reply
            reply_text = generator.generate_reply(mention.text)

            # Post reply
            bot.reply_to_tweet(mention.id, reply_text)
            print()

        print(f"\n{'='*60}")
        print(f"✅ Processed {len(mentions)} mention(s)")
        print(f"{'='*60}\n")
        return True

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        print(f"{'='*60}\n")
        return False


def post_positive_news():
    """Generate and post a 'Positive News' special report"""
    print(f"\n{'='*60}")
    print(f"Mewscast - SPECIAL REPORT: Positive News")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    try:
        from positive_news_post import PositiveNewsGenerator

        # Get optional topic from CLI args
        topic = None
        if len(sys.argv) > 3:
            topic = " ".join(sys.argv[3:])
        elif len(sys.argv) > 2 and sys.argv[1] != "special":
            topic = " ".join(sys.argv[2:])

        if topic:
            print(f"🌟 Topic: {topic}")
        else:
            print(f"🌟 Auto-searching for positive news...")

        # Initialize positive news generator
        positive_gen = PositiveNewsGenerator()

        # Find a positive story
        story_data = positive_gen.find_positive_story(topic)
        if not story_data:
            print(f"\n❌ Could not find a positive news story.")
            print(f"   Try specifying a topic: python src/main.py special positive \"topic here\"")
            return False

        article = story_data['article']

        print(f"\n{'='*60}")
        print(f"🌟 POSITIVE STORY FOUND!")
        print(f"   {article['source']}: {article['title'][:60]}...")
        print(f"{'='*60}\n")

        # Generate the post
        result = positive_gen.generate_positive_post(story_data)
        if not result:
            print(f"❌ Could not generate positive news post")
            return False

        post_text = result['post_text']

        print(f"\n📝 Positive News Post:\n{post_text}\n")

        # Initialize bots
        print("📡 Connecting to X...")
        twitter_bot = TwitterBot()

        print("🦋 Connecting to Bluesky...")
        try:
            bluesky_bot = BlueskyBot()
        except Exception as e:
            print(f"⚠️  Bluesky connection failed: {e}")
            bluesky_bot = None

        # Generate image
        image_path = None
        image_prompt = None
        try:
            print(f"🎨 Generating image...")
            img_generator = ImageGenerator()
            generator = ContentGenerator()
            image_prompt = generator.generate_image_prompt(
                article['title'],
                post_text,
                article_content=article.get('article_content')
            )
            image_path = img_generator.generate_image(image_prompt)
        except Exception as e:
            print(f"⚠️  Image generation failed: {e}")

        # Add source indicator
        source_indicator = " 📰↓"
        post_text_with_indicator = post_text + source_indicator

        # Post to X
        tweet_id = None
        x_success = False
        print(f"\n📤 Posting positive news to X...")
        if image_path:
            x_result = twitter_bot.post_tweet_with_image(post_text_with_indicator, image_path)
        else:
            x_result = twitter_bot.post_tweet(post_text_with_indicator)

        if x_result:
            tweet_id = x_result['id']
            print(f"✅ X post successful! ID: {tweet_id}")
            x_success = True

            # Post source as reply
            time.sleep(2)
            source_reply = article['url']
            reply_result = twitter_bot.reply_to_tweet(tweet_id, source_reply)
            if reply_result:
                print(f"✅ X source reply posted!")
        else:
            print(f"❌ X post failed")

        # Post to Bluesky
        bluesky_uri = None
        bluesky_success = False
        if bluesky_bot:
            print(f"\n🦋 Posting positive news to Bluesky...")
            if image_path:
                bs_result = bluesky_bot.post_skeet_with_image(post_text_with_indicator, image_path)
            else:
                bs_result = bluesky_bot.post_skeet(post_text_with_indicator)

            if bs_result:
                bluesky_uri = bs_result['uri']
                print(f"✅ Bluesky post successful! URI: {bluesky_uri}")
                bluesky_success = True

                # Post source as reply with link card
                time.sleep(2)
                reply_result = bluesky_bot.reply_to_skeet_with_link(
                    bluesky_uri, article['url']
                )
                if reply_result:
                    print(f"✅ Bluesky source reply posted!")
            else:
                print(f"❌ Bluesky post failed")

        # Record to post history
        if x_success or bluesky_success:
            config = _load_config()
            dedup_config = config.get('deduplication', {})
            tracker = PostTracker(config=dedup_config)

            tracker.record_post(
                article,
                post_content=post_text_with_indicator,
                tweet_id=tweet_id,
                bluesky_uri=bluesky_uri,
                image_prompt=image_prompt
            )

            print(f"\n{'='*60}")
            platforms = []
            if x_success:
                platforms.append("X")
            if bluesky_success:
                platforms.append("Bluesky")
            print(f"✅ POSITIVE NEWS POSTED to: {', '.join(platforms)}")
            print(f"{'='*60}\n")
            return True

        print(f"\n❌ Failed to post positive news to any platform")
        return False

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")
        return False


# ---------------------------------------------------------------------------
# Walter Croncat journalism workflow — Stage 7 orchestrator
# ---------------------------------------------------------------------------

_JOURNALISM_POST_TYPE_ALIASES = {
    "brief": PostType.REPORT,
    "report": PostType.REPORT,
    "meta": PostType.META,
    "analysis": PostType.ANALYSIS,
    "bulletin": PostType.BULLETIN,
    "correction": PostType.CORRECTION,
    "primary": PostType.PRIMARY,
}


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe_filename_component(text: str) -> str:
    """Make a story id / post type safe for use in a filename."""
    if not text:
        return "unknown"
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


def _write_draft_file(
    drafts_dir: str,
    draft: DraftPost,
    dossier: StoryDossier,
    subfolder: str = "",
) -> str:
    """Write a DraftPost + dossier metadata to a markdown file under drafts/.

    Returns the absolute path that was written.
    """
    target_dir = os.path.join(drafts_dir, subfolder) if subfolder else drafts_dir
    os.makedirs(target_dir, exist_ok=True)

    story_slug = _safe_filename_component(draft.story_id)
    type_slug = _safe_filename_component(draft.post_type.value)
    filename = f"{story_slug}_{type_slug}.md"
    path = os.path.join(target_dir, filename)

    # Dedup outlets while preserving first-seen order. When a dossier has
    # two articles from the same outlet (e.g., two WaPo stories on the
    # same event), the draft header was showing "Reuters, WaPo, WaPo, AP"
    # which read as a cosmetic bug. Iteration 9 cleanup.
    _seen_outlets: set[str] = set()
    _unique_outlets: list[str] = []
    for _a in dossier.articles:
        if _a.outlet and _a.outlet not in _seen_outlets:
            _seen_outlets.add(_a.outlet)
            _unique_outlets.append(_a.outlet)
    outlets_list = ", ".join(_unique_outlets) or "(none)"
    primary_urls = ", ".join(p.url for p in dossier.primary_sources) or "(none)"

    dossier_meta = {
        "story_id": dossier.story_id,
        "headline_seed": dossier.headline_seed,
        "detected_at": dossier.detected_at,
        "article_count": len(dossier.articles),
        "primary_source_count": len(dossier.primary_sources),
        "outlet_slants": dossier.outlet_slants,
    }

    body = [
        f"# Croncat DRAFT — {draft.post_type.value}",
        "",
        f"- **story_id**: `{draft.story_id}`",
        f"- **post_type**: {draft.post_type.value}",
        f"- **sign_off**: {draft.sign_off!r}",
        f"- **outlets**: {outlets_list}",
        f"- **primary_sources**: {primary_urls}",
        "",
        "## Draft post",
        "",
        "```",
        draft.text,
        "```",
        "",
        "## Dossier metadata",
        "",
        "```json",
        json.dumps(dossier_meta, indent=2, default=str),
        "```",
        "",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    return path


def post_journalism_cycle(
    dry_run: bool = False,
    forced_post_type: PostType | None = None,
) -> bool:
    """
    Run one cycle of the Walter Croncat journalism pipeline.

    Stages 1-7:
      1. Trend detection (TrendDetector)
      2. Story triage (StoryTriage)
      3. Source gather + primary source find (SourceGatherer, PrimarySourceFinder)
      4. Meta-analysis (MetaAnalyzer -> MetaAnalysisBrief)
      5. Post composition (PostComposer -> DraftPost)
      6. Verification gate (VerificationGate)
      7. Publish (TwitterBot / BlueskyBot) + record dossier

    Args:
      dry_run: if True, write the DraftPost to drafts/<story_id>_<post_type>.md
        instead of publishing. Useful for validation runs.
      forced_post_type: if provided, override the brief's suggested_post_type
        with this one (used by the `journalism brief|meta|bulletin|correction`
        CLI modes for deterministic per-type cycles).

    Returns:
      True: the cycle ran to completion. This may mean a post was published
        or a draft written, OR that there were no newsworthy candidates this
        cycle (a legitimate no-op — Cronkite himself would sometimes not have
        enough for a story).
      False: an actual error occurred — meta-analysis crashed, verification
        gate could not evaluate, the publish path failed on all platforms, etc.
    """
    print(f"\n{'=' * 60}")
    print(f"Walter Croncat journalism cycle — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if dry_run:
        print("Mode: DRY RUN (drafts only, no publish)")
    if forced_post_type:
        print(f"Forced post type: {forced_post_type.value}")
    print(f"{'=' * 60}\n")

    try:
        config = _load_config()
    except Exception as e:
        print(f"[journalism] failed to load config.yaml: {e}")
        return False

    journalism_cfg = config.get("journalism", {}) or {}
    # Config gate — if the master switch is off and this is NOT a dry run,
    # refuse to publish. Dry runs are always allowed because they are the
    # validation mechanism.
    if not journalism_cfg.get("enabled", False) and not dry_run:
        print(
            "[journalism] config.journalism.enabled is false; refusing to "
            "publish. Re-run with --dry-run to generate drafts only."
        )
        return False

    trend_cfg = journalism_cfg.get("trend_detection", {}) or {}
    triage_cfg = journalism_cfg.get("triage", {}) or {}
    gather_cfg = journalism_cfg.get("source_gather", {}) or {}
    meta_cfg = journalism_cfg.get("meta_analysis", {}) or {}
    composer_cfg = journalism_cfg.get("composer", {}) or {}
    verification_cfg = journalism_cfg.get("verification", {}) or {}
    dry_run_cfg = journalism_cfg.get("dry_run", {}) or {}

    max_candidates = int(trend_cfg.get("max_candidates", 15))
    use_llm_triage = bool(triage_cfg.get("use_llm", False))
    target_sources = int(gather_cfg.get("target_count", 7))
    meta_model = meta_cfg.get("model", "claude-opus-4-6")
    composer_model = composer_cfg.get("model", "claude-sonnet-4-6")
    max_length = int(composer_cfg.get("max_length", 280))
    long_form_max_length = int(composer_cfg.get("long_form_max_length", 4000))
    drafts_dir = os.path.join(_project_root(), dry_run_cfg.get("drafts_dir", "drafts"))
    os.makedirs(drafts_dir, exist_ok=True)

    registry_path = os.path.join(
        _project_root(),
        journalism_cfg.get("outlet_registry", "outlet_registry.yaml"),
    )

    # ---- Bot / fetcher init -----------------------------------------------
    # TwitterBot is initialized in BOTH dry-run and publish mode because
    # Stage 1 trend detection reads X regardless of whether we intend to
    # publish. If TwitterBot init fails (e.g. missing credentials), we log
    # and fall through — TrendDetector will gracefully fall back to
    # NewsFetcher. Bluesky stays publish-only: it is never used for trend
    # detection, only for posting.
    twitter_bot = None
    bluesky_bot = None
    generator = None
    tracker = None

    print("[journalism] Initializing TwitterBot for trend detection...")
    try:
        twitter_bot = TwitterBot()
    except Exception as e:
        print(f"[journalism] X bot init failed: {e} — Stage 1 will fall back to NewsFetcher")
        twitter_bot = None

    if not dry_run:
        print("[journalism] Initializing Bluesky + content generator for publish mode...")
        try:
            bluesky_bot = BlueskyBot()
        except Exception as e:
            print(f"[journalism] Bluesky bot init failed: {e}")
            bluesky_bot = None
        if twitter_bot is None and bluesky_bot is None:
            print("[journalism] both X and Bluesky bots failed to init; aborting publish cycle")
            return False
        try:
            generator = ContentGenerator()
        except Exception as e:
            print(f"[journalism] ContentGenerator init failed: {e}")
            generator = None
        dedup_config = config.get("deduplication", {}) or {}
        tracker = PostTracker(config=dedup_config)

    print("[journalism] Initializing NewsFetcher + pipeline stages...")
    news_fetcher = NewsFetcher()
    dossier_store = DossierStore()

    trend_detector = TrendDetector(
        registry_path=registry_path,
        twitter_bot=twitter_bot,
        news_fetcher=news_fetcher,
    )
    story_triage = StoryTriage(use_llm=use_llm_triage)
    source_gatherer = SourceGatherer(
        news_fetcher=news_fetcher,
        registry_path=registry_path,
    )
    primary_finder = PrimarySourceFinder()
    meta_analyzer = MetaAnalyzer(model=meta_model)
    post_composer = PostComposer(
        model=composer_model,
        max_length=max_length,
        long_form_max_length=long_form_max_length,
    )
    verification_gate = VerificationGate(
        max_length=max_length,
        long_form_max_length=long_form_max_length,
    )

    # ---- Stage 1: trend detection -----------------------------------------
    print(f"\n[journalism] Stage 1 — detecting trends (max_candidates={max_candidates})")
    candidates = trend_detector.detect_trends(max_candidates=max_candidates)
    print(f"[journalism] Stage 1 yielded {len(candidates)} candidates")
    if not candidates:
        print("[journalism] no candidates from Stage 1 — clean exit, nothing to post this cycle")
        return True

    # ---- Stage 2: triage --------------------------------------------------
    print("[journalism] Stage 2 — triaging candidates")
    passed = story_triage.triage(candidates)
    print(f"[journalism] Stage 2 passed {len(passed)} / {len(candidates)}")
    if not passed:
        print("[journalism] no candidates passed triage — clean exit, nothing to post this cycle")
        return True

    # ---- Stage 2b: story-level dedup -------------------------------------
    # Walter Croncat runs multiple times per day. Without dedup the pipeline
    # picks the same dominant X story every cycle and burns Claude calls on
    # the same META. Iteration 7 added a persistent `journalism_seen_stories.txt`
    # committed by the dry-run workflow: one story_id per line, plus its first-
    # seen timestamp for future pruning. Before selecting a candidate, we walk
    # the triage-passed list in rank order and pick the first story_id we have
    # not seen today. If every candidate is already seen, we fall through and
    # take the top one anyway (better to re-report than to post nothing) but
    # we log it explicitly so QA sees the fallback firing.
    seen_path = os.path.join(_project_root(), "journalism_seen_stories.txt")
    seen_story_ids: set[str] = set()
    # Iteration 11: semantic dedup via proper-noun overlap. Iteration 10
    # surfaced the Bondi-subpoena-vs-Bondi-deposition case where the same
    # underlying event got two different story_ids because the two outlets
    # used different headline wording. story_id-exact dedup missed it.
    # Fix: store each seen headline alongside the story_id and timestamp,
    # then at dedup time extract proper nouns from the candidate and each
    # seen headline, skip on >= SEMANTIC_DEDUP_OVERLAP shared proper nouns.
    # File format (backward-compatible): <story_id>\t<iso_timestamp>\t<headline>
    # Legacy 1-column and 2-column lines still parse; they just can't
    # contribute to semantic overlap (only byte-identical story_id match).
    def _clean_headline_for_matching(h: str) -> str:
        """Normalize a headline for semantic dedup: strip outlet suffix and
        fluff prefix. Both transforms are idempotent. Used at two sites:
        the seen-file read path (to populate noun sets) and the
        _semantic_match candidate path (to extract the candidate's nouns).
        Both sites must use the same normalization for symmetric matching.

        Iteration 16 added the outlet suffix strip (Bug 24: Adam Back vs
        Rex Heuermann false-matched via {new, york, times} suffix tokens).
        Iteration 17 added the fluff prefix strip (Bug 25: any two stories
        starting with "Live Updates:" false-matched via {live, updates}).
        """
        if not h:
            return ""
        # Strip outlet suffix first (e.g. " - The New York Times")
        cleaned = _SUFFIX_STRIP_RE.sub("", h).strip()
        # Then strip fluff prefix (e.g. "Live Updates:", "BREAKING:")
        for prefix in _FLUFF_PREFIXES:
            if cleaned.upper().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        return cleaned

    SEEN_PRUNE_DAYS = 14
    # Semantic-dedup threshold. 2 shared proper nouns is intentionally loose
    # because news headlines are often written in different phrasings for the
    # same event (e.g., "Bondi won't testify" vs "Bondi Won't Appear on Capitol
    # Hill for Scheduled Epstein Deposition" — they share exactly {bondi,
    # epstein}, which is 2). Threshold 3 missed that case in iteration 10.
    # Tradeoff: 2 will occasionally collapse two legitimately-distinct
    # political stories that share two common named entities (e.g. "Trump +
    # Iran deal" and "Trump fires Iran envoy") into one cycle's worth of
    # coverage. In practice, re-reporting related Trump/Iran stories within
    # a 14-day window is acceptable because the trend feed moves faster than
    # our cycle cadence anyway.
    SEMANTIC_DEDUP_OVERLAP = 2  # >= this many shared proper nouns = same story
    seen_header_lines: list[str] = []
    seen_kept_lines: list[str] = []
    # list of (story_id, headline, proper_noun_set) for semantic matching
    seen_entries: list[tuple[str, str, set[str]]] = []
    pruned_count = 0
    try:
        if os.path.exists(seen_path):
            now_utc = datetime.now(timezone.utc)
            with open(seen_path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.rstrip("\n")
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("#"):
                        seen_header_lines.append(raw)
                        continue
                    # Format: "<story_id>\t<iso_timestamp>\t<headline>" (new),
                    # or "<story_id>\t<iso_timestamp>" (iteration 7), or just
                    # "<story_id>" (legacy).
                    parts = stripped.split("\t", 2)
                    story_id_part = parts[0].strip()
                    if not story_id_part:
                        continue
                    # Pruning decision: if we can parse a timestamp and it's
                    # older than the threshold, drop the entry. If we can't
                    # parse a timestamp (legacy / malformed lines), keep it —
                    # we don't have enough information to prune safely.
                    keep = True
                    if len(parts) >= 2:
                        ts_str = parts[1].strip()
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            age_days = (now_utc - ts).total_seconds() / 86400.0
                            if age_days > SEEN_PRUNE_DAYS:
                                keep = False
                                pruned_count += 1
                        except Exception:
                            pass  # unparseable timestamp — keep the entry
                    if keep:
                        seen_kept_lines.append(raw)
                        seen_story_ids.add(story_id_part)
                        # Capture the headline for semantic dedup if present.
                        # Legacy lines without a headline column still get
                        # story_id-exact matching; just no semantic signal.
                        headline_part = parts[2].strip() if len(parts) >= 3 else ""
                        # Iteration 16 + 17: normalize headlines by stripping
                        # outlet suffix AND fluff prefix before extracting
                        # proper nouns. Two bugs in the same class:
                        # - Bug 24 (iter 16): Adam Back vs Rex Heuermann
                        #   false-matched via {new, york, times} suffix
                        # - Bug 25 (iter 17): Live Updates prefix stories
                        #   false-matched via {live, updates}
                        # Both stripped via _clean_headline_for_matching().
                        headline_for_nouns = _clean_headline_for_matching(headline_part)
                        nouns = _extract_proper_nouns(headline_for_nouns) if headline_for_nouns else set()
                        seen_entries.append((story_id_part, headline_part, nouns))
            # If any entries were pruned, rewrite the file. The workflow's
            # commit step will pick up the change and commit it just like
            # a mark-as-seen append.
            if pruned_count > 0:
                try:
                    with open(seen_path, "w", encoding="utf-8") as f:
                        for h in seen_header_lines:
                            f.write(h + "\n")
                        for k in seen_kept_lines:
                            f.write(k + "\n")
                    print(f"[journalism] pruned {pruned_count} seen-stories entries "
                          f"older than {SEEN_PRUNE_DAYS} days")
                except Exception as e:
                    print(f"[journalism] could not rewrite pruned seen-stories file ({e})")
    except Exception as e:
        print(f"[journalism] could not read seen-stories file ({e}); continuing without dedup")

    def _semantic_match(cand_headline: str) -> tuple[bool, str, int]:
        """Return (is_match, matched_story_id, overlap_count) if this candidate
        headline shares >=SEMANTIC_DEDUP_OVERLAP proper nouns with any seen
        entry that has a stored headline. Otherwise (False, '', 0).

        Iteration 16 + 17: the candidate is normalized through
        _clean_headline_for_matching (strips both outlet suffix and fluff
        prefix) before extracting proper nouns. The seen entries are
        normalized the same way at read time, so the comparison is
        symmetric. Without this, outlet-suffix tokens and prefix-fluff
        tokens would create spurious matches between unrelated stories.
        """
        cand_for_nouns = _clean_headline_for_matching(cand_headline)
        cand_nouns = _extract_proper_nouns(cand_for_nouns)
        if len(cand_nouns) < SEMANTIC_DEDUP_OVERLAP:
            return (False, "", 0)
        for sid, shl, snouns in seen_entries:
            if not snouns:
                continue
            overlap = len(cand_nouns & snouns)
            if overlap >= SEMANTIC_DEDUP_OVERLAP:
                return (True, sid, overlap)
        return (False, "", 0)

    candidate = None
    skipped_count = 0
    for c in passed:
        # (1) Exact story_id dedup — cheap, catches same-headline-same-day
        if c.story_id in seen_story_ids:
            skipped_count += 1
            print(f"[journalism] skipping already-seen story_id={c.story_id} "
                  f"({c.headline_seed[:60]}...)")
            continue
        # (2) Semantic dedup via proper-noun overlap — catches same-event-
        #     different-headline (iteration 11 Bug 19 fix).
        matched, matched_sid, overlap = _semantic_match(c.headline_seed)
        if matched:
            skipped_count += 1
            print(f"[journalism] skipping semantically-duplicate candidate "
                  f"({c.headline_seed[:60]}...) — {overlap} proper nouns match "
                  f"already-seen story_id={matched_sid}")
            continue
        candidate = c
        break

    if candidate is None:
        # Every triage-passed candidate is already in the seen set.
        # Clean exit — same semantics as "no candidates passed triage":
        # nothing new to report this cycle. Iteration 7 originally fell
        # through to passed[0] ("better to re-report than sit out"), but
        # iteration 13 run 30 proved that logic wrong: re-reporting a
        # story Cronkite already filed is worse than skipping the cycle.
        # Cronkite didn't do the same lead twice on the same broadcast.
        print(
            f"[journalism] all {len(passed)} triage-passed candidates are already "
            f"in the seen set (exact or semantic); clean exit, nothing new to report "
            f"this cycle"
        )
        return True

    if skipped_count > 0:
        print(f"[journalism] dedup skipped {skipped_count} already-seen candidate(s); "
              f"selected the next unseen story")

    print(f"[journalism] Selected candidate: {candidate.headline_seed[:80]}...")

    # ---- Stage 3: gather + primary source ---------------------------------
    print("[journalism] Stage 3a — gathering sources")
    dossier = source_gatherer.gather(candidate, target_count=target_sources)
    print(f"[journalism] Stage 3a collected {len(dossier.articles)} articles")

    print("[journalism] Stage 3b — finding primary sources")
    added_primary = primary_finder.find(dossier)
    print(f"[journalism] Stage 3b added {len(added_primary)} primary sources")

    dossier_store.save_dossier(dossier)

    # Bug 5 short-circuit: a 0-article dossier has nothing for Stage 4 to
    # analyze. Burning Opus + Sonnet calls only to have Stage 6 reject on
    # source_count is a waste. Treat this as a clean no-op cycle (same
    # semantics as "no candidates passed triage").
    if len(dossier.articles) == 0:
        print(
            f"[journalism] Stage 3 returned 0 articles for "
            f"'{candidate.headline_seed[:80]}...' — clean exit, "
            f"nothing to report on this cycle"
        )
        return True

    # ---- Stage 4: meta-analysis -------------------------------------------
    print("[journalism] Stage 4 — meta-analysis")
    try:
        brief = meta_analyzer.analyze(dossier)
    except Exception as e:
        print(f"[journalism] Stage 4 failed: {e}")
        return False
    dossier_store.save_brief(brief)
    print(
        f"[journalism] Stage 4 suggested_post_type="
        f"{brief.suggested_post_type.value} confidence={brief.confidence}"
    )

    # ---- Stage 5: compose -------------------------------------------------
    chosen_type = forced_post_type or brief.suggested_post_type
    print(f"[journalism] Stage 5 — composing {chosen_type.value} post")
    try:
        # Don't pass max_length — let the composer pick the right budget
        # per post type (long_form_max_length for META, max_length for the
        # rest). Passing max_length=280 here is how the char_limit bug
        # slipped in before.
        draft = post_composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=chosen_type,
        )
    except Exception as e:
        print(f"[journalism] Stage 5 failed: {e}")
        return False

    # ---- Stage 6: verification gate (with single retry) -------------------
    print("[journalism] Stage 6 — verifying draft")
    result = verification_gate.verify(draft, dossier)
    if not result.passed:
        print(f"[journalism] Stage 6 failures: {result.failures}")
        print("[journalism] Stage 6 — retry composing with gate feedback")
        try:
            draft = post_composer.compose(
                brief=brief,
                dossier=dossier,
                post_type=chosen_type,
                retry_reasons=result.failures,
            )
        except Exception as e:
            print(f"[journalism] Stage 5 retry failed: {e}")
            return False
        result = verification_gate.verify(draft, dossier)
        if not result.passed:
            print(f"[journalism] Stage 6 FINAL failures: {result.failures}")
            rejected_path = _write_draft_file(
                drafts_dir, draft, dossier, subfolder="rejected"
            )
            print(f"[journalism] rejected draft written to {rejected_path}")
            return False

    # ---- Stage 7: publish or dry-run write --------------------------------

    # Mark the story as seen BEFORE writing the draft so the seen-stories
    # file reflects that this story has been successfully processed this
    # cycle. If we crash between draft-write and mark-seen, the next run
    # would pick it up again — acceptable, since "re-report after a crash"
    # is better than "silently skip after a crash." Idempotent: if the
    # story_id is already in the file, this is a no-op.
    try:
        already_seen = candidate.story_id in seen_story_ids
        if not already_seen:
            # Iteration 11: include the headline_seed as a 3rd TSV column
            # so future runs can do semantic dedup against it. Sanitize
            # any stray tabs or newlines in the headline to preserve the
            # one-record-per-line TSV format.
            safe_headline = (candidate.headline_seed or "").replace("\t", " ").replace("\n", " ").strip()
            with open(seen_path, "a", encoding="utf-8") as f:
                f.write(
                    f"{candidate.story_id}\t"
                    f"{datetime.now(timezone.utc).isoformat()}\t"
                    f"{safe_headline}\n"
                )
            print(f"[journalism] marked story_id={candidate.story_id} as seen")
    except Exception as e:
        print(f"[journalism] could not update seen-stories file ({e}); continuing")

    if dry_run:
        path = _write_draft_file(drafts_dir, draft, dossier)
        print(f"[journalism] DRY RUN draft written to {path}")
        return True

    print("[journalism] Stage 7 — publishing")

    # Best-effort image generation — reuse the existing content generator
    # path used by post_scheduled_tweet. Failure is not fatal.
    image_path = None
    image_prompt = None
    if generator is not None:
        try:
            image_prompt = generator.generate_image_prompt(
                dossier.headline_seed,
                draft.text,
                article_content=dossier.articles[0].body if dossier.articles else None,
            )
            img_gen = ImageGenerator()
            image_path = img_gen.generate_image(image_prompt)
        except Exception as e:
            print(f"[journalism] image generation failed (continuing): {e}")

    # Primary publish: post to X and Bluesky. We reuse the same text for
    # both platforms in this first rollout; a later phase can specialize.
    post_text = draft.text

    tweet_id = None
    reply_tweet_id = None
    x_success = False
    if twitter_bot is not None:
        try:
            if image_path:
                x_result = twitter_bot.post_tweet_with_image(post_text, image_path)
            else:
                x_result = twitter_bot.post_tweet(post_text)
            if x_result:
                tweet_id = x_result.get("id")
                x_success = True
                print(f"[journalism] X post ok: {tweet_id}")

                # Source-link reply if we have a primary source url
                primary_url = (
                    dossier.primary_sources[0].url
                    if dossier.primary_sources
                    else (dossier.articles[0].url if dossier.articles else None)
                )
                if primary_url:
                    time.sleep(2)
                    reply_result = twitter_bot.reply_to_tweet(tweet_id, primary_url)
                    if reply_result:
                        reply_tweet_id = reply_result.get("id")
        except Exception as e:
            print(f"[journalism] X publish failed: {e}")

    bluesky_uri = None
    bluesky_reply_uri = None
    bluesky_success = False
    if bluesky_bot is not None:
        try:
            if image_path:
                bs_result = bluesky_bot.post_skeet_with_image(post_text, image_path)
            else:
                bs_result = bluesky_bot.post_skeet(post_text)
            if bs_result:
                bluesky_uri = bs_result.get("uri")
                bluesky_success = True
                print(f"[journalism] Bluesky post ok: {bluesky_uri}")

                primary_url = (
                    dossier.primary_sources[0].url
                    if dossier.primary_sources
                    else (dossier.articles[0].url if dossier.articles else None)
                )
                if primary_url:
                    time.sleep(2)
                    reply_result = bluesky_bot.reply_to_skeet_with_link(
                        bluesky_uri, primary_url
                    )
                    if reply_result:
                        bluesky_reply_uri = reply_result.get("uri")
        except Exception as e:
            print(f"[journalism] Bluesky publish failed: {e}")

    if not (x_success or bluesky_success):
        print("[journalism] no platform accepted the post; failing cycle")
        return False

    # Record to post history + dossier store
    if tracker is not None:
        synthetic_story = {
            "title": dossier.headline_seed,
            "url": dossier.articles[0].url if dossier.articles else None,
            "source": dossier.articles[0].outlet if dossier.articles else "Unknown",
        }
        tracker.record_post(
            synthetic_story,
            post_content=post_text,
            tweet_id=tweet_id,
            reply_tweet_id=reply_tweet_id,
            bluesky_uri=bluesky_uri,
            bluesky_reply_uri=bluesky_reply_uri,
            image_prompt=image_prompt,
            dossier_id=draft.story_id,
            post_type=draft.post_type.value,
        )

    post_url = None
    if tweet_id:
        post_url = f"https://x.com/i/web/status/{tweet_id}"
    elif bluesky_uri:
        post_url = bluesky_uri
    dossier_store.save_post_record(draft.story_id, draft, post_url=post_url)

    print(f"\n{'=' * 60}")
    print("[journalism] cycle complete")
    print(f"{'=' * 60}\n")
    return True


def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()

    # Check mode from environment or argument
    mode = os.getenv("BOT_MODE", "scheduled")

    if len(sys.argv) > 1:
        mode = sys.argv[1]

    print(f"\n🚀 Starting Mewscast in '{mode}' mode...\n")

    if mode == "scheduled" or mode == "post":
        success = post_scheduled_tweet()
    elif mode == "reply":
        success = reply_to_mentions()
    elif mode == "both":
        success1 = post_scheduled_tweet()
        success2 = reply_to_mentions()
        success = success1 and success2
    elif mode == "special":
        # Special edition posts
        special_type = sys.argv[2] if len(sys.argv) > 2 else None
        if special_type == "positive":
            success = post_positive_news()
        else:
            print(f"❌ Unknown special post type: {special_type}")
            print("Available special types:")
            print("  positive [topic]  - Positive News Special Report")
            sys.exit(1)
    elif mode == "journalism":
        # Walter Croncat journalism workflow — new pipeline.
        #
        # Subcommands:
        #   python src/main.py journalism                  # one cycle, real publish
        #   python src/main.py journalism --dry-run        # one cycle, drafts only
        #   python src/main.py journalism brief            # force a REPORT cycle
        #   python src/main.py journalism meta             # force a META cycle
        #   python src/main.py journalism bulletin         # force a BULLETIN cycle
        #   python src/main.py journalism correction       # force a CORRECTION cycle
        #
        # --dry-run can be combined with any post-type subcommand.
        extra_args = [a for a in sys.argv[2:]]
        dry_run = "--dry-run" in extra_args
        extra_args = [a for a in extra_args if a != "--dry-run"]

        forced_type: PostType | None = None
        if extra_args:
            subtype = extra_args[0].lower()
            if subtype in _JOURNALISM_POST_TYPE_ALIASES:
                forced_type = _JOURNALISM_POST_TYPE_ALIASES[subtype]
            else:
                print(f"❌ Unknown journalism post type: {subtype}")
                print("Available: brief, meta, analysis, bulletin, correction, primary")
                sys.exit(1)

        success = post_journalism_cycle(dry_run=dry_run, forced_post_type=forced_type)
    else:
        print(f"❌ Unknown mode: {mode}")
        print("Available modes: scheduled, reply, both, special, journalism")
        sys.exit(1)

    # Exit with appropriate code for CI/CD
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
