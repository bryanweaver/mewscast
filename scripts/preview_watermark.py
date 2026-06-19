"""Preview the Walter signature watermark on existing post images without
shipping it to the live pipeline.

Usage:
    # Watermark a single image (output goes to preview_watermark/)
    python scripts/preview_watermark.py docs/dossiers/images/some-story.png

    # Sample N random images from a directory
    python scripts/preview_watermark.py docs/dossiers/images --sample 8

    # Try multiple opacity / size settings on the same image (variant sweep)
    python scripts/preview_watermark.py docs/dossiers/images/some-story.png \\
        --sweep

    # All four corners on one image
    python scripts/preview_watermark.py path/to/image.png --corners

Writes results to ./preview_watermark/ at the repo root (gitignored).
"""
import argparse
import os
import random
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _p in (_PROJECT_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from watermark import apply_watermark  # noqa: E402

PREVIEW_DIR = os.path.join(_PROJECT_ROOT, "preview_watermark")

VALID_EXTS = (".png", ".jpg", ".jpeg")


def _gather_inputs(arg_path: str, sample: int) -> list[str]:
    """Resolve the input argument into a concrete list of file paths."""
    if os.path.isfile(arg_path):
        return [arg_path]
    if os.path.isdir(arg_path):
        files = [
            os.path.join(arg_path, f)
            for f in os.listdir(arg_path)
            if f.lower().endswith(VALID_EXTS)
            and ".field-notes." not in f  # field-notes already have a Grok-rendered sig
        ]
        if not files:
            return []
        if sample and sample < len(files):
            files = random.sample(files, sample)
        return sorted(files)
    raise FileNotFoundError(arg_path)


def _out_path(src: str, suffix: str = "") -> str:
    base = os.path.splitext(os.path.basename(src))[0]
    ext = ".png"
    return os.path.join(PREVIEW_DIR, f"{base}{suffix}{ext}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Image file or directory")
    parser.add_argument(
        "--sample", type=int, default=0,
        help="If path is a directory, randomly sample N images.",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Generate variants with different opacity/size combos.",
    )
    parser.add_argument(
        "--corners", action="store_true",
        help="Generate one watermarked copy per corner.",
    )
    parser.add_argument(
        "--opacity", type=float, default=0.55,
        help="Alpha multiplier (0..1). Default 0.55 (classy artist-signature).",
    )
    parser.add_argument(
        "--size", type=float, default=0.20,
        help="Width ratio (0..1). Default 0.20 (20%% of image width).",
    )
    parser.add_argument(
        "--corner", default="bottom-right",
        choices=("bottom-right", "bottom-left", "top-right", "top-left"),
    )
    args = parser.parse_args()

    os.makedirs(PREVIEW_DIR, exist_ok=True)
    inputs = _gather_inputs(args.path, args.sample)
    if not inputs:
        print(f"No images found at {args.path}")
        sys.exit(1)

    written = 0
    for src in inputs:
        if args.sweep:
            for opacity in (0.40, 0.55, 0.70):
                for size in (0.15, 0.20, 0.25):
                    suffix = f"__op{int(opacity * 100)}_sz{int(size * 100)}"
                    dst = _out_path(src, suffix)
                    apply_watermark(
                        src, output_path=dst,
                        opacity=opacity, size_ratio=size,
                        corner=args.corner,
                    )
                    written += 1
        elif args.corners:
            for corner in ("bottom-right", "bottom-left", "top-right", "top-left"):
                suffix = f"__{corner.replace('-', '_')}"
                dst = _out_path(src, suffix)
                apply_watermark(
                    src, output_path=dst,
                    opacity=args.opacity, size_ratio=args.size, corner=corner,
                )
                written += 1
        else:
            dst = _out_path(src)
            apply_watermark(
                src, output_path=dst,
                opacity=args.opacity, size_ratio=args.size, corner=args.corner,
            )
            written += 1

    print(f"Wrote {written} preview image(s) to {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
