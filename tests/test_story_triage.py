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
        assert triage._is_hard_reject(c) is True

    def test_anonymous_single_source_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Anonymous official may resign next week",
            source_signals=["FoxNews"],
        )
        assert triage._is_hard_reject(c) is True

    def test_single_politician_tweet_no_event_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Senator slammed by colleague in heated exchange",
            source_signals=["FoxNews"],
        )
        assert triage._is_hard_reject(c) is True

    def test_recycled_outrage_without_event_is_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Politician slammed, blasted, and eviscerated on the floor",
            source_signals=["FoxNews", "Newsmax"],
        )
        assert triage._is_hard_reject(c) is True

    def test_multi_source_event_is_not_hard_rejected(self, triage):
        c = _Candidate(
            headline_seed="Senate passes Appropriations Bill 68-32",
            source_signals=["Reuters", "AP", "FoxNews"],
        )
        assert triage._is_hard_reject(c) is False


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
