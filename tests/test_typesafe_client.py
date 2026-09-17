"""Offline tests for src/typesafe_client.py.

All HTTP is stubbed. These tests never call api.typesafe.ai.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from typesafe_client import (
    TypeSafeClient,
    TypeSafeError,
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


def _client(payload, status_code=200):
    def _post(*_args, **_kwargs):
        return _FakeResponse(status_code=status_code, payload=payload)

    return TypeSafeClient(
        api_key="test-key",
        model="jev-latest",
        post=_post,
    )


def test_evaluate_parses_noul_and_choice():
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
    result = _client(payload).evaluate({"headline": "x"}, {"newsworthy": {"type": "noul"}})
    assert result.model == "jev-1.13.0"
    assert result.noul("newsworthy") == pytest.approx(0.88)
    chosen, confidence, probs = result.choice("same_event")
    assert chosen == "novel"
    assert confidence == pytest.approx(0.91)
    assert probs["novel"] == pytest.approx(0.91)


def test_evaluate_401_raises():
    with pytest.raises(TypeSafeError, match="401"):
        _client({}, status_code=401).evaluate({"headline": "x"}, {"q": {"type": "noul"}})


def test_same_event_skips_only_at_high_confidence(capsys):
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
        _client(payload),
        "Congress averts shutdown with appropriations vote",
        seen,
        confidence_threshold=0.85,
        story_id="cand-1",
    )
    assert verdict.is_duplicate is True
    assert verdict.matched_story_id == "2026-09-01-senate-vote-aaa"
    out = capsys.readouterr().out
    assert "l4_same_event action=skip_duplicate" in out
    assert "matched=2026-09-01-senate-vote-aaa" in out
    assert '"kind": "l4_same_event"' in out


def test_same_event_low_confidence_fails_open(capsys):
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
        _client(payload),
        "Trump fires Iran envoy",
        [("2026-09-01-iran-talks-bbb", "Iran deal talks resume")],
        confidence_threshold=0.85,
    )
    assert verdict.is_duplicate is False
    assert verdict.matched_story_id == ""
    assert "action=low_confidence_keep" in capsys.readouterr().out


def test_same_event_novel_keeps(capsys):
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
        _client(payload),
        "SCOTUS voting-rights ruling",
        [("2026-09-01-abortion-ccc", "SCOTUS abortion ruling")],
    )
    assert verdict.is_duplicate is False
    assert "action=keep_novel" in capsys.readouterr().out


def test_same_event_error_fails_open_and_logs(capsys):
    def _boom(*_a, **_k):
        raise RuntimeError("network down")

    client = TypeSafeClient(api_key="test-key", post=_boom)
    verdict = judge_same_event(
        client,
        "Any headline",
        [("sid", "Already covered")],
    )
    assert verdict.is_duplicate is False
    assert verdict.engine == "error"
    out = capsys.readouterr().out
    assert "action=fail_open" in out
    assert "engine=error" in out


def test_relevance_keeps_and_drops(capsys):
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
        _client(payload),
        "Senate passes appropriations bill",
        articles,
        noul_threshold=0.50,
    )
    assert flags == [True, False]
    out = capsys.readouterr().out
    assert "kind=relevance" in out or "relevance action=" in out
    assert "keep=[True, False]" in out


def test_relevance_error_returns_none_for_haiku_fallback(capsys):
    flags = judge_article_relevance(
        _client({}, status_code=500),
        "Headline",
        [SimpleNamespace(outlet="AP", title="t", body="b")],
    )
    assert flags is None
    assert "action=fallback_haiku" in capsys.readouterr().out


def test_brief_worth_skips_gossip(capsys):
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
    verdict = judge_brief_worth(_client(payload), dossier)
    assert verdict.proceed is False
    assert verdict.skip_reason == "gossip_high_world_change_low"
    out = capsys.readouterr().out
    assert "action=skip_opus" in out
    assert "skip_reason=gossip_high_world_change_low" in out


def test_brief_worth_proceeds_on_news(capsys):
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
    verdict = judge_brief_worth(_client(payload), dossier)
    assert verdict.proceed is True
    assert verdict.skip_reason == ""
    assert "action=proceed_opus" in capsys.readouterr().out


def test_brief_worth_error_proceeds(capsys):
    dossier = SimpleNamespace(
        story_id="s3",
        headline_seed="Anything",
        articles=[],
        primary_sources=[],
    )
    verdict = judge_brief_worth(_client({}, status_code=429), dossier)
    assert verdict.proceed is True
    assert verdict.engine == "error"
    assert "action=fail_open_proceed" in capsys.readouterr().out


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


def test_source_gatherer_uses_jev_for_borderline(monkeypatch, capsys):
    from source_gatherer import SourceGatherer

    payload = {
        "model": "jev-latest",
        "answers": {"article_0": {"noul": 0.11}},
        "usage": {},
    }
    gatherer = SourceGatherer(
        news_fetcher=None,
        typesafe_client=_client(payload),
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
    assert "relevance action=" in capsys.readouterr().out


def test_source_gatherer_falls_back_to_haiku_when_jev_errors(monkeypatch, capsys):
    from source_gatherer import SourceGatherer

    gatherer = SourceGatherer(
        news_fetcher=None,
        typesafe_client=_client({}, status_code=500),
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
    assert "action=fallback_haiku" in capsys.readouterr().out
