"""
Bluesky outlet reply bot — replies to news outlet skeets with Walter's
cross-outlet dossier analysis.

Mirrors the X-side outlet_reply_bot.py flow but against the AT Protocol:
  1. Finds eligible recent journalism posts (posts_history.json)
  2. Scores the dossier's META angle — worth replying only when the
     cross-outlet analysis adds real value (disagreements, framing
     differences, missing context)
  3. Searches Bluesky for the outlet's skeet about the same story
  4. Replies with a link-card pointing at the full dossier page

Why a Bluesky outlet-reply bot exists at all (2026-04-19):
  X shipped an API-v2 policy on 2026-02-23 that rejects programmatic
  replies unless the target author has @mentioned or quote-posted us.
  Big outlets will not do that. The X outlet-reply path is effectively
  dead for this account size — see commit b4c899aa and the config.yaml
  comment on follow_before_reply for references. Bluesky's AT Protocol
  has no equivalent restriction: every public post is openly repliable
  by default, so outlet-reply can actually work there.

Safety invariants:
  - Config-gated (journalism.outlet_reply.bluesky_enabled must be true)
  - Same per-day / per-outlet / per-story caps as the X bot, counted
    in a separate bluesky_outlet_reply_history.json
  - Never replies to the same dossier twice on the same platform
  - Graceful error handling (catch, log, skip)

Handle resolution:
  Most large outlets on Bluesky verify with their domain as the handle
  (reuters.com, nytimes.com, theguardian.com, bbc.co.uk). The outlet
  registry already stores `domain`, so we use that as the default
  Bluesky handle. An explicit `bluesky_handle` field in the registry
  overrides when an outlet's Bluesky handle differs from its domain.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

# Add src to path for sibling imports (mirrors outlet_reply_bot.py).
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from bluesky_bot import BlueskyBot
from dossier_store import DossierStore
from trend_detector import _extract_proper_nouns


# ---------------------------------------------------------------------------
# Pure-function helpers (mirror outlet_reply_bot.py — kept in sync by hand)
# ---------------------------------------------------------------------------

def _load_journalism_outlet_reply_config() -> dict:
    """Load the journalism.outlet_reply section from config.yaml."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    try:
        with open(config_path, 'r') as f:
            full_config = yaml.safe_load(f)
        return full_config.get('journalism', {}).get('outlet_reply', {})
    except Exception as e:
        print(f"✗ Could not load config: {e}")
        return {}


def _load_outlet_registry() -> dict:
    """Load outlet_registry.yaml keyed by outlet name."""
    registry_path = Path(__file__).parent.parent / "outlet_registry.yaml"
    try:
        with open(registry_path, 'r') as f:
            data = yaml.safe_load(f)
        return {o['name']: o for o in data.get('outlets', [])}
    except Exception as e:
        print(f"✗ Could not load outlet registry: {e}")
        return {}


def _get_recent_journalism_posts(hours: int = 8) -> list:
    """Return journalism-pipeline posts from posts_history.json within window."""
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
    eligible.sort(key=lambda p: p['timestamp'], reverse=True)
    return eligible


def _has_meaningful_meta_angle(brief_data: dict, min_score: int) -> bool:
    """Same scoring heuristic as the X bot — keeps the "worth replying"
    bar consistent across platforms."""
    score = 0
    if brief_data.get('disagreements'):
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
    return score >= min_score


def _compose_reply(brief_data: dict, dossier_url: str, outlet_count: int) -> str:
    """Compose a professional reply linking to the dossier. Bluesky posts
    cap at 300 chars including the URL and link-card, so the templates
    here are tighter than the X-side equivalents. No emoji. No puns."""
    n = outlet_count
    disagreements = brief_data.get('disagreements', [])
    missing = brief_data.get('missing_context', [])
    framing = brief_data.get('framing_analysis', {})
    if disagreements:
        return f"We covered this across {n} outlets — here's where the accounts diverge: {dossier_url}"
    if missing:
        return f"We analyzed {n} outlets on this — here's what none of them mentioned: {dossier_url}"
    if len(framing) >= 3:
        return f"Same story, {n} different framings. Full cross-outlet breakdown: {dossier_url}"
    return f"Cross-outlet dossier on this story ({n} outlets): {dossier_url}"


