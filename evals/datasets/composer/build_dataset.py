"""Build the composer eval dataset by pairing brief.json inputs with the
composed tweet outputs from posts_history.json.

Outputs:
  - cases.jsonl   — frozen (input, output) pairs, one JSON per line
  - labels.md     — human-editable rubric form for hand-scoring each case

Re-run whenever you want to refresh the dataset from new history.
"""
import json
import os
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POSTS = ROOT / "posts_history.json"
DOSSIERS = ROOT / "docs" / "dossiers"
OUT_DIR = Path(__file__).resolve().parent

RUBRIC_FIELDS = [
    ("hook",         "1=dull opener, 5=stop-scrolling hook"),
    ("fidelity",     "1=fabricated/distorted, 5=every claim grounded in consensus_facts"),
    ("tone",         "1=off-brand, 5=pitch-perfect Walter Croncat news anchor"),
    ("concision",    "1=padded/wasteful, 5=every word earns its place"),
    ("attribution",  "1=missing/wrong outlets, 5=correctly credits sources"),
    ("overall",      "1=would not publish, 5=would publish unchanged"),
]


def load_pairs():
    posts = json.loads(POSTS.read_text())["posts"]
    journ = [p for p in posts if p.get("post_pipeline") == "journalism" and p.get("dossier_id")]

    pairs = []
    for p in journ:
        brief_path = DOSSIERS / f"{p['dossier_id']}.brief.json"
        if not brief_path.exists():
            continue
        brief_data = json.loads(brief_path.read_text())
        pairs.append({
            "case_id": p["dossier_id"],
            "post_type": p.get("post_type", "?"),
            "topic": p.get("topic", ""),
            "source": p.get("source", ""),
            "url": p.get("url", ""),
            "timestamp": p.get("timestamp", ""),
            "brief": brief_data.get("brief", {}),
            "headline_seed": brief_data.get("headline_seed", ""),
            "composed_tweet": p.get("content", ""),
            "image_prompt": p.get("image_prompt", ""),
        })
    pairs.sort(key=lambda c: c["timestamp"])
    return pairs


def write_jsonl(pairs):
    out = OUT_DIR / "cases.jsonl"
    with out.open("w") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(pairs)} cases)")


def render_labels_md(pairs):
    lines = [
        "# Composer eval — labeling worksheet",
        "",
        "Score each case on the 1-5 rubric below. Edit this file in place.",
        "When done, run `python evals/datasets/composer/parse_labels.py` to",
        "validate and produce `labels.json`.",
        "",
        "## Rubric",
        "",
    ]
    for name, desc in RUBRIC_FIELDS:
        lines.append(f"- **{name}** — {desc}")
    lines += [
        "",
        "Also: `publish_again` = `y` / `n`, `notes` = freeform.",
        "Leave any score blank if you can't tell — eval will skip blanks.",
        "",
        "---",
        "",
    ]

    for i, c in enumerate(pairs, 1):
        brief = c["brief"]
        facts = brief.get("consensus_facts", []) or []
        disagreements = brief.get("disagreements", []) or []
        missing = brief.get("missing_context", []) or []

        lines += [
            f"## Case {i:02d} — `{c['case_id']}`",
            "",
            f"- **post_type:** {c['post_type']}",
            f"- **suggested_post_type (brief):** {brief.get('suggested_post_type','?')}",
            f"- **primary source:** {c['source']}",
            f"- **timestamp:** {c['timestamp']}",
            "",
            "### Headline seed",
            "",
            f"> {c['headline_seed'].strip() or '(empty)'}",
            "",
            "### Consensus facts",
            "",
        ]
        for f in facts[:8]:
            lines.append(f"- {f}")
        if len(facts) > 8:
            lines.append(f"- _…and {len(facts)-8} more_")
        lines += ["", "### Disagreements", ""]
        if not disagreements:
            lines.append("_(none)_")
        for d in disagreements[:4]:
            lines.append(f"- **{d.get('topic','?')}**")
            for outlet, pos in (d.get("positions", {}) or {}).items():
                lines.append(f"  - {outlet}: {pos}")
        if len(disagreements) > 4:
            lines.append(f"- _…and {len(disagreements)-4} more_")
        if missing:
            lines += ["", "### Missing context", ""]
            for m in missing[:5]:
                lines.append(f"- {m}")

        lines += [
            "",
            "### Composed tweet",
            "",
            "```",
            c["composed_tweet"].strip(),
            "```",
            "",
            "### Your scores",
            "",
        ]
        for name, _ in RUBRIC_FIELDS:
            lines.append(f"- {name}: ")
        lines += [
            "- publish_again: ",
            "- notes: ",
            "",
            "---",
            "",
        ]

    out = OUT_DIR / "labels.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    pairs = load_pairs()
    if not pairs:
        raise SystemExit("no matched (post + brief) pairs found")
    write_jsonl(pairs)
    render_labels_md(pairs)
