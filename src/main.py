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
from dossier_store import DossierStore, DraftPost, PostType, SIGN_OFFS, StoryDossier
from trend_detector import TrendDetector, TrendCandidate, _extract_proper_nouns, _stable_story_id
from story_triage import StoryTriage
from source_gatherer import _FLUFF_PREFIXES, _SUFFIX_STRIP_RE, SourceGatherer
from primary_source_finder import PrimarySourceFinder
from meta_analyzer import MetaAnalyzer
from post_composer import PostComposer
from verification_gate import (
    CHAR_LIMIT_REASON_PREFIX,
    VerificationGate,
    VerificationResult,
)
from draft_analyzer import analyze_draft, print_analysis
from dossier_renderer import (
    bluesky_web_url,
    render_dossier_page,
    render_index_page,
    render_sitemap,
)


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
            print(f"⚠️  Bluesky connection failed: {type(e).__name__}: {e!r}")
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
        image_prompt = None  # full anchored prompt sent to Grok — for audit
        try:
            print(f"🎨 Attempting to generate image with Grok...")
            img_generator = ImageGenerator()

            # Generate image prompt using Claude (with full article for story-specific imagery)
            # Use bluesky text since it's more straightforward
            dynamic_prompt = generator.generate_image_prompt(
                selected_story['title'] if selected_story else "news",
                bluesky_text,
                article_content=selected_story.get('article_content') if selected_story else None
            )

            # Generate image using Grok. Capture the full anchored prompt
            # (subject + eye-catch + style + dynamic) so audit history has the
            # exact bytes that were sent to the model, not just the Claude part.
            image_path, image_prompt = img_generator.generate_image(dynamic_prompt)

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
                image_prompt=image_prompt,
                post_pipeline="legacy",
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


def _inline_dossier_url_into_meta(
    text: str,
    dossier_url: str,
    sign_off: str | None,
) -> str:
    """Return META post text with the dossier URL inlined before the sign-off.

    META posts are long-form (6500-char budget) and the self-reply pattern
    added a second tweet that looked redundant in the profile feed — the
    first line of a META post is often visible in the feed view while the
    rest is collapsed behind "Show more". Inlining the URL makes the
    dossier link part of the same post, so no self-reply is needed.

    Shape:
        {body text}

        Full dossier: {url}

        {sign_off}

    If the draft doesn't end with the expected sign-off (shouldn't happen
    — the verification gate enforces it — but defend anyway), the URL is
    appended to the end.
    """
    if sign_off and text.rstrip().endswith(sign_off):
        body = text.rstrip()[: -len(sign_off)].rstrip()
        return f"{body}\n\nFull dossier: {dossier_url}\n\n{sign_off}"
    return f"{text.rstrip()}\n\nFull dossier: {dossier_url}"


def _compose_dossier_reply_text(
    brief_data: dict | None,
    outlet_count: int,
) -> str:
    """Short self-reply line that introduces the dossier link.

    Picks a template based on what the brief flagged — disagreements,
    missing context, or multi-outlet framing differences. Falls back
    to a generic line when the brief is empty or none of the hooks
    apply. Pure function; no I/O.

    Callers append a newline + dossier URL after this string to form
    the full reply body. Budget: ~240 chars, leaving room for the URL.
    """
    brief_data = brief_data or {}
    disagreements = brief_data.get("disagreements") or []
    missing_context = brief_data.get("missing_context") or []
    framing = brief_data.get("framing_analysis") or {}

    # Avoid ungrammatical "1 outlets". Below 2, use a plural-neutral phrase.
    count_phrase = f"{outlet_count} outlets" if outlet_count >= 2 else "these outlets"

    if disagreements:
        return f"Where {count_phrase}' accounts diverge — full dossier:"
    if missing_context:
        return f"What {count_phrase} reported — and what they left out:"
    if len(framing) >= 3:
        n = outlet_count if outlet_count >= 2 else len(framing)
        return f"{n} outlets, {n} framings — cross-outlet breakdown:"
    return "Full cross-outlet dossier on this story:"


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


def _generate_journalism_image(
    draft: DraftPost, dossier: StoryDossier, save_path: str = "temp_image.png"
) -> tuple:
    """Generate a post-type-aware image for a journalism post.

    Returns (image_file_path, anchored_prompt) on success, (None, None) on
    failure. The `anchored_prompt` is the FULL prompt sent to the image
    model — subject + eye-catch + style-anchor + dynamic prompt — captured
    for audit. Best-effort: never raises.
    """
    try:
        print(f"[journalism] generating {draft.post_type.value}-style image...")
        article_body = dossier.articles[0].body if dossier.articles else ""
        article_section = (
            f"\nFULL ARTICLE CONTENT (extract visual details):\n{article_body[:3000]}\n"
            if article_body else ""
        )

        img_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "journalism_image.md"
        )
        with open(img_prompt_path, "r", encoding="utf-8") as f:
            img_template = f.read()

        img_request = img_template.replace("{post_type}", draft.post_type.value)
        img_request = img_request.replace("{topic}", dossier.headline_seed[:200])
        img_request = img_request.replace("{draft_text}", draft.text[:500])
        img_request = img_request.replace("{article_section}", article_section)

        from anthropic import Anthropic as _Anthropic
        _img_client = _Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        _img_resp = _img_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": img_request}],
        )
        image_prompt = _img_resp.content[0].text.strip().strip('"').strip("'")
        # Budget raised to 800 as part of A5 overhaul — matches the legacy
        # content_generator.generate_image_prompt path.
        if len(image_prompt) > 800:
            image_prompt = image_prompt[:800]
        print(f"[journalism] image prompt ({draft.post_type.value}): {image_prompt[:100]}...")

        img_gen = ImageGenerator()
        # Pass post_type so the generator can pick the matching style anchor.
        # Capture the FULL anchored prompt (subject + eye-catch + style +
        # dynamic) and propagate it up — audit history saves what was actually
        # sent to the model, not the pre-anchor Claude suggestion.
        image_path, anchored_prompt = img_gen.generate_image(
            image_prompt,
            save_path=save_path,
            post_type=draft.post_type.value,
        )
        return image_path, anchored_prompt
    except Exception as e:
        print(f"[journalism] image generation failed (continuing): {e}")
        return None, None


