"""
Walter's Field Notes — consensus-facts extractor for dossier replies.

Pulls the first N consensus facts from a dossier brief, strips the
"— reported by ..." attribution tails the meta-analyzer appends, and
returns a clean list ready to be rendered into the Field Notes image
reply by ImageGenerator.generate_field_notes.

Pure-Python, no I/O, no LLM calls. Skipping behavior is the caller's
decision — this module reports what it has and lets main.py gate on it.
"""
from __future__ import annotations

import re

# Words that indicate the start of a meta-analyzer attribution tail.
# Tails look like " — reported in body text by CNBC and NPR" or " —
# confirmed by both CNBC and NPR". We strip everything from the dash
# onward when the dash is followed by one of these verbs. Lowercase
# match; the actual fact text may use either case.
_ATTRIBUTION_VERBS = (
    "reported",
    "confirmed",
    "stated",
    "noted",
    "referenced",
    "headlined",
    "described",
    "mentioned",
    "according",
    "per ",
    "from ",
    "via ",
)

# Match a dash separator followed by an attribution verb. Handles em-dash
# (U+2014), en-dash (U+2013), and the ASCII " -- " / " - " fallbacks. The
# leading whitespace before the dash is required so we don't accidentally
# match a hyphen inside a word (e.g. "self-inflicted").
_ATTRIBUTION_TAIL_RE = re.compile(
    r"\s+[\u2013\u2014\-]{1,2}\s+(" + "|".join(_ATTRIBUTION_VERBS) + r")",
    re.IGNORECASE,
)


def strip_attribution_tail(fact: str) -> str:
    """Remove a trailing meta-analyzer attribution tail from a fact.

    Examples:
      "Putin said X — reported in body text by CNBC and NPR."
        -> "Putin said X"
      "Three killed — confirmed by CNBC, NPR."
        -> "Three killed"
      "Plain fact with no tail."  (returned unchanged)
        -> "Plain fact with no tail."

    Trailing punctuation/whitespace is normalized so the cleaned fact
    ends with a single period when one fits, otherwise no terminal punct.
    """
    if not fact:
        return ""
    match = _ATTRIBUTION_TAIL_RE.search(fact)
    if match:
        fact = fact[: match.start()]
    fact = fact.rstrip(" \t\r\n,;:-\u2013\u2014")
    # Re-add a single terminal period unless the fact already ends with
    # sentence-ending punctuation.
    if fact and fact[-1] not in ".!?\"'":
        fact = fact + "."
    return fact


def extract_top_facts(
    brief: dict | None,
    n: int = 3,
    min_chars: int = 20,
) -> list[str]:
    """Return the first ``n`` consensus facts from ``brief`` with attribution
    tails stripped.

    Args:
        brief: A dossier brief dict (the value of brief.to_dict() or the
            ``brief`` block of a saved dossier). ``None`` returns ``[]``.
        n: How many facts to return. Defaults to 3.
        min_chars: Drop facts shorter than this after cleanup (avoids
            single-word "facts" that occasionally slip through the brief).

    Returns an empty list when there aren't ``n`` usable facts — caller
    decides whether to skip the field-notes reply entirely. Returns an
    empty list for non-positive ``n`` (caller asked for nothing).
    """
    if n <= 0:
        return []
    if not brief:
        return []
    raw_facts = brief.get("consensus_facts") or []
    cleaned: list[str] = []
    for fact in raw_facts:
        if not isinstance(fact, str):
            continue
        stripped = strip_attribution_tail(fact).strip()
        if len(stripped) < min_chars:
            continue
        cleaned.append(stripped)
        if len(cleaned) >= n:
            break
    if len(cleaned) < n:
        return []
    return cleaned
