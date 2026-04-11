"""
Post-draft factual analysis — uses Claude Haiku to compare the draft
against the article bodies and headline seed for factual accuracy.

Instead of hardcoded term hierarchies (which miss edge cases), this
sends a single cheap Haiku call that understands language, context,
and the full spectrum of possible escalation patterns.

This is INFORMATIONAL, not a hard gate. It runs after Stage 6 passes
and logs findings. If escalation patterns become frequent, it can be
tightened into a verification gate check.

Usage:
    from draft_analyzer import analyze_draft, print_analysis
    findings = analyze_draft(draft_text, headline_seed, dossier)
    print_analysis(findings)
"""
from __future__ import annotations

import json
import os
from typing import Optional

from dossier_store import StoryDossier


# ---------------------------------------------------------------------------
# The Haiku analysis prompt
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """\
You are a fact-checking editor reviewing an AI-generated news post before publication.

## HEADLINE SEED (what originally triggered story detection — may be stale):
{headline_seed}

## ARTICLE BODIES (the ground truth from news outlets):
{article_bodies}

## DRAFT POST (what the AI model produced):
{draft_text}

## YOUR TASK

Compare the draft post against the article bodies on three dimensions.
For each, assess whether the draft ESCALATES beyond what the bodies support,
MATCHES the bodies, or is CONSERVATIVE (weaker than what bodies say).

### 1. Legal / procedural status
Does the draft use a stronger legal term than the bodies support?
Examples of escalation: bodies say "questioned" but draft says "arrested";
bodies say "charged" but draft says "convicted"; bodies say "investigation"
but draft says "indictment."
Examples of conservative: bodies say "charged" but draft says "arrested" (weaker).

### 2. Casualty / harm severity
Does the draft overstate harm? Bodies say "injured" but draft says "killed";
bodies say "missing" but draft says "confirmed dead."

### 3. Attribution certainty
Does the draft state something as confirmed fact when bodies only say
"allegedly" or "reportedly"? Does it drop hedges that sources included?

### 4. Fabricated details
Does the draft include any specific facts (names, numbers, dates, locations,
quotes) that do NOT appear in any of the article bodies? This is the most
serious category — inventing facts that aren't in the source material.

## ALSO NOTE
Compare the headline seed against the article bodies — the headline may be
stale (written earlier in the story's timeline). Note if the bodies have
materially advanced beyond what the headline says.

## IGNORE THESE — THEY ARE NOT FABRICATIONS
The draft is written by an AI news bot called "Walter Croncat" (a cat
reporter persona). The following are INTENTIONAL post formatting elements,
NOT fabricated content — do NOT flag them:
- "#BreakingMews" — the bot's branded hashtag for breaking news
- "And that's the mews." — the REPORT sign-off (a pun on "news")
- "And that's the mews — coverage report." — the META sign-off
- "This cat's view — speculative, personal, subjective." — the ANALYSIS sign-off
- "And that's the mews — straight from the source." — the PRIMARY sign-off
- Any cat puns, cat references, or the phrase "Walter Croncat"
- The word "mews" used as a pun for "news"
These are part of the bot's persona, not errors in sourcing.

## OUTPUT FORMAT
Return ONLY a JSON object with this exact shape (no markdown fences, no prose):

{{
  "overall": "CLEAN" | "ESCALATION" | "FABRICATION",
  "findings": [
    {{
      "category": "legal_status" | "casualty" | "attribution" | "fabrication" | "headline_drift",
      "severity": "ok" | "minor" | "major",
      "draft_claim": "what the draft says",
      "source_support": "what the bodies actually say",
      "assessment": "one sentence explanation"
    }}
  ]
}}

If the draft is factually accurate and properly sourced, return:
{{"overall": "CLEAN", "findings": []}}

Be rigorous but fair. A draft that uses a term supported by ANY article body
is not escalating — even if the headline seed used a weaker term. The bodies
are the ground truth, not the headline.
"""


# ---------------------------------------------------------------------------
# Analysis function
# ---------------------------------------------------------------------------

