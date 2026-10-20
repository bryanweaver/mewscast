"""Daily read-only digest of X mentions and quote tweets for @mewscast.

Fetches new mentions via get_me + get_users_mentions(since_id=...), and
quote tweets via get_quote_tweets for posts_history entries from the last
3 days. Writes docs/x_mentions_digest.json. Persists since_id and dedups
by tweet id.

Strictly read-only: no replies, likes, reposts, or DMs. Fail-soft: API
errors are logged and the process exits 0.

Usage: python scripts/x_mentions_digest.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIGEST_PATH = os.path.join(REPO_ROOT, "docs", "x_mentions_digest.json")
DEFAULT_POSTS_PATH = os.path.join(REPO_ROOT, "posts_history.json")

MEWSCAST_HANDLE = "mewscast"
MENTIONS_MAX_RESULTS = 50
QUOTES_MAX_RESULTS = 20
QUOTE_LOOKBACK_DAYS = 3

CORRECTION_KEYWORDS = (
    "wrong",
    "false",
    "correction",
    "inaccurate",
    "misleading",
)
CORRECTION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in CORRECTION_KEYWORDS) + r")",
    re.IGNORECASE,
)

# Methods this module is allowed to call on the tweepy client.
READ_ONLY_METHODS = frozenset({"get_me", "get_users_mentions", "get_quote_tweets"})

# Header names (case-insensitive) worth logging from X API responses.
_HEADER_HINTS = ("rate", "limit", "usage")


def looks_like_correction(text: Optional[str]) -> tuple[bool, list[str]]:
    """Flag text that looks like a correction claim.

    Returns (matched, keywords_found). Matching is case-insensitive and
    uses a word-start boundary so 'wrongly' / 'falsehood' still flag.
    """
    if not text:
        return False, []
    found = []
    seen = set()
    for match in CORRECTION_RE.finditer(text):
        word = match.group(0).lower()
        for keyword in CORRECTION_KEYWORDS:
            if word.startswith(keyword) and keyword not in seen:
                seen.add(keyword)
                found.append(keyword)
    return bool(found), found


def parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp or datetime into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_ts(value: Any) -> Optional[str]:
    parsed = parse_ts(value)
    if parsed is None:
        if isinstance(value, str) and value:
            return value
        return None
    return parsed.isoformat()


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def tweet_id(obj: Any) -> Optional[str]:
    value = _attr(obj, "id")
    if value is None:
        return None
    return str(value)


def tweet_url(handle: Optional[str], status_id: Optional[str]) -> Optional[str]:
    if not status_id:
        return None
    user = (handle or "i").lstrip("@")
    return f"https://x.com/{user}/status/{status_id}"


def max_snowflake(*ids: Optional[str]) -> Optional[str]:
    """Return the numerically largest tweet id (snowflake)."""
    nums: list[int] = []
    for raw in ids:
        if raw is None or raw == "":
            continue
        try:
            nums.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    return str(max(nums))


def extract_interesting_headers(headers: Any) -> dict[str, str]:
    """Pick rate-limit / usage headers from a mapping or response object."""
    if headers is None:
        return {}
    raw = headers
    if hasattr(headers, "headers"):
        raw = headers.headers
    if raw is None:
        return {}
    try:
        items = raw.items()
    except Exception:
        return {}
    interesting: dict[str, str] = {}
    for key, value in items:
        low = str(key).lower()
        if any(hint in low for hint in _HEADER_HINTS):
            interesting[str(key)] = str(value)
    return interesting


def headers_from_obj(obj: Any) -> dict[str, str]:
    """Best-effort header extraction from a tweepy response or exception."""
    if obj is None:
        return {}
    for candidate in (
        obj,
        _attr(obj, "response"),
        _attr(obj, "raw"),
        _attr(obj, "_raw"),
    ):
        found = extract_interesting_headers(candidate)
        if found:
            return found
    return {}


class ReadOnlyXClient:
    """Thin wrapper that only exposes read methods and logs request counts."""

    def __init__(self, client: Any):
        self._client = client
        self.request_counts = {name: 0 for name in sorted(READ_ONLY_METHODS)}
        self.logged_headers: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._install_header_hook()

    def _install_header_hook(self) -> None:
        session = getattr(self._client, "session", None)
        if session is None or not hasattr(session, "request"):
            return
        original = session.request

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            resp = original(*args, **kwargs)
            headers = extract_interesting_headers(resp)
            if headers:
                self._record_headers("session", headers, error=False)
            return resp

        try:
            session.request = wrapped
        except Exception:
            return

    def _record_headers(self, method: str, headers: dict[str, str], error: bool) -> None:
        if not headers:
            return
        entry = {"method": method, "error": error, "headers": headers}
        self.logged_headers.append(entry)
        print(f"X API headers ({method}{' error' if error else ''}): {headers}")

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in READ_ONLY_METHODS:
            raise RuntimeError(f"Read-only digest refused to call {name}")
        self.request_counts[name] = self.request_counts.get(name, 0) + 1
        print(f"X API request: {name} (#{self.request_counts[name]})")
        try:
            result = getattr(self._client, name)(*args, **kwargs)
        except Exception as exc:
            headers = headers_from_obj(exc)
            self._record_headers(name, headers, error=True)
            msg = f"{name} failed: {type(exc).__name__}: {exc}"
            self.errors.append(msg)
            print(f"⚠️  {msg}")
            return None
        headers = headers_from_obj(result)
        self._record_headers(name, headers, error=False)
        return result

    def get_me(self, **kwargs: Any) -> Any:
        return self._call("get_me", **kwargs)

    def get_users_mentions(self, *args: Any, **kwargs: Any) -> Any:
        max_results = kwargs.get("max_results", MENTIONS_MAX_RESULTS)
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = MENTIONS_MAX_RESULTS
        kwargs["max_results"] = max(1, min(max_results, MENTIONS_MAX_RESULTS))
        return self._call("get_users_mentions", *args, **kwargs)

    def get_quote_tweets(self, *args: Any, **kwargs: Any) -> Any:
        max_results = kwargs.get("max_results", QUOTES_MAX_RESULTS)
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = QUOTES_MAX_RESULTS
        kwargs["max_results"] = max(1, min(max_results, QUOTES_MAX_RESULTS))
        return self._call("get_quote_tweets", *args, **kwargs)


def build_readonly_client() -> ReadOnlyXClient:
    """Build a v2 tweepy client from the repo's @mewscast X secrets."""
    import tweepy

    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")
    bearer_token = os.getenv("X_BEARER_TOKEN")
    if not all([api_key, api_secret, access_token, access_token_secret, bearer_token]):
        raise ValueError("Missing X API credentials. Check X_* secrets.")
    client = tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=False,
    )
    return ReadOnlyXClient(client)


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_posts_history(path: str) -> list[dict[str, Any]]:
    doc = load_json(path, {"posts": []})
    if isinstance(doc, list):
        return doc
    posts = doc.get("posts") if isinstance(doc, dict) else None
    return posts if isinstance(posts, list) else []


