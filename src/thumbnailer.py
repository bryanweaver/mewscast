"""Generate small WebP thumbnails of dossier images for the homepage card feed.

Why this exists: dossier hero images are 5-6 MB PNGs. The homepage shows a grid
of every dossier; loading full PNGs would be hundreds of megabytes. A ~400px
WebP thumbnail is ~30-50 KB — small enough to commit to git and to render a
long, lazy-loaded grid instantly.

Fail-soft by design: a thumbnail failure must never break publishing.
"""

from __future__ import annotations

import os

THUMB_WIDTH = 400
THUMB_QUALITY = 80


def make_thumbnail(
    src_path: str,
    dest_path: str,
    width: int = THUMB_WIDTH,
    quality: int = THUMB_QUALITY,
) -> bool:
    """Resize ``src_path`` to ``width`` px (preserving aspect) and write WebP.

    Returns True on success, False on any failure (without raising).
    Skips upscaling — images already narrower than ``width`` are saved as-is.
    """
    try:
        from PIL import Image

        if not os.path.isfile(src_path):
            print(f"[thumb] skip — source missing: {src_path}")
            return False

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with Image.open(src_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > width:
                new_h = max(1, round(h * width / w))
                im = im.resize((width, new_h), Image.LANCZOS)
            im.save(dest_path, "WEBP", quality=quality, method=6)

        return True
    except Exception as e:  # pragma: no cover - fail-soft
        print(f"[thumb] failed {src_path} -> {dest_path}: {e}")
        return False
