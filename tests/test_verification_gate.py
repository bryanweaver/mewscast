"""
Unit tests for src/verification_gate.py — the Stage 6 copy desk.

The keystone check `_check_signoff_matches_type` gets exhaustive coverage
here because it enforces the single highest-leverage rule in the Walter
Croncat journalism workflow:

    Cronkite's signature sign-off only ever appears under straight reporting.

If we get nothing else right, we get this right.
"""
import os
import sys

import pytest

# Path setup
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from dossier_store import (  # noqa: E402
    ArticleRecord,
    DraftPost,
    PostType,
    PrimarySource,
    SIGN_OFFS,
    StoryDossier,
)
from verification_gate import VerificationGate  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_dossier(outlets=("Reuters", "Associated Press"), primary_sources=None) -> StoryDossier:
    articles = [
        ArticleRecord(
            outlet=o,
            url=f"https://example.com/{i}",
            title=f"title {i}",
            body=f"body text {i}",
            fetched_at="2026-04-08T19:35:00+00:00",
        )
        for i, o in enumerate(outlets)
    ]
    return StoryDossier(
        story_id="20260408-vg-test",
        headline_seed="Test story",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=articles,
        primary_sources=list(primary_sources or []),
        outlet_slants={o: "" for o in outlets},
    )


def _make_draft(
    text: str,
    post_type: PostType,
    outlets_referenced=("Reuters", "Associated Press"),
    primary_urls=(),
) -> DraftPost:
    return DraftPost(
        text=text,
        post_type=post_type,
        sign_off=SIGN_OFFS[post_type],
        story_id="20260408-vg-test",
        outlets_referenced=list(outlets_referenced),
        primary_source_urls=list(primary_urls),
    )


@pytest.fixture
def gate() -> VerificationGate:
    # Generous char limit so we never trip char_limit accidentally on keystone tests.
    return VerificationGate(max_length=600)


@pytest.fixture
def two_outlet_dossier() -> StoryDossier:
    return _make_dossier(("Reuters", "Associated Press"))


# ---------------------------------------------------------------------------
# KEYSTONE — _check_signoff_matches_type
# ---------------------------------------------------------------------------

