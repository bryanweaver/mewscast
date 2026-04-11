"""
Post-draft factual analysis — compares key terms between the headline
seed, article bodies, and the generated draft text.

Catches cases where the draft uses a STRONGER term than what the article
bodies support (e.g., draft says "convicted" but bodies only say "charged").
Also catches the opposite — where the draft UNDERREPORTS something all
bodies agree on.

This is an INFORMATIONAL analysis, not a hard gate. It runs after Stage 6
passes and logs its findings. Over time, if we see escalation patterns, it
can be tightened into a verification gate check.

Usage:
    from draft_analyzer import analyze_draft
    findings = analyze_draft(draft_text, headline_seed, dossier)
    # findings is a dict with "escalations", "confirmations", "summary"
"""
from __future__ import annotations

import re
from typing import Optional

from dossier_store import StoryDossier


# ---------------------------------------------------------------------------
# Term severity hierarchies — ordered from weakest to strongest
# ---------------------------------------------------------------------------

# Legal status: the lifecycle of a criminal case
LEGAL_STATUS_HIERARCHY = [
    # (term_pattern, severity_level, display_label)
    (r"\bquestioned\b", 1, "questioned"),
    (r"\bquestioning\b", 1, "questioned"),
    (r"\bperson of interest\b", 1, "person of interest"),
    (r"\bdetained\b", 2, "detained"),
    (r"\bin custody\b", 2, "in custody"),
    (r"\barrested\b", 3, "arrested"),
    (r"\barrest\b", 3, "arrested"),
    (r"\bcharged\b", 4, "charged"),
    (r"\bcharges filed\b", 4, "charged"),
    (r"\bindicted\b", 5, "indicted"),
    (r"\bindictment\b", 5, "indicted"),
    (r"\bpleads guilty\b", 6, "pleads guilty"),
    (r"\bpled guilty\b", 6, "pleads guilty"),
    (r"\bpleaded guilty\b", 6, "pleads guilty"),
    (r"\bguilty plea\b", 6, "pleads guilty"),
    (r"\bconvicted\b", 7, "convicted"),
    (r"\bfound guilty\b", 7, "convicted"),
    (r"\bacquitted\b", 7, "acquitted"),  # same severity level, different outcome
    (r"\bsentenced\b", 8, "sentenced"),
]

# Casualty / status reporting
CASUALTY_HIERARCHY = [
    (r"\bmissing\b", 1, "missing"),
    (r"\breported missing\b", 1, "missing"),
    (r"\bdisappeared\b", 1, "disappeared"),
    (r"\binjured\b", 2, "injured"),
    (r"\bwounded\b", 2, "wounded"),
    (r"\bhospitalized\b", 2, "hospitalized"),
    (r"\bcritical condition\b", 3, "critical condition"),
    (r"\blife-threatening\b", 3, "life-threatening"),
    (r"\bpresumed dead\b", 4, "presumed dead"),
    (r"\bfeared dead\b", 4, "feared dead"),
    (r"\bdied\b", 5, "died"),
    (r"\bkilled\b", 5, "killed"),
    (r"\bconfirmed dead\b", 5, "confirmed dead"),
]

# Attribution certainty
ATTRIBUTION_HIERARCHY = [
    (r"\balleged\b", 1, "alleged"),
    (r"\bsuspected\b", 1, "suspected"),
    (r"\baccused\b", 2, "accused"),
    (r"\breportedly\b", 2, "reportedly"),
    (r"\bconfirmed\b", 3, "confirmed"),
    (r"\bproven\b", 4, "proven"),
    (r"\badmitted\b", 4, "admitted"),
]

ALL_HIERARCHIES = {
    "legal_status": LEGAL_STATUS_HIERARCHY,
    "casualty": CASUALTY_HIERARCHY,
    "attribution": ATTRIBUTION_HIERARCHY,
}


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

