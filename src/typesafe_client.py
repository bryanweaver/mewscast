"""TypeSafe / Jev client for journalism decision hops.

Jev is a judgment layer, not a writer. This module sends one shared state
plus typed questions to System One and returns values Python can threshold.
Claude still writes the brief and the post.

Live HTTP is never called from pytest — tests mock ``TypeSafeClient.evaluate``
or construct a client with a stub ``post`` function. Production fails open:
a missing key, timeout, or unexpected payload never blocks a publish cycle.

Decision rows are appended to ``docs/reports/typesafe_decisions.jsonl`` so
later review can see what Jev returned, which threshold fired, and whether
the hop skipped a story, dropped an article, or let the pipeline continue.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_S = 20
DEFAULT_LOG_RELPATH = os.path.join("docs", "reports", "typesafe_decisions.jsonl")

# Conservative first-wiring thresholds. Auto-skip / auto-drop only when Jev
# is this sure; anything fuzzier falls through (fail-open).
DEFAULT_SAME_EVENT_CONFIDENCE = 0.85
DEFAULT_RELEVANCE_NOUL = 0.50
DEFAULT_BRIEF_WORTH_NOUL = 0.35
DEFAULT_BRIEF_GOSSIP_NOUL = 0.80
DEFAULT_BRIEF_THIN_NOUL = 0.85
DEFAULT_MAX_SEEN_OPTIONS = 40
DEFAULT_MAX_BORDERLINE = 12


class TypeSafeError(Exception):
    """Raised when the System One call fails or the payload is unusable."""


@dataclass
class TypeSafeResult:
    """Parsed System One response."""
    answers: dict
    model: str
    usage: dict
    raw: dict
    elapsed_ms: int

    def noul(self, name: str) -> Optional[float]:
        block = self.answers.get(name) or {}
        if not isinstance(block, dict):
            return None
        value = block.get("noul")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def choice(self, name: str) -> tuple[Optional[str], Optional[float], dict]:
        block = self.answers.get(name) or {}
        if not isinstance(block, dict):
            return None, None, {}
        chosen = block.get("choice")
        confidence = block.get("confidence")
        probabilities = block.get("probabilities") or {}
        if not isinstance(chosen, str):
            chosen = None
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = None
        else:
            confidence = float(confidence)
        if not isinstance(probabilities, dict):
            probabilities = {}
        return chosen, confidence, probabilities


@dataclass
class SameEventVerdict:
    is_duplicate: bool
    matched_story_id: str = ""
    engine: str = "jev"
    choice: Optional[str] = None
    confidence: Optional[float] = None
    probabilities: dict = field(default_factory=dict)
    fallback_reason: str = ""


@dataclass
class BriefWorthVerdict:
    proceed: bool
    engine: str = "jev"
    nouls: dict = field(default_factory=dict)
    skip_reason: str = ""
    fallback_reason: str = ""


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_log_path() -> str:
    override = os.getenv("TYPESAFE_LOG_PATH", "").strip()
    if override:
        return override
    return os.path.join(_project_root(), DEFAULT_LOG_RELPATH)


def typesafe_config(journalism_cfg: Optional[dict] = None) -> dict:
    """Normalize ``journalism.typesafe`` with defaults for missing keys."""
    raw = (journalism_cfg or {}).get("typesafe") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "model": raw.get("model") or DEFAULT_MODEL,
        "same_event_confidence": float(
            raw.get("same_event_confidence", DEFAULT_SAME_EVENT_CONFIDENCE)
        ),
        "relevance_noul": float(raw.get("relevance_noul", DEFAULT_RELEVANCE_NOUL)),
        "brief_worth_noul": float(raw.get("brief_worth_noul", DEFAULT_BRIEF_WORTH_NOUL)),
        "brief_gossip_noul": float(raw.get("brief_gossip_noul", DEFAULT_BRIEF_GOSSIP_NOUL)),
        "brief_thin_noul": float(raw.get("brief_thin_noul", DEFAULT_BRIEF_THIN_NOUL)),
        "max_seen_options": int(raw.get("max_seen_options", DEFAULT_MAX_SEEN_OPTIONS)),
        "max_borderline": int(raw.get("max_borderline", DEFAULT_MAX_BORDERLINE)),
        "timeout_s": int(raw.get("timeout_s", DEFAULT_TIMEOUT_S)),
    }


def append_typesafe_decision(record: dict, path: Optional[str] = None) -> None:
    """Append one JSON line. Failure is non-fatal — never block publish."""
    dest = path or default_log_path()
    try:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        print(f"[typesafe] could not append decision log: {exc}")


def client_from_env(
    model: str = DEFAULT_MODEL,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Optional["TypeSafeClient"]:
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        return None
    return TypeSafeClient(api_key=api_key, model=model, timeout_s=timeout_s)


class TypeSafeClient:
    """Thin ``requests`` wrapper around ``POST /v1/systemone``."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        post: Optional[Callable[..., Any]] = None,
        log_path: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._post = post or requests.post
        self.log_path = log_path

    def evaluate(self, state: Any, questions: dict) -> TypeSafeResult:
        if not questions:
            raise TypeSafeError("no questions supplied")
        payload = {
            "state": state,
            "model": self.model,
            "questions": questions,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        try:
            resp = self._post(
                API_URL, headers=headers, json=payload, timeout=self.timeout_s
            )
        except Exception as exc:
            raise TypeSafeError(f"request failed: {exc}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code == 401:
            raise TypeSafeError("401 unauthorized — key missing or invalid")
        if resp.status_code != 200:
            body = getattr(resp, "text", "") or ""
            raise TypeSafeError(
                f"/v1/systemone returned {resp.status_code}: {body[:240]}"
            )
        try:
            raw = resp.json()
        except Exception as exc:
            raise TypeSafeError(f"unparseable JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise TypeSafeError("response is not an object")
        answers = raw.get("answers") or {}
        if not isinstance(answers, dict):
            raise TypeSafeError("answers is not an object")
        usage = raw.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        return TypeSafeResult(
            answers=answers,
            model=str(raw.get("model") or self.model),
            usage=usage,
            raw=raw,
            elapsed_ms=elapsed_ms,
        )


def _excerpt(text: str, limit: int = 700) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _log_call(
    *,
    kind: str,
    client: TypeSafeClient,
    result: Optional[TypeSafeResult],
    state_summary: dict,
    questions: dict,
    action: str,
    extra: dict,
    error: str = "",
) -> None:
    usage = (result.usage if result else {}) or {}
    record = {
        "kind": kind,
        "engine": "jev" if result is not None else "error",
        "model": result.model if result else client.model,
        "action": action,
        "elapsed_ms": result.elapsed_ms if result else None,
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        },
        "answers": result.answers if result else {},
        "questions": {
            name: {
                "type": (spec or {}).get("type"),
                "instructions": (spec or {}).get("instructions"),
            }
            for name, spec in questions.items()
        },
        "state_summary": state_summary,
        **extra,
    }
    if error:
        record["error"] = error
        record["engine"] = "error"
    append_typesafe_decision(record, path=client.log_path)
    print(
        f"[typesafe] {kind} action={action} model={record['model']} "
        f"elapsed_ms={record['elapsed_ms']} "
        f"tokens={usage.get('input_tokens')}/{usage.get('output_tokens')}"
        + (f" error={error}" if error else "")
    )


def judge_same_event(
    client: TypeSafeClient,
    candidate_headline: str,
    recent_seen: list[tuple[str, str]],
    *,
    confidence_threshold: float = DEFAULT_SAME_EVENT_CONFIDENCE,
    max_seen_options: int = DEFAULT_MAX_SEEN_OPTIONS,
    story_id: str = "",
) -> SameEventVerdict:
    """L4 same-event Choice: recent story_ids + ``novel``.

    Skip (treat as duplicate) only when Jev picks a seen option with
    confidence at or above ``confidence_threshold``. Low confidence and
    API errors fail open — same as the old Haiku hop.
    """
    if not recent_seen:
        return SameEventVerdict(
            is_duplicate=False, engine="skipped", fallback_reason="no_seen"
        )

    capped = list(recent_seen[-max_seen_options:])
    option_to_sid: dict[str, str] = {}
    already_covered: list[dict] = []
    criteria: dict[str, str] = {
        "novel": (
            "A different news event from every already-covered story, "
            "even if the same people, institutions, or topic appear."
        ),
    }
    for idx, (sid, headline) in enumerate(capped):
        key = f"seen_{idx:02d}"
        option_to_sid[key] = sid
        already_covered.append({"id": key, "story_id": sid, "headline": headline})
        criteria[key] = headline or sid

    state = {
        "candidate": candidate_headline,
        "already_covered": already_covered,
    }
    questions = {
        "same_event": {
            "type": "choice",
            "instructions": (
                "Which already-covered story is the same news event as "
                "`candidate`, regardless of wording, outlet, or angle? "
                "Choose `novel` if `candidate` is a different event."
            ),
            "criteria": criteria,
        }
    }
    extra = {
        "story_id": story_id,
        "headline": (candidate_headline or "")[:280],
        "seen_count": len(capped),
        "threshold": confidence_threshold,
    }
    try:
        result = client.evaluate(state, questions)
    except TypeSafeError as exc:
        _log_call(
            kind="l4_same_event",
            client=client,
            result=None,
            state_summary={"candidate": (candidate_headline or "")[:280],
                           "seen_count": len(capped)},
            questions=questions,
            action="fail_open",
            extra=extra,
            error=str(exc),
        )
        return SameEventVerdict(
            is_duplicate=False,
            engine="error",
            fallback_reason=str(exc),
        )

    chosen, confidence, probabilities = result.choice("same_event")
    matched_sid = option_to_sid.get(chosen or "", "")
    is_dup = bool(
        chosen
        and chosen != "novel"
        and matched_sid
        and confidence is not None
        and confidence >= confidence_threshold
    )
    if chosen and chosen != "novel" and matched_sid and not is_dup:
        action = "low_confidence_keep"
    elif is_dup:
        action = "skip_duplicate"
    else:
        action = "keep_novel"

    extra.update({
        "choice": chosen,
        "confidence": confidence,
        "matched_story_id": matched_sid,
        "probabilities": probabilities,
    })
    _log_call(
        kind="l4_same_event",
        client=client,
        result=result,
        state_summary={
            "candidate": (candidate_headline or "")[:280],
            "seen_count": len(capped),
            "seen_story_ids": [sid for sid, _ in capped],
        },
        questions=questions,
        action=action,
        extra=extra,
    )
    return SameEventVerdict(
        is_duplicate=is_dup,
        matched_story_id=matched_sid if is_dup else "",
        engine="jev",
        choice=chosen,
        confidence=confidence,
        probabilities=probabilities,
    )


def judge_article_relevance(
    client: TypeSafeClient,
    headline: str,
    articles: list[Any],
    *,
    noul_threshold: float = DEFAULT_RELEVANCE_NOUL,
    max_borderline: int = DEFAULT_MAX_BORDERLINE,
    story_id: str = "",
) -> Optional[list[bool]]:
    """One Noul per borderline article. Returns None on error (Haiku fallback)."""
    if not articles:
        return []

    batch = list(articles[:max_borderline])
    overflow_keep = [True] * max(0, len(articles) - len(batch))
    article_state: list[dict] = []
    questions: dict[str, dict] = {}
    for idx, article in enumerate(batch):
        qname = f"article_{idx}"
        title = getattr(article, "title", "") or ""
        outlet = getattr(article, "outlet", "") or ""
        body = getattr(article, "body", "") or ""
        article_state.append({
            "id": qname,
            "outlet": outlet,
            "title": title,
            "excerpt": _excerpt(f"{title}\n{body}", 900),
        })
        questions[qname] = {
            "type": "noul",
            "instructions": (
                f"Is `articles` item `{qname}` about the same news story as "
                f"`headline`, not merely the same topic or a related sidebar?"
            ),
        }
    state = {"headline": headline, "articles": article_state}
    extra = {
        "story_id": story_id,
        "headline": (headline or "")[:280],
        "article_count": len(articles),
        "scored_count": len(batch),
        "threshold": noul_threshold,
        "outlets": [getattr(a, "outlet", "") for a in batch],
        "titles": [(getattr(a, "title", "") or "")[:120] for a in batch],
    }
    try:
        result = client.evaluate(state, questions)
    except TypeSafeError as exc:
        _log_call(
            kind="relevance",
            client=client,
            result=None,
            state_summary={"headline": (headline or "")[:280],
                           "article_count": len(articles)},
            questions=questions,
            action="fallback_haiku",
            extra=extra,
            error=str(exc),
        )
        return None

    keep: list[bool] = []
    nouls: dict[str, Optional[float]] = {}
    for idx in range(len(batch)):
        qname = f"article_{idx}"
        value = result.noul(qname)
        nouls[qname] = value
        # Missing noul fails open (keep). Explicit low noul drops.
        keep.append(value is None or value >= noul_threshold)

    extra.update({"nouls": nouls, "keep": keep})
    dropped = sum(1 for flag in keep if not flag)
    _log_call(
        kind="relevance",
        client=client,
        result=result,
        state_summary={
            "headline": (headline or "")[:280],
            "article_count": len(articles),
            "scored_count": len(batch),
            "outlets": extra["outlets"],
        },
        questions=questions,
        action=f"scored keep={len(keep) - dropped} drop={dropped}",
        extra=extra,
    )
    return keep + overflow_keep


def judge_brief_worth(
    client: TypeSafeClient,
    dossier: Any,
    *,
    worth_threshold: float = DEFAULT_BRIEF_WORTH_NOUL,
    gossip_threshold: float = DEFAULT_BRIEF_GOSSIP_NOUL,
    thin_threshold: float = DEFAULT_BRIEF_THIN_NOUL,
) -> BriefWorthVerdict:
    """Pre-Opus gate: skip a wasted brief only on a high-confidence no.

    Atomic nouls are combined in code:
      skip if gossip is high AND world-change is low
      OR thin/off-topic is high AND checkable is low
    Any missing noul or API error proceeds to Opus.
    """
    articles = list(getattr(dossier, "articles", None) or [])
    primaries = list(getattr(dossier, "primary_sources", None) or [])
    headline = getattr(dossier, "headline_seed", "") or ""
    story_id = getattr(dossier, "story_id", "") or ""
    article_state = []
    for article in articles[:8]:
        article_state.append({
            "outlet": getattr(article, "outlet", "") or "",
            "title": getattr(article, "title", "") or "",
            "excerpt": _excerpt(getattr(article, "body", "") or "", 400),
        })
    state = {
        "headline": headline,
        "article_count": len(articles),
        "outlets": [getattr(a, "outlet", "") for a in articles],
        "articles": article_state,
        "primary_sources": [
            {
                "kind": getattr(p, "kind", "") or "",
                "title": getattr(p, "title", "") or "",
            }
            for p in primaries[:5]
        ],
    }
    questions = {
        "genuine_world_change": {
            "type": "noul",
            "instructions": (
                "Does `headline` plus the collected articles describe a "
                "genuine, checkable change in the world (a vote, ruling, "
                "attack, filing, or similar), not gossip or vibe?"
            ),
        },
        "checkable": {
            "type": "noul",
            "instructions": (
                "Can the core claim be checked against named outlets or a "
                "primary document in this dossier?"
            ),
        },
        "gossip_or_vibe": {
            "type": "noul",
            "instructions": (
                "Is this primarily celebrity gossip, recycled outrage, or "
                "unverified rumor rather than a need-to-know news event?"
            ),
        },
        "thin_or_offtopic": {
            "type": "noul",
            "instructions": (
                "Are the collected articles too thin, contradictory, or "
                "off-topic to support a factual multi-outlet brief?"
            ),
        },
    }
    extra = {
        "story_id": story_id,
        "headline": headline[:280],
        "article_count": len(articles),
        "outlets": state["outlets"],
        "thresholds": {
            "worth": worth_threshold,
            "gossip": gossip_threshold,
            "thin": thin_threshold,
        },
    }
    try:
        result = client.evaluate(state, questions)
    except TypeSafeError as exc:
        _log_call(
            kind="brief_worth",
            client=client,
            result=None,
            state_summary={"headline": headline[:280], "article_count": len(articles)},
            questions=questions,
            action="fail_open_proceed",
            extra=extra,
            error=str(exc),
        )
        return BriefWorthVerdict(
            proceed=True, engine="error", fallback_reason=str(exc)
        )

    nouls = {
        name: result.noul(name)
        for name in (
            "genuine_world_change",
            "checkable",
            "gossip_or_vibe",
            "thin_or_offtopic",
        )
    }
    world = nouls["genuine_world_change"]
    checkable = nouls["checkable"]
    gossip = nouls["gossip_or_vibe"]
    thin = nouls["thin_or_offtopic"]

    skip_reason = ""
    if (
        gossip is not None
        and world is not None
        and gossip >= gossip_threshold
        and world < worth_threshold
    ):
        skip_reason = "gossip_high_world_change_low"
    elif (
        thin is not None
        and checkable is not None
        and thin >= thin_threshold
        and checkable < worth_threshold
    ):
        skip_reason = "thin_high_checkable_low"

    proceed = skip_reason == ""
    extra.update({"nouls": nouls, "skip_reason": skip_reason})
    _log_call(
        kind="brief_worth",
        client=client,
        result=result,
        state_summary={
            "headline": headline[:280],
            "article_count": len(articles),
            "outlets": state["outlets"],
        },
        questions=questions,
        action="skip_opus" if not proceed else "proceed_opus",
        extra=extra,
    )
    return BriefWorthVerdict(
        proceed=proceed,
        engine="jev",
        nouls=nouls,
        skip_reason=skip_reason,
    )
