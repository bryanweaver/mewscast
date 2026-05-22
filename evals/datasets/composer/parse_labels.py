"""Parse labels.md (your hand-scored worksheet) into labels.json so the eval
harness can consume it. Validates that each case has at minimum an `overall`
score so the eval has something to anchor on.

Usage:
    python evals/datasets/composer/parse_labels.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS_MD = HERE / "labels.md"
LABELS_JSON = HERE / "labels.json"

CASE_HEADER_RE = re.compile(r"^## Case \d+ — `([^`]+)`\s*$")
SCORE_LINE_RE = re.compile(
    r"^- (hook|fidelity|tone|concision|attribution|overall|publish_again|notes):\s*(.*)$"
)
NUMERIC_FIELDS = {"hook", "fidelity", "tone", "concision", "attribution", "overall"}


def parse() -> list[dict]:
    text = LABELS_MD.read_text().splitlines()
    cases = []
    cur = None
    for line in text:
        m = CASE_HEADER_RE.match(line)
        if m:
            if cur:
                cases.append(cur)
            cur = {"case_id": m.group(1), "scores": {}}
            continue
        if cur is None:
            continue
        sm = SCORE_LINE_RE.match(line)
        if not sm:
            continue
        key, val = sm.group(1), sm.group(2).strip()
        if not val:
            continue
        if key in NUMERIC_FIELDS:
            try:
                n = int(val)
            except ValueError:
                raise SystemExit(f"case {cur['case_id']}: {key} must be int 1-5, got {val!r}")
            if not 1 <= n <= 5:
                raise SystemExit(f"case {cur['case_id']}: {key} out of range: {n}")
            cur["scores"][key] = n
        elif key == "publish_again":
            v = val.lower()
            if v not in {"y", "n", "yes", "no"}:
                raise SystemExit(f"case {cur['case_id']}: publish_again must be y/n, got {val!r}")
            cur["scores"]["publish_again"] = v.startswith("y")
        elif key == "notes":
            cur["scores"]["notes"] = val
    if cur:
        cases.append(cur)
    return cases


def main():
    cases = parse()
    labeled = [c for c in cases if "overall" in c["scores"]]
    skipped = [c for c in cases if "overall" not in c["scores"]]
    LABELS_JSON.write_text(json.dumps(cases, indent=2, ensure_ascii=False))
    print(f"parsed {len(cases)} cases → {LABELS_JSON}")
    print(f"  labeled (has overall):  {len(labeled)}")
    print(f"  unlabeled (skip in eval): {len(skipped)}")
    if labeled:
        avg = sum(c["scores"]["overall"] for c in labeled) / len(labeled)
        print(f"  current avg overall: {avg:.2f}")


if __name__ == "__main__":
    main()
