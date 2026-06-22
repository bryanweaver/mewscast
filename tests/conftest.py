"""
Shared test setup — loaded by pytest before any test module is collected.

The project's main.py, twitter_bot.py, bluesky_bot.py, and outlet_reply_bot.py
all pull in heavy third-party packages (tweepy, atproto, anthropic,
content_generator). Several test files mock these via sys.modules at
module-import time, and running them together in one pytest session
produces order-dependent collisions (e.g. one file's bare
types.ModuleType("tweepy") sticks around and another file's
sys.modules.setdefault doesn't overwrite it).

This conftest centralises the mock surface so every test file sees the
same stubbed modules regardless of collection order.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock


_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_project_root, "src")
for _p in (_project_root, _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_module(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None or not isinstance(mod, types.ModuleType):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod


# ---- tweepy ---------------------------------------------------------------
# Use a proper exception hierarchy. Earlier this aliased both names to bare
# `Exception`, which made `except TooManyRequests` catch every other
# TweepyException (and FileNotFoundError, etc.), breaking the error-path
# branches in TwitterBot.post_tweet / post_tweet_with_image.
class _StubTweepyException(Exception):
    pass


class _StubTooManyRequests(_StubTweepyException):
    pass


_tweepy = _ensure_module("tweepy")
# Constructors must be MagicMock *instances* (callable mocks), not the
# MagicMock *class*. Calling the class with a MagicMock positional arg
# (e.g. tweepy.API(oauth_handler_mock)) triggers an InvalidSpecError
# because MagicMock treats the first positional as `spec`.
for _attr, _val in (
    ("Client", MagicMock()),
    ("API", MagicMock()),
    ("OAuth1UserHandler", MagicMock()),
    ("TweepyException", _StubTweepyException),
    ("TooManyRequests", _StubTooManyRequests),
):
    if not hasattr(_tweepy, _attr):
        setattr(_tweepy, _attr, _val)


# ---- atproto --------------------------------------------------------------
_atproto = _ensure_module("atproto")
if not hasattr(_atproto, "models"):
    _atproto.models = MagicMock()
if not hasattr(_atproto, "Client"):
    _atproto.Client = MagicMock()


# ---- anthropic ------------------------------------------------------------
_anthropic = _ensure_module("anthropic")
if not hasattr(_anthropic, "Anthropic"):
    _anthropic.Anthropic = MagicMock()


# ---- Pre-import REAL first-party + dependency modules with proper stubs in
# place. Several test files install bare stub modules for `bs4`,
# `bluesky_client`, `twitter_bot`, and `content_generator` via
# `sys.modules.setdefault(...)` at module-import time. `setdefault` is a
# no-op when the key already exists, so eagerly loading the REAL modules
# here neutralises those stubs. Tests that relied on the stubs keep
# working because they mock at the *call site* (`b.bot = Mock()`), not at
# the module level.
#
# bs4 is the most consequential preload: news_fetcher.py uses real
# BeautifulSoup parsing in its tests, and a MagicMock-shaped stub causes
# `'str' object has no attribute 'decompose'` style runtime errors.
for _mod in ("bs4", "bluesky_client", "content_generator", "twitter_bot"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except Exception:
            sys.modules[_mod] = types.ModuleType(_mod)
