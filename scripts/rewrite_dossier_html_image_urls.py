"""One-shot: rewrite image URLs inside existing dossier HTML files so
they point at the R2 bucket instead of relative ``./images/X.png`` and
absolute ``https://mewscast.us/dossiers/images/X.png``.

Run AFTER the bucket is seeded (scripts/upload_dossier_images_to_r2.py)
and BEFORE the gitignore commit. The site keeps working because the
rewritten URLs immediately resolve at R2_IMAGE_BASE_URL.

Usage:
    R2_IMAGE_BASE_URL=https://images.mewscast.us \\
        python scripts/rewrite_dossier_html_image_urls.py
    # or with --dry-run to preview the diff
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS_DIR = ROOT / "docs" / "dossiers"

ABS_PAT = re.compile(r"https://mewscast\.us/dossiers/images/([^\"'\s>]+\.png)")
REL_PAT = re.compile(r"\./images/([^\"'\s>]+\.png)")


def rewrite_one(html: str, base: str) -> tuple[str, int]:
    n = 0

    def _abs(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"{base}/{m.group(1)}"

    def _rel(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"{base}/{m.group(1)}"

    html = ABS_PAT.sub(_abs, html)
    html = REL_PAT.sub(_rel, html)
    return html, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base", default=os.environ.get("R2_IMAGE_BASE_URL", ""))
    args = ap.parse_args()

    base = args.base.rstrip("/")
    if not base:
        print("R2_IMAGE_BASE_URL is not set (use --base or env). Aborting.")
        return 2

    html_files = sorted(DOSSIERS_DIR.glob("*.html"))
    print(f"scanning {len(html_files)} html file(s) in {DOSSIERS_DIR}")

    touched = 0
    total_subs = 0
    for f in html_files:
        original = f.read_text(encoding="utf-8")
        new, n = rewrite_one(original, base)
        if n == 0:
            continue
        touched += 1
        total_subs += n
        if args.dry_run:
            print(f"  DRY: {f.name} — {n} substitution(s)")
        else:
            f.write_text(new, encoding="utf-8")
            print(f"  wrote {f.name} — {n} substitution(s)")

    print(f"done: files_touched={touched} substitutions={total_subs} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
