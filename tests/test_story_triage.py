"""
Unit tests for src/story_triage.py — Stage 2 of the Walter Croncat
journalism workflow.

Covers:
  - Heuristic scoring against each of the 5 need-to-know dimensions
  - Pass-threshold behavior (3/5)
  - Hard rejects: gossip, anonymous single-source, outrage recycling,
    single tweet from one politician with no event
  - triage() end-to-end filter on lists of candidates
"""
import os
import sys
from dataclasses import dataclass

import pytest

# Path setup
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from story_triage import StoryTriage  # noqa: E402


# ---------------------------------------------------------------------------
# Local stub that quacks like trend_detector.TrendCandidate
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    headline_seed: str
    detected_at: str = "2026-04-08T19:30:00+00:00"
    source_signals: list = None
    engagement: int = 0
    story_id: str = "test-id"
    source: str = "x"

    def __post_init__(self):
        if self.source_signals is None:
            self.source_signals = []


@pytest.fixture
def triage() -> StoryTriage:
    return StoryTriage(use_llm=False)


# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------

class TestHeuristicScore:
    def test_multi_outlet_senate_vote_passes(self, triage):
        c = _Candidate(
            headline_seed="Senate passes Appropriations Bill 68-32, averting shutdown - Reuters",
            source_signals=["Reuters", "AP", "FoxNews"],
            engagement=200,
        )
        score, reasons = triage._heuristic_score(c)
        assert score >= 3
        assert "multi-outlet(3)" in reasons
        assert "event-verb" in reasons

    def test_doj_indictment_passes(self, triage):
        c = _Candidate(
            headline_seed="DOJ files indictment in alleged bribery scheme tied to FAA contract",
            source_signals=["Reuters", "AP"],
        )
        score, reasons = triage._heuristic_score(c)
        assert score >= 3
        assert "accountability" in reasons

    def test_single_source_rumor_fails_scoring(self, triage):
        c = _Candidate(
            headline_seed="Source says something might happen",
            source_signals=["FoxNews"],
        )
        score, _ = triage._heuristic_score(c)
        assert score < 3

    def test_impact_axis_recognized(self, triage):
        c = _Candidate(
            headline_seed="Major drug recall affects thousands, FDA announces",
            source_signals=["Reuters", "AP"],
        )
        score, reasons = triage._heuristic_score(c)
        assert "impact" in reasons
        assert "event-verb" in reasons

    def test_proper_noun_qualifies_checkable(self, triage):
        c = _Candidate(
            headline_seed="Nakasaki Arts Festival opens Thursday",
            source_signals=["Reuters", "AP"],
        )
        score, reasons = triage._heuristic_score(c)
        # At minimum, checkable + multi-outlet should fire
        assert "checkable" in reasons
        assert "multi-outlet(2)" in reasons


# ---------------------------------------------------------------------------
# Hard rejects
# ---------------------------------------------------------------------------

class TestHardRejects:
    def test_gossip_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Kim Kardashian seen wearing new outfit at premiere",
            source_signals=["nypost"],
        )
        assert triage._is_hard_reject(c) is not None

    def test_anonymous_single_source_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Anonymous official may resign next week",
            source_signals=["FoxNews"],
        )
        assert triage._is_hard_reject(c) is not None

    def test_single_politician_tweet_no_event_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Senator slammed by colleague in heated exchange",
            source_signals=["FoxNews"],
        )
        assert triage._is_hard_reject(c) is not None

    def test_recycled_outrage_without_event_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Politician slammed, blasted, and eviscerated on the floor",
            source_signals=["FoxNews", "Newsmax"],
        )
        assert triage._is_hard_reject(c) is not None

    def test_multi_source_event_is_not_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Senate passes Appropriations Bill 68-32",
            source_signals=["Reuters", "AP", "FoxNews"],
        )
        assert triage._is_hard_reject(c) is None


# ---------------------------------------------------------------------------
# Full triage() pipeline
# ---------------------------------------------------------------------------

class TestTriageFullPipeline:
    def test_passes_real_story_and_drops_gossip(self, triage):
        candidates = [
            _Candidate(
                headline_seed="Senate passes Appropriations Bill 68-32 averting shutdown",
                source_signals=["Reuters", "AP", "FoxNews"],
                engagement=200,
                story_id="a",
            ),
            _Candidate(
                headline_seed="Kim Kardashian seen wearing new outfit at premiere",
                source_signals=["nypost"],
                engagement=500,
                story_id="b",
            ),
            _Candidate(
                headline_seed="DOJ files indictment in alleged bribery scheme tied to FAA contract",
                source_signals=["Reuters", "AP"],
                engagement=80,
                story_id="c",
            ),
        ]
        passing = triage.triage(candidates)
        ids = [c.story_id for c in passing]
        assert "a" in ids, f"Senate vote should pass: {ids}"
        assert "c" in ids, f"DOJ indictment should pass: {ids}"
        assert "b" not in ids, f"gossip leaked through: {ids}"

    def test_preserves_candidate_order(self, triage):
        candidates = [
            _Candidate(
                headline_seed="Senate passes Appropriations Bill 68-32",
                source_signals=["Reuters", "AP"],
                story_id="first",
            ),
            _Candidate(
                headline_seed="DOJ files indictment in FAA contract bribery scheme",
                source_signals=["Reuters", "AP"],
                story_id="second",
            ),
        ]
        passing = triage.triage(candidates)
        assert [c.story_id for c in passing] == ["first", "second"]

    def test_empty_candidate_list_returns_empty(self, triage):
        assert triage.triage([]) == []

    def test_all_rejected_returns_empty(self, triage):
        candidates = [
            _Candidate(
                headline_seed="Senator allegedly slammed by anonymous critic",
                source_signals=["FoxNews"],
            ),
        ]
        passing = triage.triage(candidates)
        assert passing == []

    def test_high_engagement_does_not_override_gossip_hard_reject(self, triage):
        c = _Candidate(
            headline_seed="Kardashian wedding outfit revealed at red carpet premiere",
            source_signals=["nypost"],
            engagement=10_000,
        )
        passing = triage.triage([c])
        assert passing == []


