"""
Outlet reply bot — replies to news outlet tweets with Walter's cross-outlet
dossier analysis when it adds genuine value to the conversation.

After Walter publishes a journalism post, this bot:
  1. Finds eligible recent posts with dossier analysis
  2. Checks if the dossier has a meaningful META angle (disagreements,
     framing differences, missing context)
  3. Searches X for the original outlet's tweet about the same story
  4. Replies with a professional message linking to the full dossier page

Safety invariants:
  - Config-gated (journalism.outlet_reply.enabled must be true)
  - Max 2 replies per day
  - Max 1 reply per outlet per 72 hours
  - Max 1 reply per cycle
  - Only replies to priority outlets
  - Never replies to the same dossier twice
  - Graceful error handling (catch, log, skip)
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import re
import yaml

# Add src to path for sibling imports
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from twitter_bot import TwitterBot
from dossier_store import DossierStore
from trend_detector import _extract_proper_nouns


class OutletReplyBot:
    """Replies to outlet tweets with Walter's cross-outlet dossier analysis."""

    def __init__(self):
        self.bot = TwitterBot()
        self.dossier_store = DossierStore()
        self.config = self._load_config()
        self.registry = self._load_outlet_registry()
        self.history_path = Path(__file__).parent.parent / "outlet_reply_history.json"
        self.reply_history = self._load_reply_history()

    # ---- config & data loading -------------------------------------------

    def _load_config(self) -> dict:
        """Load the journalism.outlet_reply section from config.yaml."""
        config_path = Path(__file__).parent.parent / "config.yaml"
        try:
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f)
            return full_config.get('journalism', {}).get('outlet_reply', {})
        except Exception as e:
            print(f"✗ Could not load config: {e}")
            return {}

    def _load_outlet_registry(self) -> dict:
        """Load outlet_registry.yaml, keyed by outlet name."""
        registry_path = Path(__file__).parent.parent / "outlet_registry.yaml"
        try:
            with open(registry_path, 'r') as f:
                data = yaml.safe_load(f)
            registry = {}
            for outlet in data.get('outlets', []):
                registry[outlet['name']] = outlet
            return registry
        except Exception as e:
            print(f"✗ Could not load outlet registry: {e}")
            return {}

    def _load_reply_history(self) -> dict:
        """Load reply history from JSON file."""
        if self.history_path.exists():
            with open(self.history_path, 'r') as f:
                return json.load(f)
        return {
            'replies': [],
            'last_cleanup': datetime.now(timezone.utc).isoformat()
        }

    def _save_reply_history(self):
        """Save reply history to disk."""
        with open(self.history_path, 'w') as f:
            json.dump(self.reply_history, f, indent=2)
        print("✓ Saved outlet reply history")

    def _cleanup_old_history(self):
        """Remove entries older than 90 days. Runs at most once per week."""
        last_cleanup = datetime.fromisoformat(
            self.reply_history.get('last_cleanup', '2000-01-01T00:00:00+00:00')
        )
        now = datetime.now(timezone.utc)

        if now - last_cleanup < timedelta(days=7):
            return

        print("🧹 Cleaning up old outlet reply history...")
        cutoff = now - timedelta(days=90)

        replies = self.reply_history.get('replies', [])
        original_count = len(replies)
        self.reply_history['replies'] = [
            r for r in replies
            if datetime.fromisoformat(r.get('timestamp', '2000-01-01T00:00:00+00:00')) > cutoff
        ]
        removed = original_count - len(self.reply_history['replies'])
        if removed > 0:
            print(f"   Removed {removed} old reply records")

        self.reply_history['last_cleanup'] = now.isoformat()
        self._save_reply_history()

    # ---- candidate selection ---------------------------------------------

    def _get_recent_journalism_posts(self, hours: int = 8) -> list:
        """Return journalism-pipeline posts from posts_history.json within the window."""
        history_path = Path(__file__).parent.parent / "posts_history.json"
        try:
            with open(history_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"✗ Could not load posts_history.json: {e}")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        eligible = []

        for post in data.get('posts', []):
            if post.get('post_pipeline') != 'journalism':
                continue
            if not post.get('dossier_id'):
                continue
            try:
                ts = datetime.fromisoformat(post['timestamp'].replace('Z', '+00:00'))
                if ts >= cutoff:
                    eligible.append(post)
            except (ValueError, KeyError):
                continue

        # Most recent first
        eligible.sort(key=lambda p: p.get('timestamp', ''), reverse=True)
        return eligible

    def _has_meaningful_meta_angle(self, brief_data: dict) -> bool:
        """Score the dossier brief to decide if it's worth replying.

        Scoring:
          +2 if disagreements list is non-empty
          +2 if framing_analysis has 3+ distinct outlets
          +1 per missing_context entry (max 3)
          +3 if suggested_post_type is META
          +1 if confidence >= 0.60

        Returns True if score >= min_meta_score (config, default 3).
        """
        score = 0

        disagreements = brief_data.get('disagreements', [])
        if disagreements:
            score += 2

        framing = brief_data.get('framing_analysis', {})
        if len(framing) >= 3:
            score += 2

        missing = brief_data.get('missing_context', [])
        score += min(len(missing), 3)

        if brief_data.get('suggested_post_type') == 'META':
            score += 3

        if brief_data.get('confidence', 0) >= 0.60:
            score += 1

        min_score = self.config.get('min_meta_score', 3)
        return score >= min_score

    def _load_dossier_data(self, dossier_id: str) -> dict:
        """Load dossier data, falling back to the brief sidecar.

        The full dossier JSON (dossiers/{story_id}.json) is gitignored and
        only exists locally. In CI, falls back to the committed brief sidecar
        at docs/dossiers/{story_id}.brief.json which contains the brief +
        article outlet/URL list (no bodies).
        """
        # Try full dossier first (local dev)
        data = self.dossier_store.read_raw(dossier_id)
        if data:
            return data

        # Fall back to brief sidecar (CI)
        brief_path = Path(__file__).parent.parent / "docs" / "dossiers" / f"{dossier_id}.brief.json"
        try:
            with open(brief_path, 'r', encoding='utf-8') as f:
                sidecar = json.load(f)
            # Reshape to match the full dossier structure
            return {
                'brief': sidecar.get('brief', {}),
                'dossier': {
                    'headline_seed': sidecar.get('headline_seed', ''),
                    'articles': sidecar.get('articles', []),
                },
            }
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"✗ Could not load brief sidecar: {e}")
            return {}

    def _story_reply_count(self, dossier_id: str) -> int:
        """Count how many successful replies we've made for this dossier."""
        return sum(
            1 for r in self.reply_history.get('replies', [])
            if r.get('dossier_id') == dossier_id
        )

    def _is_story_completed(self, dossier_id: str) -> bool:
        """Check if we've hit the max replies for this story."""
        max_per_story = self.config.get('max_replies_per_story', 3)
        count = self._story_reply_count(dossier_id)
        return count >= max_per_story

    def _outlets_already_replied(self, dossier_id: str) -> set:
        """Return set of outlet handles we've already replied to for this dossier."""
        return {
            r.get('outlet_handle')
            for r in self.reply_history.get('replies', [])
            if r.get('dossier_id') == dossier_id
        }

    # ---- outlet tweet matching -------------------------------------------

    def _find_outlet_tweet(self, outlet_handle: str, headline_seed: str,
                           article_urls: list) -> Optional[dict]:
        """Search X for the outlet's tweet about this story.

        Builds a query like: from:{handle} ({noun1} OR {noun2}) -is:retweet
        Returns the best matching tweet dict, or None.

        Recall vs precision:
          - Headlines typically have 4-6 proper nouns, but an outlet's
            wire-style tweet usually uses only a subset (e.g. the full
            headline mentions "UNIFIL + Hezbollah + Lebanon" while BBC's
            tweet may only say "Lebanon" and "Hezbollah"). AND-ing three
            required terms misses these matches entirely.
          - Fix: OR the top 2 longest proper nouns so the search is
            permissive on recall; the scorer below filters for precision.
          - Score threshold 1.0 requires either 2 shared proper nouns
            (2 * 0.5) or 1 shared noun + URL-domain match (0.5 + 1.0).
            A single-noun match alone is rejected as too weak.
        """
        nouns = _extract_proper_nouns(headline_seed)
        if not nouns:
            print(f"   No proper nouns extracted from headline")
            return None

        # Pick the 2 most distinctive proper nouns (longest = usually most
        # specific — "Hezbollah" beats "UN"). OR them so a headline full of
        # proper nouns doesn't force every outlet tweet to include all of
        # them. See docstring for precision backstop via _score_tweet_match.
        sorted_nouns = sorted(nouns, key=len, reverse=True)[:2]
        if len(sorted_nouns) >= 2:
            noun_query = f"({sorted_nouns[0]} OR {sorted_nouns[1]})"
        else:
            noun_query = sorted_nouns[0]

        query = f"from:{outlet_handle} {noun_query} -is:retweet"
        print(f"   Searching: {query}")

        try:
            response = self.bot.client.search_recent_tweets(
                query=query,
                max_results=10,
                tweet_fields=[
                    'author_id', 'public_metrics', 'created_at',
                    'entities', 'reply_settings',
                ],
            )

            if not response.data:
                print(f"   No results for query")
                return None

            # Score each tweet against ALL headline proper nouns (not just
            # the 2 used in the query) so near-miss candidates still score.
            # Pre-filter reply-restricted tweets (reply_settings ≠ 'everyone')
            # — outlets commonly lock breaking-news threads to
            # following/mentioned/subscribers, and the reply POST would 403
            # at runtime. Skipping here saves the doomed API call and lets
            # us fall through to a lower-scored but postable candidate.
            best_tweet = None
            best_score = 0.0

            for tweet in response.data:
                rs = getattr(tweet, 'reply_settings', None)
                if isinstance(rs, str) and rs != 'everyone':
                    print(
                        f"   Skipping tweet {tweet.id}: "
                        f"reply_settings={rs} (not repliable)"
                    )
                    continue

                score = self._score_tweet_match(
                    tweet.text or '', headline_seed, article_urls
                )
                if score > best_score:
                    best_score = score
                    best_tweet = tweet

            # 1.0 floor = either 2 shared nouns or 1 noun + URL match.
            # Single-noun matches (0.5) are too weak under the OR query.
            if best_score < 1.0:
                print(f"   Best match score too low: {best_score:.2f}")
                return None

            tweet_url = f"https://x.com/{outlet_handle}/status/{best_tweet.id}"
            rs_log = getattr(best_tweet, 'reply_settings', None)
            print(f"   Found match (score {best_score:.2f}): {tweet_url}")
            print(f"   Text: {best_tweet.text[:120]}...")
            if isinstance(rs_log, str):
                print(f"   reply_settings: {rs_log}")
            return {
                'tweet_id': best_tweet.id,
                'tweet_url': tweet_url,
                'text': best_tweet.text[:150] if best_tweet.text else '',
                'score': best_score,
            }

        except Exception as e:
            print(f"✗ Error searching for outlet tweet: {e}")
            return None

    def _score_tweet_match(self, tweet_text: str, headline_seed: str,
                           article_urls: list) -> float:
        """Score how well a tweet matches the story.

        +0.5 per shared proper noun with headline_seed
        +1.0 if tweet contains a URL domain matching article_urls
        """
        score = 0.0

        headline_nouns = _extract_proper_nouns(headline_seed)
        tweet_nouns = _extract_proper_nouns(tweet_text)
        shared = headline_nouns & tweet_nouns
        score += len(shared) * 0.5

        # Check if tweet references any article URLs (by domain)
        tweet_lower = tweet_text.lower()
        for url in article_urls:
            # Extract domain from URL
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace('www.', '')
                if domain and domain in tweet_lower:
                    score += 1.0
                    break
            except Exception:
                continue

        return score

    # ---- reply composition -----------------------------------------------

    def _compose_reply(self, brief_data: dict, dossier_url: str,
                       outlet_count: int) -> str:
        """Compose a professional reply linking to the dossier.

        Template-based. Max ~250 chars to leave room for URL.
        Professional tone. No cat puns. No self-promotion.
        """
        disagreements = brief_data.get('disagreements', [])
        missing_context = brief_data.get('missing_context', [])
        framing = brief_data.get('framing_analysis', {})
        n = outlet_count

        if disagreements:
            templates = [
                f"We covered this across {n} outlets — here's where their accounts diverge:\n{dossier_url}",
                f"How {n} outlets reported this story differently — and where the facts diverge:\n{dossier_url}",
            ]
        elif missing_context:
            templates = [
                f"We analyzed {n} outlets on this story — here's what none of them mentioned:\n{dossier_url}",
                f"What {n} outlets reported — and what got left out:\n{dossier_url}",
            ]
        elif len(framing) >= 3:
            templates = [
                f"{n} outlets, {n} different framings. Full cross-outlet breakdown:\n{dossier_url}",
                f"Same story, {n} different angles. See how each outlet framed it:\n{dossier_url}",
            ]
        else:
            templates = [
                f"Cross-outlet analysis of this story from {n} sources:\n{dossier_url}",
                f"How {n} outlets covered this story — the full dossier:\n{dossier_url}",
            ]

        reply = random.choice(templates)

        # Safety: ensure under 280 chars
        if len(reply) > 280:
            reply = f"Cross-outlet analysis from {n} sources:\n{dossier_url}"

        return reply

    # ---- safety checks ---------------------------------------------------

    def _check_daily_reply_limit(self) -> bool:
        """Return True if we haven't hit the daily reply cap."""
        max_per_day = self.config.get('max_replies_per_day', 2)
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        today_count = sum(
            1 for r in self.reply_history.get('replies', [])
            if datetime.fromisoformat(r.get('timestamp', '2000-01-01T00:00:00+00:00')) >= today_start
        )

        if today_count >= max_per_day:
            print(f"⚠️  Daily reply limit reached ({today_count}/{max_per_day})")
            return False

        print(f"✓ Daily replies: {today_count}/{max_per_day}")
        return True

    def _check_per_outlet_cooldown(self, outlet_handle: str) -> bool:
        """Return True if we haven't replied to this outlet recently."""
        cooldown_hours = self.config.get('per_outlet_cooldown_hours', 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)

        recent = any(
            r.get('outlet_handle') == outlet_handle
            and datetime.fromisoformat(r.get('timestamp', '2000-01-01T00:00:00+00:00')) > cutoff
            for r in self.reply_history.get('replies', [])
        )

        if recent:
            print(f"   → Skipping @{outlet_handle} (replied within {cooldown_hours}h)")
            return False
        return True

    # ---- main entry point ------------------------------------------------

    def run_reply_cycle(self, dry_run: bool = False) -> bool:
        """Run one outlet reply cycle.

        Args:
            dry_run: If True, find and compose replies but don't post them.

        Returns:
            True if a reply was posted (or would have been in dry-run mode).
        """
        print("\n" + "=" * 80)
        print("📰 OUTLET REPLY CYCLE")
        print("=" * 80)
        print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if dry_run:
            print("🔍 DRY RUN — will not post replies")

        # Check enabled (dry-run bypasses this gate so you can preview output)
        if not dry_run and not self.config.get('enabled', False):
            print("⚠️  Outlet reply is disabled in config")
            print("=" * 80)
            return False

        # Cleanup old history
        self._cleanup_old_history()

        # Check daily limit
        if not self._check_daily_reply_limit():
            print("=" * 80)
            return False

        # Get recent journalism posts
        window = self.config.get('eligible_window_hours', 8)
        posts = self._get_recent_journalism_posts(hours=window)
        print(f"\n📋 Found {len(posts)} journalism posts in last {window}h")

        if not posts:
            print("   No eligible posts")
            print("=" * 80)
            return False

        priority_outlets = set(self.config.get('priority_outlets', []))

        for post in posts:
            dossier_id = post.get('dossier_id')
            if not dossier_id:
                continue

            # Skip if we've hit the max replies for this story
            story_count = self._story_reply_count(dossier_id)
            max_per_story = self.config.get('max_replies_per_story', 3)
            if story_count >= max_per_story:
                print(f"\n⏭  Story completed ({story_count}/{max_per_story} replies): {dossier_id[:40]}...")
                continue

            print(f"\n🔎 Checking dossier: {dossier_id[:50]}...")

            # Load dossier data (full JSON locally, brief sidecar in CI)
            dossier_data = self._load_dossier_data(dossier_id)
            if not dossier_data:
                print("   Dossier not found (no full JSON or brief sidecar), skipping")
                continue

            brief = dossier_data.get('brief', {})
            dossier = dossier_data.get('dossier', {})

            # Check meta angle quality
            if not self._has_meaningful_meta_angle(brief):
                print("   Meta angle score too low, skipping")
                continue

            # Get articles and match to outlet registry
            articles = dossier.get('articles', [])
            if not articles:
                print("   No articles in dossier, skipping")
                continue

            # Build outlet → article URLs mapping
            outlet_articles = {}
            for article in articles:
                outlet_name = article.get('outlet', '')
                if outlet_name not in outlet_articles:
                    outlet_articles[outlet_name] = []
                if article.get('url'):
                    outlet_articles[outlet_name].append(article['url'])

            # Sort outlets: priority_outlets first, then by registry priority
            outlet_candidates = []
            for outlet_name in outlet_articles:
                reg = self.registry.get(outlet_name, {})
                handle = reg.get('handle')
                if not handle:
                    continue
                # Only consider priority_outlets if configured
                if priority_outlets and handle not in priority_outlets:
                    continue
                priority = reg.get('priority', 99)
                outlet_candidates.append({
                    'name': outlet_name,
                    'handle': handle,
                    'priority': priority,
                    'urls': outlet_articles[outlet_name],
                })

            # Sort by priority (lower = better)
            outlet_candidates.sort(key=lambda o: o['priority'])

            # Remove outlets we've already replied to for this story
            already_replied_handles = self._outlets_already_replied(dossier_id)
            outlet_candidates = [
                o for o in outlet_candidates
                if o['handle'] not in already_replied_handles
            ]

            if not outlet_candidates:
                print("   No priority outlets remaining in dossier")
                continue

            if story_count > 0:
                print(f"   Story has {story_count}/{max_per_story} replies, "
                      f"{len(outlet_candidates)} outlets remaining")

            headline = dossier.get('headline_seed', post.get('topic', ''))

            # Validate dossier_id before building URL
            if not re.match(r'^[\w\-\.]+$', dossier_id):
                print(f"   Invalid dossier_id format, skipping: {dossier_id}")
                continue

            dossier_url = f"https://mewscast.us/dossiers/{dossier_id}.html"
            outlet_count = len(outlet_articles)

            for outlet in outlet_candidates:
                handle = outlet['handle']

                if not self._check_per_outlet_cooldown(handle):
                    continue

                print(f"\n   Searching for @{handle}'s tweet...")
                match = self._find_outlet_tweet(handle, headline, outlet['urls'])

                if not match:
                    print(f"   No matching tweet from @{handle}")
                    continue

                # Compose reply
                reply_text = self._compose_reply(brief, dossier_url, outlet_count)
                print(f"\n   💬 Reply to @{handle}:")
                print(f"      {reply_text[:100]}...")

                tweet_url = match.get('tweet_url') or (
                    f"https://x.com/{handle}/status/{match['tweet_id']}"
                )

                if dry_run:
                    print("\n   🔍 DRY RUN — would have posted this reply:")
                    print(f"   ┌─ Replying to @{handle}'s tweet: {tweet_url}")
                    print(f"   │  Tweet: {match['text']}")
                    print(f"   │")
                    print(f"   │  Reply text:")
                    print(f"   │  {reply_text}")
                    print(f"   │")
                    print(f"   │  Dossier: {dossier_id}")
                    print(f"   │  Outlets in dossier: {outlet_count}")
                    print(f"   └─ (not posted — dry run)")
                    print("=" * 80)
                    return True

                # Experiment: follow the outlet before replying. X's
                # direct "People you follow" reply-rule is author-side
                # (the outlet would have to follow Walter), so this is
                # NOT expected to instantly unlock 403'd replies — but
                # sustained engagement may soften X's anti-automation
                # heuristics for verified-account replies over time.
                # Idempotent; any failure is non-fatal.
                try:
                    self.bot.follow_user_by_handle(handle)
                except Exception as _follow_err:
                    print(f"   Follow attempt errored (non-fatal): {_follow_err}")

                # Post the reply — let rate limit errors propagate to
                # fail the GHA workflow hard (same pattern as twitter_bot.py)
                try:
                    result = self.bot.reply_to_tweet(
                        tweet_id=match['tweet_id'],
                        text=reply_text
                    )
                except Exception as e:
                    # TooManyRequests re-raised by twitter_bot.reply_to_tweet
                    # will propagate up — only catch other errors here
                    if 'TooManyRequests' in type(e).__name__:
                        raise
                    print(f"   ✗ Error posting reply to {tweet_url}: {e}")
                    continue

                if not result:
                    print(f"   ✗ Reply failed (target: {tweet_url})")
                    continue

                # Record in history
                self.reply_history.setdefault('replies', []).append({
                    'dossier_id': dossier_id,
                    'outlet_handle': handle,
                    'outlet_name': outlet['name'],
                    'outlet_tweet_id': match['tweet_id'],
                    'outlet_tweet_url': tweet_url,
                    'reply_tweet_id': result.get('id'),
                    'reply_text': reply_text,
                    'dossier_url': dossier_url,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self._save_reply_history()

                print(f"   ✓ Replied to {tweet_url}")
                print("=" * 80)
                return True

        print("\n   No successful replies this cycle")
        print("=" * 80)
        return False


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    bot = OutletReplyBot()
    bot.run_reply_cycle(dry_run=dry_run)
