"""
Unit tests for src/post_composer.py — Stage 5 of the Walter Croncat
journalism workflow.

Covers:
  - Correct prompt file loaded per post type
  - Correct sign-off attached to the resulting DraftPost
  - Composer does NOT stamp the sign-off onto the text (verification_gate does)
  - correction_inputs thread through
  - retry_reasons thread through as a system-style preface
  - Claude failure raises RuntimeError
  - Strips leading/trailing quotes from the model response
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
    Disagreement,
    DraftPost,
    MetaAnalysisBrief,
    PostType,
    PrimarySource,
    SIGN_OFFS,
    StoryDossier,
)
from post_composer import PROMPT_FILES, PostComposer  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubPromptLoader:
    """Records filename + kwargs of every load() call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def load(self, filename, **kwargs):
        self.calls.append((filename, dict(kwargs)))
        return f"[STUB {filename}] kwargs={sorted(kwargs.keys())}"


class _FakeClaude:
    def __init__(self, text, capture_prompt: list = None):
        self._text = text
        self._capture = capture_prompt
        self.calls = 0
        outer = self

        class _Messages:
            def create(inner_self, **kwargs):
                outer.calls += 1
                if outer._capture is not None:
                    msgs = kwargs.get("messages", [])
                    if msgs:
                        outer._capture.append(msgs[0].get("content", ""))

                class _Block:
                    def __init__(self, t):
                        self.text = t

                class _Resp:
                    def __init__(self, t):
                        self.content = [_Block(t)]

                return _Resp(outer._text)

        self.messages = _Messages()


@pytest.fixture
def dossier() -> StoryDossier:
    return StoryDossier(
        story_id="20260408-compose-test",
        headline_seed="Senate passes appropriations bill 68-32",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters", url="https://reuters.com/x", title="t",
                body="body 1", fetched_at="2026-04-08T19:35:00+00:00",
            ),
            ArticleRecord(
                outlet="Associated Press", url="https://apnews.com/y", title="t",
                body="body 2", fetched_at="2026-04-08T19:36:00+00:00",
            ),
        ],
        primary_sources=[
            PrimarySource(
                kind="congress_record",
                url="https://www.congress.gov/x",
                title="Roll call",
                excerpt="Yeas 68, nays 32",
            )
        ],
        outlet_slants={"Reuters": "wire", "Associated Press": "wire"},
    )


@pytest.fixture
def brief() -> MetaAnalysisBrief:
    return MetaAnalysisBrief(
        story_id="20260408-compose-test",
        consensus_facts=["Senate voted 68-32"],
        disagreements=[Disagreement(topic="framing", positions={"Reuters": "math"})],
        framing_analysis={"Reuters": "leads on math"},
        primary_source_alignment=["Roll call confirms 68-32"],
        missing_context=["No mention of $14B supplement"],
        suggested_post_type=PostType.REPORT,
        suggested_post_type_reason="Two outlets confirm.",
        confidence=0.85,
    )


# ---------------------------------------------------------------------------
# Per-type prompt loading
# ---------------------------------------------------------------------------

