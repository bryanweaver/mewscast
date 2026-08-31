"""
Tests proving the dead-files cleanup claim.

These tests verify that:
1. Dead JSON files are deleted (outlet_reply_history.json, x_engagement_history.json, x_scrape_result.json)
2. Dead Python modules are deleted (vocab_report.py, analytics.py, filter_history.py, etc.)
3. README no longer references 404/ghost paths
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


class TestDeadFilesDeleted:
    """Verify that dead files have been removed from the repository."""

    @pytest.mark.parametrize("dead_json", [
        "outlet_reply_history.json",
        "x_engagement_history.json",
        "x_scrape_result.json",
    ])
    def test_dead_json_files_removed(self, dead_json: str):
        """Dead JSON files at repo root must not exist."""
        dead_path = PROJECT_ROOT / dead_json
        assert not dead_path.exists(), f"Dead file should be deleted: {dead_json}"

    @pytest.mark.parametrize("dead_module", [
        "vocab_report.py",
    ])
    def test_dead_src_modules_removed(self, dead_module: str):
        """Dead modules in src/ must not exist."""
        dead_path = SRC_DIR / dead_module
        assert not dead_path.exists(), f"Dead module should be deleted: src/{dead_module}"

    @pytest.mark.parametrize("dead_script", [
        "analytics.py",
        "filter_history.py",
        "generate_og_image.py",
        "prep_signature.py",
        "preview_watermark.py",
        "backfill_thumbnails.py",
    ])
    def test_dead_scripts_removed(self, dead_script: str):
        """Dead scripts must not exist."""
        dead_path = SCRIPTS_DIR / dead_script
        assert not dead_path.exists(), f"Dead script should be deleted: scripts/{dead_script}"


class TestReadmeAccuracy:
    """Verify README matches the actual tree."""

    @pytest.fixture
    def readme_content(self) -> str:
        return README_PATH.read_text()

    def test_no_positive_news_post_reference(self, readme_content: str):
        """README must not reference src/positive_news_post.py (file doesn't exist)."""
        assert "positive_news_post.py" not in readme_content, \
            "README should not reference positive_news_post.py (file does not exist)"

    def test_no_vocab_report_reference(self, readme_content: str):
        """README must not reference src/vocab_report.py (file deleted)."""
        assert "vocab_report.py" not in readme_content, \
            "README should not reference vocab_report.py (file deleted)"

    def test_no_dead_scripts_reference(self, readme_content: str):
        """README must not reference deleted scripts in the project structure."""
        dead_scripts = [
            "filter_history.py",
            "analytics.py",
            "generate_og_image.py",
            "prep_signature.py",
            "preview_watermark.py",
            "backfill_thumbnails.py",
        ]
        for script in dead_scripts:
            pattern = rf"├──\s*{re.escape(script)}|│\s*├──\s*{re.escape(script)}"
            matches = re.findall(pattern, readme_content)
            assert not matches, \
                f"README should not reference {script} in the project structure"

    def test_no_ghost_test_files_in_readme(self, readme_content: str):
        """README must not list test files that don't exist."""
        ghost_tests = ["test_outlet_reply.py", "test_x_engagement.py"]
        for test_file in ghost_tests:
            assert test_file not in readme_content, \
                f"README should not reference {test_file} (file does not exist)"

