"""Test the L4 LLM dedup gate against known-duplicate and known-novel cases.

Reproduces the exact prompt used in src/main.py::_llm_same_event_check so we
can verify the gate's behavior end-to-end with the live Haiku model. Reads
the current journalism_seen_stories.txt to ground the test in real recent
headlines.

Pass cases:
  1. Candidate "Abortion pill rulings cause whiplash and confusion - Axios"
     vs seen "Supreme Court gives abortion pill mifepristone a 1-week
     reprieve from a major change - NPR" → MUST flag duplicate (this is
     the exact failure mode that triggered the 2026-05-05 fix).
  2. Candidate "Crypto exchange Coinbase to cut about 14% of workforce in
     AI shift" → MUST NOT flag duplicate (no related coverage).

Exit code 0 = both cases correct. Exit code 1 = at least one wrong.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def load_seen_headlines(path: Path, max_entries: int = 50) -> list[tuple[str, str]]:
    """Read the seen-stories TSV and return [(story_id, headline), ...].
    Drops legacy 1- and 2-column entries (they have no headline)."""
    out: list[tuple[str, str]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 3)
        if len(parts) < 3:
            continue
        sid = parts[0].strip()
        headline = parts[2].strip()
        if sid and headline:
            out.append((sid, headline))
    return out[-max_entries:]


def llm_same_event_check(cand_headline: str,
                         recent_seen: list[tuple[str, str]]) -> tuple[bool, str, str]:
    """Reproduces src/main.py::_llm_same_event_check verbatim. Returns
    (is_duplicate, matched_story_id, reasoning)."""
    if not recent_seen:
        return (False, "", "no seen entries")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    seen_block = "\n".join(f"[{sid}] {hl}" for sid, hl in recent_seen)
    prompt = (
        "You are an editor judging whether a CANDIDATE news story is the "
        "SAME NEWS EVENT as any story already covered, regardless of "
        "headline phrasing, outlet, or framing angle.\n\n"
        "ALREADY-COVERED (last 14 days):\n"
        f"{seen_block}\n\n"
        f"CANDIDATE: {cand_headline}\n\n"
        "SAME news event examples:\n"
        "- 'Supreme Court gives abortion pill mifepristone a 1-week reprieve'\n"
        "  vs 'Abortion pill rulings cause whiplash and confusion'\n"
        "  → SAME (same SCOTUS mifepristone stay)\n"
        "- 'Pentagon to pull 5,000 troops from Germany'\n"
        "  vs 'Germany urges defense after US withdrawal announcement'\n"
        "  → SAME (same Pentagon decision)\n"
        "- 'Iran says US has responded to peace proposal'\n"
        "  vs 'Iran reviewing Washington reply on 14-point plan'\n"
        "  → SAME (same diplomatic exchange)\n\n"
        "DIFFERENT events:\n"
        "- 'SCOTUS Voting Rights ruling' vs 'SCOTUS abortion ruling'\n"
        "  → DIFFERENT (different cases)\n"
        "- 'Trump fires Iran envoy' vs 'Trump-Iran deal talks resume'\n"
        "  → DIFFERENT (different actions, even if same actors)\n\n"
        "Respond with STRICT JSON only, no other text:\n"
        '{"duplicate_of": "<story_id from list above>", "reasoning": "<one sentence>"}\n'
        "or if novel:\n"
        '{"duplicate_of": null, "reasoning": "<one sentence>"}'
    )
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip() if resp.content else ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return (False, "", f"unparseable: {text[:160]!r}")
    data = json.loads(m.group(0))
    dup_id = data.get("duplicate_of")
    reasoning = data.get("reasoning", "")
    if dup_id and isinstance(dup_id, str):
        return (True, dup_id, reasoning)
    return (False, "", reasoning)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    seen_path = repo_root / "journalism_seen_stories.txt"
    seen = load_seen_headlines(seen_path)
    print(f"[test_dedup] Loaded {len(seen)} seen headlines from {seen_path.name}")
    print()

    cases = [
        # (label, candidate_headline, expected_duplicate)
        (
            "Abortion-pill follow-up (KNOWN DUPLICATE — was the 2026-05-05 bug)",
            "SCOTUS halts 5th Circuit ruling on mifepristone access by mail - Reuters",
            True,
        ),
        (
            "Pentagon Germany follow-up (KNOWN DUPLICATE)",
            "Berlin reacts as US announces 5,000-troop withdrawal from Germany - DW",
            True,
        ),
        (
            "Coinbase layoffs (KNOWN NOVEL — no related seen coverage)",
            "Crypto exchange Coinbase to cut about 14% of workforce in AI shift - CNBC",
            False,
        ),
        (
            "Romanian government collapse (KNOWN NOVEL)",
            "Romania's pro-European coalition collapses after PM resigns - BBC",
            False,
        ),
    ]

    failures = 0
    for label, cand, expected in cases:
        print(f"--- {label} ---")
        print(f"    Candidate: {cand}")
        try:
            is_dup, sid, reason = llm_same_event_check(cand, seen)
        except Exception as e:
            print(f"    ERROR: {e}")
            failures += 1
            continue
        verdict = "DUPLICATE" if is_dup else "NOVEL"
        expected_str = "DUPLICATE" if expected else "NOVEL"
        ok = is_dup == expected
        marker = "PASS" if ok else "FAIL"
        print(f"    Verdict: {verdict} (expected {expected_str}) [{marker}]")
        if is_dup:
            print(f"    Matched: {sid}")
        if reason:
            print(f"    Reason:  {reason[:200]}")
        if not ok:
            failures += 1
        print()

    if failures:
        print(f"[test_dedup] FAILED — {failures}/{len(cases)} cases wrong")
        return 1
    print(f"[test_dedup] OK — all {len(cases)} cases match expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
