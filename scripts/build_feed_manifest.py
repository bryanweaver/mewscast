"""Rebuild docs/feed.json from the committed dossier .meta.json sidecars.

The publish pipeline regenerates feed.json on every run (see
_render_dossier_html). This standalone version builds the same manifest from
the meta sidecars, for the initial backfill and for ad-hoc rebuilds without
running the full pipeline.

Usage:
    python scripts/build_feed_manifest.py
"""

from __future__ import annotations

import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from dossier_renderer import render_feed_json  # noqa: E402

DOSSIERS_DIR = os.path.join(_ROOT, "docs", "dossiers")
THUMBS_DIR = os.path.join(DOSSIERS_DIR, "thumbs")
FEED_PATH = os.path.join(_ROOT, "docs", "feed.json")


def main() -> int:
    entries = []
    for mp in sorted(glob.glob(os.path.join(DOSSIERS_DIR, "*.meta.json"))):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                m = json.load(f)
            # Same wrapping render_index_page / render_feed_json expect.
            entries.append({
                "story_id": m.get("story_id", ""),
                "dossier": {"headline_seed": m.get("headline_seed", "")},
                "post": {
                    "draft": {"post_type": m.get("post_type", "")},
                    "published_at": m.get("published_at", ""),
                },
                "brief": {"confidence": m.get("confidence", 0)},
            })
        except Exception:
            continue

    feed_json = render_feed_json(entries, THUMBS_DIR)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        f.write(feed_json)

    count = feed_json.count('"id"')
    with_thumb = feed_json.count('"thumb": "')
    print(f"wrote {FEED_PATH}: {count} items ({with_thumb} with thumbnails)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
