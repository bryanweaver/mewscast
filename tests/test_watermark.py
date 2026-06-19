"""Tests for src/watermark.py — the Walter signature compositor.

Scope:
  - Watermark visibly modifies an image (alpha composite actually fires)
  - Contrast-aware tint flips between bright and dark backgrounds
  - Corner positioning respects the requested corner
  - ImageGenerator wiring: watermark.enabled config knob, skip-on-disabled,
    error-swallow behavior (post pipeline never breaks on watermark failure)
"""
import os
import sys
from unittest.mock import patch

from PIL import Image
import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _p in (_PROJECT_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _make_solid_image(path: str, color: tuple[int, int, int], size=(800, 533)) -> None:
    Image.new("RGB", size, color).save(path, "PNG")


def _signature_corner_mean_luminance(image_path: str, corner: str = "bottom-right") -> float:
    """Sample the corner patch where the watermark would land and return
    its mean luminance. Useful for asserting the watermark actually
    altered pixels relative to the original."""
    img = Image.open(image_path).convert("L")
    w, h = img.size
    patch_w = int(w * 0.20)
    patch_h = int(patch_w * 0.34)  # signature aspect ratio is ~1091:367
    margin = int(w * 0.025)
    if corner == "bottom-right":
        box = (w - patch_w - margin, h - patch_h - margin, w - margin, h - margin)
    elif corner == "top-left":
        box = (margin, margin, margin + patch_w, margin + patch_h)
    else:
        raise ValueError(corner)
    patch = img.crop(box)
    hist = patch.histogram()
    total = sum(i * hist[i] for i in range(256))
    pixels = sum(hist)
    return total / pixels if pixels else 0.0


class TestWatermarkModule:
    def test_applies_visible_change_on_bright_background(self, tmp_path):
        """On a white image, the watermark adds dark ink — luminance drops
        in the target corner."""
        from watermark import apply_watermark

        src = str(tmp_path / "white.png")
        dst = str(tmp_path / "white_wm.png")
        _make_solid_image(src, (255, 255, 255))
        before = _signature_corner_mean_luminance(src)
        apply_watermark(src, output_path=dst, opacity=0.60)
        after = _signature_corner_mean_luminance(dst)
        # White before → dark ink composited → luminance must drop
        assert after < before - 5, (
            f"Watermark didn't darken corner on white background "
            f"(before={before:.1f}, after={after:.1f})"
        )

    def test_applies_visible_change_on_dark_background(self, tmp_path):
        """On a black image, the watermark adds light ink — luminance rises."""
        from watermark import apply_watermark

        src = str(tmp_path / "black.png")
        dst = str(tmp_path / "black_wm.png")
        _make_solid_image(src, (0, 0, 0))
        before = _signature_corner_mean_luminance(src)
        apply_watermark(src, output_path=dst, opacity=0.60)
        after = _signature_corner_mean_luminance(dst)
        # Black before → light ink composited → luminance must rise
        assert after > before + 5, (
            f"Watermark didn't lighten corner on black background "
            f"(before={before:.1f}, after={after:.1f})"
        )

    def test_corner_argument_positions_watermark(self, tmp_path):
        """Specifying corner=top-left puts the ink in the top-left, not
        bottom-right."""
        from watermark import apply_watermark

        src = str(tmp_path / "white2.png")
        dst = str(tmp_path / "white2_tl.png")
        _make_solid_image(src, (255, 255, 255))
        apply_watermark(src, output_path=dst, opacity=0.60, corner="top-left")
        # Top-left should be darkened; bottom-right should remain white
        tl_lum = _signature_corner_mean_luminance(dst, corner="top-left")
        br_lum = _signature_corner_mean_luminance(dst, corner="bottom-right")
        assert tl_lum < 240, f"Top-left wasn't darkened ({tl_lum:.1f})"
        assert br_lum > 250, f"Bottom-right unexpectedly modified ({br_lum:.1f})"

    def test_invalid_corner_raises(self, tmp_path):
        from watermark import apply_watermark

        src = str(tmp_path / "white3.png")
        _make_solid_image(src, (255, 255, 255))
        with pytest.raises(ValueError):
            apply_watermark(src, output_path=str(tmp_path / "out.png"), corner="middle")


class TestImageGeneratorWatermarkWiring:
    """Verify ImageGenerator picks up the watermark config and invokes the
    compositor at the right time."""

    def _make_gen(self, monkeypatch, **overrides):
        cfg = {
            "model": "grok-imagine-image-quality",
            "aspect_ratio": "3:2",
            "watermark": {
                "enabled": True,
                "opacity": 0.60,
                "size_ratio": 0.20,
                "corner": "bottom-right",
                **overrides,
            },
        }
        monkeypatch.setattr("image_generator._load_image_config", lambda: cfg)
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator
            return ImageGenerator()

    def test_watermark_config_loaded(self, monkeypatch):
        gen = self._make_gen(monkeypatch)
        assert gen.watermark_enabled is True
        assert gen.watermark_opacity == 0.60
        assert gen.watermark_size_ratio == 0.20
        assert gen.watermark_corner == "bottom-right"

    def test_watermark_disabled_skips_compositor(self, monkeypatch, tmp_path):
        gen = self._make_gen(monkeypatch, enabled=False)
        # Create a stub image and a tracker
        path = str(tmp_path / "stub.png")
        _make_solid_image(path, (255, 255, 255))
        before_bytes = open(path, "rb").read()
        gen._maybe_watermark(path)
        after_bytes = open(path, "rb").read()
        assert before_bytes == after_bytes, "Disabled watermark still modified the file"

    def test_watermark_enabled_modifies_file(self, monkeypatch, tmp_path):
        gen = self._make_gen(monkeypatch)
        path = str(tmp_path / "stub2.png")
        _make_solid_image(path, (255, 255, 255))
        before_bytes = open(path, "rb").read()
        gen._maybe_watermark(path)
        after_bytes = open(path, "rb").read()
        assert before_bytes != after_bytes, "Enabled watermark didn't modify the file"

    def test_watermark_failure_swallowed(self, monkeypatch, tmp_path):
        """If the compositor blows up, the pipeline must continue. Pass a
        nonexistent file — apply_watermark will raise FileNotFoundError, and
        _maybe_watermark must catch it."""
        gen = self._make_gen(monkeypatch)
        gen._maybe_watermark(str(tmp_path / "does_not_exist.png"))  # should not raise
