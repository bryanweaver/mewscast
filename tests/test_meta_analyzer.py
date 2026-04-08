"""
Unit tests for src/meta_analyzer.py — Stage 4 of the Walter Croncat
journalism workflow.

Covers:
  - Prompt construction pulls articles + primary sources
  - Clean JSON response parsing
  - Fenced JSON response parsing
  - Prose-wrapped JSON response parsing
  - Invalid suggested_post_type falls back to REPORT
  - Total garbage returns None
  - End-to-end analyze() with a fake client (counts API calls)
  - JSON-parse retry logic on malformed first response
  - Raising RuntimeError when the model fails twice in a row
"""
import json
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
    MetaAnalysisBrief,
    PostType,
    PrimarySource,
    StoryDossier,
)
from meta_analyzer import MetaAnalyzer  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubPromptLoader:
    """Minimal prompt loader stub; returns a templated string so the
    prompt can be asserted on."""

    def __init__(self):
        self.calls = []

    def load(self, filename, **kwargs):
        self.calls.append((filename, dict(kwargs)))
        return (
            f"[STUB PROMPT {filename}]\n"
            f"story_id={kwargs.get('story_id')}\n"
            f"article_count={kwargs.get('article_count')}\n"
            f"--- ARTICLES ---\n{kwargs.get('articles_block')}\n"
            f"--- PRIMARY ---\n{kwargs.get('primary_sources_block')}\n"
        )


