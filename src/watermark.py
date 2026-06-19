"""Apply a Walter Croncat paw + signature watermark to a generated image.

The signature asset at docs/images/walter-signature.png is pure black ink
on a transparent background — kept monochrome so we can tint it to any
color at composite time. The compositor samples the target patch on the
base image and picks a tint that contrasts with it: dark ink on bright
backgrounds, light ink on dark backgrounds. A soft drop shadow in the
opposite tone provides a guaranteed-legibility outline.

Design constraints (per product brief):
  - "Like an artist signs a painting" — small, corner-positioned, subtle
  - "Not too big" — default 18% of image width
  - "Classy" — never a solid box, never a logo plate; just ink-on-frame
  - "Always has contrast with the background" — luminance-aware tint flip

Usage:
    from watermark import apply_watermark
    apply_watermark("temp_image.png")  # in-place
    apply_watermark("temp_image.png", output_path="preview.png")
"""
import os
from typing import Optional

from PIL import Image, ImageFilter


# Default asset location. Resolved relative to the repo root so callers
# don't need to pass an absolute path. Override via the signature_asset
# argument if needed (e.g. for tests).
_DEFAULT_SIGNATURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "images", "walter-signature.png",
)


def _tint_monochrome_asset(asset: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Recolor a pure-black + alpha asset to the given RGB tone, preserving
    the alpha channel. Works because the source is monochrome — every
    visible pixel is (0, 0, 0, a)."""
    r, g, b, a = asset.split()
    tinted = Image.merge(
        "RGBA",
        (
            r.point(lambda _: rgb[0]),
            g.point(lambda _: rgb[1]),
            b.point(lambda _: rgb[2]),
            a,
        ),
    )
    return tinted


def _scale_alpha(asset: Image.Image, opacity: float) -> Image.Image:
    """Multiply the alpha channel by opacity (0..1)."""
    r, g, b, a = asset.split()
    a = a.point(lambda v: int(v * opacity))
    return Image.merge("RGBA", (r, g, b, a))


def _mean_luminance(patch: Image.Image) -> float:
    """Return mean luminance (0..255) of an RGB(A) patch."""
    grey = patch.convert("L")
    hist = grey.histogram()
    total = sum(i * hist[i] for i in range(256))
    pixels = sum(hist)
    return total / pixels if pixels else 128.0


def apply_watermark(
    image_path: str,
    output_path: Optional[str] = None,
    signature_asset: str = _DEFAULT_SIGNATURE_PATH,
    opacity: float = 0.55,
    size_ratio: float = 0.20,
    margin_ratio: float = 0.025,
    corner: str = "bottom-right",
) -> str:
    """Composite the Walter signature onto an image with contrast-aware tinting.

    Args:
        image_path: source image to watermark.
        output_path: where to write the result. If None, writes to image_path
            (in-place — destructive).
        signature_asset: path to the transparent PNG signature.
        opacity: 0..1 multiplier on the asset's alpha. 0.55 is the classy
            "artist signature" baseline; bump to 0.75 if too subtle.
        size_ratio: watermark width as a fraction of image width. 0.20 = 20%.
        margin_ratio: corner inset as a fraction of image width. 0.025 = 2.5%.
        corner: one of bottom-right / bottom-left / top-right / top-left.

    Returns:
        The output path.
    """
    if output_path is None:
        output_path = image_path

    base = Image.open(image_path).convert("RGBA")
    bw, bh = base.size

    asset = Image.open(signature_asset).convert("RGBA")
    aw, ah = asset.size
    target_w = int(bw * size_ratio)
    target_h = int(ah * (target_w / aw))
    asset = asset.resize((target_w, target_h), Image.LANCZOS)

    margin = int(bw * margin_ratio)
    if corner == "bottom-right":
        pos = (bw - target_w - margin, bh - target_h - margin)
    elif corner == "bottom-left":
        pos = (margin, bh - target_h - margin)
    elif corner == "top-right":
        pos = (bw - target_w - margin, margin)
    elif corner == "top-left":
        pos = (margin, margin)
    else:
        raise ValueError(f"Unknown corner: {corner}")

    # Sample target patch to decide tint direction
    patch = base.crop((pos[0], pos[1], pos[0] + target_w, pos[1] + target_h))
    lum = _mean_luminance(patch)
    if lum >= 128:
        # Bright patch → dark ink with a faint light halo for legibility
        sig_color = (25, 25, 25)
        halo_color = (255, 255, 255)
    else:
        # Dark patch → light ink with a faint dark halo
        sig_color = (235, 235, 235)
        halo_color = (0, 0, 0)

    sig = _tint_monochrome_asset(asset, sig_color)
    sig = _scale_alpha(sig, opacity)

    # Soft halo: same shape, opposite tone, blurred, low opacity. Sits
    # underneath the main signature and provides a 1-2px legibility outline
    # without looking like a stamped plate.
    halo = _tint_monochrome_asset(asset, halo_color)
    halo = _scale_alpha(halo, opacity * 0.4)
    halo = halo.filter(ImageFilter.GaussianBlur(radius=2))

    # Composite halo first, then signature on top
    composite = Image.new("RGBA", base.size, (0, 0, 0, 0))
    composite.alpha_composite(halo, dest=pos)
    composite.alpha_composite(sig, dest=pos)
    final = Image.alpha_composite(base, composite)

    # Preserve original format. Most source images are PNG; if JPEG, flatten.
    ext = os.path.splitext(output_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        final.convert("RGB").save(output_path, "JPEG", quality=92, optimize=True)
    else:
        final.save(output_path, "PNG", optimize=True)

    return output_path
