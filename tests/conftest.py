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
_tweepy = _ensure_module("tweepy")
for _attr, _val in (
    ("Client", MagicMock),
    ("API", MagicMock),
    ("OAuth1UserHandler", MagicMock),
    ("TweepyException", Exception),
    ("TooManyRequests", Exception),
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


# ---- content_generator ----------------------------------------------------
# outlet_reply_bot.py historically stubbed this as a bare ModuleType with
# only _truncate_at_sentence. main.py also imports ContentGenerator from
# it. Ensure both names exist regardless of which test file was collected
# first or whether the real module is on sys.path.
_cg = _ensure_module("content_generator")
if not hasattr(_cg, "_truncate_at_sentence"):
    _cg._truncate_at_sentence = lambda text, max_len=280: text[:max_len]
if not hasattr(_cg, "ContentGenerator"):
    _cg.ContentGenerator = MagicMock()
