"""
Stage 5 — Post Composer (Walter Croncat journalism workflow).

Picks one of the six post-type prompts based on the brief's suggested_post_type
(or an explicit override) and asks Claude to generate the post text. The
composer assembles a DraftPost dataclass — text, sign-off, post type, outlet
list — but it does NOT itself stamp the sign-off onto the text. Per the
Cronkite-fidelity principle, the model has to learn the rule. The verification
gate (Stage 6) is what enforces it after the fact.

Public API:
    PostComposer(
        model="claude-sonnet-4-6",
        anthropic_client=None,
        prompt_loader=None,
        max_length=280,
        long_form_max_length=4000,
    )
        .compose(brief, dossier, post_type=None, max_length=None) -> DraftPost
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from dossier_store import (
    DraftPost,
    MetaAnalysisBrief,
    PostType,
    SIGN_OFFS,
    StoryDossier,
)
from verification_gate import CHAR_LIMIT_REASON_PREFIX


# ---------------------------------------------------------------------------
# Post-type → prompt filename mapping
# Phase A established the convention {post_type_lower}_post.md.
# ---------------------------------------------------------------------------

PROMPT_FILES: dict[PostType, str] = {
    PostType.REPORT:     "report_post.md",
    PostType.META:       "meta_post.md",
    PostType.ANALYSIS:   "analysis_post.md",
    PostType.BULLETIN:   "bulletin_post.md",
    PostType.CORRECTION: "correction_post.md",
    PostType.PRIMARY:    "primary_post.md",
}


# Post types that may use the X Premium long-form character budget.
# Kept in lockstep with VerificationGate.LONG_FORM_TYPES so the composer
# never generates a draft longer than the gate will accept.
LONG_FORM_TYPES: set[PostType] = {
    PostType.META,
}


class PostComposer:
    """Stage 5 of the Croncat journalism pipeline."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        anthropic_client=None,
        prompt_loader=None,
        max_length: int = 280,
        long_form_max_length: int = 4000,
    ):
        self.model = model
        self._client = anthropic_client
        self._prompt_loader = prompt_loader
        self.max_length = max_length
        self.long_form_max_length = long_form_max_length

    def _effective_max_length(self, post_type: PostType) -> int:
        """Return the character budget the prompt template should see for
        this post type. META gets the long-form budget; everything else
        uses the standard 280-char budget."""
        if post_type in LONG_FORM_TYPES:
            return self.long_form_max_length
        return self.max_length

    def _max_tokens_for(self, post_type: PostType) -> int:
        """Scale the Claude `max_tokens` ceiling to the character budget for
        this post type.

        Rule of thumb: ~3 characters per output token, plus a 300-token
        safety margin so the model isn't forced to clip the sign-off.
        A 600-token floor preserves historical behavior for short-form
        posts (REPORT/BULLETIN/etc — 280 chars maps to ~393 tokens, well
        below the floor). Long-form META at 4000 chars maps to ~1633
        tokens, which leaves enough headroom for a full coverage report
        plus the keystone sign-off.

        Surfaced by QA loop iteration 2 run 24160420780, where META
        drafts were being truncated mid-sentence by a hardcoded
        max_tokens=600 ceiling and then rejected by the verification
        gate for sign-off mismatch (a downstream symptom of the upstream
        token-budget bug).
        """
        char_budget = self._effective_max_length(post_type)
        return max(600, (char_budget // 3) + 300)

    # ---- public ------------------------------------------------------------

    def compose(
        self,
        brief: MetaAnalysisBrief,
        dossier: StoryDossier,
        post_type: Optional[PostType] = None,
        max_length: Optional[int] = None,
        correction_inputs: Optional[dict] = None,
        retry_reasons: Optional[list[str]] = None,
    ) -> DraftPost:
        """Render a draft post for the chosen post type.

        `correction_inputs` is the only post-type-specific extra hook —
        CORRECTION needs original_post_text, original_post_url, wrong_claim,
        corrected_claim, corrected_source_outlet, corrected_source_url.
        For every other post type the brief + dossier is enough.

        `retry_reasons` is populated by the caller (Stage 7 orchestrator)
        when the verification gate has just rejected a prior draft. The
        reasons are injected as a system-style preface above the main prompt
        so the model can see exactly which rules it broke and how to fix
        them on the second attempt. If None or empty, the main prompt is
        sent verbatim.

        `max_length` is optional. If the caller passes an explicit value
        it wins (used by tests that want a specific budget). Otherwise the
        composer picks the right budget per post type: long_form_max_length
        for META, max_length for everything else.
        """
        chosen_type = post_type or brief.suggested_post_type
        if not isinstance(chosen_type, PostType):
            chosen_type = PostType(chosen_type)

        effective_max = (
            max_length if max_length is not None
            else self._effective_max_length(chosen_type)
        )

        # Claude's prose output doesn't count chars precisely. The prompt
        # gets a target tighter than the gate enforces, creating a safety
        # margin for the model's natural overshoot:
        #   - Short-form (280): 7% margin -> 260 (iteration 12 regression)
        #   - Long-form META (6500): 5% margin -> 6175 (run 24605009292
        #     overshot by 569 chars on first draft and 141 on retry,
        #     disproving the earlier "no margin needed" assumption)
        # Explicit max_length from the caller wins verbatim — tests rely
        # on this to pin exact budgets. Floors (200 short-form, 500
        # long-form) guard against compounded retries shrinking below a
        # usable length if a new LONG_FORM_TYPES member with a small
        # budget is ever added.
        # The floor is clamped to effective_max — if the configured budget
        # is smaller than the floor (e.g. max_length=150), the hard gate
        # limit wins. Otherwise prompt_target would exceed effective_max
        # and every draft would fail char_limit on the first attempt.
        target_floor = min(
            500 if chosen_type in LONG_FORM_TYPES else 200,
            effective_max,
        )
        if max_length is not None:
            prompt_target = effective_max
        elif chosen_type in LONG_FORM_TYPES:
            prompt_target = max(target_floor, int(effective_max * 0.95))
        else:
            prompt_target = max(target_floor, int(effective_max * 0.93))

        # If a prior attempt already overshot the char budget, tighten the
        # target further so the rewrite has real headroom to trim. Without
        # this, retries tend to shrink by only a few percent and still miss
        # (run 24605009292: 7069 -> 6641, both over 6500). The floor
        # prevents unbounded shrinkage across many retries.
        if retry_reasons and any(
            isinstance(r, str) and r.startswith(CHAR_LIMIT_REASON_PREFIX)
            for r in retry_reasons
        ):
            prompt_target = max(target_floor, int(prompt_target * 0.93))

        prompt = self._build_prompt(
            chosen_type, brief, dossier, prompt_target, correction_inputs or {}
        )

        if retry_reasons:
            prompt = self._prefix_with_retry_guidance(prompt, retry_reasons)

        client = self._get_client()
        try:
            text = self._call_claude(client, prompt, chosen_type)
        except Exception as e:
            raise RuntimeError(f"post_composer: Claude call failed: {e}") from e

        text = self._strip_quotes(text or "").strip()

        # Post-process the draft before returning so the verification gate
        # never sees oversize text or orphan hedge terms. The model's retry
        # prompt was insufficient in practice (run 24605009292: 7069 -> 6641,
        # both over 6500). Hard-enforce the budget here.
        outlet_names = [a.outlet for a in dossier.articles if a.outlet]
        text = self._repair_hedge_attribution(text, outlet_names)
        text = self._enforce_char_limit(text, effective_max)

        sign_off = SIGN_OFFS.get(chosen_type)

        outlets_referenced = [a.outlet for a in dossier.articles]
        primary_source_urls = [p.url for p in dossier.primary_sources]

        return DraftPost(
            text=text,
            post_type=chosen_type,
            sign_off=sign_off,
            story_id=dossier.story_id,
            outlets_referenced=outlets_referenced,
            primary_source_urls=primary_source_urls,
        )

    # ---- post-processing repairs (belt-and-suspenders for gate rules) -----

    @staticmethod
    def _enforce_char_limit(text: str, max_length: int) -> str:
        """Truncate text to <= max_length at the nearest sentence boundary.

        The composer prompt already asks the model to stay under the limit
        with a safety margin, but long-form outputs overshoot anyway. The
        gate (Stage 6) will reject >max_length drafts and the retry only
        shrinks by a few percent — see run 24605009292 where 7069 -> 6641
        chars, both still over the 6500 cap. Hard-enforce here.

        Preference order when trimming:
          1. Cut at the last sentence end (``. `` / ``! `` / ``? ``) <= cap
          2. Cut at the last paragraph boundary (``\\n\\n``) <= cap
          3. Cut at the last whitespace <= cap
          4. Hard cut at the cap as a final fallback
        """
        if not text or len(text) <= max_length:
            return text

        window = text[: max_length + 1]

        # Prefer a sentence boundary. Walk the common terminators and
        # pick the latest one that fits. Any sentence break is better than
        # a mid-word cut — no pct-of-budget threshold.
        best = -1
        for terminator in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
            idx = window.rfind(terminator)
            if idx > best:
                best = idx + len(terminator) - 1  # keep the punctuation
        if best >= 0:
            return text[: best + 1].rstrip()

        # No sentence break in window — try paragraph, then whitespace,
        # then a hard cut as the final fallback.
        para = window.rfind("\n\n")
        if para >= 0:
            return text[:para].rstrip()
        space = window.rfind(" ")
        if space >= 0:
            return text[:space].rstrip()
        return text[:max_length].rstrip()

    @staticmethod
    def _repair_hedge_attribution(text: str, outlet_names: list[str]) -> str:
        """Attribute bare ``reportedly`` / ``according to`` to an outlet.

        The verification gate's ``hedge_attribution`` check fails when these
        trigger phrases appear without an outlet name within 80 chars. If
        the model produced such a phrase, graft the first available outlet
        onto it so the gate passes (e.g. ``reportedly`` -> ``reportedly,
        according to [outlet]``). This is a rescue, not a rewrite: the draft
        is otherwise acceptable.
        """
        import re as _re

        if not text or not outlet_names:
            return text

        first_outlet = outlet_names[0]

        def _window_has_outlet(t: str, start: int, end: int) -> bool:
            w = t[max(0, start - 80) : min(len(t), end + 80)].lower()
            return any(o.lower() in w for o in outlet_names)

        # Pass 1: bare "reportedly" with no outlet in its window — graft one.
        pattern_reportedly = _re.compile(r"\breportedly\b", flags=_re.IGNORECASE)
        out: list[str] = []
        last = 0
        for m in pattern_reportedly.finditer(text):
            s, e = m.span()
            if _window_has_outlet(text, s, e):
                continue
            insertion = f"{m.group(0)}, according to {first_outlet}"
            out.append(text[last:s])
            out.append(insertion)
            last = e
        if out:
            out.append(text[last:])
            text = "".join(out)

        # Pass 2: bare "according to" with no outlet in its window — append one.
        pattern_according = _re.compile(r"\baccording to\b", flags=_re.IGNORECASE)
        out = []
        last = 0
        for m in pattern_according.finditer(text):
            s, e = m.span()
            if _window_has_outlet(text, s, e):
                continue
            # Insert the outlet right after "according to" so the phrase reads
            # naturally. Preserve the model's casing on the trigger itself.
            insertion = f"{m.group(0)} {first_outlet},"
            out.append(text[last:s])
            out.append(insertion)
            last = e
        if out:
            out.append(text[last:])
            text = "".join(out)

        return text

    # ---- prompt construction (pure logic — exercised by smoke test) -------

    @staticmethod
    def _prefix_with_retry_guidance(prompt: str, reasons: list[str]) -> str:
        """Prepend a system-style block explaining what the verification gate
        rejected on the previous attempt.

        The block is appended BEFORE the original prompt so the main
        instructions stay intact. The gate's failure strings are rendered
        verbatim — they read like "signoff_matches_type: REPORT post must
        end with ..." which is exactly the feedback the model needs.
        """
        if not reasons:
            return prompt
        bullet_list = "\n".join(f"- {r}" for r in reasons)
        retry_block = (
            "# RETRY — verification gate rejected your previous draft.\n"
            "The following rules were broken. Fix each one and re-draft the\n"
            "post. Do NOT apologize. Do NOT explain. Output only the corrected\n"
            "post text exactly as it should be published.\n\n"
            f"{bullet_list}\n\n"
            "---\n\n"
        )
        return retry_block + prompt

    def _build_prompt(
        self,
        post_type: PostType,
        brief: MetaAnalysisBrief,
        dossier: StoryDossier,
        max_length: int,
        correction_inputs: dict,
    ) -> str:
        loader = self._get_prompt_loader()
        filename = PROMPT_FILES[post_type]

        # Common placeholders shared across most prompts
        common = self._common_placeholders(brief, dossier, max_length)

        # Post-type-specific placeholders
        if post_type == PostType.BULLETIN:
            single_outlet = self._single_outlet(dossier)
            return loader.load(filename, single_outlet=single_outlet, **common)

        if post_type == PostType.META:
            topic = self._meta_topic(brief, dossier)
            return loader.load(filename, topic=topic, **common)

        if post_type == PostType.PRIMARY:
            ps = dossier.primary_sources[0] if dossier.primary_sources else None
            primary_kind = ps.kind if ps else "primary_source"
            primary_title = ps.title if ps else "Primary source"
            primary_excerpt = (ps.excerpt or "") if ps else ""
            return loader.load(
                filename,
                primary_source_kind=primary_kind,
                primary_source_title=primary_title,
                primary_source_excerpt=primary_excerpt,
                **common,
            )

        if post_type == PostType.CORRECTION:
            ci = correction_inputs or {}
            return loader.load(
                filename,
                original_post_text=ci.get("original_post_text", ""),
                original_post_url=ci.get("original_post_url", ""),
                wrong_claim=ci.get("wrong_claim", ""),
                corrected_claim=ci.get("corrected_claim", ""),
                corrected_source_outlet=ci.get("corrected_source_outlet", ""),
                corrected_source_url=ci.get("corrected_source_url", ""),
                brief_json=common["brief_json"],
                max_length=max_length,
            )

        # REPORT, ANALYSIS — only need the common placeholder set
        return loader.load(filename, **common)

    @staticmethod
    def _common_placeholders(
        brief: MetaAnalysisBrief, dossier: StoryDossier, max_length: int
    ) -> dict:
        outlets = sorted({a.outlet for a in dossier.articles}) if dossier.articles else []
        primary_url = dossier.primary_sources[0].url if dossier.primary_sources else ""

        # Sourcing transparency counts (Phase 4)
        full_text_count = sum(
            1 for a in dossier.articles if a.body and len(a.body) >= 500
        )
        headline_only_count = len(dossier.articles) - full_text_count

        # Time/date context — same shape used by content_generator
        now = datetime.now()
        current_date = now.strftime("%B %d, %Y")
        day_of_week = now.strftime("%A")
        hour = now.hour
        if 5 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 18:
            time_period = "afternoon"
        else:
            time_period = "evening"

        try:
            brief_json = json.dumps(brief.to_dict(), indent=2, default=str)
        except Exception:
            brief_json = "{}"

        return {
            "brief_json": brief_json,
            "outlets_list": ", ".join(outlets),
            "primary_source_url": primary_url,
            "max_length": max_length,
            "current_date": current_date,
            "day_of_week": day_of_week,
            "time_period": time_period,
            "full_text_count": full_text_count,
            "headline_only_count": headline_only_count,
        }

    @staticmethod
    def _single_outlet(dossier: StoryDossier) -> str:
        if dossier.articles:
            return dossier.articles[0].outlet
        return ""

    @staticmethod
    def _meta_topic(brief: MetaAnalysisBrief, dossier: StoryDossier) -> str:
        # Best topic anchor we have for a META post is the headline_seed
        return dossier.headline_seed

    # ---- Claude call -------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic SDK not installed") from e
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY env var not set")
        self._client = Anthropic(api_key=api_key)
        return self._client

    def _get_prompt_loader(self):
        if self._prompt_loader is not None:
            return self._prompt_loader
        from prompt_loader import get_prompt_loader
        self._prompt_loader = get_prompt_loader()
        return self._prompt_loader

    def _call_claude(self, client, prompt: str, post_type: PostType) -> str:
        msg = client.messages.create(
            model=self.model,
            max_tokens=self._max_tokens_for(post_type),
            messages=[{"role": "user", "content": prompt}],
        )
        if hasattr(msg, "content") and msg.content:
            first = msg.content[0]
            if hasattr(first, "text"):
                return first.text
            if isinstance(first, dict):
                return first.get("text", "")
        return ""

    @staticmethod
    def _strip_quotes(text: str) -> str:
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text


# ---------------------------------------------------------------------------
# Smoke test — pure logic only (no API calls)
# ---------------------------------------------------------------------------

class _StubPromptLoader:
    """Records the filename + kwargs of every load() call for assertion."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def load(self, filename, **kwargs):
        self.calls.append((filename, dict(kwargs)))
        return f"[STUB {filename}] {sorted(kwargs.keys())}"


class _FakeClaude:
    def __init__(self, text):
        self._text = text
        self.calls = 0

        outer = self
        class _Messages:
            def create(inner_self, **kwargs):
                outer.calls += 1
                class _Resp:
                    def __init__(self, t):
                        class _Block:
                            def __init__(self, x): self.text = x
                        self.content = [_Block(t)]
                return _Resp(outer._text)
        self.messages = _Messages()


def _smoke_test() -> None:
    from dossier_store import ArticleRecord, Disagreement, PrimarySource

    dossier = StoryDossier(
        story_id="20260408-smoke-compose",
        headline_seed="Senate passes appropriations bill 68-32",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters", url="https://reuters.com/x", title="t",
                body="body 1", fetched_at="2026-04-08T19:35:00+00:00",
            ),
            ArticleRecord(
                outlet="AP News", url="https://apnews.com/y", title="t",
                body="body 2", fetched_at="2026-04-08T19:36:00+00:00",
            ),
        ],
        primary_sources=[
            PrimarySource(
                kind="congress_record",
                url="https://www.congress.gov/x",
                title="Roll call",
                excerpt="Yeas 68, nays 32",
            ),
        ],
        outlet_slants={"Reuters": "wire", "AP News": "wire"},
    )

    brief = MetaAnalysisBrief(
        story_id="20260408-smoke-compose",
        consensus_facts=["Senate voted 68-32"],
        disagreements=[Disagreement(topic="framing", positions={"Reuters": "math"})],
        framing_analysis={"Reuters": "leads on math"},
        primary_source_alignment=["Roll call confirms 68-32"],
        missing_context=["No mention of $14B supplement"],
        suggested_post_type=PostType.REPORT,
        suggested_post_type_reason="Two outlets confirm.",
        confidence=0.85,
    )

    # Test each post type renders the right prompt with the right placeholders
    for post_type, expected_filename in PROMPT_FILES.items():
        loader = _StubPromptLoader()
        fake_text = (
            "The Senate voted 68-32. Reuters reports the bill now goes to the House.\n\n"
            "And that's the mews."
        )
        client = _FakeClaude(fake_text)
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
        )

        correction_inputs = None
        if post_type == PostType.CORRECTION:
            correction_inputs = {
                "original_post_text": "An earlier post said 72-28.",
                "original_post_url": "https://x.com/WalterCroncat/status/1",
                "wrong_claim": "vote was 72-28",
                "corrected_claim": "vote was 68-32",
                "corrected_source_outlet": "Senate roll call",
                "corrected_source_url": "https://www.congress.gov/x",
            }

        draft = composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=post_type,
            max_length=280,
            correction_inputs=correction_inputs,
        )

        assert isinstance(draft, DraftPost)
        assert draft.post_type == post_type
        assert draft.story_id == dossier.story_id
        assert draft.outlets_referenced == ["Reuters", "AP News"]
        assert draft.primary_source_urls == ["https://www.congress.gov/x"]
        assert draft.sign_off == SIGN_OFFS[post_type]
        # Check the right prompt file was loaded
        assert len(loader.calls) == 1
        called_filename, called_kwargs = loader.calls[0]
        assert called_filename == expected_filename, (
            f"{post_type}: expected {expected_filename}, got {called_filename}"
        )
        # Common placeholders always present
        if post_type != PostType.CORRECTION:
            for key in ("brief_json", "outlets_list", "primary_source_url", "max_length",
                        "current_date", "day_of_week", "time_period"):
                assert key in called_kwargs, f"{post_type}: missing common placeholder {key}"
        # Per-type placeholders
        if post_type == PostType.BULLETIN:
            assert called_kwargs.get("single_outlet") == "Reuters"
        if post_type == PostType.META:
            assert called_kwargs.get("topic") == dossier.headline_seed
        if post_type == PostType.PRIMARY:
            assert called_kwargs.get("primary_source_kind") == "congress_record"
            assert called_kwargs.get("primary_source_title") == "Roll call"
            assert called_kwargs.get("primary_source_excerpt") == "Yeas 68, nays 32"
        if post_type == PostType.CORRECTION:
            assert called_kwargs.get("wrong_claim") == "vote was 72-28"
            assert called_kwargs.get("corrected_claim") == "vote was 68-32"
            assert called_kwargs.get("corrected_source_outlet") == "Senate roll call"

    # Sanity: composer never stamps the sign-off itself — it leaves the
    # prompt's text intact and lets verification_gate enforce.
    loader2 = _StubPromptLoader()
    client2 = _FakeClaude("Hello world.")  # no sign-off in the body
    composer2 = PostComposer(anthropic_client=client2, prompt_loader=loader2)
    draft2 = composer2.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)
    assert draft2.text == "Hello world."  # untouched
    assert draft2.sign_off == "And that's the mews."  # metadata only

    print("post_composer smoke test OK")


if __name__ == "__main__":
    _smoke_test()
