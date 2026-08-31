"""
Tests proving the dead-files cleanup claim.

These tests verify that:
1. Dead JSON files are deleted (outlet_reply_history.json, x_engagement_history.json, x_scrape_result.json)
2. Dead Python modules are deleted (vocab_report.py, analytics.py, filter_history.py, etc.)
3. README no longer references 404 paths
4. README workflow list matches actual .github/workflows/
5. README test file count matches actual tests/test_*.py count
"""
import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
TESTS_DIR = PROJECT_ROOT / "tests"
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
        """README must not reference deleted scripts as if they are live."""
        dead_scripts = ["filter_history.py"]
        for script in dead_scripts:
            pattern = rf"├──\s*{re.escape(script)}|│\s*├──\s*{re.escape(script)}"
            matches = re.findall(pattern, readme_content)
            assert not matches, \
                f"README should not reference {script} in the project structure"
        assert "scripts/analytics.py" not in readme_content or "track_analytics.py" in readme_content, \
            "README should reference track_analytics.py, not analytics.py"

    def test_no_ghost_test_files_in_readme(self, readme_content: str):
        """README must not list test files that don't exist."""
        ghost_tests = ["test_outlet_reply.py", "test_x_engagement.py"]
        for test_file in ghost_tests:
            assert test_file not in readme_content, \
                f"README should not reference {test_file} (file does not exist)"

    def test_readme_test_file_count_matches_tree(self, readme_content: str):
        """README test file count must match actual test_*.py count."""
        actual_test_files = list(TESTS_DIR.glob("test_*.py"))
        actual_count = len(actual_test_files)

        count_match = re.search(r"(\d+)\s+test\s+files?", readme_content, re.IGNORECASE)
        assert count_match, "README should mention test file count"

        readme_count = int(count_match.group(1))
        assert readme_count == actual_count, \
            f"README claims {readme_count} test files but tree has {actual_count}"

    def test_readme_workflow_list_complete(self, readme_content: str):
        """README must list all workflows in .github/workflows/."""
        actual_workflows = {f.stem for f in WORKFLOWS_DIR.glob("*.yml")}

        required_workflows = {
            "journalism-publish",
            "journalism-dry-run",
            "journalism-republish",
            "post-correction",
            "post-pin-explainer",
            "bluesky-engage",
            "engage-cats-bluesky",
            "bluesky-outlet-reply",
            "triage-review",
            "track-analytics",
            "rebuild-history",
            "seed-history-images",
            "test-dedup",
            "x-cat-repost",
            "x-mention-reply",
        }

        for workflow in required_workflows:
            assert workflow in actual_workflows, \
                f"Workflow {workflow}.yml should exist in .github/workflows/"
            assert f"{workflow}.yml" in readme_content, \
                f"README should list {workflow}.yml in the project structure"


class TestLiveFilesStillExist:
    """Verify that live files referenced by workflows still exist."""

    def test_track_analytics_exists(self):
        """scripts/track_analytics.py must exist (used by track-analytics.yml)."""
        assert (SCRIPTS_DIR / "track_analytics.py").exists()

    def test_journalism_dry_run_exists(self):
        """scripts/journalism_dry_run.py must exist (used by journalism-dry-run.yml)."""
        assert (SCRIPTS_DIR / "journalism_dry_run.py").exists()

    def test_triage_review_exists(self):
        """scripts/triage_review.py must exist (used by triage-review.yml)."""
        assert (SCRIPTS_DIR / "triage_review.py").exists()

    def test_rebuild_history_exists(self):
        """scripts/rebuild_history.py must exist (used by rebuild-history.yml)."""
        assert (SCRIPTS_DIR / "rebuild_history.py").exists()
