"""
Triage feedback-loop review script.

Reads docs/reports/triage_decisions.jsonl (appended each journalism
cycle by main.py) and writes a human-readable markdown report to
docs/reports/triage-review-<date>.md. The goal is to surface patterns
that call for adjusting the heuristic — specifically:

  1. Borderline DROPs (score=2) that were missing only one signal.
     These are the candidates most likely to become passes if we add
     a verb to EVENT_TOKENS or a token to IMPACT_TOKENS.
  2. Hard-reject rule distribution — a rule firing more than expected
     hints that it's too aggressive.
  3. Haiku rescue rate — how often use_llm actually bumped a score=2
     to pass. Near-zero means the LLM isn't helping; near-100% means
     the heuristic is too strict.

Usage:
    python scripts/triage_review.py                     # last 7 days
    python scripts/triage_review.py --days 14            # wider window
    python scripts/triage_review.py --out path.md        # custom output

The script is intentionally pure-python-stdlib so it can run in any
Python 3.10+ environment without pulling requirements.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_PATH = PROJECT_ROOT / "docs" / "reports" / "triage_decisions.jsonl"
DEFAULT_OUT_DIR = PROJECT_ROOT / "docs" / "reports"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_decisions(path: Path, since: datetime) -> list[dict]:
    """Return decisions whose ``ts`` is >= ``since``. Malformed lines skipped."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_raw = r.get("ts") or ""
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= since:
                rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def summarise(decisions: list[dict]) -> dict:
    """Compute the buckets the markdown report renders."""
    verdict_counts: Counter[str] = Counter()
    hard_rule_counts: Counter[str] = Counter()
    missing_by_verdict: dict[str, Counter[str]] = defaultdict(Counter)
    borderline_dropped_missing_one: list[dict] = []
    borderline_dropped: list[dict] = []
    llm_attempts = 0
    llm_rescues = 0

    for d in decisions:
        v = d.get("verdict", "")
        verdict_counts[v] += 1

        if v == "REJECT":
            rule = d.get("hard_rule", "(no-rule)")
            hard_rule_counts[rule] += 1

        for m in d.get("missing", []) or []:
            missing_by_verdict[v][m] += 1

        # Borderline drop = DROP with score == PASS_THRESHOLD - 1 (== 2).
        # Only these could plausibly become PASSes with a rule tweak.
        if v == "DROP" and d.get("score") == 2:
            borderline_dropped.append(d)
            missing = d.get("missing", []) or []
            if len(missing) == 1:
                borderline_dropped_missing_one.append(d)

        if d.get("llm_used"):
            llm_attempts += 1
            if d.get("llm_verdict") is True:
                llm_rescues += 1

    return {
        "n": len(decisions),
        "verdicts": verdict_counts,
        "hard_rules": hard_rule_counts,
        "missing_by_verdict": missing_by_verdict,
        "borderline_dropped": borderline_dropped,
        "borderline_dropped_missing_one": borderline_dropped_missing_one,
        "llm_attempts": llm_attempts,
        "llm_rescues": llm_rescues,
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _fmt_counter(c: Counter, top: int | None = None) -> str:
    items = c.most_common(top) if top else sorted(c.items(), key=lambda x: (-x[1], x[0]))
    if not items:
        return "- (none)"
    return "\n".join(f"- **{k}** — {v}" for k, v in items)


def _fmt_drops(drops: list[dict], top: int = 20) -> str:
    if not drops:
        return "- (none)"
    lines = []
    for d in drops[:top]:
        headline = (d.get("headline") or "")[:90]
        missing = ", ".join(d.get("missing", []) or [])
        reasons = ", ".join(d.get("reasons", []) or [])
        lines.append(f"- **{headline}**  \n  missing: `{missing}`  \n  fired: `{reasons}`")
    if len(drops) > top:
        lines.append(f"- ... and {len(drops) - top} more")
    return "\n".join(lines)


def render_markdown(summary: dict, since: datetime, until: datetime) -> str:
    total = summary["n"]
    verdicts = summary["verdicts"]
    missing_drop = summary["missing_by_verdict"].get("DROP", Counter())

    llm_attempts = summary["llm_attempts"]
    llm_rescues = summary["llm_rescues"]
    rescue_rate = (
        f"{llm_rescues}/{llm_attempts} = {llm_rescues / llm_attempts:.0%}"
        if llm_attempts
        else "0/0"
    )

    lines = [
        f"# Triage review — {since.date()} to {until.date()}",
        "",
        f"Total decisions: **{total}**   "
        f"(PASS: {verdicts.get('PASS', 0)}, "
        f"DROP: {verdicts.get('DROP', 0)}, "
        f"REJECT: {verdicts.get('REJECT', 0)})",
        "",
        "## 1. Borderline DROPs missing only ONE signal",
        "",
        "*These are the highest-leverage targets: one more token match on the "
        "listed signal would have flipped the verdict to PASS.*",
        "",
        _fmt_drops(summary["borderline_dropped_missing_one"]),
        "",
        "## 2. All score=2 borderline DROPs (top 20)",
        "",
        _fmt_drops(summary["borderline_dropped"]),
        "",
        "## 3. Hard-reject rule distribution",
        "",
        _fmt_counter(summary["hard_rules"]),
        "",
        "## 4. Which signals most often missing on DROPs",
        "",
        _fmt_counter(missing_drop),
        "",
        "## 5. Haiku LLM rescue rate (score=2 borderline → PASS)",
        "",
        f"- Attempts: {llm_attempts}",
        f"- Rescues:  {llm_rescues}",
        f"- Rate:     {rescue_rate}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7,
                        help="How many days back to include (default 7)")
    parser.add_argument("--input", type=Path, default=DECISIONS_PATH,
                        help="Path to triage_decisions.jsonl")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output markdown path (default: "
                             "docs/reports/triage-review-YYYY-MM-DD.md)")
    args = parser.parse_args(argv)

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=args.days)

    decisions = load_decisions(args.input, since)
    if not decisions:
        print(f"No triage decisions in the last {args.days} days at {args.input}",
              file=sys.stderr)
        # Still write an (empty-ish) report so the weekly cron produces
        # something a reviewer can open — helps confirm the job is alive.

    summary = summarise(decisions)
    md = render_markdown(summary, since, until)

    out_path = args.out or (DEFAULT_OUT_DIR / f"triage-review-{until.date().isoformat()}.md")
    os.makedirs(out_path.parent, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
