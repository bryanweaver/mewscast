"""One-shot prep: convert a black-on-white signature JPG into a transparent
PNG suitable for watermark compositing.

Strategy: luminance-as-alpha. Each pixel's brightness becomes its
transparency — pure white → fully transparent, pure black → fully opaque,
gray ink splatter → semi-transparent. RGB is forced to pure black so JPG
color fringing can't leak through and so the asset can be tinted at
composite time (multiply by any color).

A threshold step removes JPG compression noise (faint near-white speckle
that would otherwise produce a thin haze across the whole canvas and
defeat the auto-trim).

Usage:
    python scripts/prep_signature.py docs/images/walter_signature.jpg \
        docs/images/walter-signature.png
"""
import os
import sys

from PIL import Image

NOISE_ALPHA_THRESHOLD = 25


def prep(src: str, dst: str) -> None:
    grey = Image.open(src).convert("L")
    w, h = grey.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    in_px = grey.load()
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            alpha = 255 - in_px[x, y]
            if alpha >= NOISE_ALPHA_THRESHOLD:
                out_px[x, y] = (0, 0, 0, alpha)

    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)

    out.save(dst, "PNG", optimize=True)
    cw, ch = out.size
    print(f"Wrote {dst} — {cw}x{ch}, {os.path.getsize(dst) // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: prep_signature.py <src.jpg> <dst.png>")
        sys.exit(1)
    prep(sys.argv[1], sys.argv[2])