# ---------------------------------------------------------------------------
# Regression tests for QA loop #1 bugs (expanded EVENT_TOKENS,
# news_fetcher source field, news_fetcher multi-outlet credit)
# ---------------------------------------------------------------------------

class TestExpandedEventTokens:
    """Headlines that were hard-rejected in QA loop #1 because their event
    verbs were missing from EVENT_TOKENS. These should now be recognized."""

    def test_guilty_plea_is_event(self, triage):
        c = _Candidate(
            headline_seed="Rex Heuermann Pleads Guilty to Gilgo Beach Serial Killings",
            source_signals=["Reuters", "AP"],
        )
        score, reasons = triage._heuristic_score(c)
        assert "event-verb" in reasons, f"'pleads guilty' should be an event verb: {reasons}"
        assert score >= 3

    def test_declares_is_event(self, triage):
        c = _Candidate(
            headline_seed="Hegseth declares victory in Iran",
            source_signals=["Reuters", "AP"],
        )
        _, reasons = triage._heuristic_score(c)
        assert "event-verb" in reasons

    def test_wins_is_event(self, triage):
        c = _Candidate(
            headline_seed="Chris Taylor wins Wisconsin Supreme Court race",
            source_signals=["Reuters", "AP"],
        )
        _, reasons = triage._heuristic_score(c)
        assert "event-verb" in reasons

    def test_charged_is_event(self, triage):
        c = _Candidate(
            headline_seed="Former official charged with perjury in grand jury probe",
            source_signals=["Reuters"],
        )
        _, reasons = triage._heuristic_score(c)
        assert "event-verb" in reasons


class TestNewsFetcherSource:
    """Regression for Bug 2b — NewsFetcher-fallback candidates are single-
    signal by construction (one URL per top-story) but Google News top-
    stories is itself a curated aggregation. They should not trip the
    single_signal hard-reject and should get multi-outlet credit in scoring."""

    def test_news_fetcher_single_signal_no_event_is_not_hard_rejected(self, triage):
        # Without the source=news_fetcher flag, this would be hard-rejected:
        # single_signal + no event verb + no accountability.
        c = _Candidate(
            headline_seed="Nakasaki Arts Festival opens Thursday",
            source_signals=["theguardian.com"],
            source="news_fetcher",
        )
        assert triage._is_hard_reject(c) is None

    def test_news_fetcher_gets_multi_outlet_credit(self, triage):
        c = _Candidate(
            headline_seed="Israeli attack kills Al Jazeera journalist Mohammed Wishah",
            source_signals=["aljazeera.com"],
            source="news_fetcher",
        )
        score, reasons = triage._heuristic_score(c)
        # Should fire multi-outlet(google-news-curated)
        assert any("multi-outlet" in r for r in reasons), f"expected multi-outlet credit: {reasons}"
        # And the full score should now reach the threshold
        assert score >= 3, f"news_fetcher candidate with event+impact+checkable should pass: {reasons}"

    def test_x_single_signal_still_hard_rejected(self, triage):
        # Same headline as above but as an X candidate — still gets hard rejected
        # because we only relax the rule for news_fetcher candidates.
        c = _Candidate(
            headline_seed="Nakasaki Arts Festival opens Thursday",
            source_signals=["RandomTwitterHandle"],
            source="x",
        )
        assert triage._is_hard_reject(c) is not None

    def test_news_fetcher_gossip_still_rejected(self, triage):
        # Gossip rejection is unconditional — news_fetcher tag does not
        # whitelist celebrity coverage.
        c = _Candidate(
            headline_seed="Kim Kardashian seen wearing new outfit at premiere",
            source_signals=["nypost.com"],
            source="news_fetcher",
        )
        assert triage._is_hard_reject(c) is not None

    def test_rex_heuermann_end_to_end_passes(self, triage):
        """The canonical QA loop #1 failure case — guilty plea from a
        NewsFetcher-fallback candidate. Should pass triage end-to-end."""
        c = _Candidate(
            headline_seed="Rex Heuermann Pleads Guilty to Gilgo Beach Serial Killings",
            source_signals=["nypost.com"],
            source="news_fetcher",
        )
        passing = triage.triage([c])
        assert len(passing) == 1, "Rex Heuermann guilty plea should pass triage"

    def test_chris_taylor_end_to_end_passes(self, triage):
        """Another QA loop #1 failure — election win from NewsFetcher fallback."""
        c = _Candidate(
            headline_seed="Chris Taylor wins Wisconsin Supreme Court race, expanding liberal majority",
            source_signals=["wpr.org"],
            source="news_fetcher",
        )
        passing = triage.triage([c])
        assert len(passing) == 1, "Chris Taylor Supreme Court win should pass triage"
