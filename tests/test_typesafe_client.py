"""Offline tests for src/typesafe_client.py.

All HTTP is stubbed. These tests never call api.typesafe.ai.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from typesafe_client import (
    TypeSafeClient,
    TypeSafeError,
    append_typesafe_decision,
    judge_article_relevance,
    judge_brief_worth,
    judge_same_event,
    typesafe_config,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _client(payload, log_path, status_code=200):
    def _post(*_args, **_kwargs):
        return _FakeResponse(status_code=status_code, payload=payload)

    return TypeSafeClient(
        api_key="test-key",
        model="jev-latest",
        post=_post,
        log_path=str(log_path),
    )


def _read_log(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def test_evaluate_parses_noul_and_choice(tmp_path):
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "same_event": {
                "choice": "novel",
                "confidence": 0.91,
                "probabilities": {"novel": 0.91, "seen_00": 0.09},
            },
            "newsworthy": {"noul": 0.88},
        },
        "usage": {"input_tokens": 40, "output_tokens": 8},
    }
    client = _client(payload, tmp_path / "log.jsonl")
    result = client.evaluate({"headline": "x"}, {"newsworthy": {"type": "noul"}})
    assert result.model == "jev-1.13.0"
    assert result.noul("newsworthy") == pytest.approx(0.88)
    chosen, confidence, probs = result.choice("same_event")
    assert chosen == "novel"
    assert confidence == pytest.approx(0.91)
    assert probs["novel"] == pytest.approx(0.91)


def test_evaluate_401_raises(tmp_path):
    client = _client({}, tmp_path / "log.jsonl", status_code=401)
    with pytest.raises(TypeSafeError, match="401"):
        client.evaluate({"headline": "x"}, {"q": {"type": "noul"}})


def test_same_event_skips_only_at_high_confidence(tmp_path):
    log = tmp_path / "log.jsonl"
    seen = [("2026-09-01-senate-vote-aaa", "Senate passes spending bill")]
    payload = {
        "model": "jev-latest",
        "answers": {
            "same_event": {
                "choice": "seen_00",
                "confidence": 0.92,
                "probabilities": {"seen_00": 0.92, "novel": 0.08},
            }
        },
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }
    verdict = judge_same_event(
        _client(payload, log),
        "Congress averts shutdown with appropriations vote",
        seen,
        confidence_threshold=0.85,
        story_id="cand-1",
    )
    assert verdict.is_duplicate is True
    assert verdict.matched_story_id == "2026-09-01-senate-vote-aaa"
    row = _read_log(log)[0]
    assert row["kind"] == "l4_same_event"
    assert row["action"] == "skip_duplicate"
    assert row["matched_story_id"] == "2026-09-01-senate-vote-aaa"
    assert "ts" in row


def test_same_event_low_confidence_fails_open(tmp_path):
    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {
            "same_event": {
                "choice": "seen_00",
                "confidence": 0.61,
                "probabilities": {"seen_00": 0.61, "novel": 0.39},
            }
        },
        "usage": {},
    }
    verdict = judge_same_event(
        _client(payload, log),
        "Trump fires Iran envoy",
        [("2026-09-01-iran-talks-bbb", "Iran deal talks resume")],
        confidence_threshold=0.85,
    )
    assert verdict.is_duplicate is False
    assert verdict.matched_story_id == ""
    assert _read_log(log)[0]["action"] == "low_confidence_keep"


def test_same_event_novel_keeps(tmp_path):
    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {
            "same_event": {
                "choice": "novel",
                "confidence": 0.94,
                "probabilities": {"novel": 0.94, "seen_00": 0.06},
            }
        },
        "usage": {},
    }
    verdict = judge_same_event(
        _client(payload, log),
        "SCOTUS voting-rights ruling",
        [("2026-09-01-abortion-ccc", "SCOTUS abortion ruling")],
    )
    assert verdict.is_duplicate is False
    assert _read_log(log)[0]["action"] == "keep_novel"


def test_same_event_error_fails_open_and_logs(tmp_path):
    log = tmp_path / "log.jsonl"

    def _boom(*_a, **_k):
        raise RuntimeError("network down")

    client = TypeSafeClient(
        api_key="test-key", post=_boom, log_path=str(log)
    )
    verdict = judge_same_event(
        client,
        "Any headline",
        [("sid", "Already covered")],
    )
    assert verdict.is_duplicate is False
    assert verdict.engine == "error"
    row = _read_log(log)[0]
    assert row["action"] == "fail_open"
    assert row["engine"] == "error"


def test_relevance_keeps_and_drops(tmp_path):
    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {
            "article_0": {"noul": 0.81},
            "article_1": {"noul": 0.12},
        },
        "usage": {"input_tokens": 80, "output_tokens": 6},
    }
    articles = [
        SimpleNamespace(outlet="Reuters", title="Senate vote", body="The Senate voted 68-32."),
        SimpleNamespace(outlet="USA Today", title="Celebrity gossip", body="A singer posted a selfie."),
    ]
    flags = judge_article_relevance(
        _client(payload, log),
        "Senate passes appropriations bill",
        articles,
        noul_threshold=0.50,
    )
    assert flags == [True, False]
    row = _read_log(log)[0]
    assert row["kind"] == "relevance"
    assert row["nouls"]["article_0"] == pytest.approx(0.81)
    assert row["keep"] == [True, False]


def test_relevance_error_returns_none_for_haiku_fallback(tmp_path):
    log = tmp_path / "log.jsonl"
    client = _client({}, log, status_code=500)
    flags = judge_article_relevance(
        client,
        "Headline",
        [SimpleNamespace(outlet="AP", title="t", body="b")],
    )
    assert flags is None
    assert _read_log(log)[0]["action"] == "fallback_haiku"


def test_brief_worth_skips_gossip(tmp_path):
    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {
            "genuine_world_change": {"noul": 0.20},
            "checkable": {"noul": 0.40},
            "gossip_or_vibe": {"noul": 0.91},
            "thin_or_offtopic": {"noul": 0.30},
        },
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }
    dossier = SimpleNamespace(
        story_id="s1",
        headline_seed="Celebrity couple spotted at brunch",
        articles=[
            SimpleNamespace(outlet="UsWeekly", title="Brunch", body="They ate eggs."),
        ],
        primary_sources=[],
    )
    verdict = judge_brief_worth(_client(payload, log), dossier)
    assert verdict.proceed is False
    assert verdict.skip_reason == "gossip_high_world_change_low"
    row = _read_log(log)[0]
    assert row["action"] == "skip_opus"
    assert row["skip_reason"] == "gossip_high_world_change_low"


def test_brief_worth_proceeds_on_news(tmp_path):
    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {
            "genuine_world_change": {"noul": 0.90},
            "checkable": {"noul": 0.88},
            "gossip_or_vibe": {"noul": 0.08},
            "thin_or_offtopic": {"noul": 0.10},
        },
        "usage": {},
    }
    dossier = SimpleNamespace(
        story_id="s2",
        headline_seed="Senate voted 68-32 on appropriations",
        articles=[
            SimpleNamespace(outlet="Reuters", title="Senate vote", body="The Senate voted."),
            SimpleNamespace(outlet="AP", title="Spending bill", body="The bill passed."),
        ],
        primary_sources=[],
    )
    verdict = judge_brief_worth(_client(payload, log), dossier)
    assert verdict.proceed is True
    assert verdict.skip_reason == ""
    assert _read_log(log)[0]["action"] == "proceed_opus"


def test_brief_worth_error_proceeds(tmp_path):
    log = tmp_path / "log.jsonl"
    client = _client({}, log, status_code=429)
    dossier = SimpleNamespace(
        story_id="s3",
        headline_seed="Anything",
        articles=[],
        primary_sources=[],
    )
    verdict = judge_brief_worth(client, dossier)
    assert verdict.proceed is True
    assert verdict.engine == "error"


def test_append_typesafe_decision_is_nonfatal(tmp_path):
    dest = tmp_path / "nested" / "log.jsonl"
    append_typesafe_decision({"kind": "manual", "action": "probe"}, path=str(dest))
    rows = _read_log(dest)
    assert rows[0]["kind"] == "manual"
    assert rows[0]["action"] == "probe"
    assert rows[0]["ts"]


def test_typesafe_config_defaults():
    cfg = typesafe_config({})
    assert cfg["enabled"] is True
    assert cfg["model"] == "jev-latest"
    assert cfg["same_event_confidence"] == pytest.approx(0.85)


@dataclass
class _Article:
    outlet: str
    url: str
    title: str
    body: str
    fetched_at: str = "2026-09-17T00:00:00+00:00"
    is_wire_derived: bool = False
    headline_only: bool = False


def test_source_gatherer_uses_jev_for_borderline(tmp_path, monkeypatch):
    from source_gatherer import SourceGatherer

    log = tmp_path / "log.jsonl"
    payload = {
        "model": "jev-latest",
        "answers": {"article_0": {"noul": 0.11}},
        "usage": {},
    }
    gatherer = SourceGatherer(
        news_fetcher=None,
        typesafe_client=_client(payload, log),
        typesafe_cfg={"relevance_noul": 0.50, "max_borderline": 12},
    )
    monkeypatch.setattr(gatherer, "_extract_headline_nouns", lambda _h: {"d4vd", "celeste", "hernandez"})
    articles = [
        _Article(
            outlet="DW",
            url="https://example.com/music",
            title="Music industry news",
            body="D4vd has been trending worldwide after recent events.",
        )
    ]
    kept = gatherer._filter_relevant_articles(
        articles, "Singer D4vd arrested for murder of Celeste Rivas Hernandez"
    )
    assert kept == []
    assert _read_log(log)[0]["kind"] == "relevance"


def test_typesafe_review_summarises_skips(tmp_path):
    sys_path_scripts = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    )
    if sys_path_scripts not in sys.path:
        sys.path.insert(0, sys_path_scripts)
    import typesafe_review

    log = tmp_path / "typesafe_decisions.jsonl"
    rows = [
        {
            "ts": "2026-09-17T12:00:00+00:00",
            "kind": "l4_same_event",
            "action": "skip_duplicate",
            "engine": "jev",
            "headline": "Senate vote",
            "confidence": 0.93,
            "matched_story_id": "sid-1",
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
        {
            "ts": "2026-09-17T12:01:00+00:00",
            "kind": "brief_worth",
            "action": "proceed_opus",
            "engine": "jev",
            "nouls": {"genuine_world_change": 0.9, "checkable": 0.8,
                      "gossip_or_vibe": 0.1, "thin_or_offtopic": 0.1},
            "usage": {"input_tokens": 20, "output_tokens": 4},
        },
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    summary = typesafe_review.summarise(typesafe_review.load_decisions(log, since))
    assert summary["n"] == 2
    assert summary["by_kind"]["l4_same_event"] == 1
    assert len(summary["skips"]) == 1
    markdown = typesafe_review.render(summary, 7)
    assert "skip_duplicate" in markdown
    assert "Senate vote" in markdown


def test_source_gatherer_falls_back_to_haiku_when_jev_errors(tmp_path, monkeypatch):
    from source_gatherer import SourceGatherer

    log = tmp_path / "log.jsonl"
    gatherer = SourceGatherer(
        news_fetcher=None,
        typesafe_client=_client({}, log, status_code=500),
        typesafe_cfg={"relevance_noul": 0.50},
    )
    monkeypatch.setattr(gatherer, "_extract_headline_nouns", lambda _h: {"d4vd", "celeste", "hernandez"})
    monkeypatch.setattr(gatherer, "_haiku_relevance_check", lambda *_a, **_k: True)
    articles = [
        _Article(
            outlet="DW",
            url="https://example.com/music",
            title="Music industry news",
            body="D4vd has been trending worldwide after recent events.",
        )
    ]
    kept = gatherer._filter_relevant_articles(
        articles, "Singer D4vd arrested for murder of Celeste Rivas Hernandez"
    )
    assert len(kept) == 1
    assert _read_log(log)[0]["action"] == "fallback_haiku"