class TestComposePromptSelection:
    @pytest.mark.parametrize("post_type,expected_filename", list(PROMPT_FILES.items()))
    def test_loads_correct_prompt_file(self, post_type, expected_filename, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("Reuters reports 68-32.\n\nAnd that's the mews.")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)

        correction_inputs = None
        if post_type == PostType.CORRECTION:
            correction_inputs = {
                "original_post_text": "old post",
                "original_post_url": "https://x/1",
                "wrong_claim": "wrong",
                "corrected_claim": "right",
                "corrected_source_outlet": "congress.gov",
                "corrected_source_url": "https://congress.gov/x",
            }

        draft = composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=post_type,
            correction_inputs=correction_inputs,
        )
        assert len(loader.calls) == 1
        assert loader.calls[0][0] == expected_filename
        assert isinstance(draft, DraftPost)
        assert draft.post_type == post_type
        assert draft.story_id == dossier.story_id

    def test_default_post_type_from_brief(self, brief, dossier):
        """If caller omits post_type, fall back to brief.suggested_post_type."""
        loader = _StubPromptLoader()
        client = _FakeClaude("Reuters reports 68-32.\n\nAnd that's the mews.")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        draft = composer.compose(brief=brief, dossier=dossier)
        assert draft.post_type == PostType.REPORT  # brief default
        assert loader.calls[0][0] == "report_post.md"

    def test_string_post_type_coerced(self, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("text")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        draft = composer.compose(brief=brief, dossier=dossier, post_type="META")
        assert draft.post_type == PostType.META


# ---------------------------------------------------------------------------
# Sign-off metadata
# ---------------------------------------------------------------------------

class TestSignoffMetadata:
    @pytest.mark.parametrize("post_type", list(PostType))
    def test_draft_sign_off_matches_sign_offs_table(self, post_type, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("some text")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        correction_inputs = None
        if post_type == PostType.CORRECTION:
            correction_inputs = {
                "original_post_text": "x", "original_post_url": "y",
                "wrong_claim": "w", "corrected_claim": "c",
                "corrected_source_outlet": "o", "corrected_source_url": "u",
            }
        draft = composer.compose(
            brief=brief, dossier=dossier, post_type=post_type,
            correction_inputs=correction_inputs,
        )
        assert draft.sign_off == SIGN_OFFS[post_type]

    def test_composer_does_not_stamp_signoff_onto_text(self, brief, dossier):
        """The composer must leave the body untouched — verification_gate
        is where sign-off enforcement happens. If the stub Claude returns a
        body with no sign-off, the draft.text must still be unchanged."""
        loader = _StubPromptLoader()
        client = _FakeClaude("Hello world.")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        draft = composer.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)
        assert draft.text == "Hello world."
        assert draft.sign_off == "And that's the mews."


# ---------------------------------------------------------------------------
# correction_inputs threading
# ---------------------------------------------------------------------------

class TestCorrectionInputs:
    def test_correction_inputs_threaded_into_prompt(self, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("CORRECTION: the vote was 68-32.")
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        ci = {
            "original_post_text": "An earlier post said 72-28.",
            "original_post_url": "https://x.com/WalterCroncat/status/1",
            "wrong_claim": "vote was 72-28",
            "corrected_claim": "vote was 68-32",
            "corrected_source_outlet": "Senate roll call",
            "corrected_source_url": "https://www.congress.gov/x",
        }
        composer.compose(
            brief=brief, dossier=dossier,
            post_type=PostType.CORRECTION,
            correction_inputs=ci,
        )
        # Inspect the kwargs the loader saw
        assert loader.calls[0][0] == "correction_post.md"
        kwargs = loader.calls[0][1]
        assert kwargs["wrong_claim"] == "vote was 72-28"
        assert kwargs["corrected_claim"] == "vote was 68-32"
        assert kwargs["corrected_source_outlet"] == "Senate roll call"
        assert kwargs["corrected_source_url"] == "https://www.congress.gov/x"


# ---------------------------------------------------------------------------
# retry_reasons threading
# ---------------------------------------------------------------------------

class TestRetryReasons:
    def test_retry_reasons_prefixed_to_prompt(self, brief, dossier):
        captured_prompts: list[str] = []
        loader = _StubPromptLoader()
        client = _FakeClaude("ok text", capture_prompt=captured_prompts)
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)

        composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=PostType.REPORT,
            retry_reasons=[
                "signoff_matches_type: REPORT post must end with 'And that's the mews.'",
                "outlet_in_body: post body does not name any outlet",
            ],
        )
        assert len(captured_prompts) == 1
        prompt_sent = captured_prompts[0]
        assert "RETRY" in prompt_sent
        assert "signoff_matches_type" in prompt_sent
        assert "outlet_in_body" in prompt_sent
        # The original stub prompt must still be present
        assert "[STUB report_post.md]" in prompt_sent

    def test_empty_retry_reasons_no_prefix(self, brief, dossier):
        captured_prompts: list[str] = []
        loader = _StubPromptLoader()
        client = _FakeClaude("ok text", capture_prompt=captured_prompts)
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        composer.compose(
            brief=brief, dossier=dossier,
            post_type=PostType.REPORT,
            retry_reasons=[],
        )
        assert "RETRY" not in captured_prompts[0]

    def test_none_retry_reasons_no_prefix(self, brief, dossier):
        captured_prompts: list[str] = []
        loader = _StubPromptLoader()
        client = _FakeClaude("ok text", capture_prompt=captured_prompts)
        composer = PostComposer(anthropic_client=client, prompt_loader=loader)
        composer.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)
        assert "RETRY" not in captured_prompts[0]


# ---------------------------------------------------------------------------
# Per-post-type max_length passed to prompt template
# ---------------------------------------------------------------------------

