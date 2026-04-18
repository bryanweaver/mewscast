"""
Unit tests for _compose_dossier_reply_text in src/main.py.

Covers the template branches — disagreements, missing_context, multi-
framing, generic fallback — and edge cases (empty brief, outlet_count
below 2).
"""
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_project_root, "src")
for _p in (_project_root, _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub heavy external modules that main.py pulls in transitively.
for _modname in ("tweepy", "atproto", "anthropic"):
    if _modname not in sys.modules:
        sys.modules[_modname] = types.ModuleType(_modname)
# atproto.models is referenced as an attribute; give it a MagicMock
sys.modules["atproto"].models = MagicMock()
sys.modules["atproto"].Client = MagicMock()
sys.modules["anthropic"].Anthropic = MagicMock()

import main  # noqa: E402


compose = main._compose_dossier_reply_text


class TestComposeDossierReplyText:
    def test_disagreements_branch(self):
        brief = {"disagreements": [{"claim": "x"}]}
        out = compose(brief, 5)
        assert "5 outlets" in out
        assert "diverge" in out
        assert out.endswith(":")

    def test_missing_context_branch(self):
        brief = {"missing_context": ["the subsidy detail nobody mentioned"]}
        out = compose(brief, 4)
        assert "4 outlets" in out
        assert "left out" in out

    def test_multi_framing_branch(self):
        brief = {"framing_analysis": {"a": "x", "b": "y", "c": "z"}}
        out = compose(brief, 3)
        assert "framings" in out or "framing" in out
        assert "3" in out

    def test_generic_fallback_no_signals(self):
        out = compose({}, 2)
        assert "cross-outlet" in out.lower()
        # Generic branch doesn't name a count
        assert "outlets" not in out or "dossier" in out.lower()

    def test_none_brief_falls_back_to_generic(self):
        out = compose(None, 0)
        assert "dossier" in out.lower()

    def test_single_outlet_phrasing_is_plural_neutral(self):
        # outlet_count=1 should not produce "1 outlets"
        out = compose({"disagreements": [1]}, 1)
        assert "1 outlets" not in out
        assert "these outlets" in out

    def test_multi_framing_uses_framing_count_when_outlet_count_small(self):
        # outlet_count=0 but framing has 3 entries — use framing count
        brief = {"framing_analysis": {"a": "x", "b": "y", "c": "z"}}
        out = compose(brief, 0)
        assert "3" in out

    def test_disagreements_precedence_over_missing_context(self):
        brief = {
            "disagreements": [{"claim": "x"}],
            "missing_context": ["y"],
            "framing_analysis": {"a": "b", "c": "d", "e": "f"},
        }
        out = compose(brief, 5)
        assert "diverge" in out

    def test_length_leaves_room_for_url(self):
        # Reply body is hook + "\n" + URL (~50 chars). X tweet limit 280.
        # Hook should be under ~240 to stay safe.
        for brief in [
            {"disagreements": [1]},
            {"missing_context": ["x"]},
            {"framing_analysis": {"a": "1", "b": "2", "c": "3"}},
            {},
        ]:
            out = compose(brief, 99)  # worst-case big count
            assert len(out) <= 240, f"hook too long ({len(out)}): {out}"
