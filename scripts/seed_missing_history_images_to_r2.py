#!/usr/bin/env python3
"""Seed R2 with every dossier image that exists in git history but not in the bucket.

One-off companion to scripts/upload_dossier_images_to_r2.py, meant to run
right before the history rewrite that purges docs/dossiers/images/ from git
(docs/R2_IMAGES_MIGRATION.md step 8). The original seed deliberately skipped
*.field-notes.png; this script uploads everything so nothing is lost when
the blobs are destroyed. It reads the files straight out of git history
(the images are gitignored and absent from the working tree), so it needs a
full clone (fetch-depth: 0 in CI).

Idempotent: lists the bucket first and only uploads missing keys.
Requires R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.r2_uploader import _get_client, _r2_configured, upload_dossier_image  # noqa: E402

IMAGES_PREFIX = "docs/dossiers/images/"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_ROOT, check=True, capture_output=True, text=True
    ).stdout


def historical_image_paths() -> list[str]:
    """Every unique docs/dossiers/images/*.png path across all refs."""
    out = _git("rev-list", "--objects", "--all")
    paths = set()
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith(IMAGES_PREFIX) and parts[1].endswith(".png"):
            paths.add(parts[1])
    return sorted(paths)


def latest_blob(path: str) -> str | None:
    """Blob sha of the newest committed version of ``path`` (skipping deletes)."""
    commit = _git("log", "--all", "--diff-filter=d", "-1", "--format=%H", "--", path).strip()
    if not commit:
        return None
    return _git("rev-parse", f"{commit}:{path}").strip()


def bucket_keys() -> set[str]:
    client = _get_client()
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=os.environ["R2_BUCKET"]):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


def main() -> int:
    if not _r2_configured():
        print("R2 env vars missing — aborting.")
        return 1

    paths = historical_image_paths()
    existing = bucket_keys()
    missing = [p for p in paths if os.path.basename(p) not in existing]
    print(f"{len(paths)} historical images, {len(existing)} objects in bucket, "
          f"{len(missing)} to upload")

    failures = 0
    for path in missing:
        key = os.path.basename(path)
        sha = latest_blob(path)
        if sha is None:
            print(f"❌ no non-delete commit found for {path}")
            failures += 1
            continue
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with open(tmp_path, "wb") as fh:
                subprocess.run(
                    ["git", "cat-file", "blob", sha],
                    cwd=_ROOT, check=True, stdout=fh,
                )
            if not upload_dossier_image(tmp_path, key=key):
                failures += 1
        finally:
            os.unlink(tmp_path)

    print(f"done: {len(missing) - failures} uploaded, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
