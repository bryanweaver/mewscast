"""
Retry helper for X API search calls.

X's `api.twitter.com` sits behind Cloudflare, which issues *managed
challenges* that fail any non-browser client (tweepy can't solve a
JavaScript puzzle). These challenges are transient and fire per-request
at random — a query that 403s once usually succeeds a few seconds later
from the same credentials and IP. See recent runs 24632379177 and
24632601061 where outlet-reply search 403'd even though the same client
had just succeeded elsewhere in the same cycle.

This module wraps any callable with short, jittered exponential
backoff so a single 403 doesn't kill the call. It does NOT retry
auth-level failures (401) or rate-limit errors (429) — those require
different responses.
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Matches the HTTP status values that indicate a transient Cloudflare /
# upstream hiccup worth retrying. Not retrying 401 (bad credentials —
# won't get better) or 429 (rate limit — needs a longer wait than our
# budget allows, and retrying worsens it).
_RETRYABLE_STATUSES = frozenset({403, 500, 502, 503, 504})


def _status_of(exc: BaseException) -> int | None:
    """Best-effort extraction of HTTP status from a tweepy/requests error.

    Tweepy wraps responses in its own exception classes that carry the
    underlying HTTP response on attributes like ``response`` or
    ``api_errors``. Falling back to string inspection is the pragmatic
    tiebreaker when the attribute shape varies across tweepy versions.
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if isinstance(code, int):
            return code
    msg = str(exc)
    for status in _RETRYABLE_STATUSES:
        if f"{status} Forbidden" in msg or msg.startswith(str(status)):
            return status
    return None


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    label: str = "x_api",
    sleeper: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Call ``fn()`` with retry on retryable HTTP failures.

    Delays: jittered exponential, base * (2^attempt) ± 20%. With
    base_delay=2 and attempts=3 the schedule is roughly
    [~2s, ~4s, fail]. A single Cloudflare hiccup survives.

    Args:
        fn: zero-arg callable that performs the API call.
        attempts: total attempts including the first. Must be >= 1.
        base_delay: seconds multiplier for the jittered exponential backoff.
        label: prefix for console logging so runs identify which caller retried.
        sleeper / rng: injected for tests — default to time.sleep / random.random.

    Returns:
        Whatever ``fn()`` returns.

    Raises:
        Whatever ``fn()`` raises on the final attempt, unchanged. If the
        failure is non-retryable (e.g. 401), raises immediately without
        sleeping or retrying.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — forward whatever tweepy raises
            status = _status_of(e)
            is_last = i == attempts - 1
            if status not in _RETRYABLE_STATUSES:
                # Non-retryable (auth error, bad query, rate limit) — let it fly.
                raise
            last_exc = e
            if is_last:
                raise
            # Jittered exponential: base * 2^i * (0.8..1.2)
            delay = base_delay * (2 ** i) * (0.8 + 0.4 * rng())
            print(
                f"[{label}] attempt {i + 1}/{attempts} failed with HTTP {status}; "
                f"retrying in {delay:.1f}s"
            )
            sleeper(delay)

    # Unreachable — the loop either returns or raises on the last attempt.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("call_with_retry exhausted without returning or raising")
