"""Tests for bluesky_outlet_reply — pure-function helpers + score logic.

The full flow (search + reply) is exercised manually via --dry-run on
the GHA workflow; unit tests here cover the deterministic pieces:
  - meta-angle scoring
  - reply template selection
  - handle resolution (bluesky_handle vs domain vs missing)
  - skeet match scoring (noun overlap + URL domain bonus)
"""
from __future__ import annotations

import os
import sys

import pytest

# Allow import of src modules without installing the project.
_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(os.path.dirname(_here), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from bluesky_outlet_reply import (  # noqa: E402
    BlueskyOutletReplyBot,
    _compose_reply,
    _has_meaningful_meta_angle,
    _score_skeet_match,
)


class TestHasMeaningfulMetaAngle:
    def test_zero_signals_scores_zero_fails(self):
        assert not _has_meaningful_meta_angle({}, min_score=3)

    def test_disagreements_alone_below_threshold(self):
        # disagreements = +2, but threshold is 3
        assert not _has_meaningful_meta_angle(
            {"disagreements": ["a"]}, min_score=3
        )

    def test_disagreements_plus_one_missing_passes(self):
        assert _has_meaningful_meta_angle(
            {"disagreements": ["x"], "missing_context": ["y"]},
            min_score=3,
        )

    def test_meta_post_type_alone_passes(self):
        # META = +3 == threshold
        assert _has_meaningful_meta_angle(
            {"suggested_post_type": "META"}, min_score=3
        )

    def test_three_outlet_framing_plus_confidence_passes(self):
        # framing=2 + confidence>=0.6=1 = 3
        assert _has_meaningful_meta_angle(
            {"framing_analysis": {"a": "", "b": "", "c": ""}, "confidence": 0.7},
            min_score=3,
        )

    def test_raising_threshold_blocks_borderline(self):
        assert not _has_meaningful_meta_angle(
            {"disagreements": ["x"], "missing_context": ["y"]},
            min_score=5,
        )


class TestComposeReply:
    def test_disagreements_template(self):
        text = _compose_reply(
            {"disagreements": ["accounts differ"]},
            "https://mewscast.us/dossiers/x.html",
            outlet_count=4,
        )
        assert "diverge" in text
        assert "4 outlets" in text
        assert "https://mewscast.us/dossiers/x.html" in text

    def test_missing_context_template(self):
        text = _compose_reply(
            {"missing_context": ["none mentioned"]},
            "https://mewscast.us/dossiers/y.html",
            outlet_count=5,
        )
        assert "none of them mentioned" in text
        assert "5 outlets" in text

    def test_framing_template(self):
        text = _compose_reply(
            {"framing_analysis": {"a": "", "b": "", "c": ""}},
            "https://mewscast.us/dossiers/z.html",
            outlet_count=3,
        )
        assert "different framings" in text

    def test_fallback_template(self):
        text = _compose_reply(
            {},
            "https://mewscast.us/dossiers/w.html",
            outlet_count=2,
        )
        assert "Cross-outlet dossier" in text

    def test_reply_stays_under_300_chars(self):
        text = _compose_reply(
            {"disagreements": ["x"]},
            "https://mewscast.us/dossiers/some-long-story-id.html",
            outlet_count=10,
        )
        assert len(text) <= 300, f"reply too long: {len(text)}"


class TestOutletBlueskyHandle:
    def test_explicit_bluesky_handle_wins(self):
        h = BlueskyOutletReplyBot._outlet_bluesky_handle(
            {"bluesky_handle": "reuters.com", "domain": "reuters.example"}
        )
        assert h == "reuters.com"

    def test_at_prefix_stripped(self):
        h = BlueskyOutletReplyBot._outlet_bluesky_handle(
            {"bluesky_handle": "@reuters.com"}
        )
        assert h == "reuters.com"

    def test_domain_fallback(self):
        h = BlueskyOutletReplyBot._outlet_bluesky_handle({"domain": "bbc.co.uk"})
        assert h == "bbc.co.uk"

    def test_no_domain_no_bluesky_returns_none(self):
        assert BlueskyOutletReplyBot._outlet_bluesky_handle({}) is None

    def test_not_on_bluesky_sentinel_returns_none_not_domain(self):
        # When the outlet is explicitly flagged as not_on_bluesky, we must
        # NOT silently fall back to its domain — that would build ghost
        # queries against third-party ActivityPub bridges.
        h = BlueskyOutletReplyBot._outlet_bluesky_handle(
            {"bluesky_handle": "not_on_bluesky", "domain": "foxnews.com"}
        )
        assert h is None


class TestScoreSkeetMatch:
    def test_two_shared_nouns_hits_threshold(self):
        score = _score_skeet_match(
            "Austrian police investigating baby food contamination in Vienna",
            "Austrian police found rat poison in baby food jar Vienna",
            article_urls=[],
        )
        # Expect at least 2 shared proper nouns (Austrian, Vienna) = 1.0
        assert score >= 1.0

    def test_url_domain_match_boosts_score(self):
        score = _score_skeet_match(
            "See our full story at apnews.com/something",
            "Austrian police found rat poison in Vienna",
            article_urls=["https://apnews.com/article/12345"],
        )
        # URL domain match adds 1.0 even with zero noun overlap.
        assert score >= 1.0

    def test_zero_overlap_scores_zero(self):
        score = _score_skeet_match(
            "Completely unrelated sports result today",
            "Austrian police investigation",
            article_urls=[],
        )
        assert score == 0.0

    def test_www_is_stripped_on_domain_match(self):
        score = _score_skeet_match(
            "Details at www.bbc.co.uk/news",
            "Austrian police",
            article_urls=["https://bbc.co.uk/news/article"],
        )
        assert score >= 1.0