def _score_skeet_match(text: str, headline_seed: str, article_urls: list) -> float:
    """Same scoring as X: shared proper nouns + URL domain bonus."""
    from urllib.parse import urlparse
    score = 0.0
    text_nouns = _extract_proper_nouns(text or "")
    headline_nouns = _extract_proper_nouns(headline_seed or "")
    shared = headline_nouns & text_nouns
    score += len(shared) * 0.5
    tl = (text or "").lower()
    for url in article_urls or []:
        try:
            dom = urlparse(url).netloc.replace('www.', '')
            if dom and dom in tl:
                score += 1.0
                break
        except Exception:
            continue
    return score


# ---------------------------------------------------------------------------
# BlueskyOutletReplyBot
# ---------------------------------------------------------------------------

class BlueskyOutletReplyBot:
    """Posts outlet replies on Bluesky with a dossier link card."""

    HISTORY_FILENAME = "bluesky_outlet_reply_history.json"

    def __init__(self):
        self.bot = BlueskyBot()
        self.dossier_store = DossierStore()
        self.config = _load_journalism_outlet_reply_config()
        self.registry = _load_outlet_registry()
        self.history_path = Path(__file__).parent.parent / self.HISTORY_FILENAME
        self.history = self._load_history()

    # ---- history --------------------------------------------------------

    def _load_history(self) -> dict:
        if self.history_path.exists():
            with open(self.history_path, 'r') as f:
                return json.load(f)
        return {
            'replies': [],
            'last_cleanup': datetime.now(timezone.utc).isoformat(),
        }

    def _save_history(self) -> None:
        with open(self.history_path, 'w') as f:
            json.dump(self.history, f, indent=2)
        print("✓ Saved Bluesky outlet reply history")

    def _cleanup_old_history(self) -> None:
        """Drop reply records older than 90 days; runs at most weekly."""
        last = datetime.fromisoformat(
            self.history.get('last_cleanup', '2000-01-01T00:00:00+00:00')
        )
        now = datetime.now(timezone.utc)
        if now - last < timedelta(days=7):
            return
        cutoff = now - timedelta(days=90)
        replies = self.history.get('replies', [])
        n_before = len(replies)
        self.history['replies'] = [
            r for r in replies
            if datetime.fromisoformat(r.get('timestamp', '2000-01-01T00:00:00+00:00'))
            > cutoff
        ]
        removed = n_before - len(self.history['replies'])
        if removed:
            print(f"🧹 Removed {removed} old Bluesky reply records")
        self.history['last_cleanup'] = now.isoformat()
        self._save_history()

    def _daily_reply_count(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        return sum(
            1 for r in self.history.get('replies', [])
            if datetime.fromisoformat(r.get('timestamp', '2000-01-01T00:00:00+00:00'))
            > cutoff
        )

    def _story_reply_count(self, dossier_id: str) -> int:
        return sum(
            1 for r in self.history.get('replies', [])
            if r.get('dossier_id') == dossier_id
        )

    def _outlets_already_replied(self, dossier_id: str) -> set[str]:
        return {
            r.get('outlet_handle') for r in self.history.get('replies', [])
            if r.get('dossier_id') == dossier_id
        }

    def _per_outlet_cooldown_ok(self, handle: str) -> bool:
        cooldown_h = self.config.get('per_outlet_cooldown_hours', 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_h)
        for r in self.history.get('replies', []):
            if r.get('outlet_handle') == handle:
                ts = datetime.fromisoformat(
                    r.get('timestamp', '2000-01-01T00:00:00+00:00')
                )
                if ts > cutoff:
                    return False
        return True

    # ---- dossier --------------------------------------------------------

    def _load_dossier_data(self, dossier_id: str) -> dict | None:
        """Full JSON locally; brief sidecar in CI (same as X bot)."""
        data = self.dossier_store.read_raw(dossier_id)
        if data:
            return data
        brief_path = (
            Path(__file__).parent.parent / "docs" / "dossiers"
            / f"{dossier_id}.brief.json"
        )
        try:
            with open(brief_path, 'r', encoding='utf-8') as f:
                sidecar = json.load(f)
            return {
                'brief': sidecar.get('brief', {}),
                'dossier': {
                    'headline_seed': sidecar.get('headline_seed', ''),
                    'articles': sidecar.get('articles', []),
                },
            }
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"✗ Could not load brief sidecar for {dossier_id}: {e}")
            return None

    # ---- handle resolution ----------------------------------------------

    # Sentinel value for outlets explicitly confirmed NOT to be on
    # Bluesky. Stored in outlet_registry.yaml as:
    #   bluesky_handle: not_on_bluesky
    # When we see this sentinel we must NOT fall back to the outlet's
    # domain — that would produce ghost queries like `from:foxnews.com`
    # which on Bluesky today either 404 or match a third-party
    # ActivityPub-bridge bot that isn't really the outlet.
    NOT_ON_BLUESKY = 'not_on_bluesky'

    @classmethod
    def _outlet_bluesky_handle(cls, outlet: dict) -> str | None:
        """Prefer explicit bluesky_handle, fall back to domain. Returns
        None if the registry says the outlet is not on Bluesky.

        Domains are the common verification path on Bluesky
        (reuters.com, nytimes.com, theguardian.com all own their domain
        handles), so falling back to ``domain`` gives opportunistic
        coverage for outlets we haven't explicitly mapped yet.
        """
        h = outlet.get('bluesky_handle')
        if isinstance(h, str) and h:
            if h == cls.NOT_ON_BLUESKY:
                return None
            return h.lstrip('@')
        domain = outlet.get('domain')
        if domain:
            return str(domain).lstrip('@')
        return None

    # ---- search ---------------------------------------------------------

    def _find_outlet_skeet(self, handle: str, headline_seed: str,
                           article_urls: list) -> Optional[dict]:
        """Search Bluesky for the outlet's skeet about this story.

        Uses the same OR-of-top-2-nouns query shape as the X bot and the
        same scoring floor (1.0 = either 2 shared nouns or 1 noun + URL
        domain match). Bluesky's search_posts doesn't accept a -is:retweet
        operator but the from: filter combined with the scorer is enough.
        """
        nouns = _extract_proper_nouns(headline_seed)
        if not nouns:
            print(f"   No proper nouns extracted from headline")
            return None

        sorted_nouns = sorted(nouns, key=len, reverse=True)[:2]
        if len(sorted_nouns) >= 2:
            noun_clause = f"({sorted_nouns[0]} OR {sorted_nouns[1]})"
        else:
            noun_clause = sorted_nouns[0]
        query = f"from:{handle} {noun_clause}"
        print(f"   Searching Bluesky: {query}")

        try:
            response = self.bot.client.app.bsky.feed.search_posts({
                'q': query,
                'limit': 10,
            })
        except Exception as e:
            print(f"   ✗ Bluesky search error: {e}")
            return None

        posts = getattr(response, 'posts', None) or []
        if not posts:
            print(f"   No Bluesky results for @{handle}")
            return None

        best = None
        best_score = 0.0
        for post in posts:
            text = ''
            rec = getattr(post, 'record', None)
            if rec is not None:
                text = getattr(rec, 'text', '') or ''
            score = _score_skeet_match(text, headline_seed, article_urls)
            if score > best_score:
                best_score = score
                best = post

        if best is None or best_score < 1.0:
            print(f"   Best Bluesky match score too low: {best_score:.2f}")
            return None

        best_text = ''
        rec = getattr(best, 'record', None)
        if rec is not None:
            best_text = getattr(rec, 'text', '') or ''

        print(f"   Found Bluesky match (score {best_score:.2f}): {best.uri}")
        print(f"   Text: {best_text[:120]}...")
        return {
            'uri': best.uri,
            'cid': best.cid,
            'text': best_text[:200],
            'score': best_score,
        }

    # ---- run ------------------------------------------------------------

    def run(self, dry_run: bool = False) -> bool:
        """Main entry point. Returns True if we replied, False otherwise."""
        print("=" * 80)
        print("🦋 Bluesky Outlet Reply Bot")
        print("=" * 80)

        if not self.config.get('bluesky_enabled', False):
            print("❌ bluesky_enabled=false in config, exiting")
            return False

        self._cleanup_old_history()

        max_per_day = self.config.get('max_replies_per_day', 9)
        today_count = self._daily_reply_count()
        print(f"✓ Daily replies: {today_count}/{max_per_day}")
        if today_count >= max_per_day:
            print("   Daily reply cap reached, exiting")
            return False

        window = self.config.get('eligible_window_hours', 8)
        posts = _get_recent_journalism_posts(hours=window)
        print(f"\n📋 Found {len(posts)} journalism posts in last {window}h")
        if not posts:
            return False

        priority_outlets = set(self.config.get('priority_outlets', []))
        min_meta = self.config.get('min_meta_score', 3)
        max_per_story = self.config.get('max_replies_per_story', 3)

        for post in posts:
            dossier_id = post.get('dossier_id')
            if not dossier_id:
                continue
            story_count = self._story_reply_count(dossier_id)
            if story_count >= max_per_story:
                print(f"\n⏭  Story completed ({story_count}/{max_per_story}): {dossier_id[:40]}...")
                continue

            print(f"\n🔎 Checking dossier: {dossier_id[:50]}...")
            data = self._load_dossier_data(dossier_id)
            if not data:
                print("   Dossier not found, skipping")
                continue
            brief = data.get('brief', {})
            dossier = data.get('dossier', {})
            if not _has_meaningful_meta_angle(brief, min_meta):
                print(f"   Meta angle score below {min_meta}, skipping")
                continue

            articles = dossier.get('articles', [])
            if not articles:
                print("   No articles in dossier, skipping")
                continue

            outlet_articles: dict[str, list[str]] = {}
            for a in articles:
                outlet_name = a.get('outlet', '')
                outlet_articles.setdefault(outlet_name, [])
                if a.get('url'):
                    outlet_articles[outlet_name].append(a['url'])

            # Build candidates — use the X priority_outlets list as a
            # shortlist (priority is a cross-platform editorial signal,
            # not X-specific), but look up each outlet's Bluesky handle.
            candidates = []
            for outlet_name, urls in outlet_articles.items():
                reg = self.registry.get(outlet_name, {})
                bsky_handle = self._outlet_bluesky_handle(reg)
                if not bsky_handle:
                    continue
                if priority_outlets and reg.get('handle') not in priority_outlets:
                    continue
                candidates.append({
                    'name': outlet_name,
                    'handle': bsky_handle,
                    'priority': reg.get('priority', 99),
                    'urls': urls,
                })
            candidates.sort(key=lambda o: o['priority'])

            already = self._outlets_already_replied(dossier_id)
            candidates = [c for c in candidates if c['handle'] not in already]
            if not candidates:
                print("   No priority outlets remaining on Bluesky for this story")
                continue

            import re
            if not re.match(r'^[\w\-\.]+$', dossier_id):
                print(f"   Invalid dossier_id format, skipping: {dossier_id}")
                continue
            dossier_url = f"https://mewscast.us/dossiers/{dossier_id}.html"
            outlet_count = len(outlet_articles)
            headline = dossier.get('headline_seed', post.get('topic', ''))

            for outlet in candidates:
                handle = outlet['handle']
                if not self._per_outlet_cooldown_ok(handle):
                    continue

                print(f"\n   Searching for @{handle}'s skeet...")
                match = self._find_outlet_skeet(handle, headline, outlet['urls'])
                if not match:
                    continue

                reply_text = _compose_reply(brief, dossier_url, outlet_count)
                print(f"\n   💬 Reply to @{handle}:\n      {reply_text[:150]}")

                if dry_run:
                    print("\n   🔍 DRY RUN — would have posted this Bluesky reply")
                    print(f"   Parent: {match['uri']}")
                    print(f"   Dossier: {dossier_url}")
                    print("=" * 80)
                    return True

                try:
                    result = self.bot.reply_to_skeet_with_link(
                        parent_uri=match['uri'],
                        url=dossier_url,
                        text=reply_text,
                    )
                except Exception as e:
                    print(f"   ✗ Bluesky reply error: {e}")
                    continue
                if not result:
                    print(f"   ✗ Bluesky reply failed (uri={match['uri']})")
                    continue

                self.history.setdefault('replies', []).append({
                    'dossier_id': dossier_id,
                    'outlet_handle': handle,
                    'outlet_name': outlet['name'],
                    'parent_uri': match['uri'],
                    'reply_uri': result.get('uri'),
                    'reply_text': reply_text,
                    'dossier_url': dossier_url,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self._save_history()
                print(f"   ✓ Replied on Bluesky: {result.get('uri')}")
                print("=" * 80)
                return True

        print("\n   No successful Bluesky replies this cycle")
        print("=" * 80)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Find match and print plan, do not post")
    args = parser.parse_args(argv)
    bot = BlueskyOutletReplyBot()
    ok = bot.run(dry_run=args.dry_run)
    return 0 if ok or args.dry_run else 0  # never fail the GHA on "no reply"


if __name__ == "__main__":
    sys.exit(main())
