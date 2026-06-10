"""One-shot: upload every existing dossier PNG under docs/dossiers/images/
to the configured R2 bucket. Idempotent — re-running re-uploads, which
overwrites with the same content. Safe.

Run locally with R2 creds in env (or in a .env file) BEFORE flipping the
gitignore. After this completes you can untrack the images dir without
breaking the live site.

Usage:
    python scripts/upload_dossier_images_to_r2.py
    python scripts/upload_dossier_images_to_r2.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `src/` importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from r2_uploader import _r2_configured, upload_dossier_image  # noqa: E402


IMAGES_DIR = ROOT / "docs" / "dossiers" / "images"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list files but don't upload")
    args = ap.parse_args()

    if not IMAGES_DIR.is_dir():
        print(f"no images dir at {IMAGES_DIR}")
        return 1

    if not args.dry_run and not _r2_configured():
        print("R2 env vars are not set. Aborting. (Use --dry-run to list files.)")
        return 2

    pngs = sorted(IMAGES_DIR.glob("*.png"))
    print(f"found {len(pngs)} png file(s) under {IMAGES_DIR}")

    ok = 0
    fail = 0
    for p in pngs:
        key = p.name
        if args.dry_run:
            print(f"  DRY: would upload {key} ({p.stat().st_size} bytes)")
            ok += 1
            continue
        if upload_dossier_image(str(p), key=key):
            ok += 1
        else:
            fail += 1

    print(f"done: ok={ok} fail={fail}")
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