def analyze_draft(
    draft_text: str,
    headline_seed: str,
    dossier: StoryDossier,
    model: str = "claude-haiku-4-5-20251001",
) -> dict:
    """Use Claude Haiku to compare draft against sources for factual accuracy.

    Returns a dict with "overall" (CLEAN/ESCALATION/FABRICATION) and
    "findings" (list of specific observations). Returns a fallback dict
    if the API call fails or no API key is set.
    """
    # Build the article bodies block
    body_sections = []
    for i, art in enumerate(dossier.articles, 1):
        body = art.body or art.title or "(no body text)"
        outlet = art.outlet or "Unknown"
        ho = " [headline-only]" if getattr(art, "headline_only", False) else ""
        body_sections.append(f"### Article {i}: {outlet}{ho}\n{body[:3000]}")

    article_bodies = "\n\n".join(body_sections) if body_sections else "(no articles in dossier)"

    # Build the prompt
    prompt = _ANALYSIS_PROMPT.format(
        headline_seed=headline_seed or "(none)",
        article_bodies=article_bodies,
        draft_text=draft_text or "(empty draft)",
    )

    # Call Haiku
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_result("no ANTHROPIC_API_KEY set")

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except Exception as e:
        return _fallback_result(f"Haiku call failed: {e}")

    # Parse the JSON response
    try:
        # Strip markdown fences if the model wrapped it
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        # Validate structure
        if "overall" not in result:
            result["overall"] = "UNKNOWN"
        if "findings" not in result or not isinstance(result["findings"], list):
            result["findings"] = []
        return result
    except json.JSONDecodeError:
        return _fallback_result(f"could not parse Haiku response as JSON: {raw[:200]}")


def _fallback_result(reason: str) -> dict:
    """Return a safe fallback when analysis can't run."""
    return {
        "overall": "SKIPPED",
        "findings": [],
        "_skipped_reason": reason,
    }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def print_analysis(findings: dict) -> None:
    """Print findings to stdout in a QA-friendly format."""
    overall = findings.get("overall", "UNKNOWN")

    if overall == "SKIPPED":
        reason = findings.get("_skipped_reason", "unknown reason")
        print(f"[draft_analyzer] skipped: {reason}")
        return

    items = findings.get("findings", [])

    if overall == "CLEAN" and not items:
        print("[draft_analyzer] factual analysis: CLEAN — no issues found")
        return

    print(f"[draft_analyzer] factual analysis: {overall}")
    for f in items:
        sev = f.get("severity", "?")
        cat = f.get("category", "?")
        assessment = f.get("assessment", "")
        draft_claim = f.get("draft_claim", "")
        source = f.get("source_support", "")

        if sev == "ok":
            icon = "OK"
        elif sev == "minor":
            icon = "MINOR"
        else:
            icon = "MAJOR"

        print(f"[draft_analyzer]   [{icon}] {cat}: {assessment}")
        if draft_claim and source:
            print(f"[draft_analyzer]         draft: \"{draft_claim}\"")
            print(f"[draft_analyzer]         source: \"{source}\"")


# ---------------------------------------------------------------------------
# Smoke test (no API call — just validates the prompt builds correctly)
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    from dossier_store import ArticleRecord

    dossier = StoryDossier(
        story_id="test-1",
        headline_seed="Man questioned by police after wife disappears",
        detected_at="2026-04-10T00:00:00Z",
        articles=[
            ArticleRecord(
                outlet="BBC",
                url="https://bbc.com/x",
                title="Man arrested in wife disappearance",
                body="Police arrested Brian Hooker, 58, on Friday. He denies wrongdoing.",
                fetched_at="2026-04-10T00:00:00Z",
            ),
        ],
    )

    draft = "Brian Hooker was arrested after his wife disappeared. BBC reports."

    # Test without API key — should return SKIPPED gracefully
    original_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        result = analyze_draft(draft, dossier.headline_seed, dossier)
        assert result["overall"] == "SKIPPED", f"expected SKIPPED without API key, got {result}"
    finally:
        if original_key:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    # Verify prompt construction doesn't crash
    body_sections = []
    for i, art in enumerate(dossier.articles, 1):
        body_sections.append(f"### Article {i}: {art.outlet}\n{art.body[:3000]}")
    prompt = _ANALYSIS_PROMPT.format(
        headline_seed=dossier.headline_seed,
        article_bodies="\n\n".join(body_sections),
        draft_text=draft,
    )
    assert "Brian Hooker" in prompt
    assert "questioned" in prompt  # from headline
    assert "arrested" in prompt    # from body

    print("draft_analyzer smoke test OK")


if __name__ == "__main__":
    _smoke_test()
