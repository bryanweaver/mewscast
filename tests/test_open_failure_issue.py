"""Tests for scripts/open_failure_issue.py.

These tests import and call the real script functions, mocking only the
network layer (urllib.request.urlopen). This ensures we're testing the
actual dedup and issue-creation logic, not a mock of it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _load_script():
    """Import open_failure_issue.py as a module."""
    script_path = Path(__file__).parent.parent / "scripts" / "open_failure_issue.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("open_failure_issue", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestScriptExists:
    """Test that the script exists and is importable."""

    def test_script_file_exists(self):
        script_path = Path(__file__).parent.parent / "scripts" / "open_failure_issue.py"
        assert script_path.exists(), "open_failure_issue.py must exist in scripts/"

    def test_script_importable(self):
        mod = _load_script()
        assert hasattr(mod, "main")
        assert hasattr(mod, "issue_exists_for_run")
        assert hasattr(mod, "create_issue")


class TestIssueExistsForRun:
    """Test the dedup logic: issue_exists_for_run."""

    def test_returns_true_when_issue_found(self):
        mod = _load_script()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "total_count": 1,
            "items": [{"id": 123, "title": "CI failure: Test"}]
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = mod.issue_exists_for_run(
                "fake-token", "owner/repo", "12345",
                "https://github.com/owner/repo/actions/runs/12345"
            )

        assert result is True
        req = mock_urlopen.call_args[0][0]
        assert '%2A%2ARun+ID%3A%2A%2A+12345' in req.full_url

    def test_returns_false_when_no_issue_found(self):
        mod = _load_script()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "total_count": 0,
            "items": []
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = mod.issue_exists_for_run(
                "fake-token", "owner/repo", "12345",
                "https://github.com/owner/repo/actions/runs/12345"
            )

        assert result is False

    def test_returns_true_on_api_error_fail_closed(self):
        """On search failure (e.g. 403), return True to prevent duplicate issues."""
        mod = _load_script()
        import urllib.error
        error = urllib.error.HTTPError(
            "https://api.github.com/search/issues",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"message": "rate limited"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = mod.issue_exists_for_run(
                "fake-token", "owner/repo", "12345",
                "https://github.com/owner/repo/actions/runs/12345"
            )

        assert result is True


class TestCreateIssue:
    """Test the issue creation logic."""

    def test_creates_issue_successfully(self):
        mod = _load_script()
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.read.return_value = json.dumps({
            "id": 999,
            "html_url": "https://github.com/owner/repo/issues/1"
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = mod.create_issue(
                "fake-token",
                "owner/repo",
                "Test Workflow",
                "12345",
                "https://github.com/owner/repo/actions/runs/12345",
            )

        assert result is True
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.method == "POST"
        body = json.loads(req.data.decode())
        assert "Test Workflow" in body["title"]
        assert "12345" in body["body"]
        assert "https://github.com/owner/repo/actions/runs/12345" in body["body"]

    def test_returns_false_on_failure(self):
        mod = _load_script()
        import urllib.error
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/owner/repo/issues",
            422,
            "Validation Failed",
            {},
            io.BytesIO(b'{"message": "Validation Failed"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = mod.create_issue(
                "fake-token",
                "owner/repo",
                "Test Workflow",
                "12345",
                "https://github.com/owner/repo/actions/runs/12345",
            )

        assert result is False


class TestMain:
    """Test the main entry point."""

    def test_fails_without_env_vars(self):
        mod = _load_script()
        env = {}
        with patch.dict(os.environ, env, clear=True):
            result = mod.main()
        assert result == 1

    def test_skips_when_issue_already_exists(self):
        mod = _load_script()
        env = {
            "GITHUB_TOKEN": "fake-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "WORKFLOW_NAME": "Test Workflow",
            "RUN_ID": "12345",
            "RUN_URL": "https://github.com/owner/repo/actions/runs/12345",
        }
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "total_count": 1,
            "items": [{"id": 123}]
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, env, clear=True):
            with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
                result = mod.main()

        assert result == 0
        assert mock_urlopen.call_count == 1

    def test_creates_issue_when_not_exists(self):
        mod = _load_script()
        env = {
            "GITHUB_TOKEN": "fake-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "WORKFLOW_NAME": "Test Workflow",
            "RUN_ID": "12345",
            "RUN_URL": "https://github.com/owner/repo/actions/runs/12345",
        }
        search_response = MagicMock()
        search_response.status = 200
        search_response.read.return_value = json.dumps({
            "total_count": 0,
            "items": []
        }).encode()
        search_response.__enter__ = MagicMock(return_value=search_response)
        search_response.__exit__ = MagicMock(return_value=False)

        create_response = MagicMock()
        create_response.status = 201
        create_response.read.return_value = json.dumps({
            "id": 999,
            "html_url": "https://github.com/owner/repo/issues/1"
        }).encode()
        create_response.__enter__ = MagicMock(return_value=create_response)
        create_response.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, env, clear=True):
            with patch("urllib.request.urlopen", side_effect=[search_response, create_response]) as mock_urlopen:
                result = mod.main()

        assert result == 0
        assert mock_urlopen.call_count == 2


class TestWorkflowIntegration:
    """Test that the workflow file exists and references the script."""

    def test_workflow_file_exists(self):
        workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "open-failure-issue.yml"
        assert workflow_path.exists(), "open-failure-issue.yml workflow must exist"

    def test_workflow_references_script(self):
        workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "open-failure-issue.yml"
        content = workflow_path.read_text()
        assert "open_failure_issue.py" in content
        assert "workflow_run" in content
        assert "failure" in content

    def test_listener_includes_journalism_publish_exact_name(self):
        """Listener must use the exact name from journalism-publish.yml."""
        import re
        repo_root = Path(__file__).parent.parent
        journalism_path = repo_root / ".github" / "workflows" / "journalism-publish.yml"
        listener_path = repo_root / ".github" / "workflows" / "open-failure-issue.yml"

        journalism_content = journalism_path.read_text()
        match = re.search(r'^name:\s*(.+)$', journalism_content, re.MULTILINE)
        assert match, "journalism-publish.yml must have a name: field"
        exact_name = match.group(1).strip()

        listener_content = listener_path.read_text()
        assert exact_name in listener_content, (
            f"Listener must include exact journalism name {exact_name!r}"
        )


class TestSuccessDoesNotCreateIssue:
    """Verify success runs would not trigger issue creation.
    
    The workflow uses `if: github.event.workflow_run.conclusion == 'failure'`
    so success runs never reach the script. This test verifies the workflow
    config contains this guard.
    """

    def test_workflow_only_runs_on_failure(self):
        workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "open-failure-issue.yml"
        content = workflow_path.read_text()
        assert "conclusion == 'failure'" in content or "conclusion=='failure'" in content