def empty_digest() -> dict[str, Any]:
    return {
        "account": MEWSCAST_HANDLE,
        "last_updated": None,
        "since_id": None,
        "items": [],
        "last_run": None,
    }


def load_digest(path: str) -> dict[str, Any]:
    doc = load_json(path, empty_digest())
    if not isinstance(doc, dict):
        return empty_digest()
    doc.setdefault("account", MEWSCAST_HANDLE)
    doc.setdefault("since_id", None)
    doc.setdefault("items", [])
    if not isinstance(doc["items"], list):
        doc["items"] = []
    return doc


def index_posts_by_tweet_id(posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for post in posts:
        for key in ("x_tweet_id", "x_reply_tweet_id"):
            tid = post.get(key)
            if tid:
                indexed[str(tid)] = post
    return indexed


def posts_in_lookback(
    posts: list[dict[str, Any]],
    now: datetime,
    days: int = QUOTE_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=days)
    recent = []
    for post in posts:
        ts = parse_ts(post.get("timestamp"))
        if ts is None or ts <= cutoff:
            continue
        if post.get("x_tweet_id"):
            recent.append(post)
    return recent


def format_referenced_post(post: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not post:
        return None
    tid = post.get("x_tweet_id")
    return {
        "x_tweet_id": str(tid) if tid else None,
        "url": tweet_url(MEWSCAST_HANDLE, tid),
        "topic": post.get("topic"),
        "timestamp": post.get("timestamp"),
    }


def referenced_ids(tweet: Any) -> list[str]:
    refs = _attr(tweet, "referenced_tweets") or []
    ids: list[str] = []
    for ref in refs:
        rid = tweet_id(ref) if not isinstance(ref, dict) else (
            str(ref["id"]) if ref.get("id") is not None else None
        )
        if rid:
            ids.append(rid)
    conv = _attr(tweet, "conversation_id")
    if conv:
        ids.append(str(conv))
    return ids


def resolve_referenced_post(
    tweet: Any,
    posts_by_id: dict[str, dict[str, Any]],
    fallback: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    for rid in referenced_ids(tweet):
        if rid in posts_by_id:
            return format_referenced_post(posts_by_id[rid])
    if fallback:
        return format_referenced_post(fallback)
    return None


def users_by_id(includes: Any) -> dict[str, str]:
    if includes is None:
        return {}
    users = _attr(includes, "users")
    if users is None and isinstance(includes, dict):
        users = includes.get("users")
    lookup: dict[str, str] = {}
    for user in users or []:
        uid = tweet_id(user)
        username = _attr(user, "username")
        if uid and username:
            lookup[uid] = str(username).lstrip("@")
    return lookup


def response_tweets(response: Any) -> list[Any]:
    if response is None:
        return []
    data = _attr(response, "data")
    if not data:
        return []
    if isinstance(data, list):
        return data
    return [data]


def item_from_tweet(
    tweet: Any,
    *,
    kind: str,
    users: dict[str, str],
    posts_by_id: dict[str, dict[str, Any]],
    fallback_post: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    status_id = tweet_id(tweet)
    if not status_id:
        return None
    author_id = _attr(tweet, "author_id")
    handle = users.get(str(author_id), "") if author_id is not None else ""
    text = _attr(tweet, "text") or ""
    flagged, keywords = looks_like_correction(text)
    return {
        "id": status_id,
        "kind": kind,
        "author_handle": handle,
        "text": text,
        "url": tweet_url(handle, status_id),
        "created_at": isoformat_ts(_attr(tweet, "created_at")),
        "referenced_mewscast_post": resolve_referenced_post(
            tweet, posts_by_id, fallback=fallback_post
        ),
        "looks_like_correction": flagged,
        "correction_keywords": keywords,
    }


def merge_items(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Dedup by id. Returns (merged newest-first, new_count)."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing:
        iid = item.get("id")
        if iid:
            by_id[str(iid)] = item
    new_count = 0
    for item in incoming:
        iid = item.get("id")
        if not iid:
            continue
        iid = str(iid)
        if iid in by_id:
            continue
        by_id[iid] = item
        new_count += 1

    def sort_key(item: dict[str, Any]) -> tuple[str, int]:
        created = item.get("created_at") or ""
        try:
            snowflake = int(item.get("id") or 0)
        except (TypeError, ValueError):
            snowflake = 0
        return (created, snowflake)

    merged = sorted(by_id.values(), key=sort_key, reverse=True)
    return merged, new_count


def resolve_our_user_id(client: ReadOnlyXClient) -> Optional[str]:
    """Call get_me once and return the authenticated user id."""
    me = client.get_me()
    user = _attr(me, "data") if me is not None else None
    user_id = tweet_id(user)
    if not user_id:
        print("⚠️  get_me returned no user id")
        return None
    username = _attr(user, "username")
    if username:
        print(f"Authenticated as @{username} ({user_id})")
    else:
        print(f"Authenticated user id: {user_id}")
    return user_id


def fetch_mentions(
    client: ReadOnlyXClient,
    user_id: str,
    since_id: Optional[str],
    posts_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Call get_users_mentions(since_id=..., max_results<=50)."""
    kwargs: dict[str, Any] = {
        "id": user_id,
        "max_results": MENTIONS_MAX_RESULTS,
        "tweet_fields": [
            "created_at",
            "author_id",
            "conversation_id",
            "referenced_tweets",
            "in_reply_to_user_id",
        ],
        "expansions": ["author_id", "referenced_tweets.id"],
        "user_fields": ["username"],
    }
    if since_id:
        kwargs["since_id"] = since_id

    response = client.get_users_mentions(**kwargs)
    tweets = response_tweets(response)
    users = users_by_id(_attr(response, "includes") if response is not None else None)
    items: list[dict[str, Any]] = []
    newest = since_id
    for tweet in tweets:
        author_id = _attr(tweet, "author_id")
        if author_id is not None and str(author_id) == str(user_id):
            newest = max_snowflake(newest, tweet_id(tweet))
            continue
        item = item_from_tweet(
            tweet, kind="mention", users=users, posts_by_id=posts_by_id
        )
        if item:
            items.append(item)
            newest = max_snowflake(newest, item["id"])
        else:
            newest = max_snowflake(newest, tweet_id(tweet))
    print(f"Mentions fetched: {len(items)}")
    return items, newest


def fetch_quotes(
    client: ReadOnlyXClient,
    recent_posts: list[dict[str, Any]],
    posts_by_id: dict[str, dict[str, Any]],
    our_user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for post in recent_posts:
        tid = post.get("x_tweet_id")
        if not tid:
            continue
        print(f"Fetching quote tweets for {tid}")
        response = client.get_quote_tweets(
            id=str(tid),
            max_results=QUOTES_MAX_RESULTS,
            tweet_fields=["created_at", "author_id", "conversation_id", "referenced_tweets"],
            expansions=["author_id"],
            user_fields=["username"],
        )
        tweets = response_tweets(response)
        users = users_by_id(_attr(response, "includes") if response is not None else None)
        for tweet in tweets:
            author_id = _attr(tweet, "author_id")
            if our_user_id and author_id is not None and str(author_id) == str(our_user_id):
                continue
            item = item_from_tweet(
                tweet,
                kind="quote",
                users=users,
                posts_by_id=posts_by_id,
                fallback_post=post,
            )
            if item:
                items.append(item)
    print(f"Quote tweets fetched: {len(items)}")
    return items


def run_digest(
    *,
    client: Optional[ReadOnlyXClient] = None,
    now: Optional[datetime] = None,
    digest_path: Optional[str] = None,
    posts_path: Optional[str] = None,
    write: bool = True,
) -> dict[str, Any]:
    """Collect mentions + quotes and persist the digest. Fail-soft."""
    now = now or datetime.now(timezone.utc)
    digest_path = digest_path or DEFAULT_DIGEST_PATH
    posts_path = posts_path or DEFAULT_POSTS_PATH

    digest = load_digest(digest_path)
    posts = load_posts_history(posts_path)
    posts_by_id = index_posts_by_tweet_id(posts)
    recent_posts = posts_in_lookback(posts, now)
    print(f"Posts in last {QUOTE_LOOKBACK_DAYS} days with x_tweet_id: {len(recent_posts)}")

    incoming: list[dict[str, Any]] = []
    new_since = digest.get("since_id")
    mentions_count = 0
    quotes_count = 0
    our_user_id = None

    try:
        if client is None:
            client = build_readonly_client()

        our_user_id = resolve_our_user_id(client)
        if our_user_id:
            mentions, new_since = fetch_mentions(
                client, our_user_id, digest.get("since_id"), posts_by_id
            )
            incoming.extend(mentions)
            mentions_count = len(mentions)
        else:
            print("⚠️  Skipping mentions (no authenticated user id)")

        quotes = fetch_quotes(
            client, recent_posts, posts_by_id, our_user_id if our_user_id else None
        )
        incoming.extend(quotes)
        quotes_count = len(quotes)
    except Exception as exc:
        msg = f"digest run failed softly: {type(exc).__name__}: {exc}"
        print(f"⚠️  {msg}")
        if client is not None:
            client.errors.append(msg)
        else:
            client = ReadOnlyXClient(type("Empty", (), {})())
            client.errors.append(msg)

    merged, new_count = merge_items(digest.get("items") or [], incoming)
    digest["items"] = merged
    digest["since_id"] = new_since
    digest["account"] = MEWSCAST_HANDLE
    digest["last_updated"] = now.isoformat()
    digest["last_run"] = {
        "finished_at": now.isoformat(),
        "request_counts": dict(client.request_counts) if client is not None else {},
        "rate_limit_headers": list(client.logged_headers) if client is not None else [],
        "errors": list(client.errors) if client is not None else [],
        "new_items": new_count,
        "mentions_fetched": mentions_count,
        "quotes_fetched": quotes_count,
    }

    counts = digest["last_run"]["request_counts"]
    print(f"Request counts: {counts}")
    if digest["last_run"]["rate_limit_headers"]:
        print(f"Logged {len(digest['last_run']['rate_limit_headers'])} header snapshots")
    if digest["last_run"]["errors"]:
        print(f"Soft errors ({len(digest['last_run']['errors'])}):")
        for err in digest["last_run"]["errors"]:
            print(f"  - {err}")
    print(f"New items this run: {new_count}; total stored: {len(merged)}")

    if write:
        save_json(digest_path, digest)
        print(f"Wrote {digest_path}")
    return digest


def main() -> int:
    print("=" * 60)
    print("MEWSCAST X MENTIONS DIGEST (read-only)")
    print("=" * 60)
    load_dotenv()
    try:
        run_digest()
    except Exception as exc:
        print(f"⚠️  Digest failed softly: {type(exc).__name__}: {exc}")
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