class _FakeClaudeClient:
    """Fake anthropic client that returns a queue of canned responses.

    Pass a list of response strings (or Exception instances) — each call
    to messages.create pops the next one. If the queue is empty, the last
    response is reused.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

        outer = self

        class _Messages:
            def create(inner_self, **kwargs):
                outer.calls += 1
                if not outer._responses:
                    payload = ""
                elif len(outer._responses) == 1:
                    payload = outer._responses[0]
                else:
                    payload = outer._responses.pop(0)
                if isinstance(payload, Exception):
                    raise payload

                class _Block:
                    def __init__(self, t):
                        self.text = t

                class _Resp:
                    def __init__(self, t):
                        self.content = [_Block(t)]

                return _Resp(payload)

        self.messages = _Messages()


@pytest.fixture
def dossier() -> StoryDossier:
    return StoryDossier(
        story_id="20260408-meta-test",
        headline_seed="Senate passes appropriations bill 68-32",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters",
                url="https://reuters.com/x",
                title="Reuters 68-32",
                body="Reuters wire body about the Senate vote.",
                fetched_at="2026-04-08T19:35:00+00:00",
            ),
            ArticleRecord(
                outlet="The New York Times",
                url="https://nytimes.com/y",
                title="NYT framing",
                body="NYT body framing the vote.",
                fetched_at="2026-04-08T19:36:00+00:00",
                is_wire_derived=True,
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
        outlet_slants={"Reuters": "wire", "The New York Times": "left-mainstream"},
    )


@pytest.fixture
def clean_brief_json():
    return json.dumps({
        "story_id": "20260408-meta-test",
        "consensus_facts": ["Senate voted 68-32"],
        "disagreements": [
            {"topic": "framing", "positions": {"Reuters": "math", "NYT": "politics"}}
        ],
        "framing_analysis": {"Reuters": "math", "NYT": "politics"},
        "primary_source_alignment": ["Roll call confirms 68-32"],
        "missing_context": ["No mention of $14B supplement"],
        "suggested_post_type": "META",
        "suggested_post_type_reason": "Framing divergence with primary source gap.",
        "confidence": 0.88,
    })


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    def test_prompt_contains_story_id_and_articles(self, dossier):
        loader = _StubPromptLoader()
        analyzer = MetaAnalyzer(prompt_loader=loader)
        prompt = analyzer._build_prompt(dossier)
        assert "Reuters" in prompt
        assert "20260408-meta-test" in prompt
        assert "wire-derived" in prompt  # NYT is marked wire-derived
        assert "Yeas 68" in prompt       # primary source excerpt
        assert loader.calls[0][0] == "meta_analysis.md"

    def test_prompt_handles_empty_primary_sources(self):
        d = StoryDossier(
            story_id="x",
            headline_seed="h",
            detected_at="2026-04-08T00:00:00+00:00",
            articles=[
                ArticleRecord(
                    outlet="Reuters", url="https://r/x", title="t",
                    body="b", fetched_at="2026-04-08T00:00:00+00:00",
                )
            ],
        )
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        prompt = analyzer._build_prompt(d)
        assert "No primary sources" in prompt

    def test_prompt_handles_empty_articles(self):
        d = StoryDossier(
            story_id="x",
            headline_seed="h",
            detected_at="2026-04-08T00:00:00+00:00",
            articles=[],
        )
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        prompt = analyzer._build_prompt(d)
        assert "No articles in dossier" in prompt


# ---------------------------------------------------------------------------
# Parse logic
# ---------------------------------------------------------------------------

class TestParseBrief:
    def test_parses_clean_json(self, clean_brief_json):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        brief = analyzer._parse_brief("20260408-meta-test", clean_brief_json)
        assert brief is not None
        assert brief.suggested_post_type == PostType.META
        assert brief.confidence == 0.88
        assert brief.disagreements[0].positions["Reuters"] == "math"

    def test_parses_fenced_json(self, clean_brief_json):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        fenced = "```json\n" + clean_brief_json + "\n```"
        brief = analyzer._parse_brief("20260408-meta-test", fenced)
        assert brief is not None
        assert brief.suggested_post_type == PostType.META

    def test_parses_prose_wrapped_json(self, clean_brief_json):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        wrapped = "Here is the analysis:\n\n" + clean_brief_json + "\n\nLet me know."
        brief = analyzer._parse_brief("20260408-meta-test", wrapped)
        assert brief is not None

    def test_invalid_post_type_falls_back_to_report(self):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        bad = json.dumps({
            "story_id": "x",
            "consensus_facts": [],
            "disagreements": [],
            "framing_analysis": {},
            "primary_source_alignment": [],
            "missing_context": [],
            "suggested_post_type": "GOSSIP",  # invalid
            "suggested_post_type_reason": "",
            "confidence": 0.5,
        })
        brief = analyzer._parse_brief("x", bad)
        assert brief is not None
        assert brief.suggested_post_type == PostType.REPORT

    def test_garbage_returns_none(self):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        assert analyzer._parse_brief("x", "this is not json at all") is None
        assert analyzer._parse_brief("x", "") is None

    def test_forces_story_id_when_missing(self):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        payload = json.dumps({
            "consensus_facts": [],
            "disagreements": [],
            "framing_analysis": {},
            "primary_source_alignment": [],
            "missing_context": [],
            "suggested_post_type": "REPORT",
            "suggested_post_type_reason": "",
            "confidence": 0.5,
        })
        brief = analyzer._parse_brief("fallback-id", payload)
        assert brief is not None
        assert brief.story_id == "fallback-id"

    def test_malformed_disagreements_are_filtered(self):
        analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())
        payload = json.dumps({
            "story_id": "x",
            "consensus_facts": [],
            "disagreements": [
                "not a dict",
                {"topic": "ok", "positions": {"A": "one"}},
                {"topic": "bad", "positions": "not a dict"},
            ],
            "framing_analysis": {},
            "primary_source_alignment": [],
            "missing_context": [],
            "suggested_post_type": "REPORT",
            "suggested_post_type_reason": "",
            "confidence": 0.5,
        })
        brief = analyzer._parse_brief("x", payload)
        assert brief is not None
        assert len(brief.disagreements) == 1
        assert brief.disagreements[0].topic == "ok"


# ---------------------------------------------------------------------------
# End-to-end analyze()
# ---------------------------------------------------------------------------

class TestAnalyzeEndToEnd:
    def test_single_call_on_clean_response(self, dossier, clean_brief_json):
        fake = _FakeClaudeClient([clean_brief_json])
        analyzer = MetaAnalyzer(
            anthropic_client=fake,
            prompt_loader=_StubPromptLoader(),
        )
        brief = analyzer.analyze(dossier)
        assert brief.suggested_post_type == PostType.META
        assert fake.calls == 1

    def test_retry_once_on_bad_first_response(self, dossier, clean_brief_json):
        fake = _FakeClaudeClient(["garbage not json", clean_brief_json])
        analyzer = MetaAnalyzer(
            anthropic_client=fake,
            prompt_loader=_StubPromptLoader(),
        )
        brief = analyzer.analyze(dossier)
        assert brief.suggested_post_type == PostType.META
        assert fake.calls == 2

    def test_raises_after_double_failure(self, dossier):
        fake = _FakeClaudeClient(["still garbage", "also garbage"])
        analyzer = MetaAnalyzer(
            anthropic_client=fake,
            prompt_loader=_StubPromptLoader(),
        )
        with pytest.raises(RuntimeError):
            analyzer.analyze(dossier)
        assert fake.calls == 2

    def test_raises_on_client_exception(self, dossier):
        fake = _FakeClaudeClient([RuntimeError("boom")])
        analyzer = MetaAnalyzer(
            anthropic_client=fake,
            prompt_loader=_StubPromptLoader(),
        )
        with pytest.raises(RuntimeError):
            analyzer.analyze(dossier)
