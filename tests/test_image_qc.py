"""
Unit tests for src/image_qc.py — Claude Haiku vision QC.

Scope:
  - API-key-missing path returns (True, "qc-skipped: ...")
    (QC should never block posting when it can't run.)
  - Missing file path returns (False, "qc-error: ...")
  - Successful "Yes" response parses as passed=True
  - Successful "No" response parses as passed=False
  - Exception during API call returns (True, "qc-skipped-due-to-error: ...")
    (Same reason as API-key missing: flaky QC must not block posting.)
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _p in (_PROJECT_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from image_qc import check_image  # noqa: E402


# ---------------------------------------------------------------------------
# Edge cases that don't require a real API call
# ---------------------------------------------------------------------------


class TestGuardRails:
    def test_missing_api_key_skips_gracefully(self, tmp_path):
        img = tmp_path / "x.png"
        img.write_bytes(b"fake png bytes")
        with patch.dict(os.environ, {}, clear=True):
            passed, reason = check_image(str(img))
        assert passed is True
        assert "qc-skipped" in reason
        assert "ANTHROPIC_API_KEY" in reason

    def test_missing_image_returns_qc_error(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}):
            passed, reason = check_image("nonexistent-path-12345.png")
        assert passed is False
        assert "qc-error" in reason


# ---------------------------------------------------------------------------
# Mocked Haiku vision call
# ---------------------------------------------------------------------------


def _make_anthropic_response(text: str) -> MagicMock:
    """Build a mock anthropic client response with .content[0].text = text."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class TestHaikuResponseParsing:
    def _setup_png(self, tmp_path):
        img = tmp_path / "test.png"
        # Minimal valid-looking PNG header; contents aren't parsed by the
        # QC code (it just base64-encodes them for the API).
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        return img

    def test_yes_response_parses_as_passed(self, tmp_path):
        img = self._setup_png(tmp_path)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_anthropic_response(
            "Yes\nSingle brown tabby with correct anatomy."
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
             patch("anthropic.Anthropic", return_value=mock_client):
            passed, reason = check_image(str(img))
        assert passed is True
        assert "Single brown tabby" in reason

    def test_no_response_parses_as_failed(self, tmp_path):
        img = self._setup_png(tmp_path)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_anthropic_response(
            "No\nFive legs visible on the cat."
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
             patch("anthropic.Anthropic", return_value=mock_client):
            passed, reason = check_image(str(img))
        assert passed is False
        assert "Five legs" in reason

    def test_case_insensitive_yes_is_accepted(self, tmp_path):
        img = self._setup_png(tmp_path)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_anthropic_response(
            "YES.\nGood generation."
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
             patch("anthropic.Anthropic", return_value=mock_client):
            passed, _ = check_image(str(img))
        assert passed is True

    def test_api_exception_returns_passed_with_skip_reason(self, tmp_path):
        """QC must NOT block posting when the API call fails."""
        img = self._setup_png(tmp_path)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("network error")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
             patch("anthropic.Anthropic", return_value=mock_client):
            passed, reason = check_image(str(img))
        assert passed is True
        assert "qc-skipped-due-to-error" in reason
        assert "network error" in reason
