"""
Stage 1 — Trend Detection (Walter Croncat journalism workflow).

Reads the curated `outlet_registry.yaml` watchlist, builds an X recent-search
query against the watchlist handles, and clusters the returned tweets into
candidate stories. If the X API call fails (rate limit, auth, empty), falls
back to NewsFetcher.get_top_stories() so the pipeline never hard-stops on a
Stage 1 failure.

Public API:
    TrendDetector(registry_path=None, twitter_bot=None, news_fetcher=None)
        .detect_trends(max_candidates: int = 15) -> list[TrendCandidate]

Each candidate is a dataclass that downstream stages (Stage 2 triage, Stage 3
gather) can consume directly. story_id is a stable hash so dossier_store can
use it as a filename without collision.

This module deliberately keeps all I/O behind try/except — Stage 1 failures
log and degrade, they do not raise.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Candidate dataclass
# ---------------------------------------------------------------------------

@dataclass
class TrendCandidate:
    """One candidate story coming out of Stage 1.

    Stage 2 (StoryTriage) consumes this dataclass; Stage 3 (SourceGatherer)
    uses headline_seed as the topic to fan out to NewsFetcher.
    """
    headline_seed: str             # Cluster's representative headline (longest tweet text in cluster)
    detected_at: str               # ISO-8601 UTC timestamp
    source_signals: list[str]      # Outlet handles that posted about this cluster
    engagement: int                # Sum of like + retweet + reply across cluster
    story_id: str                  # Stable hash for dossier_store filenames
    source: str = "x"              # "x" = clustered from X tweets, "news_fetcher" = Google News fallback.
    #                                Stage 2 triage uses this to relax the single-signal hard-reject
    #                                for NewsFetcher-fallback candidates (each top-story is one URL
    #                                from one outlet by construction, but Google News top-stories
    #                                is itself a curated aggregation).

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Stop-word + proper-noun helpers (mirror post_tracker._extract_proper_nouns
# so clustering behavior is consistent across the codebase)
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be',
    'this', 'that', 'these', 'those', 'it', 'can', 'will', 'has', 'have',
    'had', 'not', 'what', 'who', 'why', 'how', 'new', 'after', 'over',
    'into', 'about', 'just', 'now', 'still', 'than', 'then', 'so',
}

_SENTENCE_STARTERS = {
    'The', 'A', 'An', 'This', 'That', 'These', 'Those', 'It', 'He', 'She',
    'They', 'We', 'You', 'I', 'But', 'And', 'Or', 'So', 'Just', 'Now',
    'Here', 'There', 'Breaking', 'BREAKING', 'JUST', 'WATCH', 'LIVE',
}


def _extract_proper_nouns(text: str) -> set[str]:
    """Extract likely proper nouns (capitalized non-stop words) — case-folded."""
    out: set[str] = set()
    for word in text.split():
        clean = re.sub(r'[^\w]', '', word)
        if len(clean) <= 1:
            continue
        if clean in _SENTENCE_STARTERS:
            continue
        if clean[0].isupper():
            out.add(clean.lower())
    return out


def _normalize_headline(text: str) -> str:
    """Strip URLs, t.co shorts, emoji-ish chars and excess whitespace from a tweet."""
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _stable_story_id(headline_seed: str, detected_at: str) -> str:
    """Build a deterministic story_id from headline + day-bucket.

    We bucket by date so the same story re-detected on the same day produces
    the same id (idempotent merge into dossier_store), but a re-emergence the
    next day gets a fresh id.
    """
    day_bucket = (detected_at or "")[:10]  # YYYY-MM-DD
    digest = hashlib.sha256(
        (headline_seed.lower().strip() + "|" + day_bucket).encode("utf-8")
    ).hexdigest()[:10]
    # Slugify the headline a little for readability in filenames
    slug_words = re.findall(r'[a-zA-Z0-9]+', headline_seed.lower())[:4]
    slug = "-".join(slug_words) if slug_words else "story"
    return f"{day_bucket}-{slug}-{digest}"


# ---------------------------------------------------------------------------
# Registry loader (lightweight — no hard yaml dependency at module import)
# ---------------------------------------------------------------------------

def _default_registry_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "outlet_registry.yaml")


def _load_outlet_handles(registry_path: str) -> list[dict]:
    """Load outlet entries from outlet_registry.yaml.

    Returns list of dicts with at least `name`, `handle`, `slant`.
    Returns [] on any failure (Stage 1 must degrade gracefully).
    """
    try:
        import yaml  # local import so the smoke test runs without yaml in path
    except ImportError:
        print("[trend_detector] PyYAML not available; cannot read registry")
        return []

    if not os.path.exists(registry_path):
        print(f"[trend_detector] outlet registry not found at {registry_path}")
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # pragma: no cover - defensive
        print(f"[trend_detector] failed to parse outlet registry: {e}")
        return []

    outlets = data.get("outlets", []) if isinstance(data, dict) else []
    cleaned: list[dict] = []
    for entry in outlets:
        if not isinstance(entry, dict):
            continue
        handle = entry.get("handle")
        if not handle:
            continue
        # Strip the inline yaml comment artifacts: handles like "business  # TODO ..."
        # cannot occur because PyYAML strips comments, but defensively split anyway.
        handle = str(handle).split()[0].lstrip("@")
        cleaned.append({
            "name": entry.get("name", handle),
            "handle": handle,
            "slant": entry.get("slant", ""),
            "priority": entry.get("priority", 99),
        })
    return cleaned


# ---------------------------------------------------------------------------
# TrendDetector
# ---------------------------------------------------------------------------

class TrendDetector:
    """Stage 1 of the Croncat journalism pipeline.

    This class is intentionally low-magic. It does three things:
      1. Build an X search query from the outlet registry handles.
      2. Call tweepy.Client.search_recent_tweets and cluster the results.
      3. Fall back to NewsFetcher.get_top_stories() if anything goes wrong.
    """

    # Cap the number of handles in any single query — X recent search has
    # a hard query length limit, and bundling 30 handles is fine but more
    # would push us over. We chunk if needed.
    _MAX_HANDLES_PER_QUERY = 25

    def __init__(
        self,
        registry_path: Optional[str] = None,
        twitter_bot=None,
        news_fetcher=None,
    ):
        self.registry_path = registry_path or _default_registry_path()
        self.twitter_bot = twitter_bot
        self.news_fetcher = news_fetcher
        self.outlets = _load_outlet_handles(self.registry_path)

    # ---- public ------------------------------------------------------------

    def detect_trends(self, max_candidates: int = 15) -> list[TrendCandidate]:
        """Return up to max_candidates ranked trend candidates.

        Order of attempts:
          1. X recent search across the watchlist handles (if a tweepy client is wired).
          2. NewsFetcher.get_top_stories() fallback.
          3. Empty list (logged) — pipeline must keep going.
        """
        # Attempt 1: X
        print(f"[trend_detector] attempting X recent search path...")
        candidates = self._detect_via_x(max_candidates)
        if candidates:
            print(f"[trend_detector] X path returned {len(candidates)} candidates")
            return candidates[:max_candidates]

        # Attempt 2: NewsFetcher fallback
        print(f"[trend_detector] X path produced 0 candidates; falling back to NewsFetcher")
        candidates = self._detect_via_news_fetcher(max_candidates)
        if candidates:
            return candidates[:max_candidates]

        print("[trend_detector] no candidates from X or NewsFetcher; returning empty list")
        return []

    # ---- X path ------------------------------------------------------------

    def _detect_via_x(self, max_candidates: int) -> list[TrendCandidate]:
        # Diagnostic preflight — surface every silent return so QA can see
        # exactly why the X path is or isn't firing. Added in iteration 6
        # after 14 runs of silent NewsFetcher fallback with no idea why.
        if not self.twitter_bot:
            print(f"[trend_detector] X path skipped: twitter_bot is None")
            return []
        if not self.outlets:
            print(f"[trend_detector] X path skipped: outlet registry is empty (check {self.registry_path})")
            return []

        client = getattr(self.twitter_bot, "client", None)
        if client is None:
            print(f"[trend_detector] X path skipped: twitter_bot.client is None")
            return []

        print(f"[trend_detector] X path: {len(self.outlets)} handles in registry, "
              f"chunking at {self._MAX_HANDLES_PER_QUERY} per query")

        all_tweets: list[dict] = []
        chunk_count = 0
        try:
            for chunk in self._chunk_handles(self.outlets, self._MAX_HANDLES_PER_QUERY):
                chunk_count += 1
                query = self._build_query(chunk)
                if not query:
                    print(f"[trend_detector] chunk {chunk_count} produced empty query, skipping")
                    continue
                print(f"[trend_detector] chunk {chunk_count}: querying {len(chunk)} handles")
                try:
                    response = client.search_recent_tweets(
                        query=query,
                        max_results=100,
                        tweet_fields=[
                            'public_metrics',
                            'created_at',
                            'entities',
                            'author_id',
                        ],
                    )
                except Exception as e:
                    print(f"[trend_detector] chunk {chunk_count} X recent search failed: "
                          f"{type(e).__name__}: {e}")
                    continue

                tweets = getattr(response, "data", None) or []
                print(f"[trend_detector] chunk {chunk_count} returned {len(tweets)} tweets")
                includes_users = {}
                if hasattr(response, "includes") and response.includes:
                    users = response.includes.get("users", []) if isinstance(response.includes, dict) else []
                    for u in users:
                        includes_users[getattr(u, "id", None)] = getattr(u, "username", None)

                for t in tweets:
                    all_tweets.append(self._tweet_to_dict(t, chunk, includes_users))
        except Exception as e:
            print(f"[trend_detector] unexpected X path failure: {type(e).__name__}: {e}")
            return []

        if not all_tweets:
            print(f"[trend_detector] X path: 0 total tweets across {chunk_count} chunks — "
                  f"likely rate-limited, auth-failing, or all handles returned empty")
            return []

        print(f"[trend_detector] X path: {len(all_tweets)} tweets total across {chunk_count} chunks, "
              f"clustering...")
        return self._cluster_tweets(all_tweets, max_candidates)

    @staticmethod
    def _chunk_handles(outlets: list[dict], chunk_size: int):
        for i in range(0, len(outlets), chunk_size):
            yield outlets[i:i + chunk_size]

    @staticmethod
    def _build_query(outlets: list[dict]) -> str:
        handles = [o["handle"] for o in outlets if o.get("handle")]
        if not handles:
            return ""
        from_clauses = " OR ".join(f"from:{h}" for h in handles)
        # -is:retweet so we don't double-count wire repostings; lang:en for now.
        return f"({from_clauses}) -is:retweet lang:en"

    @staticmethod
    def _tweet_to_dict(tweet, chunk: list[dict], users_map: dict) -> dict:
        """Normalize a tweepy tweet (or a stub mock) into a plain dict."""
        text = getattr(tweet, "text", "") or ""
        metrics = getattr(tweet, "public_metrics", None) or {}
        if not isinstance(metrics, dict):
            metrics = {}
        like = metrics.get("like_count", 0) or 0
        retweet = metrics.get("retweet_count", 0) or 0
        reply = metrics.get("reply_count", 0) or 0
        engagement = like + retweet + reply

        author_id = getattr(tweet, "author_id", None)
        author_handle = users_map.get(author_id) if users_map else None
        # Fallback: pull the first matching outlet from the chunk if we
        # cannot resolve the author from `includes.users`. This is a soft
        # signal but it lets the smoke test work without an `includes` block.
        if not author_handle and chunk:
            author_handle = chunk[0].get("handle", "unknown")

        created_at = getattr(tweet, "created_at", None)
        if isinstance(created_at, datetime):
            created_iso = created_at.isoformat()
        elif isinstance(created_at, str):
            created_iso = created_at
        else:
            created_iso = datetime.now(timezone.utc).isoformat()

        return {
            "text": _normalize_headline(text),
            "author_handle": author_handle or "unknown",
            "engagement": engagement,
            "created_at": created_iso,
        }

    # ---- clustering --------------------------------------------------------

    def _cluster_tweets(self, tweets: list[dict], max_candidates: int) -> list[TrendCandidate]:
        """Group tweets into candidate stories by proper-noun overlap.

        Two tweets cluster together if they share >=2 proper nouns. We then
        take the longest tweet text as the cluster's headline_seed and sum
        engagement across the cluster.
        """
        clusters: list[dict] = []
        for tweet in tweets:
            nouns = _extract_proper_nouns(tweet["text"])
            if not nouns:
                continue

            placed = False
            for cluster in clusters:
                if len(nouns & cluster["nouns"]) >= 2:
                    cluster["tweets"].append(tweet)
                    cluster["nouns"] |= nouns
                    cluster["engagement"] += tweet["engagement"]
                    cluster["handles"].add(tweet["author_handle"])
                    placed = True
                    break
            if not placed:
                clusters.append({
                    "nouns": set(nouns),
                    "tweets": [tweet],
                    "engagement": tweet["engagement"],
                    "handles": {tweet["author_handle"]},
                })

        candidates: list[TrendCandidate] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for cluster in clusters:
            # Pick the longest tweet text as the representative headline
            headline_seed = max(
                (t["text"] for t in cluster["tweets"]),
                key=len,
                default="",
            )
            if not headline_seed:
                continue
            detected_at = min(
                (t.get("created_at", now_iso) for t in cluster["tweets"]),
                default=now_iso,
            )
            candidates.append(TrendCandidate(
                headline_seed=headline_seed,
                detected_at=detected_at,
                source_signals=sorted(cluster["handles"]),
                engagement=int(cluster["engagement"]),
                story_id=_stable_story_id(headline_seed, detected_at),
            ))

        # Rank: more signals first, then more engagement
        candidates.sort(key=lambda c: (len(c.source_signals), c.engagement), reverse=True)
        return candidates[:max_candidates]

    # ---- NewsFetcher fallback ---------------------------------------------

    def _detect_via_news_fetcher(self, max_candidates: int) -> list[TrendCandidate]:
        if not self.news_fetcher:
            return []
        try:
            top = self.news_fetcher.get_top_stories(max_stories=max_candidates * 2) or []
        except Exception as e:
            print(f"[trend_detector] NewsFetcher fallback failed: {e}")
            return []

        out: list[TrendCandidate] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for story in top[:max_candidates]:
            title = story.get("title", "") if isinstance(story, dict) else ""
            source = story.get("source", "") if isinstance(story, dict) else ""
            if not title:
                continue
            detected_at = story.get("published_date") or now_iso
            out.append(TrendCandidate(
                headline_seed=_normalize_headline(title),
                detected_at=detected_at,
                source_signals=[source] if source else [],
                engagement=0,  # NewsFetcher doesn't expose engagement metrics
                story_id=_stable_story_id(title, detected_at),
                source="news_fetcher",
            ))
        return out


# ---------------------------------------------------------------------------
# Smoke test — pure logic, no API calls
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Sanity-check the clustering logic without touching the X API."""

    # Build a fake tweepy-like response with three Senate vote tweets
    # (should cluster) and one unrelated tweet (should stand alone).
    class _Tweet:
        def __init__(self, text, author_id, like, rt, reply, created_at):
            self.text = text
            self.author_id = author_id
            self.public_metrics = {
                "like_count": like,
                "retweet_count": rt,
                "reply_count": reply,
            }
            self.created_at = created_at
            self.entities = {}

    fake_tweets = [
        _Tweet(
            "Senate passes Appropriations Bill 68-32, averting shutdown — Reuters",
            author_id=1, like=100, rt=50, reply=20,
            created_at="2026-04-08T19:30:00+00:00",
        ),
        _Tweet(
            "BREAKING: Senate Appropriations vote 68-32, midnight passage",
            author_id=2, like=80, rt=30, reply=10,
            created_at="2026-04-08T19:32:00+00:00",
        ),
        _Tweet(
            "Senate Appropriations bill clears chamber 68-32 in late-night vote",
            author_id=3, like=60, rt=20, reply=5,
            created_at="2026-04-08T19:35:00+00:00",
        ),
        _Tweet(
            "Federal Reserve holds rates steady at March meeting",
            author_id=4, like=50, rt=15, reply=8,
            created_at="2026-04-08T18:00:00+00:00",
        ),
    ]

    chunk = [
        {"handle": "Reuters", "name": "Reuters"},
        {"handle": "AP", "name": "Associated Press"},
        {"handle": "FoxNews", "name": "Fox News"},
        {"handle": "WSJ", "name": "Wall Street Journal"},
    ]
    users_map = {1: "Reuters", 2: "AP", 3: "FoxNews", 4: "WSJ"}

    detector = TrendDetector(
        registry_path=_default_registry_path(),
        twitter_bot=None,
        news_fetcher=None,
    )

    # Run the pure clustering function directly (avoid the X API path)
    normalized = [
        TrendDetector._tweet_to_dict(t, chunk, users_map) for t in fake_tweets
    ]
    clusters = detector._cluster_tweets(normalized, max_candidates=10)

    # Expect: a Senate cluster (3 tweets) and a Federal Reserve cluster (1 tweet)
    assert len(clusters) >= 1, f"expected at least one cluster, got {len(clusters)}"
    senate_cluster = next(
        (c for c in clusters if "senate" in c.headline_seed.lower()),
        None,
    )
    assert senate_cluster is not None, "expected a Senate cluster"
    assert len(senate_cluster.source_signals) >= 2, (
        f"expected the Senate cluster to span >=2 outlets, "
        f"got {senate_cluster.source_signals}"
    )
    assert senate_cluster.engagement > 0
    assert senate_cluster.story_id  # non-empty
    # Story id is stable for the same headline_seed + day
    other = _stable_story_id(senate_cluster.headline_seed, senate_cluster.detected_at)
    assert other == senate_cluster.story_id, "story_id should be deterministic"

    # Sanity-check the registry path resolution does not crash even if yaml missing
    handles = _load_outlet_handles(_default_registry_path())
    if handles:
        # Real registry — confirm a few canonical handles loaded
        names = {h["name"] for h in handles}
        assert "Reuters" in names, f"Reuters missing from registry: {names}"

    # Confirm the fallback returns [] when news_fetcher is None
    fallback_empty = detector._detect_via_news_fetcher(5)
    assert fallback_empty == [], "fallback should be empty when no news_fetcher provided"

    # Confirm the X path is a no-op when twitter_bot is None
    x_empty = detector._detect_via_x(5)
    assert x_empty == [], "X path should be empty when no twitter_bot provided"

    print("trend_detector smoke test OK")


if __name__ == "__main__":
    _smoke_test()
