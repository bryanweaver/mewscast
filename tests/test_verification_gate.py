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
    MetaAnalysisBrief,
    PostType,
    PrimarySource,
    SIGN_OFFS,
    StoryDossier,
)
from verification_gate import VerificationGate  # noqa: E402


def _make_brief(consensus_facts: list[str]) -> MetaAnalysisBrief:
    """Minimal brief for the dates_match_brief check."""
    return MetaAnalysisBrief(
        story_id="20260408-vg-test",
        consensus_facts=list(consensus_facts),
        disagreements=[],
        framing_analysis={},
        primary_source_alignment=[],
        missing_context=[],
        suggested_post_type=PostType.REPORT,
        suggested_post_type_reason="",
        confidence=0.8,
    )


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

    def test_primary_with_report_signoff_fails(self, gate):
        """PRIMARY posts stamped with the REPORT sign-off must be rejected."""
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
            "Per the Senate roll call, Reuters reports 68-32.\n\nAnd that's the mews.",
            PostType.PRIMARY,
            primary_urls=["https://www.congress.gov/x"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    # ---- Extra keystone matrix — reviewer-identified gaps -----------------

    def test_bulletin_with_analysis_signoff_mid_body_fails(self, gate):
        """A BULLETIN whose body contains the ANALYSIS sign-off phrase
        buried mid-paragraph (not at the end) must still be rejected.
        This was the H2 finding from code review."""
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            (
                "Breaking: Reuters reports a missile strike. Not yet confirmed. "
                "This cat's view — speculative, personal, subjective. "
                "More details to follow."
            ),
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_bulletin_with_meta_signoff_at_end_fails(self, gate):
        """A BULLETIN whose body ends with the META sign-off must be rejected."""
        dossier = _make_dossier(("Reuters",))
        draft = _make_draft(
            (
                "Breaking: Reuters reports a missile strike. Not yet confirmed.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.BULLETIN,
            outlets_referenced=["Reuters"],
        )
        result = gate.verify(draft, dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_correction_with_meta_signoff_at_end_fails(self, gate, two_outlet_dossier):
        """A CORRECTION ending with the META sign-off must be rejected."""
        draft = _make_draft(
            (
                "CORRECTION: vote was 68-32, not 72-28.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_analysis_with_meta_signoff_fails(self, gate, two_outlet_dossier):
        """ANALYSIS stamped with the META sign-off is a report/opinion
        confusion and must be rejected — the same class of failure as
        ANALYSIS stamped with REPORT."""
        draft = _make_draft(
            (
                "ANALYSIS\n\n"
                "Reuters and AP both reported the 68-32 vote. The eight-state "
                "bloc is becoming a pattern.\n\n"
                "And that's the mews — coverage report."
            ),
            PostType.ANALYSIS,
            outlets_referenced=["Reuters", "Associated Press"],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)

    def test_correction_with_analysis_signoff_mid_body_fails(self, gate, two_outlet_dossier):
        """CORRECTION body must not contain the ANALYSIS sign-off phrase
        anywhere, not just at the end."""
        draft = _make_draft(
            (
                "CORRECTION: vote was 68-32. This cat's view — speculative, "
                "personal, subjective. was the prior sign-off but corrections "
                "carry none."
            ),
            PostType.CORRECTION,
            outlets_referenced=[],
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("signoff_matches_type" in f for f in result.failures)


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
# _check_no_placeholder_template
# ---------------------------------------------------------------------------


class TestNoPlaceholderTemplate:
    """Leaked placeholder-template posts (from the legacy generator's
    failure fallback) must be rejected before they reach the platforms.
    Every observed instance of these phrases in posts_history.json drew
    zero engagement."""

    def test_fur_ther_details_placeholder_rejected(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "This reporter is looking into the Senate vote. "
                "Fur-ther details coming soon from my perch.\n\n"
                "And that's the mews."
            ),
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("placeholder_template" in f for f in result.failures)

    def test_reporter_looking_into_placeholder_rejected(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "Reuters. This reporter is looking into the appropriations "
                "bill.\n\nAnd that's the mews."
            ),
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("placeholder_template" in f for f in result.failures)

    def test_placeholder_rejection_is_case_insensitive(self, gate, two_outlet_dossier):
        draft = _make_draft(
            (
                "Reuters. THIS REPORTER IS LOOKING INTO the vote.\n\n"
                "And that's the mews."
            ),
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("placeholder_template" in f for f in result.failures)

    def test_placeholder_rejected_on_all_post_types(self, gate, two_outlet_dossier):
        """The guard is a correctness floor — it applies to every post
        type, not just REPORT. A leaked placeholder is a bug regardless
        of the pipeline that produced it."""
        # ANALYSIS — normally allowed looser rules, but still blocked
        draft = _make_draft(
            (
                "ANALYSIS\n\nReuters. Fur-ther details coming soon from my perch.\n\n"
                "This cat's view — speculative, personal, subjective."
            ),
            PostType.ANALYSIS,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("placeholder_template" in f for f in result.failures)

    def test_clean_draft_passes_placeholder_check(self, gate, two_outlet_dossier):
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"clean draft should pass: {result.failures}"


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


# ---------------------------------------------------------------------------
# Per-post-type char limits — META gets long_form_max_length, rest get max_length
# ---------------------------------------------------------------------------

class TestPerPostTypeCharLimit:
    """Regression tests for the bug from QA loop 24160006065 where META
    posts were rejected for exceeding a 280-char limit even though
    config.yaml has long_form_max_length: 4000 exactly for META's
    coverage-report format."""

    def _long_form_gate(self) -> VerificationGate:
        # Default production values from config.yaml
        return VerificationGate(max_length=280, long_form_max_length=4000)

    # ---- META uses the long-form budget -------------------------------

    def test_meta_post_1000_chars_passes_under_long_form(self, two_outlet_dossier):
        gate = self._long_form_gate()
        body = "Reuters and Associated Press both cover the vote. " * 18
        text = (
            "COVERAGE REPORT — Senate vote\n\n"
            + body
            + "\n\nAnd that's the mews — coverage report."
        )
        assert len(text) > 280  # sanity: would fail on 280
        assert len(text) < 4000
        draft = _make_draft(text, PostType.META)
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"1000-char META should pass long_form gate: {result.failures}"

    def test_meta_post_5000_chars_fails_even_under_long_form(self, two_outlet_dossier):
        gate = self._long_form_gate()
        # Build a clearly-over-4000-char META body
        body = ("Reuters and Associated Press cover the 68-32 vote. " * 100)
        text = (
            "COVERAGE REPORT — Senate vote\n\n"
            + body
            + "\n\nAnd that's the mews — coverage report."
        )
        assert len(text) > 4000
        draft = _make_draft(text, PostType.META)
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("char_limit" in f for f in result.failures)

    # ---- REPORT stays on the standard 280 budget ----------------------

    def test_report_post_300_chars_fails_on_standard_limit(self, two_outlet_dossier):
        gate = self._long_form_gate()
        # A 300-char REPORT body (well over 280) must be rejected even
        # though long_form_max_length=4000 is available for META.
        filler = "A" * 250
        text = f"Reuters reports {filler}\n\nAnd that's the mews."
        assert len(text) > 280
        draft = _make_draft(text, PostType.REPORT)
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("char_limit" in f for f in result.failures)

    def test_report_post_250_chars_passes(self, two_outlet_dossier):
        gate = self._long_form_gate()
        # 250-char REPORT should fit comfortably under 280
        filler = "A" * 180
        text = f"Reuters {filler}\n\nAnd that's the mews."
        assert len(text) < 280
        draft = _make_draft(text, PostType.REPORT)
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"250-char REPORT should pass: {result.failures}"

    # ---- BULLETIN is NOT in LONG_FORM_TYPES — must use 280 ------------

    def test_bulletin_post_300_chars_fails_even_with_long_form_available(
        self, two_outlet_dossier
    ):
        gate = self._long_form_gate()
        single_outlet_dossier = _make_dossier(("Reuters",))
        # BULLETIN body over 280 must still fail — BULLETIN is not long-form.
        filler = "A" * 250
        text = (
            f"Reuters reports {filler}. "
            "Not yet confirmed elsewhere."
        )
        assert len(text) > 280
        draft = DraftPost(
            text=text,
            post_type=PostType.BULLETIN,
            sign_off=None,
            story_id="20260408-vg-test",
            outlets_referenced=["Reuters"],
            primary_source_urls=[],
        )
        result = gate.verify(draft, single_outlet_dossier)
        assert not result.passed
        assert any("char_limit" in f for f in result.failures)

    # ---- ANALYSIS stays on 280 (intentional) --------------------------

    def test_analysis_post_300_chars_fails_on_standard_limit(self, two_outlet_dossier):
        """ANALYSIS is deliberately NOT in LONG_FORM_TYPES. The workflow
        doc's ANALYSIS example is short, and ANALYSIS is 'used sparingly'
        — the rarity itself is the point. Keep it on the standard 280
        budget until there's a concrete counter-example."""
        gate = self._long_form_gate()
        filler = "A" * 250
        text = (
            f"ANALYSIS\n\nReuters notes {filler}\n\n"
            "This cat's view — speculative, personal, subjective."
        )
        assert len(text) > 280
        draft = _make_draft(text, PostType.ANALYSIS)
        result = gate.verify(draft, two_outlet_dossier)
        assert not result.passed
        assert any("char_limit" in f for f in result.failures)

    # ---- The _effective_max_length helper -----------------------------

    def test_effective_max_length_for_each_post_type(self):
        gate = self._long_form_gate()
        assert gate._effective_max_length(PostType.META) == 4000
        assert gate._effective_max_length(PostType.REPORT) == 280
        assert gate._effective_max_length(PostType.ANALYSIS) == 280
        assert gate._effective_max_length(PostType.BULLETIN) == 280
        assert gate._effective_max_length(PostType.CORRECTION) == 280
        assert gate._effective_max_length(PostType.PRIMARY) == 280


# ---------------------------------------------------------------------------
# _check_dates_match_brief — catches LLM year-regression
# ---------------------------------------------------------------------------

class TestDatesMatchBrief:
    """Real-world motivating case: Tim Cook dossier 2026-04-21. The brief's
    consensus_facts said 'effective September 2026'; the composer wrote
    'September 2025' (dragged back toward its training prior). This check
    rejects that whole class of failure."""

    def test_year_matching_brief_passes(self, gate, two_outlet_dossier):
        brief = _make_brief([
            "Tim Cook is stepping down as Apple CEO effective September 2026."
        ])
        draft = _make_draft(
            "Reuters: Tim Cook steps down September 2026.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier, brief=brief)
        assert result.passed, f"year in brief should pass: {result.failures}"

    def test_year_not_in_brief_fails(self, gate, two_outlet_dossier):
        """The exact Tim Cook failure: draft substitutes 2025 for 2026."""
        brief = _make_brief([
            "Tim Cook is stepping down as Apple CEO effective September 2026."
        ])
        draft = _make_draft(
            "Reuters: Tim Cook steps down September 2025.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier, brief=brief)
        assert not result.passed
        assert any("dates_match_brief" in f for f in result.failures)
        assert any("2025" in f for f in result.failures)

    def test_no_years_in_draft_passes(self, gate, two_outlet_dossier):
        brief = _make_brief(["Senate voted 68-32 on the appropriations bill."])
        draft = _make_draft(
            "Reuters reports the Senate voted 68-32.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier, brief=brief)
        assert result.passed, f"no-year draft should pass: {result.failures}"

    def test_brief_none_skips_check(self, gate, two_outlet_dossier):
        """Legacy callers that don't pass a brief must still work."""
        draft = _make_draft(
            "Reuters: rollback begins in 2029.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier)
        assert result.passed, f"None brief should skip check: {result.failures}"

    def test_year_in_non_consensus_brief_field_passes(self, gate, two_outlet_dossier):
        """Years in any brief field (framing_analysis, missing_context, etc.)
        are allowed, not just consensus_facts."""
        brief = _make_brief(["Senate passed the bill."])
        brief.framing_analysis["Reuters"] = "Context spans 2022 through 2024."
        draft = _make_draft(
            "Reuters: bill echoes the 2022 framework.\n\nAnd that's the mews.",
            PostType.REPORT,
        )
        result = gate.verify(draft, two_outlet_dossier, brief=brief)
        assert result.passed, f"year in framing_analysis should pass: {result.failures}"