class TestPerPostTypeMaxLength:
    """Regression tests for the bug from QA loop 24160006065 where META
    posts were composed under a 280-char budget even though
    config.yaml has long_form_max_length: 4000. The composer must hand
    the right `{max_length}` placeholder to each prompt template."""

    def test_meta_post_receives_long_form_max_length(self, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("COVERAGE REPORT\n\nReuters ...\n\nAnd that's the mews — coverage report.")
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
            max_length=280,
            long_form_max_length=4000,
        )
        composer.compose(brief=brief, dossier=dossier, post_type=PostType.META)
        assert len(loader.calls) == 1
        assert loader.calls[0][0] == "meta_post.md"
        kwargs = loader.calls[0][1]
        assert kwargs["max_length"] == 4000, (
            f"META prompt must get long_form_max_length, got {kwargs['max_length']}"
        )

    def test_report_post_receives_standard_max_length(self, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("Reuters reports 68-32.\n\nAnd that's the mews.")
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
            max_length=280,
            long_form_max_length=4000,
        )
        composer.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)
        assert loader.calls[0][0] == "report_post.md"
        kwargs = loader.calls[0][1]
        assert kwargs["max_length"] == 280

    @pytest.mark.parametrize(
        "post_type,expected_max",
        [
            (PostType.REPORT, 280),
            (PostType.ANALYSIS, 280),
            (PostType.BULLETIN, 280),
            (PostType.PRIMARY, 280),
            (PostType.META, 4000),  # long-form
        ],
    )
    def test_max_length_per_post_type(self, post_type, expected_max, brief, dossier):
        loader = _StubPromptLoader()
        client = _FakeClaude("some text")
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
            max_length=280,
            long_form_max_length=4000,
        )
        composer.compose(brief=brief, dossier=dossier, post_type=post_type)
        kwargs = loader.calls[0][1]
        assert kwargs["max_length"] == expected_max, (
            f"{post_type.value}: expected max_length={expected_max}, "
            f"got {kwargs['max_length']}"
        )

    def test_correction_post_receives_standard_max_length(self, brief, dossier):
        """CORRECTION builds its prompt via a different code path
        (correction_inputs), so it also needs coverage."""
        loader = _StubPromptLoader()
        client = _FakeClaude("CORRECTION: ...")
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
            max_length=280,
            long_form_max_length=4000,
        )
        composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=PostType.CORRECTION,
            correction_inputs={
                "original_post_text": "x",
                "original_post_url": "y",
                "wrong_claim": "w",
                "corrected_claim": "c",
                "corrected_source_outlet": "o",
                "corrected_source_url": "u",
            },
        )
        kwargs = loader.calls[0][1]
        assert kwargs["max_length"] == 280

    def test_explicit_max_length_overrides_per_type_default(self, brief, dossier):
        """Tests and callers can still pass max_length= explicitly to
        override the per-post-type default. Needed so the existing
        smoke tests keep working."""
        loader = _StubPromptLoader()
        client = _FakeClaude("some text")
        composer = PostComposer(
            anthropic_client=client,
            prompt_loader=loader,
            max_length=280,
            long_form_max_length=4000,
        )
        # Force a META post to compose under 280 explicitly.
        composer.compose(
            brief=brief, dossier=dossier,
            post_type=PostType.META, max_length=280,
        )
        kwargs = loader.calls[0][1]
        assert kwargs["max_length"] == 280, (
            "Explicit max_length from caller must win over the per-type default"
        )

    def test_effective_max_length_helper(self):
        composer = PostComposer(max_length=280, long_form_max_length=4000)
        assert composer._effective_max_length(PostType.META) == 4000
        assert composer._effective_max_length(PostType.REPORT) == 280
        assert composer._effective_max_length(PostType.ANALYSIS) == 280
        assert composer._effective_max_length(PostType.BULLETIN) == 280
        assert composer._effective_max_length(PostType.CORRECTION) == 280
        assert composer._effective_max_length(PostType.PRIMARY) == 280


# ---------------------------------------------------------------------------
# Error handling + quote stripping
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_claude_failure_raises_runtimeerror(self, brief, dossier):
        class _BoomClient:
            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("boom")

        composer = PostComposer(
            anthropic_client=_BoomClient(),
            prompt_loader=_StubPromptLoader(),
        )
        with pytest.raises(RuntimeError):
            composer.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)

    def test_quoted_text_stripped(self, brief, dossier):
        client = _FakeClaude('"Reuters reports 68-32. And that\'s the mews."')
        composer = PostComposer(
            anthropic_client=client, prompt_loader=_StubPromptLoader()
        )
        draft = composer.compose(brief=brief, dossier=dossier, post_type=PostType.REPORT)
        assert not draft.text.startswith('"')
        assert not draft.text.endswith('"')
