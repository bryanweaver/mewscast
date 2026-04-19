"""Tests for x_retry.call_with_retry — the Cloudflare-403 rescue wrapper
used by trend_detector and outlet_reply_bot."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# Allow import of src modules without installing the project.
_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(os.path.dirname(_here), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from x_retry import call_with_retry  # noqa: E402


class _HTTPError(Exception):
    """Stand-in for tweepy/requests HTTPError. ``response.status_code`` is
    what the helper looks at first."""

    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"{status_code} error")
        self.response = MagicMock(status_code=status_code)


def _no_sleep(_s: float) -> None:
    return None


def _fixed_rng() -> float:
    return 0.5


class TestCallWithRetry:
    def test_first_try_success_returns_value(self):
        fn = MagicMock(return_value="ok")
        result = call_with_retry(fn, attempts=3, sleeper=_no_sleep, rng=_fixed_rng)
        assert result == "ok"
        assert fn.call_count == 1

    def test_403_then_success(self):
        fn = MagicMock(side_effect=[_HTTPError(403), "ok"])
        result = call_with_retry(fn, attempts=3, sleeper=_no_sleep, rng=_fixed_rng)
        assert result == "ok"
        assert fn.call_count == 2

    def test_403_exhausts_all_attempts_reraises(self):
        err = _HTTPError(403, "Cloudflare managed challenge")
        fn = MagicMock(side_effect=err)
        with pytest.raises(_HTTPError):
            call_with_retry(fn, attempts=3, sleeper=_no_sleep, rng=_fixed_rng)
        assert fn.call_count == 3

    def test_401_is_not_retried(self):
        fn = MagicMock(side_effect=_HTTPError(401, "bad token"))
        with pytest.raises(_HTTPError):
            call_with_retry(fn, attempts=5, sleeper=_no_sleep, rng=_fixed_rng)
        assert fn.call_count == 1, "auth failures must not burn retry budget"

    def test_429_is_not_retried(self):
        fn = MagicMock(side_effect=_HTTPError(429, "rate limited"))
        with pytest.raises(_HTTPError):
            call_with_retry(fn, attempts=5, sleeper=_no_sleep, rng=_fixed_rng)
        assert fn.call_count == 1, "rate limits need longer waits than our budget"

    def test_503_is_retried(self):
        fn = MagicMock(side_effect=[_HTTPError(503), _HTTPError(503), "ok"])
        result = call_with_retry(fn, attempts=3, sleeper=_no_sleep, rng=_fixed_rng)
        assert result == "ok"
        assert fn.call_count == 3

    def test_generic_exception_without_response_falls_back_to_message(self):
        # Raises a bare Exception whose __str__ contains the status token —
        # mirrors tweepy errors that don't always carry a .response attribute.
        fn = MagicMock(
            side_effect=[Exception("403 Forbidden — cloudflare challenge"), "ok"]
        )
        result = call_with_retry(fn, attempts=3, sleeper=_no_sleep, rng=_fixed_rng)
        assert result == "ok"
        assert fn.call_count == 2

    def test_sleeper_called_with_positive_delay_between_retries(self):
        sleeps: list[float] = []
        fn = MagicMock(side_effect=[_HTTPError(403), _HTTPError(403), "ok"])
        call_with_retry(fn, attempts=3, base_delay=2.0,
                        sleeper=sleeps.append, rng=_fixed_rng)
        # Two failed attempts -> two sleeps. Jitter with rng()=0.5 produces
        # multiplier 1.0, so delays are exactly base_delay * 2^i.
        assert sleeps == [2.0, 4.0]

    def test_attempts_must_be_at_least_one(self):
        with pytest.raises(ValueError):
            call_with_retry(MagicMock(), attempts=0)