def _extract_terms(text: str, hierarchy: list[tuple]) -> list[tuple[int, str]]:
    """Return all (severity_level, display_label) pairs found in text."""
    if not text:
        return []
    text_lower = text.lower()
    found: list[tuple[int, str]] = []
    seen_labels: set[str] = set()
    for pattern, level, label in hierarchy:
        if label in seen_labels:
            continue
        if re.search(pattern, text_lower):
            found.append((level, label))
            seen_labels.add(label)
    return found


def _max_severity(terms: list[tuple[int, str]]) -> Optional[tuple[int, str]]:
    """Return the highest-severity (level, label) from a list, or None."""
    if not terms:
        return None
    return max(terms, key=lambda t: t[0])


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_draft(
    draft_text: str,
    headline_seed: str,
    dossier: StoryDossier,
) -> dict:
    """Compare factual terms between headline, bodies, and draft.

    Returns a dict:
      {
        "escalations": [
          {"category": "legal_status", "draft_term": "arrested",
           "body_max": "questioned", "severity_delta": +2,
           "message": "Draft says 'arrested' but strongest body term is 'questioned'"}
        ],
        "confirmations": [
          {"category": "legal_status", "draft_term": "arrested",
           "body_max": "arrested", "message": "Draft matches body text"}
        ],
        "downgrades": [
          {"category": ..., "draft_term": ..., "body_max": ..., "message": ...}
        ],
        "headline_vs_body": [
          {"category": ..., "headline_term": ..., "body_max": ..., "message": ...}
        ],
        "summary": "OK" | "ESCALATION_DETECTED" | "CLEAN"
      }
    """
    # Combine all article bodies into one text for term extraction
    all_bodies = " ".join(
        art.body or "" for art in dossier.articles if art.body
    )

    result: dict = {
        "escalations": [],
        "confirmations": [],
        "downgrades": [],
        "headline_vs_body": [],
        "summary": "CLEAN",
    }

    for category, hierarchy in ALL_HIERARCHIES.items():
        draft_terms = _extract_terms(draft_text, hierarchy)
        body_terms = _extract_terms(all_bodies, hierarchy)
        headline_terms = _extract_terms(headline_seed, hierarchy)

        draft_max = _max_severity(draft_terms)
        body_max = _max_severity(body_terms)
        headline_max = _max_severity(headline_terms)

        # Skip categories where the draft doesn't use any terms
        if not draft_max:
            continue

        # Compare draft vs body
        if body_max:
            delta = draft_max[0] - body_max[0]
            if delta > 0:
                # Draft escalated beyond what bodies support
                result["escalations"].append({
                    "category": category,
                    "draft_term": draft_max[1],
                    "draft_severity": draft_max[0],
                    "body_max_term": body_max[1],
                    "body_max_severity": body_max[0],
                    "severity_delta": delta,
                    "message": (
                        f"Draft says '{draft_max[1]}' (severity {draft_max[0]}) "
                        f"but strongest body term is '{body_max[1]}' "
                        f"(severity {body_max[0]}) — delta +{delta}"
                    ),
                })
                result["summary"] = "ESCALATION_DETECTED"
            elif delta < 0:
                # Draft is more conservative than bodies — fine
                result["downgrades"].append({
                    "category": category,
                    "draft_term": draft_max[1],
                    "body_max_term": body_max[1],
                    "severity_delta": delta,
                    "message": (
                        f"Draft says '{draft_max[1]}' — bodies support "
                        f"'{body_max[1]}' (stronger). Conservative, OK."
                    ),
                })
            else:
                # Match
                result["confirmations"].append({
                    "category": category,
                    "draft_term": draft_max[1],
                    "body_max_term": body_max[1],
                    "message": f"Draft '{draft_max[1]}' matches body text",
                })
        else:
            # Draft uses a term but NO body has any term in this category
            # This could be the draft inventing a status not in the sources
            if draft_max[0] >= 3:  # only flag if it's a strong term
                result["escalations"].append({
                    "category": category,
                    "draft_term": draft_max[1],
                    "draft_severity": draft_max[0],
                    "body_max_term": "(none found in bodies)",
                    "body_max_severity": 0,
                    "severity_delta": draft_max[0],
                    "message": (
                        f"Draft says '{draft_max[1]}' but no matching "
                        f"term found in any article body"
                    ),
                })
                result["summary"] = "ESCALATION_DETECTED"

        # Also compare headline vs body (informational)
        if headline_max and body_max:
            h_delta = headline_max[0] - body_max[0]
            if h_delta != 0:
                result["headline_vs_body"].append({
                    "category": category,
                    "headline_term": headline_max[1],
                    "body_max_term": body_max[1],
                    "severity_delta": h_delta,
                    "message": (
                        f"Headline says '{headline_max[1]}', "
                        f"bodies say '{body_max[1]}' — "
                        f"{'headline is weaker' if h_delta < 0 else 'headline is stronger'}"
                    ),
                })

    return result


