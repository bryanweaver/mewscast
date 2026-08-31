#!/usr/bin/env python3
"""Open a GitHub issue for a failed workflow run.

Uses only stdlib (urllib, json). Expects environment variables:
  GITHUB_TOKEN       - PAT or GITHUB_TOKEN with issues:write
  GITHUB_REPOSITORY  - owner/repo
  WORKFLOW_NAME      - name of the failed workflow
  RUN_ID             - numeric run ID
  RUN_URL            - full URL to the run (html_url)

Exits 0 if issue created or already exists, non-zero on error.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _gh_request(
    method: str,
    url: str,
    token: str,
    data: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any]]:
    """Make a GitHub API request. Returns (status_code, parsed_json)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode() if data else None
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()) if e.fp else {}


def issue_exists_for_run(token: str, repo: str, run_id: str, run_url: str) -> bool:
    """Search open+closed issues for one mentioning this run URL.
    
    Returns True if an issue exists OR if search fails (fail closed to
    prevent duplicates on API errors like 403 rate limit).
    """
    query = f'repo:{repo} "**Run ID:** {run_id}" in:body'
    url = (
        "https://api.github.com/search/issues?"
        + urllib.parse.urlencode({"q": query, "per_page": "5"})
    )
    status, data = _gh_request("GET", url, token)
    if status != 200:
        print(f"[open_failure_issue] search failed: {status} {data}, skipping create")
        return True
    items = data.get("items", []) if isinstance(data, dict) else []
    return len(items) > 0


def create_issue(
    token: str,
    repo: str,
    workflow_name: str,
    run_id: str,
    run_url: str,
) -> bool:
    """Create a GitHub issue for the failed run. Returns True on success."""
    title = f"CI failure: {workflow_name}"
    body = (
        f"**Workflow:** {workflow_name}\n"
        f"**Run ID:** {run_id}\n"
        f"**Run URL:** {run_url}\n\n"
        "This issue was automatically opened by the failure-issue workflow."
    )
    url = f"https://api.github.com/repos/{repo}/issues"
    status, data = _gh_request("POST", url, token, {"title": title, "body": body})
    if status in (200, 201):
        issue_url = data.get("html_url", "(unknown)")
        print(f"[open_failure_issue] created issue: {issue_url}")
        return True
    print(f"[open_failure_issue] failed to create issue: {status} {data}")
    return False


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_name = os.environ.get("WORKFLOW_NAME", "")
    run_id = os.environ.get("RUN_ID", "")
    run_url = os.environ.get("RUN_URL", "")

    missing = []
    if not token:
        missing.append("GITHUB_TOKEN")
    if not repo:
        missing.append("GITHUB_REPOSITORY")
    if not workflow_name:
        missing.append("WORKFLOW_NAME")
    if not run_id:
        missing.append("RUN_ID")
    if not run_url:
        missing.append("RUN_URL")
    if missing:
        print(f"[open_failure_issue] missing env vars: {', '.join(missing)}")
        return 1

    if issue_exists_for_run(token, repo, run_id, run_url):
        print(f"[open_failure_issue] issue already exists for run {run_id}, skipping")
        return 0

    if create_issue(token, repo, workflow_name, run_id, run_url):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
