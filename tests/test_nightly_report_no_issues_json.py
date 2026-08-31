"""Verify nightly_report.py no longer writes *-issues.json files."""
from __future__ import annotations

import importlib.util
import inspect
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_script():
    """Import nightly_report.py as a module."""
    script_path = Path(__file__).parent.parent / "scripts" / "nightly_report.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("nightly_report", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNoIssuesJsonWriter:
    """Confirm the issues.json writer has been removed."""

    def test_no_issues_path_in_main_source(self):
        """The main() function source must not contain issues_path or issues.json."""
        mod = _load_script()
        source = inspect.getsource(mod.main)
        assert "issues_path" not in source, "issues_path still present in main()"
        assert "issues.json" not in source, "issues.json still present in main()"

    def test_script_does_not_write_issues_json(self, tmp_path):
        """Run the script in a temp dir and confirm no *-issues.json is created."""
        mod = _load_script()
        reports_dir = tmp_path / "docs" / "reports"
        reports_dir.mkdir(parents=True)

        fake_posts = {"posts": []}
        fake_analytics = {
            "posts": {},
            "follower_history": {"x": [], "bluesky": []},
            "last_updated": None,
        }

        def fake_load(name):
            if "posts_history" in name:
                return fake_posts
            if "analytics_history" in name:
                return fake_analytics
            raise FileNotFoundError(name)

        with patch.object(mod, "load", fake_load), \
             patch.object(mod, "ROOT", str(tmp_path)):
            mod.main()

        json_files = list(reports_dir.glob("*-issues.json"))
        assert json_files == [], f"Unexpected issues.json file(s): {json_files}"

        md_files = list(reports_dir.glob("*.md"))
        assert len(md_files) >= 1, "Expected at least one .md report file"
