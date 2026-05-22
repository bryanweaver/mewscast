"""
Walter's Field Notes — consensus-facts extractor for dossier replies.

Pulls the first N consensus facts from a dossier brief, strips the
"— reported by ..." attribution tails the meta-analyzer appends, and
returns a clean list ready to be rendered into the Field Notes image
reply by ImageGenerator.generate_field_notes.

Includes an optional Haiku-backed condenser that turns long facts into
~60-char notebook bullets so they fit comfortably on the visual page
without sacrificing fact fidelity. Falls back to the input facts on any
LLM failure so the pipeline keeps working.

Skipping behavior is the caller's decision — this module reports what it
has and lets main.py gate on it.
"""
from __future__ import annotations

import json
import os
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


_CONDENSE_SYSTEM_PROMPT = (
    "You are a copy editor for Walter Croncat, a real-journalism Bluesky/X "
    "account. You are condensing consensus facts into short notebook bullets "
    "for an image of a reporter's field-notes pad.\n\n"
    "Rules — follow EXACTLY:\n"
    "1. Preserve every named entity (people, places, organizations, "
    "agencies, countries) and every number, date, and dollar amount.\n"
    "2. Drop hedge words, throat-clearing, redundant descriptors, attributive "
    "framing, source citations, and parenthetical asides.\n"
    "3. Target 50–70 characters per bullet, max 90.\n"
    "4. Use plain declarative sentences. No quotation marks unless the "
    "original fact contains a direct quote (a phrase someone said).\n"
    "5. Do NOT invent details. Do NOT add color or speculation. If you can't "
    "condense a fact without changing its meaning, output the original.\n"
    "6. Output ONLY a JSON array of strings, one bullet per input fact, in "
    "the same order. No commentary, no markdown, no code fences."
)


def condense_facts_for_notebook(
    facts: list[str],
    headline: str = "",
    max_chars: int = 90,
    model: str = "claude-haiku-4-5-20251001",
) -> list[str]:
    """Condense consensus facts into ~60-char notebook bullets via Haiku.

    Returns a list the same length as ``facts``. If the LLM call fails,
    returns the input unchanged — the field-notes pipeline keeps working
    with full-length facts rather than silently dropping the reply.

    The condenser is constrained by ``_CONDENSE_SYSTEM_PROMPT`` to preserve
    entities/numbers/dates and refuse to invent details. Output is parsed
    as a JSON array; on any parse failure the input is returned as-is.

    Args:
        facts: original consensus-fact strings (post-attribution-stripping).
        headline: optional story headline passed to the model for context —
            helps it judge what's central vs. redundant.
        max_chars: post-LLM safety cap. Bullets longer than this are
            backfilled with the original fact (which the caller may also
            choose to truncate or not).
        model: Anthropic model id. Defaults to current Haiku.
    """
    if not facts:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # No key in the runner environment — skip condensation cleanly.
        return list(facts)

    try:
        from anthropic import Anthropic  # local import keeps the module
        # importable when anthropic isn't installed in dev environments
    except ImportError:
        return list(facts)

    user_payload = {
        "headline": headline or "",
        "facts": list(facts),
    }
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=600,
            system=_CONDENSE_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }],
        )
        raw = "".join(
            block.text for block in resp.content if getattr(block, "text", None)
        ).strip()
    except Exception as exc:  # network, auth, rate limit, etc.
        print(f"[field_notes] condense Haiku call failed (using originals): {exc}")
        return list(facts)

    # Strip code fences if the model added them despite the instruction.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[field_notes] condense unparseable response (using originals): {raw[:120]!r}")
        return list(facts)

    if not isinstance(parsed, list) or len(parsed) != len(facts):
        print(f"[field_notes] condense returned wrong shape (using originals): {parsed!r}")
        return list(facts)

    condensed: list[str] = []
    for original, candidate in zip(facts, parsed):
        if not isinstance(candidate, str):
            condensed.append(original)
            continue
        cleaned = candidate.strip()
        if not cleaned:
            condensed.append(original)
            continue
        if len(cleaned) > max_chars:
            # Model didn't honor the budget — keep the original rather than
            # truncating mid-sentence (which can chop entities). Caller may
            # decide differently in the future.
            condensed.append(original)
            continue
        condensed.append(cleaned)
    return condensed
