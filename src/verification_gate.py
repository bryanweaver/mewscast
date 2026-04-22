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

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from dossier_store import DraftPost, MetaAnalysisBrief, PostType, SIGN_OFFS, StoryDossier

# Matches any 4-digit year in the 1900–2099 range. Used by
# `_check_dates_match_brief` to reject drafts where the composer
# substituted a year from its training prior instead of copying the
# brief's year verbatim.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


# Reason-string prefix used when _check_char_limit rejects a draft.
# Exported so downstream components (post_composer retry-tightening,
# main.py fabrication-retry) can detect char-budget failures without
# duplicating the string literal. If the gate ever renames this prefix,
# consumers update by reference rather than silently drifting out of sync.
CHAR_LIMIT_REASON_PREFIX = "char_limit:"


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
        "also covered by",
    ]

    # Leaked template placeholders that must never ship. The legacy
    # single-article generator had a fallback that produced posts like
    # "This reporter is looking into {headline}. Fur-ther details coming
    # soon from my perch." which were shipping unfilled — every observed
    # instance drew zero engagement. Guarded at the gate so no pipeline
    # (legacy, journalism, or future) can ever ship them again.
    PLACEHOLDER_TEMPLATES = [
        "fur-ther details coming soon",
        "this reporter is looking into",
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

    # Post types that may use the X Premium long-form character budget.
    # META is the flagship coverage-report format and is explicitly called
    # out in the workflow doc Stage 6 table (line 269): "Long-form posts
    # allowed via Premium for META and longer REPORT types." ANALYSIS is
    # deliberately NOT here — the workflow doc's ANALYSIS example is short,
    # and section 3 of the doc describes ANALYSIS as "used sparingly" with
    # "rarity is the entire point". We keep ANALYSIS on the 280-char budget
    # until there is a concrete counter-example that needs more room.
    LONG_FORM_TYPES = {
        PostType.META,
    }

    def __init__(
        self,
        max_length: int = 280,
        long_form_max_length: int = 4000,
    ):
        self.max_length = max_length
        self.long_form_max_length = long_form_max_length

    def _effective_max_length(self, post_type: PostType) -> int:
        """Return the character budget for this post type.

        META posts get the long-form budget (X Premium). Everything else
        uses the standard 280-char budget.
        """
        if post_type in self.LONG_FORM_TYPES:
            return self.long_form_max_length
        return self.max_length

    # ---- public ------------------------------------------------------------

    def verify(
        self,
        draft: DraftPost,
        dossier: StoryDossier,
        brief: Optional[MetaAnalysisBrief] = None,
    ) -> VerificationResult:
        """Run every check and aggregate the failures.

        When `brief` is supplied, the date-match check runs against the
        Stage 4 consensus facts. Callers that don't have a brief (legacy
        tests, ad-hoc verification) pass None and the check is skipped.
        """
        failures: list[str] = []

        for check in (
            self._check_source_count,
            self._check_outlet_in_body,
            self._check_signoff_matches_type,
            self._check_no_editorial_words,
            self._check_hedge_attribution,
            self._check_primary_source_for_accountability,
            self._check_no_placeholder_template,
        ):
            ok, reason = check(draft, dossier)
            if not ok and reason:
                failures.append(reason)

        ok, reason = self._check_dates_match_brief(draft, brief)
        if not ok and reason:
            failures.append(reason)

        # _check_char_limit picks the right budget per post type —
        # META gets long_form_max_length, everything else uses max_length.
        effective_max = self._effective_max_length(draft.post_type)
        ok, reason = self._check_char_limit(draft, max_length=effective_max)
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
                    "source_count: Your BULLETIN has no hedge phrase — add 'not yet "
                    "confirmed' or 'not yet verified' somewhere in the body."
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
            f"outlet_in_body: Your draft names no outlet — add one of these to "
            f"the body: {', '.join(outlet_names)}."
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

        # Branch 1: this post type has a customary sign-off (REPORT, META,
        # ANALYSIS, PRIMARY).
        #
        # Missing sign-off is NOT a rejection. Per user preference, an
        # occasional missing sign-off is acceptable — rejecting a whole
        # story because the composer forgot to type a closing line costs
        # more than it buys. The keystone rule below still applies:
        # the draft must not end with a DIFFERENT post type's sign-off.
        # That's the opinion/reporting confusion we actually care about.
        if expected is not None:
            if text.endswith(expected):
                # Paranoia: a draft like "And that's the mews — coverage
                # report. And that's the mews." would double-stamp types.
                stripped = text[: -len(expected)].rstrip()
                for other in other_sign_offs:
                    if stripped.endswith(other):
                        return False, (
                            f"signoff_matches_type: Your {draft.post_type.value} draft ends with "
                            f"TWO sign-offs ('{other}' then '{expected}'). Remove the "
                            f"'{other}' line; keep only '{expected}'."
                        )
                return True, None

            # No expected sign-off at the end — allowed, but make sure a
            # DIFFERENT type's sign-off didn't sneak in instead. That
            # would be opinion-smuggling and is the actual trust breach.
            for other in other_sign_offs:
                if text.endswith(other):
                    return False, (
                        f"signoff_matches_type: Your {draft.post_type.value} draft ends with "
                        f"'{other}' — that's the sign-off for a different post type. "
                        f"Either end with '{expected}' or remove the sign-off entirely."
                    )
            return True, None

        # Branch 2: this post type has NO sign-off (BULLETIN, CORRECTION).
        # Cronkite's withholding rule: the absence of the sign-off is the
        # statement. We must therefore reject any draft that snuck a sign-off
        # of any kind onto an unsigned post type.
        for other in other_sign_offs:
            if text.endswith(other):
                return False, (
                    f"signoff_matches_type: Your {draft.post_type.value} draft ends "
                    f"with '{other}' — but {draft.post_type.value} posts carry NO "
                    f"sign-off. Remove that closing line."
                )
        # Belt-and-suspenders: forbid ANY sign-off string (from any post type)
        # anywhere in the body of a BULLETIN/CORRECTION, not just at the end.
        # A sign-off phrase buried mid-paragraph is still brand dilution and
        # still blurs the report/opinion line — Cronkite's withholding rule
        # applies to the phrase itself, not just its placement.
        body = draft.text or ""
        all_sign_off_phrases = [v for v in SIGN_OFFS.values() if v is not None]
        for so in all_sign_off_phrases:
            if so in body:
                return False, (
                    f"signoff_matches_type: Your {draft.post_type.value} draft contains "
                    f"the phrase '{so}' somewhere in the body — remove it. "
                    f"{draft.post_type.value} posts carry NO sign-off."
                )
        # Extra paranoia: the REPORT/META phrase "And that's the mews" as a
        # stem (without the trailing punctuation) is also forbidden, because
        # a composer could write "And that's the mews for now" and escape
        # the exact-match check above.
        if "And that's the mews" in body:
            return False, (
                f"signoff_matches_type: Your {draft.post_type.value} draft contains "
                f"\"And that's the mews\" somewhere in the body — remove that phrase. "
                f"{draft.post_type.value} posts carry NO sign-off."
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
            return False, (
                f"no_editorial_words: Your draft contains editorializing word(s) "
                f"{hits}. Replace each with a neutral verb or remove the phrase "
                f"entirely. These words smuggle opinion into straight reporting."
            )
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
                        f"hedge_attribution: You wrote '{trigger}' without naming an "
                        f"outlet near it. Change to '{trigger} <outlet>' using one of: "
                        f"{', '.join(outlet_names)}."
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

    def _check_no_placeholder_template(
        self, draft: DraftPost, dossier: StoryDossier
    ) -> tuple[bool, Optional[str]]:
        """Block leaked template placeholders from any pipeline.

        The legacy content-generator had a fallback template that produced
        zero-engagement posts when generation failed silently. Post-mortem
        showed posts like 'This reporter is looking into {headline}. Fur-ther
        details coming soon from my perch.' reaching both Bluesky and X.
        Runs for all post types — this is a correctness floor, not a style rule.
        """
        text_lower = (draft.text or "").lower()
        hits = [p for p in self.PLACEHOLDER_TEMPLATES if p in text_lower]
        if hits:
            return False, (
                f"placeholder_template: Your draft leaked template placeholder(s) "
                f"{hits}. This means upstream generation failed — rewrite the whole "
                f"draft from the brief, do not use fallback boilerplate."
            )
        return True, None

    def _check_dates_match_brief(
        self, draft: DraftPost, brief: Optional[MetaAnalysisBrief]
    ) -> tuple[bool, Optional[str]]:
        """Reject drafts that contain a 4-digit year not present in the brief.

        LLMs regress years toward their training prior — a composer reading
        "effective September 2026" in the brief will still sometimes write
        "September 2025" in the draft. Real incident: Tim Cook dossier
        2026-04-21 (docs/dossiers/2026-04-21-tim-cook-s-predecessor-*).

        The check is conservative: if *any* year in the draft doesn't also
        appear somewhere in the serialized brief, reject. Composer can
        still reference years the brief mentions in any field, not just
        consensus_facts.

        Skipped when no brief is supplied.
        """
        if brief is None:
            return True, None

        text = draft.text or ""
        draft_years = set(_YEAR_RE.findall(text))
        if not draft_years:
            return True, None

        brief_blob = json.dumps(brief.to_dict())
        allowed_years = set(_YEAR_RE.findall(brief_blob))

        missing = sorted(draft_years - allowed_years)
        if missing:
            allowed_sorted = sorted(allowed_years)
            return False, (
                f"dates_match_brief: You wrote year(s) {missing} but the brief "
                f"only uses {allowed_sorted}. Replace {missing} with the correct "
                f"year from {allowed_sorted}. This is likely an LLM year-regression "
                f"— copy years from the brief verbatim."
            )
        return True, None

    def _check_char_limit(
        self, draft: DraftPost, max_length: int = 280
    ) -> tuple[bool, Optional[str]]:
        """Hard char-limit check. Long-form META posts can pass a higher
        max_length when the gate is constructed."""
        text = draft.text or ""
        if len(text) > max_length:
            overshoot = len(text) - max_length
            return False, (
                f"{CHAR_LIMIT_REASON_PREFIX} Your draft is {len(text)} chars but "
                f"the max is {max_length} — cut at least {overshoot} chars. Keep "
                f"the lead, attribution, and sign-off; trim supporting details."
            )
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

    # ---- placeholder_template -----------------------------------------
    draft_placeholder_unfilled = DraftPost(
        text=(
            "This reporter is looking into the Senate appropriations vote. "
            "Fur-ther details coming soon from my perch.\n\n"
            "And that's the mews."
        ),
        post_type=PostType.REPORT,
        sign_off=SIGN_OFFS[PostType.REPORT],
        story_id="20260408-vg-test",
        outlets_referenced=["Reuters", "AP News"],
        primary_source_urls=[],
    )
    res = gate.verify(draft_placeholder_unfilled, dossier)
    assert not res.passed
    assert any("placeholder_template" in f for f in res.failures), res.failures

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
