"""
Stage 6 — Verification Gate (Walter Croncat journalism workflow).

The "copy desk" of the pipeline. Pure-function-style hard rules: takes a
DraftPost + StoryDossier, returns a VerificationResult. No I/O, no LLM calls,
no surprises. Every check is independent and explainable.

The keystone check is `_check_signoff_matches_type`, which enforces the
single highest-leverage rule in the entire workflow:

  *Croncat's signature sign-off only ever appears under straight reporting.*

If we get nothing else right, we get this right.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from dossier_store import DraftPost, PostType, SIGN_OFFS, StoryDossier


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """The structured outcome of a verification gate run.

    `failures` is a list of human-readable strings — one per failed check.
    The composer (Stage 5) can use these to retry once with corrective
    instructions. An empty `failures` list with `passed=True` is the
    publish-ready state.
    """
    passed: bool
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "failures": list(self.failures)}


# ---------------------------------------------------------------------------
# VerificationGate
# ---------------------------------------------------------------------------

class VerificationGate:
    """Pre-publish hard checks for Croncat draft posts."""

    EDITORIAL_WORDS = [
        "shocking",
        "outrageous",
        "stunning",
        "obviously",
        "of course",
        "everyone knows",
        "the truth is",
        "incredibly",
        "astonishing",
        "clearly,",
    ]

    HEDGE_PHRASES_FOR_BULLETIN = [
        "not yet confirmed",
        "not yet verified",
    ]

    # Post types where editorial word checking is enforced.
    # ANALYSIS is excluded because labeled commentary is allowed there;
    # the workflow doc explicitly says ANALYSIS is the home for judgment.
    EDITORIAL_ENFORCED_TYPES = {
        PostType.REPORT,
        PostType.META,
        PostType.PRIMARY,
        PostType.BULLETIN,
        PostType.CORRECTION,
    }

    def __init__(self, max_length: int = 280):
        self.max_length = max_length

    # ---- public ------------------------------------------------------------

    def verify(self, draft: DraftPost, dossier: StoryDossier) -> VerificationResult:
        """Run every check and aggregate the failures."""
        failures: list[str] = []

        for check in (
            self._check_source_count,
            self._check_outlet_in_body,
            self._check_signoff_matches_type,
            self._check_no_editorial_words,
            self._check_hedge_attribution,
            self._check_primary_source_for_accountability,
        ):
            ok, reason = check(draft, dossier)
            if not ok and reason:
                failures.append(reason)

        # _check_char_limit takes a max_length argument
        ok, reason = self._check_char_limit(draft, max_length=self.max_length)
        if not ok and reason:
            failures.append(reason)

        return VerificationResult(passed=not failures, failures=failures)

    # ---- individual checks (each returns (passed, reason_or_None)) -------

    def _check_source_count(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """REPORT and META posts need >=2 articles. BULLETIN may have 1 but
        must include a hedge phrase."""
        n = len(dossier.articles)

        if draft.post_type in (PostType.REPORT, PostType.META):
            if n < 2:
                return False, (
                    f"source_count: {draft.post_type.value} posts require >=2 outlets "
                    f"in the dossier; found {n}"
                )
            return True, None

        if draft.post_type == PostType.BULLETIN:
            text_lower = draft.text.lower()
            has_hedge = any(p in text_lower for p in self.HEDGE_PHRASES_FOR_BULLETIN)
            if n < 1:
                return False, "source_count: BULLETIN posts require >=1 outlet in the dossier"
            if not has_hedge:
                return False, (
                    "source_count: BULLETIN post body must contain a hedge phrase "
                    "(e.g. 'not yet confirmed' / 'not yet verified')"
                )
            return True, None

        # ANALYSIS, PRIMARY, CORRECTION — no fixed source-count rule here
        return True, None

    def _check_outlet_in_body(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """At least one outlet from dossier.outlet_slants (or
        dossier.articles) must appear literally in draft.text (case-insensitive)."""
        outlet_names = list(dossier.outlet_slants.keys())
        if not outlet_names:
            outlet_names = [a.outlet for a in dossier.articles]
        outlet_names = [o for o in outlet_names if o]

        # CORRECTION posts cite the corrected source which may not be a
        # dossier outlet at all (e.g. a primary document) — skip the check.
        if draft.post_type == PostType.CORRECTION:
            return True, None

        if not outlet_names:
            return False, "outlet_in_body: dossier has no outlet names to check against"

        text_lower = draft.text.lower()
        for outlet in outlet_names:
            if outlet.lower() in text_lower:
                return True, None
        return False, (
            f"outlet_in_body: post body does not name any of the outlets in the "
            f"dossier ({outlet_names})"
        )

    def _check_signoff_matches_type(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """THE KEYSTONE RULE.

        Cronkite earned "And that's the way it is" by reserving it for
        straight reporting only. Croncat's sign-offs follow the same logic:

        SIGN_OFFS (from dossier_store) is the single source of truth.

        Branches:
          - If the expected sign-off is a string (REPORT/META/ANALYSIS/
            PRIMARY), the draft text MUST end with that exact string after
            stripping trailing whitespace. This is what makes the post a
            credible REPORT/META/etc — the literal sign-off is the seal.
            We also explicitly check that the post is NOT closing with a
            DIFFERENT type's sign-off, because the worst possible outcome is
            an ANALYSIS post stamped with the REPORT sign-off (or vice
            versa). That confusion is exactly what destroys Cronkite-style
            trust.

          - If the expected sign-off is None (BULLETIN/CORRECTION), the
            draft text MUST NOT end with any of the OTHER known sign-offs
            in SIGN_OFFS.values() AND must NOT contain "And that's the mews"
            anywhere in the body. BULLETIN and CORRECTION are deliberately
            unsigned: the absence of a sign-off is itself the statement,
            mirroring Cronkite's refusal to claim "that's the way it is"
            when the facts weren't yet in.
        """
        expected = SIGN_OFFS.get(draft.post_type)
        text = (draft.text or "").rstrip()

        # Build the set of "other types' sign-offs" once.
        other_sign_offs: list[str] = [
            v for k, v in SIGN_OFFS.items()
            if v is not None and k != draft.post_type
        ]

        # Branch 1: this post type has a required sign-off (REPORT, META,
        # ANALYSIS, PRIMARY).
        if expected is not None:
            # Must end with the literal expected sign-off
            if not text.endswith(expected):
                return False, (
                    f"signoff_matches_type: {draft.post_type.value} post must end with "
                    f"the literal sign-off '{expected}'"
                )
            # Must NOT also be ending with a *different* type's sign-off.
            # This is paranoia about edge cases like "And that's the mews —
            # coverage report. And that's the mews." but it costs nothing.
            stripped = text[: -len(expected)].rstrip()
            for other in other_sign_offs:
                if stripped.endswith(other):
                    return False, (
                        f"signoff_matches_type: {draft.post_type.value} post also ends with "
                        f"another type's sign-off '{other}' before the expected one"
                    )
            return True, None

        # Branch 2: this post type has NO sign-off (BULLETIN, CORRECTION).
        # Cronkite's withholding rule: the absence of the sign-off is the
        # statement. We must therefore reject any draft that snuck a sign-off
        # of any kind onto an unsigned post type.
        for other in other_sign_offs:
            if text.endswith(other):
                return False, (
                    f"signoff_matches_type: {draft.post_type.value} posts must NOT end "
                    f"with any sign-off; found '{other}' at the end"
                )
        # Belt-and-suspenders: forbid the substring "And that's the mews"
        # anywhere in the body of a BULLETIN/CORRECTION. Even mid-paragraph
        # use would dilute the brand of the sign-off.
        if "And that's the mews" in (draft.text or ""):
            return False, (
                f"signoff_matches_type: {draft.post_type.value} posts must NOT contain "
                f"\"And that's the mews\" anywhere in the body"
            )
        return True, None

    def _check_no_editorial_words(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """Banned editorializing words. Skipped for ANALYSIS posts where
        labeled commentary is allowed."""
        if draft.post_type not in self.EDITORIAL_ENFORCED_TYPES:
            return True, None

        text_lower = (draft.text or "").lower()
        hits: list[str] = []
        for word in self.EDITORIAL_WORDS:
            # Word-boundary match for single-word entries; substring for phrases.
            if " " in word or word.endswith(","):
                if word in text_lower:
                    hits.append(word)
            else:
                if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
                    hits.append(word)

        if hits:
            return False, f"no_editorial_words: post contains banned word(s) {hits}"
        return True, None

    def _check_hedge_attribution(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """If 'according to' or 'reportedly' appears, an outlet name must
        appear within 80 chars of it."""
        text = draft.text or ""
        if not text:
            return True, None

        outlet_names = [a.outlet for a in dossier.articles]
        outlet_names = [o for o in outlet_names if o]

        for trigger in ("according to", "reportedly"):
            for match in re.finditer(re.escape(trigger), text, flags=re.IGNORECASE):
                start, end = match.span()
                window_start = max(0, start - 80)
                window_end = min(len(text), end + 80)
                window = text[window_start:window_end].lower()
                if not any(o.lower() in window for o in outlet_names):
                    return False, (
                        f"hedge_attribution: '{trigger}' used without an outlet name "
                        f"within 80 characters"
                    )
        return True, None

    def _check_primary_source_for_accountability(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """If the dossier has primary sources, the draft is allowed to omit
        the URL from the body (it goes in the source-reply per the existing
        Mewscast pattern), but the dossier MUST carry them through. We check
        the dossier — not the body — and pass.

        If the dossier has no primary sources at all, we don't fail this
        check unconditionally because not every story is an accountability
        story. We only fail when the post type is one that should *demand*
        a primary source (PRIMARY) and the dossier has none.
        """
        if draft.post_type == PostType.PRIMARY:
            if not dossier.primary_sources:
                return False, (
                    "primary_source_for_accountability: PRIMARY posts require at least one "
                    "primary source in the dossier"
                )
        # Otherwise: this check is purely advisory and always passes.
        return True, None

    def _check_char_limit(
        self, draft: DraftPost, max_length: int = 280
    ) -> tuple[bool, Optional[str]]:
        """Hard char-limit check. Long-form META posts can pass a higher
        max_length when the gate is constructed."""
        text = draft.text or ""
        if len(text) > max_length:
            return False, f"char_limit: post is {len(text)} chars (max {max_length})"
        return True, None


# ---------------------------------------------------------------------------
# Smoke test — covers each check, with extra coverage on the keystone
# ---------------------------------------------------------------------------

def _make_dossier_with_outlets(outlets: list[str], primary_sources=None) -> StoryDossier:
    from dossier_store import ArticleRecord, PrimarySource
    arts = []
    for i, o in enumerate(outlets):
        arts.append(ArticleRecord(
            outlet=o,
            url=f"https://example.com/{i}",
            title=f"t{i}",
            body=f"body {i}",
            fetched_at="2026-04-08T19:35:00+00:00",
        ))
    return StoryDossier(
        story_id="20260408-vg-test",
        headline_seed="vg test",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=arts,
        primary_sources=primary_sources or [],
        outlet_slants={o: "" for o in outlets},
    )


def _smoke_test() -> None:
    gate = VerificationGate(max_length=600)  # generous so we don't trip on smoke text

    # ---- KEYSTONE: signoff matches type --------------------------------
    dossier = _make_dossier_with_outlets(["Reuters", "AP News"])

    # REPORT — correct sign-off → passes
    draft_ok = DraftPost(
        text="Reuters reports the Senate voted 68-32.\n\nAnd that's the mews.",
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_ok, dossier)
    assert res.passed, f"REPORT happy path should pass: {res.failures}"

    # REPORT — wrong sign-off (META variant) → fails
    draft_wrong = DraftPost(
        text="Reuters reports the Senate voted 68-32.\n\nAnd that's the mews — coverage report.",
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_wrong, dossier)
    assert not res.passed
    assert any("signoff_matches_type" in f for f in res.failures), res.failures

    # ANALYSIS — correct sign-off → passes
    draft_analysis = DraftPost(
        text=(
            "ANALYSIS\n\nReuters reports the vote breakdown shows the same eight-state bloc.\n\n"
            "This cat's view — speculative, personal, subjective."
        ),
        post_type=PostType.ANALYSIS,
        sign_off=SIGN_OFFS[PostType.ANALYSIS],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_analysis, dossier)
    assert res.passed, f"ANALYSIS happy path should pass: {res.failures}"

    # ANALYSIS — REPORT sign-off snuck in → KEYSTONE FAILURE
    draft_analysis_bad = DraftPost(
        text="ANALYSIS\n\nReuters: this is a pattern.\n\nAnd that's the mews.",
        post_type=PostType.ANALYSIS,
        sign_off=SIGN_OFFS[PostType.ANALYSIS],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_analysis_bad, dossier)
    assert not res.passed
    assert any("signoff_matches_type" in f for f in res.failures), (
        f"keystone should reject ANALYSIS with REPORT sign-off, got {res.failures}"
    )

    # BULLETIN — no sign-off, hedge phrase present → passes
    draft_bulletin = DraftPost(
        text="Reuters reports a missile strike. Not yet confirmed by other outlets.",
        post_type=PostType.BULLETIN,
        sign_off=None,
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_bulletin, _make_dossier_with_outlets(["Reuters"]))
    assert res.passed, f"BULLETIN happy path should pass: {res.failures}"

    # BULLETIN — sign-off snuck in → KEYSTONE FAILURE
    draft_bulletin_bad = DraftPost(
        text=(
            "Reuters reports a missile strike. Not yet confirmed by other outlets.\n\n"
            "And that's the mews."
        ),
        post_type=PostType.BULLETIN,
        sign_off=None,
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_bulletin_bad, _make_dossier_with_outlets(["Reuters"]))
    assert not res.passed
    assert any("signoff_matches_type" in f for f in res.failures), res.failures

    # CORRECTION — must NOT carry any sign-off
    draft_correction = DraftPost(
        text="CORRECTION:\n\nA prior post said 72-28. The actual vote was 68-32.\nSource: congress.gov.",
        post_type=PostType.CORRECTION,
        sign_off=None,
        story_id="20260408-vg-test",
        outlets_referenced=[],
        primary_source_urls=[],
    )
    res = gate.verify(draft_correction, _make_dossier_with_outlets(["Reuters"]))
    assert res.passed, f"CORRECTION happy path should pass: {res.failures}"

    # CORRECTION — accidentally signed → KEYSTONE FAILURE
    draft_correction_bad = DraftPost(
        text=(
            "CORRECTION:\n\nA prior post said 72-28. The actual vote was 68-32.\n\n"
            "This cat's view — speculative, personal, subjective."
        ),
        post_type=PostType.CORRECTION,
        sign_off=None,
        story_id="20260408-vg-test",
        outlets_referenced=[],
        primary_source_urls=[],
    )
    res = gate.verify(draft_correction_bad, _make_dossier_with_outlets(["Reuters"]))
    assert not res.passed
    assert any("signoff_matches_type" in f for f in res.failures), res.failures

    # ---- source_count --------------------------------------------------
    one_outlet = _make_dossier_with_outlets(["Reuters"])
    draft_report_thin = DraftPost(
        text="Reuters reports the vote.\n\nAnd that's the mews.",
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_report_thin, one_outlet)
    assert not res.passed
    assert any("source_count" in f for f in res.failures), res.failures

    # ---- outlet_in_body ------------------------------------------------
    draft_no_outlet = DraftPost(
        text="The Senate voted 68-32.\n\nAnd that's the mews.",
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_no_outlet, dossier)
    assert not res.passed
    assert any("outlet_in_body" in f for f in res.failures), res.failures

    # ---- editorial words -----------------------------------------------
    draft_editorial = DraftPost(
        text=(
            "Reuters reports the shocking 68-32 vote. Obviously this changes everything.\n\n"
            "And that's the mews."
        ),
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_editorial, dossier)
    assert not res.passed
    assert any("no_editorial_words" in f for f in res.failures), res.failures

    # ANALYSIS allows editorial words
    draft_analysis_color = DraftPost(
        text=(
            "ANALYSIS\n\nReuters reports the shocking breakdown — and obviously this is a pattern.\n\n"
            "This cat's view — speculative, personal, subjective."
        ),
        post_type=PostType.ANALYSIS,
        sign_off=SIGN_OFFS[PostType.ANALYSIS],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_analysis_color, dossier)
    assert res.passed, f"ANALYSIS may use editorial words: {res.failures}"

    # ---- hedge_attribution ---------------------------------------------
    draft_hedge_orphan = DraftPost(
        text="The vote happened, according to officials with knowledge.\n\nAnd that's the mews.",
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_hedge_orphan, dossier)
    # Should fail outlet_in_body AND hedge_attribution
    assert not res.passed
    assert any("hedge_attribution" in f for f in res.failures), res.failures

    # ---- primary_source_for_accountability ----------------------------
    from dossier_store import PrimarySource
    primary_dossier = _make_dossier_with_outlets(
        ["Reuters", "AP News"],
        primary_sources=[PrimarySource(
            kind="congress_record",
            url="https://www.congress.gov/x",
            title="Roll call",
            excerpt=None,
        )],
    )
    draft_primary_ok = DraftPost(
        text=(
            "Per the Senate roll call, Reuters reports 68-32. The bill heads to the House.\n\n"
            "And that's the mews — straight from the source."
        ),
        post_type=PostType.PRIMARY,
        sign_off=SIGN_OFFS[PostType.PRIMARY],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=["https://www.congress.gov/x"],
    )
    res = gate.verify(draft_primary_ok, primary_dossier)
    assert res.passed, f"PRIMARY happy path should pass: {res.failures}"

    # PRIMARY without primary source → fails
    res = gate.verify(draft_primary_ok, dossier)  # dossier has no primary sources
    assert not res.passed
    assert any("primary_source_for_accountability" in f for f in res.failures), res.failures

    # ---- char_limit ----------------------------------------------------
    short_gate = VerificationGate(max_length=50)
    long_text = "A" * 100 + "\n\nAnd that's the mews."
    draft_long = DraftPost(
        text=long_text,
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = short_gate.verify(draft_long, dossier)
    assert not res.passed
    assert any("char_limit" in f for f in res.failures), res.failures

    print("verification_gate smoke test OK (keystone passes all 6 cases)")


if __name__ == "__main__":
    _smoke_test()
