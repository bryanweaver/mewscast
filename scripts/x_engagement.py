"""
Read-only X public_metrics snapshot for journalism posts (last 14 days).

Called from scripts/track_analytics.py during the daily Track Analytics job.
Uses the same @mewscast tweepy secrets as the journalism workflow.

Read-only: get_tweets only — never likes, replies, or posts.
Fail-soft: every public entry point swallows exceptions so a miss
never breaks the analytics build.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_DAYS = 14
BATCH_SIZE = 100
TWEET_FIELDS = ["public_metrics", "created_at"]
DATA_FILE = os.path.join(REPO_ROOT, "docs", "x_engagement.json")
DASHBOARD_FILE = os.path.join(REPO_ROOT, "docs", "analytics.html")
POSTS_HISTORY_FILE = os.path.join(REPO_ROOT, "posts_history.json")

# Headers that show rate-limit remaining / 24h usage so the charge is visible
# in Actions logs. Matched case-insensitively on the header name.
_HEADER_HINTS = ("rate", "limit", "usage", "remaining", "reset", "quota", "cost")

_PLACEHOLDER_RE = re.compile(
    r"/\* X_ENGAGEMENT_DATA_PLACEHOLDER \*/.*?/\* END_X_ENGAGEMENT_DATA \*/",
    re.DOTALL,
)


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (or datetime) to aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def journalism_posts_with_x_ids(
    posts: Iterable[dict],
    *,
    now: Optional[datetime] = None,
    days: int = WINDOW_DAYS,
) -> list[dict]:
    """Journalism-pipeline posts from the last `days` that have an X id."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    selected = []
    seen_ids: set[str] = set()
    if not posts or isinstance(posts, (str, bytes)):
        return selected
    for post in posts:
        if not isinstance(post, dict):
            continue
        if (post.get("post_pipeline") or "") != "journalism":
            continue
        tweet_id = post.get("x_tweet_id")
        if not tweet_id:
            continue
        tweet_id = str(tweet_id)
        if tweet_id in seen_ids:
            continue
        posted_at = parse_timestamp(post.get("timestamp"))
        if posted_at is None or posted_at < cutoff:
            continue
        seen_ids.add(tweet_id)
        selected.append(post)
    selected.sort(key=lambda p: parse_timestamp(p.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return selected


def chunked(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    """Split ids into get_tweets batches (max 100)."""
    if size <= 0:
        size = BATCH_SIZE
    return [items[i:i + size] for i in range(0, len(items), size)]


def extract_headers(obj: Any) -> dict[str, str]:
    """Best-effort header dict from a tweepy/requests response or exception."""
    if obj is None:
        return {}
    headers = getattr(obj, "headers", None)
    if headers:
        try:
            return {str(k): str(v) for k, v in dict(headers).items()}
        except Exception:
            pass
    inner = getattr(obj, "response", None)
    if inner is not None and inner is not obj:
        return extract_headers(inner)
    return {}


def interesting_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep rate-limit / usage headers that show the charge."""
    kept = {}
    for key, value in (headers or {}).items():
        lowered = key.lower()
        if any(hint in lowered for hint in _HEADER_HINTS):
            kept[key] = value
    return kept


def log_request_headers(obj: Any, request_number: int, log: Callable[..., None] = print) -> dict[str, str]:
    """Log request number plus any rate-limit/usage headers on a response or error."""
    kept = interesting_headers(extract_headers(obj))
    if kept:
        log(f"X engagement request #{request_number} rate/usage headers:")
        for key in sorted(kept, key=lambda k: k.lower()):
            log(f"  {key}: {kept[key]}")
    else:
        log(f"X engagement request #{request_number}: no rate/usage headers on response")
    return kept


def build_readonly_client(env: Optional[dict] = None):
    """Build a tweepy.Client from the journalism-workflow X_* secrets.

    Read-only by convention: callers must only invoke get_tweets.
    """
    source = env if env is not None else os.environ
    api_key = source.get("X_API_KEY")
    api_secret = source.get("X_API_SECRET")
    access_token = source.get("X_ACCESS_TOKEN")
    access_token_secret = source.get("X_ACCESS_TOKEN_SECRET")
    bearer_token = source.get("X_BEARER_TOKEN")
    if not all([api_key, api_secret, access_token, access_token_secret, bearer_token]):
        raise ValueError("Missing X API credentials (journalism-workflow X_* secrets).")
    import tweepy

    return tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=False,
    )


def _metrics_dict(tweet: Any) -> dict[str, Any]:
    raw = getattr(tweet, "public_metrics", None)
    if raw is None and isinstance(tweet, dict):
        raw = tweet.get("public_metrics")
    if not isinstance(raw, dict):
        raw = {}
    impressions = raw.get("impression_count")
    created_at = getattr(tweet, "created_at", None)
    if created_at is None and isinstance(tweet, dict):
        created_at = tweet.get("created_at")
    created_ts = parse_timestamp(created_at)
    tweet_id = getattr(tweet, "id", None)
    if tweet_id is None and isinstance(tweet, dict):
        tweet_id = tweet.get("id")
    return {
        "x_tweet_id": str(tweet_id) if tweet_id is not None else None,
        "likes": int(raw.get("like_count") or 0),
        "reposts": int(raw.get("retweet_count") or 0),
        "replies": int(raw.get("reply_count") or 0),
        "quotes": int(raw.get("quote_count") or 0),
        "impressions": int(impressions) if impressions is not None else None,
        "created_at": created_ts.isoformat() if created_ts else None,
    }


def fetch_public_metrics(
    client: Any,
    tweet_ids: list[str],
    *,
    log: Callable[..., None] = print,
) -> tuple[dict[str, dict], int]:
    """Batch-fetch public_metrics. Returns (metrics_by_id, request_count)."""
    metrics: dict[str, dict] = {}
    request_count = 0
    if not tweet_ids:
        log("X engagement request count: 0")
        return metrics, request_count

    for batch in chunked(list(tweet_ids), BATCH_SIZE):
        request_count += 1
        try:
            response = client.get_tweets(batch, tweet_fields=list(TWEET_FIELDS))
            log_request_headers(response, request_count, log=log)
        except Exception as exc:
            log_request_headers(exc, request_count, log=log)
            log(f"X engagement batch {request_count} failed (non-fatal): {exc}")
            continue

        rows = getattr(response, "data", None)
        if rows is None and isinstance(response, dict):
            rows = response.get("data")
        if not rows:
            log(f"X engagement batch {request_count}: 0 tweets")
            continue
        for tweet in rows:
            parsed = _metrics_dict(tweet)
            tweet_id = parsed.get("x_tweet_id")
            if tweet_id:
                metrics[tweet_id] = parsed
        log(f"X engagement batch {request_count}: {len(rows)} tweets")

    log(f"X engagement request count: {request_count}")
    return metrics, request_count


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def averages_by_post_type(rows: list[dict]) -> dict[str, dict]:
    """Averages keyed by post type, plus ALL."""
    if not rows:
        return {}
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        post_type = row.get("post_type") or "UNKNOWN"
        buckets.setdefault(post_type, []).append(row)
    buckets["ALL"] = list(rows)

    averages = {}
    for post_type, group in buckets.items():
        likes = [float(r.get("likes") or 0) for r in group]
        reposts = [float(r.get("reposts") or 0) for r in group]
        replies = [float(r.get("replies") or 0) for r in group]
        quotes = [float(r.get("quotes") or 0) for r in group]
        impressions = [
            float(r["impressions"])
            for r in group
            if r.get("impressions") is not None
        ]
        averages[post_type] = {
            "count": len(group),
            "likes": _mean(likes) or 0.0,
            "reposts": _mean(reposts) or 0.0,
            "replies": _mean(replies) or 0.0,
            "quotes": _mean(quotes) or 0.0,
            "impressions": _mean(impressions),
        }
    return averages


def build_payload(
    posts: list[dict],
    metrics_by_id: dict[str, dict],
    *,
    request_count: int = 0,
    now: Optional[datetime] = None,
    window_days: int = WINDOW_DAYS,
) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for post in posts:
        tweet_id = str(post.get("x_tweet_id"))
        fetched = metrics_by_id.get(tweet_id) or {}
        topic = post.get("topic") or ""
        rows.append({
            "x_tweet_id": tweet_id,
            "post_type": post.get("post_type") or "UNKNOWN",
            "posted_at": post.get("timestamp"),
            "created_at": fetched.get("created_at"),
            "topic": topic,
            "dossier_id": post.get("dossier_id"),
            "likes": fetched.get("likes", 0),
            "reposts": fetched.get("reposts", 0),
            "replies": fetched.get("replies", 0),
            "quotes": fetched.get("quotes", 0),
            "impressions": fetched.get("impressions"),
        })
    return {
        "last_updated": now.isoformat(),
        "window_days": window_days,
        "request_count": request_count,
        "posts": rows,
        "averages": averages_by_post_type(rows),
    }


def empty_payload(*, now: Optional[datetime] = None, request_count: int = 0) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "last_updated": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "request_count": request_count,
        "posts": [],
        "averages": {},
    }


def write_json(payload: dict, path: str = DATA_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def embed_in_dashboard(payload: dict, html_path: str = DASHBOARD_FILE) -> bool:
    """Replace the X engagement placeholder in analytics.html. Fail-soft."""
    if not os.path.exists(html_path):
        return False
    with open(html_path, "r", encoding="utf-8") as handle:
        html = handle.read()
    if not _PLACEHOLDER_RE.search(html):
        return False
    data_json = json.dumps(payload, ensure_ascii=False)
    replacement = (
        f"/* X_ENGAGEMENT_DATA_PLACEHOLDER */ {data_json} /* END_X_ENGAGEMENT_DATA */"
    )
    html = _PLACEHOLDER_RE.sub(lambda _m: replacement, html, count=1)
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return True


def load_posts_history(path: str = POSTS_HISTORY_FILE) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        doc = json.load(handle)
    if isinstance(doc, dict):
        return list(doc.get("posts") or [])
    if isinstance(doc, list):
        return doc
    return []


def run_x_engagement(
    posts: Optional[list[dict]] = None,
    *,
    now: Optional[datetime] = None,
    client: Any = None,
    data_path: str = DATA_FILE,
    html_path: str = DASHBOARD_FILE,
    history_path: str = POSTS_HISTORY_FILE,
    log: Callable[..., None] = print,
) -> Optional[dict]:
    """Collect, store, and render the 14-day journalism X snapshot.

    Never raises. Returns the payload on success, or None on a soft failure.
    """
    try:
        now = now or datetime.now(timezone.utc)
        if posts is None:
            try:
                posts = load_posts_history(history_path)
            except Exception as exc:
                log(f"X engagement: could not load posts_history ({exc})")
                posts = []

        selected = journalism_posts_with_x_ids(posts, now=now)
        log(f"X engagement: {len(selected)} journalism posts with X ids in last {WINDOW_DAYS} days")
        tweet_ids = [str(p["x_tweet_id"]) for p in selected]

        if client is None:
            client = build_readonly_client()

        metrics_by_id, request_count = fetch_public_metrics(client, tweet_ids, log=log)
        payload = build_payload(
            selected,
            metrics_by_id,
            request_count=request_count,
            now=now,
        )
        write_json(payload, data_path)
        log(f"X engagement: wrote {data_path} ({len(payload['posts'])} posts, {request_count} request(s))")
        if embed_in_dashboard(payload, html_path):
            log(f"X engagement: updated {html_path}")
        else:
            log("X engagement: dashboard placeholder missing or unreadable (non-fatal)")
        return payload
    except Exception as exc:
        log(f"X engagement failed (non-fatal): {exc}")
        return None


def main() -> int:
    """CLI entry. Always exits 0 so a miss never fails CI."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    run_x_engagement()
    return 0


if __name__ == "__main__":
    sys.exit(main())
