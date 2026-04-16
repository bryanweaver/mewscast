"""
Unit tests for src/image_generator.py — the image-generation wrapper.

Scope:
  - Per-post-type style anchor composition (the part that doesn't hit the API)
  - Subject anchor invariant across post types
  - Removal of the old badge-text clause (regression guard against the
    known-broken "Any press badge must read exactly 'PRESS' ..." line)
  - Aspect-ratio config validation / fallback
  - Config load path is resilient to missing image block

The actual Grok API call is NOT tested here — that's an integration concern.
"""
import os
import sys
from unittest.mock import patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _p in (_PROJECT_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Style anchor composition
# ---------------------------------------------------------------------------


class TestAnchorPrompt:
    """_anchor_prompt should prepend subject + eye-catch + style anchors
    deterministically. Assertions pick phrases unique to each anchor so
    overlap between default and per-type styles doesn't cause false matches."""

    def _make_generator(self):
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator

            return ImageGenerator()

    def test_subject_anchor_always_prepended(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("a city street", post_type="REPORT")
        assert "brown tabby cat" in result.lower()
        assert "correct four-paw anatomy" in result.lower()
        assert "news anchor" in result.lower()
        assert "a city street" in result

    def test_eyecatch_anchor_always_prepended(self):
        """Every prompt — including the no-post-type fallback — gets the
        scroll-stopping eye-catch anchor."""
        gen = self._make_generator()
        for pt in ("REPORT", "META", "ANALYSIS", "BULLETIN", "PRIMARY", "CORRECTION", None):
            result = gen._anchor_prompt("topic", post_type=pt).lower()
            assert "scroll-stopping" in result, f"missing eye-catch for {pt}"
            assert "cinematic" in result, f"missing cinematic cue for {pt}"

    def test_report_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("a city street", post_type="REPORT").lower()
        assert "vanity fair" in result
        assert "85mm" in result

    def test_meta_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("outlets disagree", post_type="META").lower()
        assert "wire-service desk" in result
        assert "monitors glowing" in result

    def test_analysis_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("a pattern", post_type="ANALYSIS").lower()
        assert "new yorker" in result
        assert "chiaroscuro" in result

    def test_bulletin_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("breaking", post_type="BULLETIN").lower()
        assert "breaking-news urgency" in result or "hand-held camera" in result
        assert "red emergency glow" in result

    def test_primary_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("the filing", post_type="PRIMARY").lower()
        assert "presidential-archive" in result
        assert "portra" in result

    def test_correction_style_anchor_applied(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("earlier post error", post_type="CORRECTION").lower()
        assert "black-and-white editorial" in result
        assert "correction stamp" in result or "crossed-out" in result

    def test_none_post_type_uses_default_style_anchor(self):
        """Legacy path passes no post_type; subject + eye-catch anchors
        stay, and a generic default style anchor is used (not a per-type one)."""
        gen = self._make_generator()
        result = gen._anchor_prompt("a story", post_type=None).lower()
        assert "brown tabby cat" in result
        assert "scroll-stopping" in result
        assert "a story" in result
        # Per-type-exclusive fragments should not appear on the default path
        assert "vanity fair" not in result
        assert "new yorker" not in result
        assert "wire-service desk" not in result
        assert "presidential-archive" not in result

    def test_unknown_post_type_falls_back_to_default(self):
        gen = self._make_generator()
        result = gen._anchor_prompt("something", post_type="MADE_UP_TYPE").lower()
        assert "brown tabby cat" in result
        assert "scroll-stopping" in result
        assert "vanity fair" not in result
        assert "new yorker" not in result


# ---------------------------------------------------------------------------
# Regression: badge-text clause must be gone
# ---------------------------------------------------------------------------


class TestBadgeTextClauseRemoved:
    """The old anchor asked Grok to render readable 'PRESS' / 'Walter Croncat'
    badge text. Grok can't do legible text reliably, so the clause was
    removed and replaced with a PIL compositing step. Guard against
    accidental re-introduction."""

    def test_no_press_badge_clause_in_any_output(self):
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator

            gen = ImageGenerator()

        for post_type in ("REPORT", "META", "ANALYSIS", "BULLETIN", "PRIMARY", "CORRECTION", None):
            result = gen._anchor_prompt("topic", post_type=post_type)
            lower = result.lower()
            assert "press badge must read" not in lower, (
                f"regression: badge-text clause reappeared for post_type={post_type}"
            )
            # Also guard the exact-text quotes that appeared in the old anchor
            assert "'press'" not in lower
            assert "'walter croncat'" not in lower


# ---------------------------------------------------------------------------
# Aspect ratio config
# ---------------------------------------------------------------------------


class TestAspectRatioConfig:
    def test_default_aspect_ratio_is_3_2(self, tmp_path, monkeypatch):
        """If image.aspect_ratio isn't explicitly set, the code default is 3:2."""
        # Point the module at an empty temp dir so no config.yaml is found
        monkeypatch.setattr(
            "image_generator._load_image_config",
            lambda: {},
        )
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator

            gen = ImageGenerator()
        assert gen.aspect_ratio == "3:2"

    def test_unsupported_aspect_ratio_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            "image_generator._load_image_config",
            lambda: {"aspect_ratio": "7:3"},
        )
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator

            gen = ImageGenerator()
        assert gen.aspect_ratio == "3:2"

    def test_supported_aspect_ratios_accepted(self, monkeypatch):
        import image_generator as module

        for ratio in ("3:2", "16:9", "4:5", "1:1"):
            monkeypatch.setattr(
                module, "_load_image_config",
                lambda r=ratio: {"aspect_ratio": r},
            )
            with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
                gen = module.ImageGenerator()
            assert gen.aspect_ratio == ratio, (
                f"expected {ratio}, got {gen.aspect_ratio}"
            )


# ---------------------------------------------------------------------------
# QC config
# ---------------------------------------------------------------------------


class TestQCConfig:
    def test_qc_disabled_by_default(self, monkeypatch):
        monkeypatch.setattr(
            "image_generator._load_image_config",
            lambda: {},
        )
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            from image_generator import ImageGenerator

            gen = ImageGenerator()
        assert gen.qc_enabled is False

    def test_qc_can_be_enabled(self, monkeypatch):
        import image_generator as module

        monkeypatch.setattr(
            module, "_load_image_config",
            lambda: {"qc": {"enabled": True, "max_retries": 3}},
        )
        with patch.dict(os.environ, {"X_AI_API_KEY": "test"}):
            gen = module.ImageGenerator()
        assert gen.qc_enabled is True
        assert gen.qc_max_retries == 3