def print_analysis(findings: dict) -> None:
    """Print the analysis findings to stdout in a QA-friendly format."""
    if findings["summary"] == "CLEAN" and not findings["confirmations"]:
        print("[draft_analyzer] no status/legal terms found in draft — nothing to compare")
        return

    print(f"[draft_analyzer] factual analysis: {findings['summary']}")

    for conf in findings["confirmations"]:
        print(f"[draft_analyzer]   OK  {conf['category']}: {conf['message']}")

    for down in findings["downgrades"]:
        print(f"[draft_analyzer]   OK  {down['category']}: {down['message']}")

    for esc in findings["escalations"]:
        print(f"[draft_analyzer]   ⚠️  {esc['category']}: {esc['message']}")

    for hvb in findings["headline_vs_body"]:
        print(f"[draft_analyzer]   ℹ️  {hvb['category']}: {hvb['message']}")


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    from dossier_store import ArticleRecord

    # Case 1: Draft matches bodies (both say "arrested")
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
            ArticleRecord(
                outlet="NBC",
                url="https://nbc.com/y",
                title="Husband arrested",
                body="Hooker was arrested and charged with obstruction. He is detained.",
                fetched_at="2026-04-10T00:00:00Z",
            ),
        ],
    )

    draft = "Brian Hooker was arrested after his wife disappeared. NBC and BBC confirm."
    findings = analyze_draft(draft, dossier.headline_seed, dossier)
    assert findings["summary"] == "CLEAN", f"expected CLEAN, got {findings}"
    # Bodies say "charged" (severity 4), draft says "arrested" (severity 3) — downgrade (conservative)
    assert any(d["draft_term"] == "arrested" for d in findings["downgrades"]), (
        f"expected 'arrested' as a downgrade vs body 'charged', got {findings['downgrades']}"
    )
    # Headline says "questioned" but bodies say "charged" — should be noted
    assert any(h["headline_term"] == "questioned" for h in findings["headline_vs_body"])

    # Case 2: Draft escalates beyond bodies
    dossier2 = StoryDossier(
        story_id="test-2",
        headline_seed="Suspect questioned in robbery",
        detected_at="2026-04-10T00:00:00Z",
        articles=[
            ArticleRecord(
                outlet="AP",
                url="https://ap.com/x",
                title="Suspect questioned",
                body="Police are questioning a suspect in the robbery. No charges yet.",
                fetched_at="2026-04-10T00:00:00Z",
            ),
        ],
    )
    draft2 = "The suspect was convicted of robbery, AP reports."
    findings2 = analyze_draft(draft2, dossier2.headline_seed, dossier2)
    assert findings2["summary"] == "ESCALATION_DETECTED"
    assert any(e["draft_term"] == "convicted" for e in findings2["escalations"])

    print("draft_analyzer smoke test OK")


if __name__ == "__main__":
    _smoke_test()
