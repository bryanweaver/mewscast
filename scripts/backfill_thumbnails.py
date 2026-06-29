"""One-shot: generate WebP thumbnails for every existing dossier image.

The publish pipeline now emits a thumbnail per new dossier (see
src/thumbnailer.py + _persist_dossier_image). This script backfills the
thumbnails for all images that predate that change.

Usage:
    python scripts/backfill_thumbnails.py [--force] [--dry-run]

- Skips images that already have an up-to-date thumbnail (unless --force).
- Excludes *.field-notes.png — those are social-reply media, never shown in
  the homepage feed.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from thumbnailer import make_thumbnail  # noqa: E402

IMAGES_DIR = os.path.join(_ROOT, "docs", "dossiers", "images")
THUMBS_DIR = os.path.join(_ROOT, "docs", "dossiers", "thumbs")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="regenerate even if thumb exists")
    ap.add_argument("--dry-run", action="store_true", help="list work without writing")
    args = ap.parse_args()

    if not os.path.isdir(IMAGES_DIR):
        print(f"no images dir: {IMAGES_DIR}")
        return 1

    pngs = sorted(
        f for f in os.listdir(IMAGES_DIR)
        if f.lower().endswith(".png") and not f.endswith(".field-notes.png")
    )
    print(f"found {len(pngs)} dossier images")

    made = skipped = failed = 0
    for fn in pngs:
        src = os.path.join(IMAGES_DIR, fn)
        dest = os.path.join(THUMBS_DIR, os.path.splitext(fn)[0] + ".webp")
        if os.path.isfile(dest) and not args.force:
            skipped += 1
            continue
        if args.dry_run:
            print(f"  WOULD make {os.path.basename(dest)}")
            made += 1
            continue
        if make_thumbnail(src, dest):
            made += 1
        else:
            failed += 1

    print(f"done: made={made} skipped={skipped} failed={failed} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