class TestSignoffMatchesTypeKeystone:
    """Every rule in the sign-off table has a named test here. The matrix
    cases below are the non-negotiable minimum coverage from the Phase C
    brief."""

    # ---- REPORT --------------------------------------------------------

    def test_report_with_correct_signoff_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"keystone REPORT happy path should pass: {result.failures}"

    def test_report_with_no_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_report_with_meta_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.\n\nAnd that's the mews — coverage report.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_report_with_analysis_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "Reuters reports the Senate voted 68-32.\n\n"
                "This cat's view — speculative, personal, subjective."
            ),
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- META ----------------------------------------------------------

    def test_meta_with_correct_signoff_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "COVERAGE REPORT — Reuters and Associated Press diverge on framing.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.META,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"keystone META happy path should pass: {result.failures}"

    def test_meta_with_report_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "COVERAGE REPORT — Reuters and Associated Press diverge on framing.\n\n"
                "And that's the mews."
            ),
            PostType.META,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- ANALYSIS ------------------------------------------------------

    def test_analysis_with_correct_signoff_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "ANALYSIS\n\nReuters reports a pattern — this cat sees the same bloc.\n\n"
                "This cat's view — speculative, personal, subjective."
            ),
            PostType.ANALYSIS,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"keystone ANALYSIS happy path should pass: {result.failures}"

    def test_analysis_with_report_signoff_fails(self, gate, two_outlet_dossier):
        """The worst-case confusion — opinion stamped as a report."""
        draft = _make_draft(
            "ANALYSIS\n\nReuters: this is a pattern.\n\nAnd that's the mews.",
            PostType.ANALYSIS,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed, "ANALYSIS with REPORT sign-off must be rejected"
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- BULLETIN ------------------------------------------------------

    def test_bulletin_with_no_signoff_and_hedge_passes(self, gate):
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            "Reuters reports a missile strike. Not yet confirmed by other outlets.",
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert result.passed, f"keystone BULLETIN happy path should pass: {result.failures}"

    def test_bulletin_with_report_signoff_fails(self, gate):
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            (
                "Reuters reports a missile strike. Not yet confirmed by other outlets.\n\n"
                "And that's the mews."
            ),
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_bulletin_with_signoff_mid_sentence_fails(self, gate):
        """BULLETIN bodies must not contain the sign-off substring anywhere."""
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            (
                "Reuters reports a missile strike — And that's the mews is the usual "
                "close, but this is not that. Not yet confirmed."
            ),
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- CORRECTION ----------------------------------------------------

    def test_correction_with_no_signoff_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "CORRECTION: A prior post said 72-28. The actual vote was 68-32. Source: congress.gov.",
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"keystone CORRECTION happy path should pass: {result.failures}"

    def test_correction_with_report_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "CORRECTION: vote was 68-32.\n\nAnd that's the mews.",
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_correction_with_analysis_signoff_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "CORRECTION: vote was 68-32.\n\n"
                "This cat's view — speculative, personal, subjective."
            ),
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- PRIMARY -------------------------------------------------------

    def test_primary_with_correct_signoff_passes(self, gate):
        dossier = _make_dossier(
            outlets=("Reuters", "Associated Press"),
            primary_sources=[
                PrimarySource(
                    kind="congress_record",
                    url="https://www.congress.gov/x",
                    title="Roll call",
                    excerpt=None,
                )
            ],
        )
        draft = _make_draft(
            (
                "Per the Senate roll call, Reuters reports 68-32. The bill heads to the House.\n\n"
                "And that's the mews — straight from the source."
            ),
            PostType.PRIMARY,
            primary_urls=["https://www.congress.gov/x"],
        )
        result = gate.verify(draft, dossier)
        assert result.passed, f"keystone PRIMARY happy path should pass: {result.failures}"

    def test_primary_without_primary_sources_in_dossier_fails(self, gate):
        """PRIMARY posts require a primary source in the dossier — this is the
        accountability check. A PRIMARY post with the right sign-off but no
        primary source must still fail."""
        dossier = _make_dossier(outlets=("Reuters", "Associated Press"))  # no primary sources
        draft = _make_draft(
            (
                "Reuters reports 68-32.\n\n"
                "And that's the mews — straight from the source."
            ),
            PostType.PRIMARY,
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("primary_source_for_accountability" in f for f in result.failures)


# ---------------------------------------------------------------------------
# _check_source_count
# ---------------------------------------------------------------------------

class TestSourceCount:
    """REPORT/META need >=2 articles; BULLETIN needs >=1 plus a hedge."""

    def test_report_with_one_article_fails(self, gate):
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            "Reuters reports the vote.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("source_count" in f for f in result.failures)

    def test_report_with_two_articles_passes_count_check(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters and Associated Press agree the vote was 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed

    def test_meta_with_one_article_fails(self, gate):
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            (
                "COVERAGE REPORT — Reuters on its own.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.META,
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("source_count" in f for f in result.failures)

    def test_bulletin_without_hedge_fails(self, gate):
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            "Reuters reports a missile strike hit downtown.",
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("source_count" in f for f in result.failures)

    def test_bulletin_with_zero_articles_fails(self, gate):
        dossier = _make_dossier(())
        draft = _make_draft(
            "Reuters reports a strike. Not yet verified by other outlets.",
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("source_count" in f for f in result.failures)


# ---------------------------------------------------------------------------
# _check_outlet_in_body
# ---------------------------------------------------------------------------

class TestOutletInBody:
    def test_report_without_outlet_name_in_body_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "The Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("outlet_in_body" in f for f in result.failures)

    def test_report_with_outlet_name_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed

    def test_correction_allowed_without_outlet_name(self, gate, two_outlet_dossier):
        """CORRECTIONs cite a corrected source that may not be a dossier outlet."""
        draft = _make_draft(
            "CORRECTION: vote was 68-32 per congress.gov.",
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed

    def test_outlet_name_match_is_case_insensitive(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "REUTERS reports the Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed


# ---------------------------------------------------------------------------
# _check_no_editorial_words
# ---------------------------------------------------------------------------

class TestNoEditorialWords:
    def test_report_with_shocking_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the shocking 68-32 vote.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("no_editorial_words" in f for f in result.failures)

    def test_report_with_obviously_fails(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the 68-32 vote. Obviously this changes everything.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("no_editorial_words" in f for f in result.failures)

    def test_analysis_with_shocking_passes(self, gate, two_outlet_dossier):
        """ANALYSIS posts are explicitly exempted — labeled commentary."""
        draft = _make_draft(
            (
                "ANALYSIS\n\nReuters reports a shocking breakdown — obviously a pattern.\n\n"
                "This cat's view — speculative, personal, subjective."
            ),
            PostType.ANALYSIS,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"ANALYSIS must allow editorial words: {result.failures}"

    def test_meta_enforces_editorial_words(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "COVERAGE REPORT — Reuters buried the stunning 68-32 detail.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.META,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("no_editorial_words" in f for f in result.failures)


# ---------------------------------------------------------------------------
# _check_hedge_attribution
# ---------------------------------------------------------------------------

class TestHedgeAttribution:
    def test_according_to_with_nearby_outlet_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "According to Reuters, the vote was 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed

    def test_according_to_without_outlet_fails(self, gate, two_outlet_dossier):
        # Include "Reuters" at the very start so outlet_in_body passes but the
        # "according to" phrase has no outlet in its ±80 char window.
        draft = _make_draft(
            (
                "Reuters. "
                + ("X " * 60)
                + "The vote happened, according to officials with knowledge.\n\n"
                + "And that's the mews."
            ),
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("hedge_attribution" in f for f in result.failures)

    def test_reportedly_with_nearby_outlet_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters says the vote was reportedly 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed


# ---------------------------------------------------------------------------
# _check_char_limit
# ---------------------------------------------------------------------------

class TestCharLimit:
    def test_post_under_limit_passes(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the vote.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed

    def test_post_over_limit_fails(self, two_outlet_dossier):
        tight_gate = VerificationGate(max_length=50)
        draft = _make_draft(
            "Reuters " + ("A" * 200) + "\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = tight_gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("char_limit" in f for f in result.failures)

    def test_long_form_gate_accepts_longer_post(self, two_outlet_dossier):
        long_gate = VerificationGate(max_length=4000)
        long_text = "Reuters " + ("A" * 3000) + "\n\nAnd that's the mews."
        draft = _make_draft(long_text, PostType.REPORT)
        result = long_gate.verify(draft, two_outlet_dossier)
        assert result.passed
