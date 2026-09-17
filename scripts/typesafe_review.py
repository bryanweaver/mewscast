"""Summarize docs/reports/typesafe_decisions.jsonl.

Each journalism cycle appends one JSON line per Jev hop (L4 same-event,
borderline relevance, pre-Opus brief gate). This script is the offline
review surface: skip rates, fail-open / Haiku-fallback counts, mean
noul/confidence, and the headlines Jev actually blocked.

Usage:
    python scripts/typesafe_review.py                # last 7 days
    python scripts/typesafe_review.py --days 14
    python scripts/typesafe_review.py --out path.md

Stdlib only — same contract as scripts/triage_review.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_PATH = PROJECT_ROOT / "docs" / "reports" / "typesafe_decisions.jsonl"
DEFAULT_OUT_DIR = PROJECT_ROOT / "docs" / "reports"


def load_decisions(path: Path, since: datetime) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_raw = row.get("ts") or ""
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= since:
                rows.append(row)
    return rows


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarise(decisions: list[dict]) -> dict:
    by_kind: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    by_engine: Counter[str] = Counter()
    errors = 0
    input_tokens = 0
    output_tokens = 0
    same_event_conf: list[float] = []
    relevance_nouls: list[float] = []
    brief_nouls: dict[str, list[float]] = {
        "genuine_world_change": [],
        "checkable": [],
        "gossip_or_vibe": [],
        "thin_or_offtopic": [],
    }
    skips: list[dict] = []

    for row in decisions:
        kind = str(row.get("kind") or "unknown")
        action = str(row.get("action") or "")
        engine = str(row.get("engine") or "")
        by_kind[kind] += 1
        by_action[f"{kind}:{action}"] += 1
        by_engine[engine] += 1
        if row.get("error") or engine == "error":
            errors += 1
        usage = row.get("usage") or {}
        try:
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            pass

        if kind == "l4_same_event":
            conf = row.get("confidence")
            if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                same_event_conf.append(float(conf))
            if action == "skip_duplicate":
                skips.append(row)
        elif kind == "relevance":
            for value in (row.get("nouls") or {}).values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    relevance_nouls.append(float(value))
        elif kind == "brief_worth":
            nouls = row.get("nouls") or {}
            for key, bucket in brief_nouls.items():
                value = nouls.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bucket.append(float(value))
            if action == "skip_opus":
                skips.append(row)

    return {
        "n": len(decisions),
        "by_kind": by_kind,
        "by_action": by_action,
        "by_engine": by_engine,
        "errors": errors,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "same_event_conf_mean": _mean(same_event_conf),
        "relevance_noul_mean": _mean(relevance_nouls),
        "brief_noul_means": {k: _mean(v) for k, v in brief_nouls.items()},
        "skips": skips,
    }


def _fmt_mean(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def render(summary: dict, days: int) -> str:
    lines = [
        f"# TypeSafe decision review — last {days} days",
        "",
        f"Total hops: **{summary['n']}**   "
        f"(errors/fail-open: {summary['errors']})   "
        f"tokens in/out: {summary['input_tokens']}/{summary['output_tokens']}",
        "",
        "## By hop",
        "",
    ]
    if not summary["by_kind"]:
        lines.append("_No TypeSafe hops in this window._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Kind | Count |")
    lines.append("|---|---|")
    for kind, count in summary["by_kind"].most_common():
        lines.append(f"| `{kind}` | {count} |")
    lines.extend(["", "## By engine", "", "| Engine | Count |", "|---|---|"])
    for engine, count in summary["by_engine"].most_common():
        lines.append(f"| `{engine}` | {count} |")
    lines.extend(["", "## By action", "", "| Action | Count |", "|---|---|"])
    for action, count in summary["by_action"].most_common():
        lines.append(f"| `{action}` | {count} |")

    brief_means = summary["brief_noul_means"]
    lines.extend([
        "",
        "## Calibrations",
        "",
        f"- L4 same-event mean confidence: **{_fmt_mean(summary['same_event_conf_mean'])}**",
        f"- Relevance mean noul: **{_fmt_mean(summary['relevance_noul_mean'])}**",
        f"- Brief `genuine_world_change` mean: **{_fmt_mean(brief_means.get('genuine_world_change'))}**",
        f"- Brief `checkable` mean: **{_fmt_mean(brief_means.get('checkable'))}**",
        f"- Brief `gossip_or_vibe` mean: **{_fmt_mean(brief_means.get('gossip_or_vibe'))}**",
        f"- Brief `thin_or_offtopic` mean: **{_fmt_mean(brief_means.get('thin_or_offtopic'))}**",
        "",
        "## Skips (duplicates + rejected briefs)",
        "",
    ])
    skips = summary["skips"]
    if not skips:
        lines.append("_None — Jev did not auto-skip a story in this window._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| When | Kind | Action | Headline | Detail |")
    lines.append("|---|---|---|---|---|")
    for row in skips:
        ts = (row.get("ts") or "")[:19]
        kind = row.get("kind") or ""
        action = row.get("action") or ""
        headline = (row.get("headline") or "").replace("|", "/")[:80]
        if kind == "l4_same_event":
            detail = (
                f"matched `{row.get('matched_story_id')}` "
                f"conf={row.get('confidence')}"
            )
        else:
            detail = row.get("skip_reason") or ""
        lines.append(f"| {ts} | `{kind}` | `{action}` | {headline} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--input", type=Path, default=DECISIONS_PATH)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    decisions = load_decisions(args.input, since)
    if not decisions:
        print(f"No TypeSafe decisions in the last {args.days} days at {args.input}",
              file=sys.stderr)
        return 0

    markdown = render(summarise(decisions), args.days)
    if args.out is None:
        stamp = datetime.now(timezone.utc).date().isoformat()
        args.out = DEFAULT_OUT_DIR / f"typesafe-review-{stamp}.md"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
