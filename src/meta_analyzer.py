"""
Stage 4 — Meta-Analyzer (Walter Croncat journalism workflow).

Calls Claude to produce a structured MetaAnalysisBrief from a StoryDossier.
This is the most expensive call in the pipeline and the heart of the
Croncat differentiator: it does NOT paraphrase one outlet, it compares all
outlets in the dossier against each other and against the primary source.

Public API:
    MetaAnalyzer(model="claude-opus-4-6", anthropic_client=None)
        .analyze(dossier: StoryDossier) -> MetaAnalysisBrief

Implementation:
- Loads prompts/meta_analysis.md via PromptLoader.
- Formats the dossier into {articles_block} and {primary_sources_block}.
- Calls Claude with max_tokens=4000.
- Parses the JSON response into a MetaAnalysisBrief.
- If parsing fails, retries once with a corrective system instruction.
- Validates the suggested_post_type against PostType; defaults to REPORT.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from dossier_store import (
    Disagreement,
    MetaAnalysisBrief,
    PostType,
    StoryDossier,
)


class MetaAnalyzer:
    """Stage 4 of the Croncat journalism pipeline."""

    def __init__(
        self,
        model: str = "claude-opus-4-6",
        anthropic_client=None,
        prompt_loader=None,
    ):
        self.model = model
        self._client = anthropic_client
        self._prompt_loader = prompt_loader

    # ---- public ------------------------------------------------------------

    def analyze(self, dossier: StoryDossier) -> MetaAnalysisBrief:
        """Produce a MetaAnalysisBrief for a dossier.

        Raises RuntimeError if the underlying Claude call fails twice and we
        cannot construct a usable brief. The caller (Phase C wire-up) decides
        whether to skip the story or queue it for human review.
        """
        client = self._get_client()
        prompt = self._build_prompt(dossier)

        try:
            raw_text = self._call_claude(client, prompt)
        except Exception as e:
            raise RuntimeError(f"meta_analyzer: Claude call failed: {e}") from e

        brief = self._parse_brief(dossier.story_id, raw_text)
        if brief is not None:
            return brief

        # Retry once with a strict corrective preface
        corrective = (
            "Your previous response was not valid JSON matching the MetaAnalysisBrief schema. "
            "Return ONLY the JSON object, no prose, no Markdown fences, no preamble. "
            "Re-do the analysis now.\n\n" + prompt
        )
        try:
            raw_text2 = self._call_claude(client, corrective)
        except Exception as e:
            raise RuntimeError(f"meta_analyzer: Claude retry failed: {e}") from e

        brief = self._parse_brief(dossier.story_id, raw_text2)
        if brief is None:
            raise RuntimeError(
                "meta_analyzer: could not parse MetaAnalysisBrief from Claude response after 1 retry"
            )
        return brief

    # ---- prompt construction (pure logic — exercised by smoke test) -------

    def _build_prompt(self, dossier: StoryDossier) -> str:
        loader = self._get_prompt_loader()
        articles_block = self._format_articles(dossier)
        primary_sources_block = self._format_primary_sources(dossier)
        return loader.load(
            "meta_analysis.md",
            story_id=dossier.story_id,
            headline_seed=dossier.headline_seed,
            detected_at=dossier.detected_at,
            article_count=len(dossier.articles),
            articles_block=articles_block,
            primary_sources_block=primary_sources_block,
        )

    @staticmethod
    def _format_articles(dossier: StoryDossier) -> str:
        if not dossier.articles:
            return "_No articles in dossier._"
        sections = []
        for i, art in enumerate(dossier.articles, start=1):
            slant = dossier.outlet_slants.get(art.outlet, "")
            slant_str = f" ({slant})" if slant else ""
            wire_flag = " [wire-derived]" if art.is_wire_derived else ""
            sections.append(
                f"## Article {i}: {art.outlet}{slant_str} — {art.title}{wire_flag}\n"
                f"URL: {art.url}\n\n"
                f"{art.body}"
            )
        return "\n\n".join(sections)

    @staticmethod
    def _format_primary_sources(dossier: StoryDossier) -> str:
        if not dossier.primary_sources:
            return "_No primary sources located for this story._"
        sections = []
        for i, ps in enumerate(dossier.primary_sources, start=1):
            excerpt = f"\nExcerpt: {ps.excerpt}" if ps.excerpt else ""
            sections.append(
                f"## Primary {i}: {ps.kind} — {ps.title}\n"
                f"URL: {ps.url}{excerpt}"
            )
        return "\n\n".join(sections)

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

    def _call_claude(self, client, prompt: str) -> str:
        msg = client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        # Tolerate both anthropic SDK objects and plain dicts (test stubs)
        if hasattr(msg, "content") and msg.content:
            first = msg.content[0]
            if hasattr(first, "text"):
                return first.text
            if isinstance(first, dict):
                return first.get("text", "")
        return ""

    # ---- response parsing --------------------------------------------------

    def _parse_brief(self, story_id: str, raw_text: str) -> Optional[MetaAnalysisBrief]:
        if not raw_text:
            return None

        text = raw_text.strip()
        # Strip Markdown fences if Claude added any
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # Find the outermost JSON object — be tolerant of leading/trailing prose
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        json_blob = text[start:end + 1]

        try:
            data = json.loads(json_blob)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        # story_id sanity: keep what Claude returned, but force ours if missing/empty
        if not data.get("story_id"):
            data["story_id"] = story_id

        # Validate suggested_post_type — fall back to REPORT if invalid
        raw_pt = data.get("suggested_post_type", "REPORT")
        try:
            validated_pt = PostType(raw_pt)
        except (ValueError, KeyError):
            print(
                f"[meta_analyzer] invalid suggested_post_type={raw_pt!r}; "
                f"defaulting to REPORT"
            )
            validated_pt = PostType.REPORT
        data["suggested_post_type"] = validated_pt.value

        # Defensive defaults for any missing keys
        data.setdefault("consensus_facts", [])
        data.setdefault("disagreements", [])
        data.setdefault("framing_analysis", {})
        data.setdefault("primary_source_alignment", [])
        data.setdefault("missing_context", [])
        data.setdefault("suggested_post_type_reason", "")
        data.setdefault("confidence", 0.5)

        # Disagreements may come back malformed (positions not a dict, etc.)
        cleaned_disagreements = []
        for d in data.get("disagreements", []) or []:
            if not isinstance(d, dict):
                continue
            topic = d.get("topic", "")
            positions = d.get("positions", {}) or {}
            if isinstance(positions, dict):
                cleaned_disagreements.append(Disagreement(topic=topic, positions={
                    str(k): str(v) for k, v in positions.items()
                }))
        # Re-encode through the canonical from_dict to enforce types
        data["disagreements"] = [d.to_dict() for d in cleaned_disagreements]

        try:
            return MetaAnalysisBrief.from_dict(data)
        except Exception as e:
            print(f"[meta_analyzer] failed to construct MetaAnalysisBrief from parsed JSON: {e}")
            return None


# ---------------------------------------------------------------------------
# Smoke test — pure logic only (no API calls)
# ---------------------------------------------------------------------------

class _StubPromptLoader:
    """Minimal prompt loader stub: returns a templated string with placeholders filled."""

    def load(self, filename, **kwargs):
        return (
            f"[STUB PROMPT for {filename}]\n"
            f"story_id={kwargs.get('story_id')}\n"
            f"article_count={kwargs.get('article_count')}\n"
            f"--- ARTICLES ---\n{kwargs.get('articles_block')}\n"
            f"--- PRIMARY ---\n{kwargs.get('primary_sources_block')}\n"
        )


def _smoke_test() -> None:
    from dossier_store import ArticleRecord, PrimarySource

    # Build a tiny dossier
    dossier = StoryDossier(
        story_id="20260408-smoke-test",
        headline_seed="Test headline",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters",
                url="https://reuters.com/x",
                title="Test 1",
                body="Body of article 1.",
                fetched_at="2026-04-08T19:35:00+00:00",
            ),
            ArticleRecord(
                outlet="The New York Times",
                url="https://nytimes.com/y",
                title="Test 2",
                body="Body of article 2.",
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
            ),
        ],
        outlet_slants={"Reuters": "wire", "The New York Times": "left-mainstream"},
    )

    analyzer = MetaAnalyzer(prompt_loader=_StubPromptLoader())

    # 1. Prompt construction is pure
    prompt = analyzer._build_prompt(dossier)
    assert "Reuters" in prompt
    assert "wire-derived" in prompt
    assert "Yeas 68" in prompt
    assert "20260408-smoke-test" in prompt

    # 2. Parser handles a clean JSON response
    clean_json = json.dumps({
        "story_id": "20260408-smoke-test",
        "consensus_facts": ["Senate voted 68-32"],
        "disagreements": [
            {"topic": "framing", "positions": {"Reuters": "math", "NYT": "politics"}}
        ],
        "framing_analysis": {"Reuters": "leads on the math", "NYT": "leads on politics"},
        "primary_source_alignment": ["Roll call confirms 68-32"],
        "missing_context": ["No mention of $14B supplement"],
        "suggested_post_type": "META",
        "suggested_post_type_reason": "Framing divergence with primary source gap.",
        "confidence": 0.88,
    })
    brief = analyzer._parse_brief("20260408-smoke-test", clean_json)
    assert brief is not None
    assert brief.suggested_post_type == PostType.META
    assert brief.consensus_facts == ["Senate voted 68-32"]
    assert brief.disagreements[0].positions["Reuters"] == "math"

    # 3. Parser handles a JSON-in-fence response
    fenced = "```json\n" + clean_json + "\n```"
    brief2 = analyzer._parse_brief("20260408-smoke-test", fenced)
    assert brief2 is not None
    assert brief2.suggested_post_type == PostType.META

    # 4. Parser handles prose-wrapped JSON
    wrapped = "Here is the analysis:\n\n" + clean_json + "\n\nLet me know if you need more."
    brief3 = analyzer._parse_brief("20260408-smoke-test", wrapped)
    assert brief3 is not None

    # 5. Invalid suggested_post_type → falls back to REPORT
    bad_pt = json.dumps({
        "story_id": "20260408-smoke-test",
        "consensus_facts": ["x"],
        "disagreements": [],
        "framing_analysis": {},
        "primary_source_alignment": [],
        "missing_context": [],
        "suggested_post_type": "GOSSIP",  # invalid
        "suggested_post_type_reason": "...",
        "confidence": 0.5,
    })
    brief4 = analyzer._parse_brief("20260408-smoke-test", bad_pt)
    assert brief4 is not None
    assert brief4.suggested_post_type == PostType.REPORT, (
        f"expected REPORT fallback, got {brief4.suggested_post_type}"
    )

    # 6. Total garbage → returns None
    junk = "this is not json at all"
    brief5 = analyzer._parse_brief("20260408-smoke-test", junk)
    assert brief5 is None

    # 7. End-to-end with a fake client that returns canned JSON
    class _FakeClient:
        def __init__(self, payload):
            self.payload = payload
            self.calls = 0

            class _Messages:
                def __init__(self, outer):
                    self.outer = outer
                def create(inner_self, **kwargs):
                    inner_self.outer.calls += 1
                    class _Resp:
                        def __init__(self, text):
                            class _Block:
                                def __init__(self, t): self.text = t
                            self.content = [_Block(text)]
                    return _Resp(inner_self.outer.payload)
            self.messages = _Messages(self)

    fake = _FakeClient(clean_json)
    analyzer2 = MetaAnalyzer(anthropic_client=fake, prompt_loader=_StubPromptLoader())
    end_to_end = analyzer2.analyze(dossier)
    assert end_to_end.suggested_post_type == PostType.META
    assert fake.calls == 1, f"expected 1 Claude call, got {fake.calls}"

    print("meta_analyzer smoke test OK")


if __name__ == "__main__":
    _smoke_test()
