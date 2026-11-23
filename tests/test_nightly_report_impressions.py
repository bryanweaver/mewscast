"""Nightly report must not treat a missing impressions field as zero.

X public_metrics include impression_count. Those counts land in
docs/x_engagement.json. analytics_history snapshots for Bluesky never
have the field, and recent X posts often have no snapshot there at all.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_script():
    script_path = Path(__file__).parent.parent / "scripts" / "nightly_report.py"
    spec = importlib.util.spec_from_file_location("nightly_report_impressions", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def report():
    return _load_script()


class TestImpressionAbsence:
    def test_missing_field_is_not_zero(self, report):
        likes, reposts, replies, impressions = report.latest_snapshot_total([
            {"likes": 3, "reposts": 1, "replies": 1},
        ])
        assert (likes, reposts, replies) == (3, 1, 1)
        assert impressions is None

    def test_stored_zero_stays_zero(self, report):
        _, _, _, impressions = report.latest_snapshot_total([
            {"likes": 0, "reposts": 0, "replies": 0, "impressions": 0},
        ])
        assert impressions == 0

    def test_x_engagement_fallback_keeps_real_impressions(self, report):
        counts = report.resolve_platform_counts(
            {},
            {"2113730934981763156": {
                "likes": 1, "reposts": 0, "replies": 1, "impressions": 13,
            }},
            "x:2113730934981763156",
            "x",
            "2113730934981763156",
        )
        assert counts == (1, 0, 1, 13)

    def test_bluesky_without_field_stays_unmeasured(self, report):
        counts = report.resolve_platform_counts(
            {"at://bsky": {"snapshots": [{"likes": 3, "reposts": 1, "replies": 1}]}},
            {},
            "at://bsky",
            "bluesky",
            None,
        )
        assert counts == (3, 1, 1, None)

    def test_add_impressions_ignores_none(self, report):
        assert report.add_impressions(None, None) is None
        assert report.add_impressions(None, 13) == 13
        assert report.add_impressions(13, None) == 13
        assert report.add_impressions(13, 0) == 13

    def test_average_skips_unmeasured_impressions(self, report):
        items = [
            {"likes": 1, "impressions": 13, "engagement": 1},
            {"likes": 3, "impressions": None, "engagement": 4},
        ]
        assert report.avg(items, "impressions") == 13
        assert report.fmt_avg(items, "impressions") == "13.00"
        assert report.fmt_avg([{"impressions": None}], "impressions") == "n/a"


class TestReportText:
    def test_report_uses_x_engagement_and_says_when_unmeasured(self, report, tmp_path):
        reports_dir = tmp_path / "docs" / "reports"
        reports_dir.mkdir(parents=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "x_engagement.json").write_text(json.dumps({
            "posts": [{
                "x_tweet_id": "2113730934981763156",
                "likes": 1,
                "reposts": 0,
                "replies": 1,
                "impressions": 13,
            }],
        }), encoding="utf-8")

        posts = {
            "posts": [{
                "timestamp": "2026-10-23T20:35:01.227230+00:00",
                "post_pipeline": "journalism",
                "post_type": "REPORT",
                "source": "NBC News",
                "topic": "Canada tariffs",
                "content": "Trump granted tariff exemptions. And that's the mews.",
                "x_tweet_id": "2113730934981763156",
                "bluesky_uri": "at://did/post/1",
            }],
        }
        analytics = {
            "posts": {
                "at://did/post/1": {
                    "platform": "bluesky",
                    "snapshots": [{"likes": 3, "reposts": 1, "replies": 1}],
                },
            },
            "follower_history": {"x": [], "bluesky": []},
            "last_updated": "2026-10-24T01:13:05.969183+00:00",
        }

        def fake_load(name):
            if "posts_history" in name:
                return posts
            if "analytics_history" in name:
                return analytics
            raise FileNotFoundError(name)

        # Freeze the report clock so the fixture post is inside the 24h window.
        from datetime import datetime, timedelta, timezone
        frozen = datetime(2026, 10, 24, 1, 13, tzinfo=timezone.utc)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(report, "load", fake_load)
            mp.setattr(report, "ROOT", str(tmp_path))
            mp.setattr(report, "NOW", frozen)
            mp.setattr(report, "CUTOFF_24H", frozen - timedelta(hours=24))
            mp.setattr(report, "CUTOFF_7D", frozen - timedelta(days=7))
            mp.setattr(report, "SIX_HOURS_AGO", frozen - timedelta(hours=6))
            report.main()

        text = (reports_dir / "latest.md").read_text(encoding="utf-8")
        # X 1 like + Bluesky 3 likes; X impressions 13; Bluesky field omitted.
        assert "4 likes / 1 reposts / 2 replies / 13 impressions" in text
        assert "Impr:13" in text
        assert "Impr:not measured" in text
        assert "not counted as zero" in text
        assert "docs/x_engagement.json" in text