def _persist_dossier_image(
    draft: DraftPost,
    dossier_store,
    image_source_path: str,
    image_prompt: str | None = None,
) -> str | None:
    """Copy/persist an image to docs/dossiers/images/ and write the relative
    path — plus the full anchored prompt, if provided — into the dossier
    JSON. Returns the relative image path or None.

    The `image_prompt` argument should be the anchored prompt actually sent
    to the image model (not just the Claude-generated dynamic piece). It is
    written to `raw["image_prompt"]` for audit alongside `raw["image_path"]`.
    """
    try:
        html_dir = os.path.join(_project_root(), "docs", "dossiers")
        images_dir = os.path.join(html_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        safe_id = _safe_filename_component(draft.story_id)
        dest = os.path.join(images_dir, f"{safe_id}.png")

        # If source != dest, copy; otherwise it was already saved there
        if os.path.abspath(image_source_path) != os.path.abspath(dest):
            import shutil
            shutil.copy2(image_source_path, dest)

        rel_path = f"images/{safe_id}.png"

        # Write into dossier JSON so the renderer can find the image AND so
        # the audit trail captures the exact prompt that was sent to Grok.
        raw = dossier_store.read_raw(draft.story_id)
        if raw:
            raw["image_path"] = rel_path
            if image_prompt is not None:
                raw["image_prompt"] = image_prompt
            dossier_store._write(draft.story_id, raw)

        print(f"[journalism] dossier image persisted: {dest}")
        return rel_path
    except Exception as e:
        print(f"[journalism] image persist failed (continuing): {e}")
        return None


def _render_dossier_html(dossier_store, draft: DraftPost, dossier: StoryDossier) -> None:
    """Render dossier HTML page + write a metadata sidecar for the index +
    rebuild the index page. Used by both dry-run and publish paths."""
    try:
        dossier_data = dossier_store.read_raw(draft.story_id)
        if not dossier_data:
            return

        html_dir = os.path.join(_project_root(), "docs", "dossiers")
        os.makedirs(html_dir, exist_ok=True)

        safe_id = _safe_filename_component(draft.story_id)

        # 1. Render the individual dossier page
        dossier_html = render_dossier_page(dossier_data)
        html_path = os.path.join(html_dir, f"{safe_id}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(dossier_html)
        print(f"[journalism] dossier HTML written to {html_path}")

        # 2. Write a metadata sidecar (no article bodies — just index fields).
        # The full dossier JSON is gitignored (copyrighted bodies). This small
        # sidecar file IS committed so the index can be rebuilt on any runner
        # without needing the full JSON.
        import json as _json
        meta = {
            "story_id": draft.story_id,
            "headline_seed": dossier.headline_seed,
            "post_type": draft.post_type.value if draft.post_type else "",
            "confidence": dossier_data.get("brief", {}).get("confidence", 0),
            "published_at": dossier_data.get("post", {}).get("published_at")
                or dossier_data.get("saved_at", ""),
            "draft_text": draft.text,
        }
        meta_path = os.path.join(html_dir, f"{safe_id}.meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            _json.dump(meta, f, indent=2)

        # 2b. Write a brief sidecar for the outlet reply bot.
        # Contains the MetaAnalysisBrief + article outlet/URL list (no bodies).
        # The full dossier JSON is gitignored, but this lightweight sidecar IS
        # committed so the outlet reply bot can score meta-angle quality and
        # match outlet tweets from any CI runner.
        brief_data = dossier_data.get("brief", {})
        if brief_data:
            brief_sidecar = {
                "story_id": draft.story_id,
                "headline_seed": dossier.headline_seed,
                "brief": brief_data,
                "articles": [
                    {"outlet": a.get("outlet", ""), "url": a.get("url", ""),
                     "title": a.get("title", "")}
                    for a in dossier_data.get("dossier", {}).get("articles", [])
                ],
            }
            brief_path = os.path.join(html_dir, f"{safe_id}.brief.json")
            with open(brief_path, "w", encoding="utf-8") as f:
                _json.dump(brief_sidecar, f, indent=2)
            print(f"[journalism] brief sidecar written to {brief_path}")

        # 3. Rebuild the index from all .meta.json files in the directory
        import glob as _glob
        entries = []
        for mp in sorted(_glob.glob(os.path.join(html_dir, "*.meta.json"))):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    m = _json.load(f)
                # Wrap in the structure render_index_page expects
                entries.append({
                    "story_id": m.get("story_id", ""),
                    "dossier": {"headline_seed": m.get("headline_seed", "")},
                    "post": {
                        "draft": {"post_type": m.get("post_type", "")},
                        "published_at": m.get("published_at", ""),
                    },
                    "brief": {"confidence": m.get("confidence", 0)},
                })
            except Exception:
                continue

        index_html = render_index_page(entries)
        index_path = os.path.join(html_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"[journalism] dossier index updated ({len(entries)} entries)")

        # 4. Regenerate sitemap.xml at docs/ root so new dossier pages
        # are discoverable by crawlers and agents. robots.txt at the same
        # level references it. Cheap to rebuild on every publish.
        try:
            sitemap_xml = render_sitemap(entries)
            sitemap_path = os.path.join(_project_root(), "docs", "sitemap.xml")
            with open(sitemap_path, "w", encoding="utf-8") as f:
                f.write(sitemap_xml)
            print(
                f"[journalism] sitemap.xml updated "
                f"({len(entries)} dossiers + static pages)"
            )
        except Exception as e:
            print(f"[journalism] sitemap generation failed (non-fatal): {e}")

    except Exception as e:
        print(f"[journalism] dossier HTML render failed (non-fatal): {e}")


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
    topic: str | None = None,
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
      topic: if provided, skip Stages 1-2 (trend detection + triage) and use
        this as the headline_seed directly. Useful for testing the pipeline
        against a specific story.

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
    if topic:
        print(f"Manual topic: {topic[:100]}")
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
    max_fallback_candidates = int(gather_cfg.get("max_fallback_candidates", 3))
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
        bluesky_bot = None
        for _attempt in range(1, 4):
            try:
                bluesky_bot = BlueskyBot()
                break
            except Exception as e:
                print(f"[journalism] Bluesky init attempt {_attempt}/3 failed: {type(e).__name__}: {e!r}")
                if _attempt < 3:
                    time.sleep(5 * _attempt)
        if bluesky_bot is None:
            print("[journalism] Bluesky init failed after 3 attempts; continuing X-only")
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

    # ---- Manual topic override: skip Stages 1-2 ----------------------------
    if topic:
        detected_at = datetime.now(timezone.utc).isoformat()
        manual_candidate = TrendCandidate(
            headline_seed=topic.strip(),
            detected_at=detected_at,
            source_signals=["manual"],
            engagement=0,
            story_id=_stable_story_id(topic.strip(), detected_at),
            source="manual",
        )
        print(f"[journalism] Skipping Stages 1-2 (manual topic)")
        print(f"[journalism] Synthetic candidate: {manual_candidate.headline_seed[:80]}...")
        candidate = manual_candidate
        passed = [manual_candidate]
    else:
        # ---- Stage 1: trend detection -----------------------------------------
        print(f"\n[journalism] Stage 1 — detecting trends (max_candidates={max_candidates})")
        candidates = trend_detector.detect_trends(max_candidates=max_candidates)
        print(f"[journalism] Stage 1 yielded {len(candidates)} candidates")
        if not candidates:
            print("[journalism] no candidates from Stage 1 — clean exit, nothing to post this cycle")
            print("[journalism] CYCLE END: published=0 reason=no_stage1_candidates")
            return True

        # ---- Stage 2: triage --------------------------------------------------
        print("[journalism] Stage 2 — triaging candidates")
        passed = story_triage.triage(candidates)
        print(f"[journalism] Stage 2 passed {len(passed)} / {len(candidates)}")
        if not passed:
            print("[journalism] no candidates passed triage — clean exit, nothing to post this cycle")
            print("[journalism] CYCLE END: published=0 reason=no_triage_passes")
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
    # Iteration 18 Bug 26 stoplist: common headline verbs, prepositions,
    # and institutional tokens that pollute the title-case proper-noun set.
    # Without filtering these, any two stories with the same institution
    # doing the same action (e.g., "Senate Passes Bill" vs "House Passes
    # Bill", "Pentagon Announces X" vs "Pentagon Announces Y") would share
    # 2+ tokens and false-match. The stoplist is applied AFTER the
    # suffix/prefix strip but BEFORE the overlap comparison.
    #
    # Conservative list — includes only tokens that are structurally
    # high-frequency in news headlines AND not distinctive as entities.
    # Tokens like "Trump", "Biden", "Iran" stay IN the noun set because
    # they're actual entity content.
    _DEDUP_STOP_TOKENS = {
        # Title-case common verbs (noise, not content entities)
        "says", "said", "reports", "report", "claims", "claim",
        "denies", "deny", "denied", "declares", "declare", "declared",
        "announces", "announce", "announced",
        "passes", "passed", "rules", "ruled", "ruling",
        "charges", "charge", "charged", "considers", "considered",
        "issues", "issued", "votes", "voted", "voting",
        "vetoes", "vetoed", "approves", "approved", "rejects", "rejected",
        "warns", "urges", "seeks", "admits", "reveals",
        # Prepositions/conjunctions capitalized in title case
        "against", "with", "from", "after", "before", "over", "under",
        "into", "onto", "through", "about", "between", "during", "while",
        # Institutional tokens — too common across unrelated stories to
        # serve as distinctive entity match keys on their own
        "house", "senate", "congress", "court", "committee",
        "administration", "department", "pentagon", "doj", "white",
        # Generic headline fillers
        "bill", "case", "plan", "deal", "news", "update", "report",
        "statement", "probe", "inquiry", "investigation",
    }

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

    def _dedup_nouns(h: str) -> set[str]:
        """Extract proper nouns for semantic dedup: clean the headline,
        extract capitalized tokens, then filter out the Bug-26 stoplist
        (common title-case verbs + institutional tokens + prepositions +
        generic headline fillers) that would otherwise cause false
        positives between unrelated stories sharing the same institutional
        actor and action verb."""
        cleaned = _clean_headline_for_matching(h)
        if not cleaned:
            return set()
        return _extract_proper_nouns(cleaned) - _DEDUP_STOP_TOKENS

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
                        # Iterations 16-18: three-stage normalization for
                        # semantic dedup noun extraction:
                        #   - Strip outlet suffix (Bug 24, iter 16)
                        #   - Strip fluff prefix (Bug 25, iter 17)
                        #   - Apply stoplist filter (Bug 26, iter 18)
                        # All three are bundled in _dedup_nouns().
                        nouns = _dedup_nouns(headline_part) if headline_part else set()
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

        Iterations 16-18: the candidate is normalized through _dedup_nouns
        which strips outlet suffix (iter 16), fluff prefix (iter 17), and
        filters a stoplist of common title-case noise tokens (iter 18)
        before computing the noun set. The seen entries are normalized
        the same way at read time so the comparison is symmetric.
        """
        cand_nouns = _dedup_nouns(cand_headline)
        if len(cand_nouns) < SEMANTIC_DEDUP_OVERLAP:
            return (False, "", 0)
        for sid, shl, snouns in seen_entries:
            if not snouns:
                continue
            overlap = len(cand_nouns & snouns)
            if overlap >= SEMANTIC_DEDUP_OVERLAP:
                return (True, sid, overlap)
        return (False, "", 0)

    # When a manual topic is provided, candidate is already set — preserve it
    # through the dedup loop (the loop will break immediately).
    candidate = candidate if topic else None
    skipped_count = 0
    for c in passed:
        if candidate is not None:
            break
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
        print("[journalism] CYCLE END: published=0 reason=all_candidates_seen")
        return True

    if skipped_count > 0:
        print(f"[journalism] dedup skipped {skipped_count} already-seen candidate(s); "
              f"selected the next unseen story")

    print(f"[journalism] Selected candidate: {candidate.headline_seed[:80]}...")

    # ---- Stage 3: gather + primary source (with fallback loop) ------------
    # Build a ranked list of fallback candidates from the triage-passed set.
    # If the primary candidate yields 0 articles, try the next unseen one.
    fallback_candidates = [candidate]
    for c in passed:
        if len(fallback_candidates) >= max_fallback_candidates:
            break
        if c is candidate:
            continue
        if c.story_id in seen_story_ids:
            continue
        matched, _, _ = _semantic_match(c.headline_seed)
        if matched:
            continue
        fallback_candidates.append(c)

    dossier = None
    for fb_idx, fb_candidate in enumerate(fallback_candidates, start=1):
        fb_label = f"[{fb_idx}/{len(fallback_candidates)}]"
        print(f"[journalism] {fb_label} Stage 3a — gathering sources for: "
              f"{fb_candidate.headline_seed[:70]}...")
        fb_dossier = source_gatherer.gather(
            fb_candidate,
            target_count=target_sources,
            seed_urls=getattr(fb_candidate, "original_urls", []),
        )
        print(f"[journalism] {fb_label} Stage 3a collected {len(fb_dossier.articles)} articles")

        print(f"[journalism] {fb_label} Stage 3b — finding primary sources")
        added_primary = primary_finder.find(fb_dossier)
        print(f"[journalism] {fb_label} Stage 3b added {len(added_primary)} primary sources")

        dossier_store.save_dossier(fb_dossier)

        # Require at least 2 articles to proceed (type-specific minimums
        # are enforced after Stage 4 decides the post type)
        if len(fb_dossier.articles) < 2:
            print(f"[journalism] {fb_label} only {len(fb_dossier.articles)} articles "
                  f"— trying next candidate")
            continue

        # This candidate worked — use it
        dossier = fb_dossier
        candidate = fb_candidate
        break

    # If all fallback candidates yielded too few articles, clean exit.
    if dossier is None or len(dossier.articles) < 2:
        print(
            f"[journalism] Stage 3 returned 0 articles for all "
            f"{len(fallback_candidates)} candidate(s) — clean exit, "
            f"nothing to report on this cycle"
        )
        print("[journalism] CYCLE END: published=0 reason=no_articles")
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

    # ---- Quality gate: tiered by post type ----------------------------------
    chosen_type = forced_post_type or brief.suggested_post_type

    # Thresholds per post type:
    #   REPORT/META: 3 sources, 0.45 confidence (multi-source corroboration)
    #   BULLETIN:    2 sources, 0.25 confidence (breaking, hedged language —
    #                the safety-net tier; caught runs with 0.30 confidence
    #                that had valid sourcing but died just below the floor)
    #   Others:      2 sources, 0.40 confidence
    _QUALITY_GATES = {
        PostType.REPORT:     {"min_articles": 3, "min_confidence": 0.45},
        PostType.META:       {"min_articles": 3, "min_confidence": 0.45},
        PostType.BULLETIN:   {"min_articles": 2, "min_confidence": 0.25},
        PostType.ANALYSIS:   {"min_articles": 2, "min_confidence": 0.40},
        PostType.PRIMARY:    {"min_articles": 2, "min_confidence": 0.40},
        PostType.CORRECTION: {"min_articles": 2, "min_confidence": 0.40},
    }
    gate = _QUALITY_GATES.get(chosen_type, {"min_articles": 3, "min_confidence": 0.45})
    n_articles = len(dossier.articles)

    if n_articles < gate["min_articles"]:
        # Auto-downgrade: if REPORT/META/ANALYSIS can't meet its 3-source
        # floor but we have ≥2 articles, re-route the story as a BULLETIN
        # (which needs only 2). BULLETIN is the safety-net post type —
        # hedged language, shorter budget — exactly what a thin-sourced
        # story should be published as. Run 24630187199 proved this was a
        # silent killer: 2 articles gathered, gate suggested REPORT, clean
        # exit. Better a smaller post than none.
        bulletin_gate = _QUALITY_GATES[PostType.BULLETIN]
        if (
            not forced_post_type
            and chosen_type in (PostType.REPORT, PostType.META, PostType.ANALYSIS)
            and n_articles >= bulletin_gate["min_articles"]
            and brief.confidence >= bulletin_gate["min_confidence"]
        ):
            print(
                f"[journalism] {chosen_type.value} requires {gate['min_articles']} sources "
                f"but only {n_articles} found — downgrading to BULLETIN"
            )
            chosen_type = PostType.BULLETIN
            gate = bulletin_gate
        else:
            print(
                f"[journalism] {chosen_type.value} requires {gate['min_articles']} sources "
                f"but only {n_articles} found — clean exit"
            )
            print(f"[journalism] CYCLE END: published=0 reason=too_few_articles_for_{chosen_type.value}")
            return True

    if brief.confidence < gate["min_confidence"]:
        print(
            f"[journalism] confidence {brief.confidence:.2f} < "
            f"{gate['min_confidence']} for {chosen_type.value} — clean exit"
        )
        print(f"[journalism] CYCLE END: published=0 reason=low_confidence_{chosen_type.value}")
        return True
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
            # BULLETIN fallback — if a long-form type blew the gate twice,
            # try the same story as a short BULLETIN before giving up.
            # BULLETIN has a tighter char budget and looser stylistic rules
            # (no sign-off, simpler structure) so it passes where the long
            # form fails. Converts "hard failure" into "smaller post" which
            # is almost always preferable to publishing nothing.
            fallback_ok = False
            if chosen_type in (PostType.REPORT, PostType.META, PostType.ANALYSIS):
                print(
                    f"[journalism] Stage 6 — falling back to BULLETIN "
                    f"after {chosen_type.value} failed verification twice"
                )
                try:
                    draft = post_composer.compose(
                        brief=brief,
                        dossier=dossier,
                        post_type=PostType.BULLETIN,
                        retry_reasons=result.failures,
                    )
                    result = verification_gate.verify(draft, dossier)
                    if result.passed:
                        chosen_type = PostType.BULLETIN
                        fallback_ok = True
                        print("[journalism] Stage 6 — BULLETIN fallback verified")
                    else:
                        print(
                            f"[journalism] BULLETIN fallback also failed: "
                            f"{result.failures}"
                        )
                except Exception as e:
                    print(f"[journalism] BULLETIN fallback compose failed: {e}")

            if not fallback_ok:
                rejected_path = _write_draft_file(
                    drafts_dir, draft, dossier, subfolder="rejected"
                )
                print(f"[journalism] rejected draft written to {rejected_path}")
                return False

    # ---- Post-draft factual analysis (FABRICATION is a hard gate) ----------
    # Compares the draft against article bodies for factual accuracy.
    # CLEAN/ESCALATION/SKIPPED → log and continue (informational).
    # FABRICATION → hard reject + retry Stage 5 once. If retry also
    # FABRICATION → reject the story entirely. This prevents publishing
    # drafts that cite outlets not in the source material.
    try:
        findings = analyze_draft(draft.text, candidate.headline_seed, dossier)
        print_analysis(findings)

        if findings.get("overall") == "FABRICATION":
            print("[journalism] FABRICATION detected — retrying Stage 5 with feedback")
            fab_reasons = [
                f"FABRICATION: {f.get('assessment', '')}"
                for f in findings.get("findings", [])
                if f.get("severity") == "major"
            ]
            # Carry the char budget explicitly — rewriting to remove
            # invented claims tends to add hedging words and blow the
            # budget (run 24595360166: fab-retry landed at 323 > 280).
            # The composer's retry path also tightens prompt_target when
            # it sees a char_limit reason, giving the rewrite real headroom.
            fab_reasons.append(
                f"{CHAR_LIMIT_REASON_PREFIX} draft MUST be <= "
                f"{post_composer._effective_max_length(chosen_type)} chars"
            )
            try:
                draft = post_composer.compose(
                    brief=brief,
                    dossier=dossier,
                    post_type=chosen_type,
                    retry_reasons=fab_reasons,
                )
            except Exception as e:
                print(f"[journalism] Stage 5 fabrication-retry failed: {e}")
                return False

            # Re-verify + re-analyze the retry draft
            result = verification_gate.verify(draft, dossier)
            if not result.passed:
                print(f"[journalism] retry draft failed verification: {result.failures}")
                return False

            retry_findings = analyze_draft(draft.text, candidate.headline_seed, dossier)
            print_analysis(retry_findings)

            if retry_findings.get("overall") == "FABRICATION":
                print("[journalism] FABRICATION persists after retry — rejecting story")
                rejected_path = _write_draft_file(
                    drafts_dir, draft, dossier, subfolder="rejected"
                )
                print(f"[journalism] rejected draft written to {rejected_path}")
                return False
            findings = retry_findings

        # Save findings to the dossier for downstream audit
        dossier_store.save_post_record(
            dossier.story_id, draft,
            post_url=None,
        )

        # Persist verification + analysis + selection data for dossier viewer
        try:
            raw = dossier_store.read_raw(dossier.story_id)
            raw["verification"] = result.to_dict() if result else None
            raw["analysis"] = findings if findings else None
            raw["selection"] = {
                "candidates_detected": len(candidates) if candidates else 0,
                "candidates_passed_triage": len(passed) if passed else 0,
                "story_id": candidate.story_id,
                "headline_seed": candidate.headline_seed,
                "source": getattr(candidate, "source", "unknown"),
            }
            dossier_store._write(dossier.story_id, raw)
        except Exception as e:
            print(f"[journalism] failed to persist extended dossier data: {e}")
    except Exception as e:
        print(f"[draft_analyzer] analysis failed (continuing): {e}")

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

        # Best-effort image generation for dry-run dossier preview.
        # Save directly to the dossier images directory (no temp file).
        safe_id = _safe_filename_component(draft.story_id)
        images_dir = os.path.join(_project_root(), "docs", "dossiers", "images")
        os.makedirs(images_dir, exist_ok=True)
        dest_path = os.path.join(images_dir, f"{safe_id}.png")

        image_path, anchored_prompt = _generate_journalism_image(draft, dossier, save_path=dest_path)
        if image_path:
            _persist_dossier_image(draft, dossier_store, image_path, image_prompt=anchored_prompt)

        # Render dossier HTML + rebuild index
        _render_dossier_html(dossier_store, draft, dossier)
        return True

    print("[journalism] Stage 7 — publishing")

    # Best-effort POST-TYPE-AWARE image generation (see prompts/journalism_image.md).
    # `image_prompt` here is the FULL anchored prompt sent to Grok — flows
    # into both the dossier JSON and posts_history.json for full audit.
    image_path, image_prompt = _generate_journalism_image(draft, dossier)
    if image_path:
        _persist_dossier_image(draft, dossier_store, image_path, image_prompt=image_prompt)

    # Primary publish: post to X and Bluesky.
    # META posts on X inline the dossier URL in the post itself (one
    # tweet instead of two) — the self-reply was redundant with the
    # long-form coverage body and cluttered the profile feed. On
    # Bluesky, META is already truncated to 300 chars so inlining the
    # URL would just get chopped off; keep the link-card self-reply
    # there as the discoverable path.
    # All other post types keep the existing self-reply pattern on both.
    dossier_url = f"https://mewscast.us/dossiers/{candidate.story_id}.html"
    is_meta = chosen_type == PostType.META
    if is_meta:
        sign_off = SIGN_OFFS.get(chosen_type)
        x_post_text = _inline_dossier_url_into_meta(draft.text, dossier_url, sign_off)
    else:
        x_post_text = draft.text
    bluesky_post_text = draft.text

    tweet_id = None
    reply_tweet_id = None
    x_success = False
    if twitter_bot is not None:
        try:
            if image_path:
                x_result = twitter_bot.post_tweet_with_image(x_post_text, image_path)
            else:
                x_result = twitter_bot.post_tweet(x_post_text)
            if x_result:
                tweet_id = x_result.get("id")
                x_success = True
                print(f"[journalism] X post ok: {tweet_id}")

                if not is_meta:
                    # Dossier reply — plain-text reply with a short
                    # brief-aware hook line + URL. The banner image was
                    # dropped (too redundant in the profile feed; the
                    # main post already carries imagery).
                    brief_dict = brief.to_dict() if brief else {}
                    outlet_count = len(dossier.articles) if dossier.articles else 0
                    reply_hook = _compose_dossier_reply_text(brief_dict, outlet_count)
                    reply_body = f"{reply_hook}\n{dossier_url}"
                    time.sleep(2)
                    try:
                        reply_result = twitter_bot.reply_to_tweet(tweet_id, reply_body)
                        if reply_result:
                            reply_tweet_id = reply_result.get("id")
                            print(f"[journalism] X dossier reply ok: {reply_tweet_id}")
                    except Exception as re:
                        print(f"[journalism] X dossier reply failed: {re}")
                else:
                    print("[journalism] META — dossier URL inlined, no self-reply")
        except Exception as e:
            print(f"[journalism] X publish failed: {e}")

    bluesky_uri = None
    bluesky_reply_uri = None
    bluesky_success = False
    if bluesky_bot is not None:
        try:
            if image_path:
                bs_result = bluesky_bot.post_skeet_with_image(bluesky_post_text, image_path)
            else:
                bs_result = bluesky_bot.post_skeet(bluesky_post_text)
            if bs_result:
                bluesky_uri = bs_result.get("uri")
                bluesky_success = True
                print(f"[journalism] Bluesky post ok: {bluesky_uri}")

                # Dossier reply — clickable link card (no banner thumbnail).
                # Bluesky allows one embed per post; using a link card keeps
                # the URL clickable, while omitting thumb_image_path drops
                # the banner image. Hook text picked from brief signals.
                # This runs for ALL post types on Bluesky (including META)
                # because the 300-char cap truncates long posts and the
                # link card is how readers reach the dossier.
                brief_dict = brief.to_dict() if brief else {}
                outlet_count = len(dossier.articles) if dossier.articles else 0
                reply_hook = _compose_dossier_reply_text(brief_dict, outlet_count)
                time.sleep(2)
                try:
                    reply_result = bluesky_bot.reply_to_skeet_with_link(
                        bluesky_uri, dossier_url,
                        text=reply_hook,
                    )
                    if reply_result:
                        bluesky_reply_uri = reply_result.get("uri")
                        print(f"[journalism] Bluesky dossier reply ok: {bluesky_reply_uri}")
                except Exception as re:
                    print(f"[journalism] Bluesky dossier reply failed: {re}")
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
            post_pipeline="journalism",
        )

    post_url = None
    if tweet_id:
        post_url = f"https://x.com/i/web/status/{tweet_id}"
    bluesky_url = bluesky_web_url(bluesky_uri) if bluesky_uri else None
    # Back-compat: if X didn't publish, keep post_url pointing at the Bluesky
    # skeet so older consumers still have a canonical link.
    if post_url is None and bluesky_url is not None:
        post_url = bluesky_url
    dossier_store.save_post_record(
        draft.story_id, draft, post_url=post_url, bluesky_url=bluesky_url
    )

    # Render dossier HTML for the public viewer + rebuild index
    _render_dossier_html(dossier_store, draft, dossier)

    print(f"\n{'=' * 60}")
    print("[journalism] cycle complete")
    print(
        f"[journalism] CYCLE END: published=1 post_type={chosen_type.value} "
        f"story_id={draft.story_id}"
    )
    print(f"{'=' * 60}\n")
    return True


def republish_draft(story_id: str, post_text: str, post_type_str: str = "REPORT") -> bool:
    """Publish a specific draft directly — skips Stages 1-6.

    Used when a dry-run produced a good draft and you want to publish
    exactly that text with an image and dossier reply, without re-running
    the full pipeline (which would pick a different trending story).

    Args:
        story_id: the dossier story_id (e.g. "2026-04-11-pope-leo-xiv-issued-0276fdcfd2")
        post_text: the exact post text to publish
        post_type_str: REPORT, META, BULLETIN, ANALYSIS, PRIMARY, CORRECTION

    Returns True on success.
    """
    print(f"\n{'=' * 60}")
    print(f"Walter Croncat republish — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Story: {story_id}")
    print(f"Type:  {post_type_str}")
    print(f"{'=' * 60}\n")

    post_type = PostType(post_type_str)

    # ---- Generate image ------------------------------------------------
    image_path = None
    image_prompt = None
    try:
        print(f"[republish] generating {post_type.value}-style image...")
        img_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "journalism_image.md"
        )
        with open(img_prompt_path, "r", encoding="utf-8") as f:
            img_template = f.read()

        img_request = img_template.replace("{post_type}", post_type.value)
        img_request = img_request.replace("{topic}", post_text[:200])
        img_request = img_request.replace("{draft_text}", post_text[:500])
        img_request = img_request.replace("{article_section}", "")

        from anthropic import Anthropic as _Anthropic
        _img_client = _Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        _img_resp = _img_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": img_request}],
        )
        image_prompt = _img_resp.content[0].text.strip().strip('"').strip("'")
        if len(image_prompt) > 800:
            image_prompt = image_prompt[:800]
        print(f"[republish] image prompt: {image_prompt[:100]}...")

        img_gen = ImageGenerator()
        # Capture the full anchored prompt for audit (posts_history.json).
        image_path, image_prompt = img_gen.generate_image(image_prompt, post_type=post_type.value)
    except Exception as e:
        print(f"[republish] image generation failed (continuing): {e}")

    # ---- Load brief sidecar for dossier-reply personalization ----------
    # The full dossier JSON is gitignored; the brief sidecar is committed
    # alongside the dossier HTML and carries the disagreements/framing/
    # missing-context signals we need. Absence is fine — the compose
    # function falls back to a generic line.
    reply_brief: dict = {}
    reply_outlet_count: int = 0
    try:
        safe_id = _safe_filename_component(story_id)
        brief_sidecar_path = os.path.join(
            _project_root(), "docs", "dossiers", f"{safe_id}.brief.json"
        )
        if os.path.exists(brief_sidecar_path):
            import json as _json
            with open(brief_sidecar_path, "r", encoding="utf-8") as f:
                _sidecar = _json.load(f)
            reply_brief = _sidecar.get("brief", {}) or {}
            reply_outlet_count = len(_sidecar.get("articles", []) or [])
    except Exception as _sidecar_err:
        print(f"[republish] brief sidecar load failed (using generic reply): {_sidecar_err}")

    # ---- Publish to X --------------------------------------------------
    # META posts inline the dossier URL in the X post itself and skip
    # the self-reply (mirrors post_journalism_cycle). Other types keep
    # the self-reply pattern.
    dossier_url = f"https://mewscast.us/dossiers/{story_id}.html"
    is_meta = post_type == PostType.META
    if is_meta:
        sign_off = SIGN_OFFS.get(post_type)
        x_post_text = _inline_dossier_url_into_meta(post_text, dossier_url, sign_off)
    else:
        x_post_text = post_text
    bluesky_post_text = post_text

    tweet_id = None
    reply_tweet_id = None
    x_success = False
    try:
        twitter_bot = TwitterBot()
        if image_path:
            x_result = twitter_bot.post_tweet_with_image(x_post_text, image_path)
        else:
            x_result = twitter_bot.post_tweet(x_post_text)
        if x_result:
            tweet_id = x_result.get("id")
            x_success = True
            print(f"[republish] X post ok: {tweet_id}")

            if is_meta:
                print("[republish] META — dossier URL inlined, no X self-reply")
            else:
                # Dossier reply — plain text, no banner (redundant with the
                # main post's image). Brief-aware hook line.
                reply_hook = _compose_dossier_reply_text(reply_brief, reply_outlet_count)
                reply_body = f"{reply_hook}\n{dossier_url}"
                time.sleep(2)
                try:
                    reply_result = twitter_bot.reply_to_tweet(tweet_id, reply_body)
                    if reply_result:
                        reply_tweet_id = reply_result.get("id")
                        print(f"[republish] X dossier reply ok: {reply_tweet_id}")
                except Exception as re:
                    print(f"[republish] X dossier reply failed: {re}")
    except Exception as e:
        print(f"[republish] X publish failed: {e}")

    # ---- Publish to Bluesky --------------------------------------------
    # Bluesky keeps the link-card self-reply even for META, because the
    # 300-char cap truncates long META bodies and the card is how users
    # reach the dossier.
    bluesky_success = False
    try:
        bluesky_bot = BlueskyBot()
        if image_path:
            bs_result = bluesky_bot.post_skeet_with_image(bluesky_post_text, image_path)
        else:
            bs_result = bluesky_bot.post_skeet(bluesky_post_text)
        if bs_result:
            bluesky_uri = bs_result.get("uri")
            bluesky_success = True
            print(f"[republish] Bluesky post ok: {bluesky_uri}")

            # Dossier reply — clickable link card, no banner thumbnail.
            reply_hook = _compose_dossier_reply_text(reply_brief, reply_outlet_count)
            time.sleep(2)
            try:
                reply_result = bluesky_bot.reply_to_skeet_with_link(
                    bluesky_uri, dossier_url,
                    text=reply_hook,
                )
                if reply_result:
                    print(f"[republish] Bluesky dossier reply ok")
            except Exception as re:
                print(f"[republish] Bluesky dossier reply failed: {re}")
    except Exception as e:
        print(f"[republish] Bluesky publish failed: {e}")

    if not (x_success or bluesky_success):
        print("[republish] no platform accepted the post")
        return False

    # Record to post history
    try:
        tracker = PostTracker()
        tracker.record_post(
            {"title": post_text[:100], "url": None, "source": "republish"},
            post_content=post_text,
            tweet_id=tweet_id,
            reply_tweet_id=reply_tweet_id,
            image_prompt=image_prompt,
            dossier_id=story_id,
            post_type=post_type.value,
            post_pipeline="journalism",
        )
    except Exception as e:
        print(f"[republish] post history record failed: {e}")

    print(f"\n{'=' * 60}")
    print("[republish] done")
    if tweet_id:
        print(f"  X: https://x.com/mewscast/status/{tweet_id}")
    print(f"  Dossier: https://mewscast.us/dossiers/{story_id}.html")
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
        # Pipeline dispatch: honor pipelines.legacy.enabled /
        # pipelines.journalism.enabled in config.yaml. If legacy is paused
        # (the current default), route scheduled posts through the
        # journalism pipeline so every post ships with a dossier. If both
        # are enabled, legacy wins to preserve historical behavior. If
        # both are disabled, error out so it's obvious nothing ran.
        try:
            _cfg = _load_config()
        except Exception as _e:
            print(f"⚠️  Could not load config.yaml ({_e}); defaulting to legacy pipeline")
            _cfg = {}
        _pipelines_cfg = (_cfg.get("pipelines") or {})
        _legacy_enabled = bool((_pipelines_cfg.get("legacy") or {}).get("enabled", True))
        _journalism_enabled = bool((_pipelines_cfg.get("journalism") or {}).get("enabled", False))

        if _legacy_enabled:
            success = post_scheduled_tweet()
        elif _journalism_enabled:
            print(
                "📰 Legacy pipeline paused via config; routing scheduled post "
                "through the Walter Croncat journalism pipeline"
            )
            success = post_journalism_cycle()
        else:
            print(
                "❌ Both pipelines.legacy.enabled and pipelines.journalism.enabled "
                "are false in config.yaml — nothing to run. Flip one to true."
            )
            success = False
    elif mode == "reply":
        success = reply_to_mentions()
    elif mode == "both":
        success1 = post_scheduled_tweet()
        success2 = reply_to_mentions()
        success = success1 and success2
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
        #   python src/main.py journalism --topic "US tariffs on China" --dry-run
        #
        # --dry-run and --topic can be combined with any post-type subcommand.
        extra_args = [a for a in sys.argv[2:]]
        dry_run = "--dry-run" in extra_args
        extra_args = [a for a in extra_args if a != "--dry-run"]

        # Parse --topic "some topic here"
        topic_override: str | None = None
        filtered_args = []
        i = 0
        while i < len(extra_args):
            if extra_args[i] == "--topic" and i + 1 < len(extra_args):
                topic_override = extra_args[i + 1]
                i += 2
            else:
                filtered_args.append(extra_args[i])
                i += 1
        extra_args = filtered_args

        forced_type: PostType | None = None
        if extra_args:
            subtype = extra_args[0].lower()
            if subtype in _JOURNALISM_POST_TYPE_ALIASES:
                forced_type = _JOURNALISM_POST_TYPE_ALIASES[subtype]
            else:
                print(f"❌ Unknown journalism post type: {subtype}")
                print("Available: brief, meta, analysis, bulletin, correction, primary")
                sys.exit(1)

        success = post_journalism_cycle(
            dry_run=dry_run, forced_post_type=forced_type, topic=topic_override
        )
    elif mode == "republish":
        # Republish a specific draft without re-running the pipeline.
        #   python src/main.py republish <story_id>
        # Reads the draft text from docs/dossiers/<story_id>.meta.json
        # (saved during dry-run). No manual text entry needed.
        if len(sys.argv) < 3:
            print("Usage: python src/main.py republish <story_id>")
            sys.exit(1)
        story_id = sys.argv[2]
        # Load draft text and post type from the committed meta sidecar
        meta_path = os.path.join(
            _project_root(), "docs", "dossiers", f"{story_id}.meta.json"
        )
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            post_text = meta.get("draft_text", "")
            post_type_str = meta.get("post_type", "REPORT")
            if not post_text:
                print(f"Error: no draft_text in {meta_path}")
                print("This dossier may predate the draft_text sidecar. "
                      "Re-run the dry-run to regenerate it.")
                sys.exit(1)
            print(f"[republish] loaded draft from {meta_path}")
            print(f"[republish] post type: {post_type_str}")
            print(f"[republish] text ({len(post_text)} chars): {post_text[:80]}...")
        except FileNotFoundError:
            print(f"Error: {meta_path} not found. Run a dry-run first.")
            sys.exit(1)
        success = republish_draft(story_id, post_text, post_type_str)
    else:
        print(f"❌ Unknown mode: {mode}")
        print("Available modes: scheduled, reply, both, special, journalism, republish")
        sys.exit(1)

    # Exit with appropriate code for CI/CD
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
