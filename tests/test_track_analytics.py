"""Tests for scripts/track_analytics.py follower-snapshot helpers."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_script():
    """Import track_analytics.py without pulling live credentials."""
    sys.modules.setdefault(
        "dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
    )
    script_path = Path(__file__).parent.parent / "scripts" / "track_analytics.py"
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("track_analytics", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def track():
    return _load_script()


class TestUtcDay:
    def test_iso_with_offset(self, track):
        assert track.utc_day("2026-04-12T23:08:04.389609+00:00") == "2026-04-12"

    def test_zulu_suffix(self, track):
        assert track.utc_day("2026-05-04T23:16:48.518179Z") == "2026-05-04"

    def test_empty(self, track):
        assert track.utc_day("") is None
        assert track.utc_day(None) is None


class TestUpsertFollowerSnapshot:
    def test_appends_to_empty_list(self, track):
        snap = {"timestamp": "2026-05-04T23:00:00+00:00", "followers": 58}
        out = track.upsert_follower_snapshot([], snap)
        assert out == [snap]

    def test_replaces_last_snapshot_on_same_utc_day(self, track):
        existing = [
            {"timestamp": "2026-04-12T02:23:28+00:00", "followers": 45},
            {"timestamp": "2026-04-12T13:08:19+00:00", "followers": 49},
        ]
        newest = {"timestamp": "2026-04-12T23:08:04+00:00", "followers": 54}
        out = track.upsert_follower_snapshot(existing, newest)
        assert out[-1] == newest
        assert out[-1]["followers"] == 54
        assert len(out) == 2  # replaced last only; earlier same-day row kept

    def test_appends_when_last_snapshot_is_a_different_day(self, track):
        existing = [
            {"timestamp": "2026-05-03T23:13:49+00:00", "followers": 58},
        ]
        newest = {"timestamp": "2026-05-04T23:16:48+00:00", "followers": 58}
        out = track.upsert_follower_snapshot(existing, newest)
        assert len(out) == 2
        assert out[-1] is newest

    def test_does_not_collapse_older_same_day_duplicates(self, track):
        """Historical same-day duplicates stay; only the trailing same-day row is replaced."""
        existing = [
            {"timestamp": "2026-04-12T02:23:28+00:00", "followers": 45},
            {"timestamp": "2026-04-12T02:38:26+00:00", "followers": 45},
            {"timestamp": "2026-04-12T02:40:32+00:00", "followers": 45},
            {"timestamp": "2026-04-12T13:08:19+00:00", "followers": 49},
            {"timestamp": "2026-04-13T23:00:00+00:00", "followers": 55},
        ]
        newest = {"timestamp": "2026-04-14T01:00:00+00:00", "followers": 56}
        out = track.upsert_follower_snapshot(list(existing), newest)
        assert [s["followers"] for s in out] == [45, 45, 45, 49, 55, 56]
        assert len(out) == 6

    def test_treats_none_list_as_empty(self, track):
        snap = {"timestamp": "2026-05-04T23:00:00+00:00", "followers": 58}
        out = track.upsert_follower_snapshot(None, snap)
        assert out == [snap]
