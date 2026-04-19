"""
Stage 2 — Story Triage (Walter Croncat journalism workflow).

Filters TrendCandidates from Stage 1 down to the 1–4 stories per cycle worth
actually reporting on. Implements the need-to-know criteria from the workflow
doc Section 2 / Stage 2.

A candidate **passes** if it scores >= 3 of:
  - Affects health/safety/rights/money of a meaningful population
  - Is a genuine change in the world (a vote, ruling, release — not a quote)
  - Multiple outlets reporting (>= 2 source_signals OR detectable via news fetcher)
  - Factually checkable (named sources, named institutions — not just rumor)
  - Plausibly accountability-related (mentions of agencies, courts, oversight)

A candidate is **rejected** outright if:
  - Single tweet from a politician with no underlying event (only one signal AND
    no event verbs in the headline)
  - Pure celebrity gossip (entertainment vocabulary dominates)
  - Single anonymous source with no corroboration (only one signal AND
    "anonymous" / "sources say" in the headline)
  - Recycled outrage with no new facts (outrage vocabulary dominates and
    no event verbs)

Two modes:
  - **Heuristic** (default, no API cost) — pattern-matching against vocabulary lists.
  - **LLM fallback** (opt-in via `use_llm=True`) — calls Claude Haiku for cheap
    classification. Disabled by default; the heuristic path stands alone for
    cost-free CI runs and the smoke test.
"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trend_detector import TrendCandidate


# ---------------------------------------------------------------------------
# Vocabulary buckets — these are heuristic, intentionally narrow
# ---------------------------------------------------------------------------

# Verbs/nouns that signal "a thing actually happened in the world"
EVENT_TOKENS = {
    "vote", "voted", "passed", "passes", "rejected", "ruling", "ruled",
    "verdict", "indicted", "indictment", "convicted", "sentenced",
    "filed", "files", "filing", "released", "release", "announced",
    "signed", "vetoed", "subpoenaed", "subpoena", "arrested", "fired",
    "resigned", "killed", "wounded", "injured", "struck", "strike",
    "launch", "launched", "attack", "attacked", "explosion", "crash",
    "outbreak", "recall", "recalls", "shutdown", "deadline", "approved",
    "denied", "blocked", "grants", "granted", "raid", "raided",
    "decision", "decided", "issued", "issues", "report", "reports",
    # Added after QA loop #1 — these were obviously events but missed.
    "pleads", "plea", "guilty", "declares", "declared",
    "wins", "won", "identified", "dismisses", "dismissed",
    "denies", "steps down", "stepped down",
    "confirms", "confirmed", "admits", "admitted",
    "testifies", "testified", "charged", "charges",
    "sues", "sued",
    # Added 2026-04-19 after run 24630670415 hard-rejected big stories
    # (Strait of Hormuz shuttered, Russian oil waiver extended, Trump
    # envoys head to Pakistan, Kentucky rehab allegations) because their
    # verbs weren't on the whitelist. Broadened across the common
    # action categories so routine breaking news can pass triage.
    # Action / movement
    "shuttered", "shut", "closes", "closed", "reopens", "reopened",
    "heads", "head", "headed", "travels", "traveled", "arrives", "arrived",
    "departs", "departed", "flees", "fled", "evacuates", "evacuated",
    "rescued", "rescues", "seized", "seizes", "withdrew", "withdraws",
    "withdrew", "deploys", "deployed", "recalls", "recalled",
    # Policy / legal action
    "extends", "extended", "imposes", "imposed", "lifts", "lifted",
    "bans", "banned", "enacted", "enacts", "repeals", "repealed",
    "ratifies", "ratified", "upholds", "upheld", "overturns", "overturned",
    "pardons", "pardoned", "commuted", "commutes",
    # Institutional / political
    "endorses", "endorsed", "nominates", "nominated", "confirms",
    "impeached", "recalls", "recalled", "appoints", "appointed",
    "elects", "elected", "sanctioned", "sanctions",
    # Conflict / crisis
    "warns", "warned", "threatens", "threatened", "demands", "demanded",
    "weighs", "weighed", "negotiating", "negotiate", "negotiated",
    "talks", "meets", "met", "meeting", "summit", "walks out",
    "ceasefire", "agreement", "deal",
    # Market / finance
    "surges", "surged", "tumbles", "tumbled", "plunges", "plunged",
    "soared", "soars", "crashed", "crashes", "cut", "cuts",
    "raises", "raised", "lowers", "lowered", "hikes", "hiked",
    "merges", "merged", "acquires", "acquired",
    # Reporting forms with no explicit verb
    "alleges", "alleged", "allegations", "allegation", "claim", "claims",
    "findings", "investigation", "probe", "audit",
    "brings", "brought", "expands", "expanded", "launches",
    "grows", "grew", "fell", "falls",
}

# Tokens that suggest health/safety/rights/money impact on a population
IMPACT_TOKENS = {
    "deaths", "killed", "wounded", "injured", "outbreak", "recall",
    "tariff", "tariffs", "jobs", "layoffs", "unemployment", "inflation",
    "rates", "tax", "taxes", "subsidy", "subsidies", "voting", "rights",
    "abortion", "ruling", "shutdown", "benefits", "medicare", "medicaid",
    "insurance", "drug", "drugs", "vaccine", "epidemic", "pandemic",
    "wage", "wages", "minimum", "rent", "housing", "evictions", "shooting",
    "shootings", "shooter", "fatal", "fatalities", "bombing", "missile",
    "sanctions", "embargo", "deportation", "immigration", "asylum",
    "regulation", "regulations", "ban", "banned",
}

# Tokens that flag accountability / institutional oversight angles
ACCOUNTABILITY_TOKENS = {
    "doj", "fbi", "sec", "irs", "epa", "fda", "ftc", "nlrb", "cfpb",
    "ag", "attorney", "prosecutor", "grand jury", "subpoena",
    "subpoenaed", "indicted", "indictment", "investigation",
    "investigated", "oversight", "inspector", "audit", "audited",
    "whistleblower", "leaked", "scotus", "supreme court", "court",
    "judge", "ruling", "ruled", "filed", "filing", "lawsuit",
    "congress", "senate", "house", "committee", "hearing", "testimony",
    "perjury", "contempt", "fraud", "bribery", "corruption", "ethics",
    "watchdog", "transparency", "foia",
}

# Tokens that suggest the headline is checkable (named institutions or roles)
CHECKABLE_TOKENS = {
    "reuters", "ap", "afp", "bloomberg", "wsj", "nyt", "washington post",
    "guardian", "bbc", "cnn", "fox news", "ft", "axios", "politico",
    "propublica", "scotusblog", "press release", "transcript", "filing",
    "report says", "according to", "statement", "official",
    "officials", "spokesperson", "spokesman", "spokeswoman",
}

# Outrage / vibes — recycled-outrage red flags
OUTRAGE_TOKENS = {
    "outrage", "outraged", "slammed", "destroys", "destroyed", "owns",
    "epic", "savage", "fires back", "claps back", "eviscerates",
    "annihilates", "torches", "shreds", "demolishes", "wrecked",
    "blasts", "blasted", "rips", "ripped", "humiliated",
}

# Celebrity / gossip / entertainment red flags
GOSSIP_TOKENS = {
    "kardashian", "jenner", "bieber", "swift", "kanye", "drake",
    "celebrity", "celebs", "instagram", "tiktok", "viral", "selfie",
    "outfit", "red carpet", "premiere", "rumor", "rumors", "reportedly dating",
    "split", "engaged", "engagement ring", "baby bump", "wedding",
}

# Anonymous-source red flags (these are not necessarily disqualifying on
# their own, but combined with low source-signal count they tip the balance)
ANONYMOUS_TOKENS = {
    "anonymous", "sources tell", "people familiar", "person familiar",
    "according to sources", "a source said", "unnamed", "off the record",
}


# ---------------------------------------------------------------------------
# StoryTriage
# ---------------------------------------------------------------------------

class StoryTriage:
    """Need-to-know filter for trend candidates.

    Default mode is heuristic-only. The LLM mode is OPTIONAL — it calls
    Claude Haiku for cheap classification — and is gated behind the
    `use_llm` constructor flag so the smoke test (and CI) can run with
    no network access.
    """

    PASS_THRESHOLD = 3

    # Canonical names for the 5 scoring dimensions — used by the feedback
    # logger to compute `missing` (which signals didn't fire) so a later
    # review can see at a glance which verbs/tokens would have unblocked
    # a borderline drop.
    _ALL_SIGNALS = (
        "multi-outlet", "event-verb", "impact", "checkable", "accountability",
    )

    def __init__(self, use_llm: bool = False, anthropic_client=None, model: str = "claude-haiku-4-6"):
        self.use_llm = use_llm
        self._anthropic_client = anthropic_client
        self._model = model
        # Populated by triage() each call — one record per candidate. The
        # orchestrator (main.py) reads this after triage() returns and
        # appends it to docs/reports/triage_decisions.jsonl for later
        # review (which verbs to add, which rules are too aggressive).
        self.last_decisions: list[dict] = []

    # ---- public ------------------------------------------------------------

    def triage(self, candidates: list["TrendCandidate"]) -> list["TrendCandidate"]:
        """Return only candidates that pass triage, in original order.

        Side effect: populates self.last_decisions with one dict per
        candidate recording its verdict, score, reasons, missing signals,
        and (if applicable) the hard-reject rule that fired. The caller
        is expected to persist this for offline review — see main.py.
        """
        passing: list["TrendCandidate"] = []
        self.last_decisions = []
        for c in candidates:
            score, reasons = self._heuristic_score(c)

            # Hard rejects
            hard_rule = self._is_hard_reject(c)
            if hard_rule is not None:
                print(f"[story_triage] REJECT '{c.headline_seed[:60]}...' — hard reject ({hard_rule})")
                self.last_decisions.append(
                    self._decision_record(c, "REJECT", score, reasons, hard_rule=hard_rule)
                )
                continue

            # Optional LLM second opinion (only if heuristic is borderline)
            llm_used = False
            llm_verdict: bool | None = None
            if self.use_llm and score == self.PASS_THRESHOLD - 1:
                llm_used = True
                llm_verdict = self._llm_classify(c)
                if llm_verdict:
                    score += 1
                    reasons.append("llm:pass")

            if score >= self.PASS_THRESHOLD:
                print(
                    f"[story_triage] PASS  '{c.headline_seed[:60]}...' "
                    f"score={score} reasons={reasons}"
                )
                passing.append(c)
                self.last_decisions.append(
                    self._decision_record(c, "PASS", score, reasons,
                                          llm_used=llm_used, llm_verdict=llm_verdict)
                )
            else:
                print(
                    f"[story_triage] DROP  '{c.headline_seed[:60]}...' "
                    f"score={score} reasons={reasons}"
                )
                self.last_decisions.append(
                    self._decision_record(c, "DROP", score, reasons,
                                          llm_used=llm_used, llm_verdict=llm_verdict)
                )
        return passing

    # ---- decision record ---------------------------------------------------

    @classmethod
    def _decision_record(
        cls,
        candidate: "TrendCandidate",
        verdict: str,
        score: int,
        reasons: list[str],
        hard_rule: str | None = None,
        llm_used: bool = False,
        llm_verdict: bool | None = None,
    ) -> dict:
        """Build a JSON-friendly decision record for the feedback logger.

        `missing` lists the canonical signals that did NOT fire — this is
        what a reviewer scans to find "score=2 drops that only needed one
        more event-verb" and decide which verbs to add to the whitelist.
        """
        fired = {r.split("(")[0] for r in reasons if r != "llm:pass"}
        missing = [s for s in cls._ALL_SIGNALS if s not in fired]
        record = {
            "headline": (candidate.headline_seed or "")[:280],
            "verdict": verdict,
            "score": score,
            "reasons": list(reasons),
            "missing": missing,
            "source_signals": len(candidate.source_signals or []),
            "source": getattr(candidate, "source", "x"),
            "story_id": getattr(candidate, "story_id", ""),
        }
        if hard_rule is not None:
            record["hard_rule"] = hard_rule
        if llm_used:
            record["llm_used"] = True
            record["llm_verdict"] = bool(llm_verdict)
        return record

    # ---- heuristic core ----------------------------------------------------

    def _heuristic_score(self, candidate: "TrendCandidate") -> tuple[int, list[str]]:
        """Score a candidate against the 5 need-to-know dimensions.

        Returns (score, reasons). Score is 0..5; reasons is a list of human-
        readable strings explaining which checks fired.
        """
        text = (candidate.headline_seed or "").lower()
        is_news_fetcher = getattr(candidate, "source", "x") == "news_fetcher"
        score = 0
        reasons: list[str] = []

        # 1. Multi-outlet reporting
        # NewsFetcher-fallback candidates come from Google News top-stories,
        # which is itself a curated aggregation across outlets — treat each
        # one as multi-outlet by construction even though source_signals has
        # only the one URL source on it.
        if len(candidate.source_signals) >= 2:
            score += 1
            reasons.append(f"multi-outlet({len(candidate.source_signals)})")
        elif is_news_fetcher:
            score += 1
            reasons.append("multi-outlet(google-news-curated)")

        # 2. Genuine change in the world (event verb present)
        if self._has_token(text, EVENT_TOKENS):
            score += 1
            reasons.append("event-verb")

        # 3. Impact axis (health/safety/rights/money)
        if self._has_token(text, IMPACT_TOKENS):
            score += 1
            reasons.append("impact")

        # 4. Factually checkable (institutional / outlet / role names)
        # Pull proper nouns from the headline as a proxy — names of places,
        # people and organizations make a story checkable.
        if self._has_token(text, CHECKABLE_TOKENS) or self._has_proper_noun(candidate.headline_seed):
            score += 1
            reasons.append("checkable")

        # 5. Accountability / institutional angle
        if self._has_token(text, ACCOUNTABILITY_TOKENS):
            score += 1
            reasons.append("accountability")

        return score, reasons

    def _is_hard_reject(self, candidate: "TrendCandidate") -> str | None:
        """Return the name of the hard-reject rule that fired, or None.

        Returning a string (vs bool) lets the feedback logger record WHY
        a story was rejected so a later review can tell whether a rule
        is too aggressive.
        """
        text = (candidate.headline_seed or "").lower()
        single_signal = len(candidate.source_signals) <= 1
        # Candidates from the NewsFetcher fallback are single-signal by
        # construction (each top-story is one URL from one outlet), but
        # Google News top-stories is itself a curated aggregation — the
        # "single_signal means one random tweet" heuristic does not apply.
        # We treat news_fetcher candidates as if they had multi-outlet
        # corroboration for the purpose of the single-signal hard-rejects.
        is_news_fetcher = getattr(candidate, "source", "x") == "news_fetcher"

        # Pure celebrity gossip
        if self._has_token(text, GOSSIP_TOKENS) and not self._has_token(text, EVENT_TOKENS):
            return "gossip_no_event"

        # Single anonymous source with no corroboration
        # (skipped for news_fetcher: Google News curation ~= corroboration)
        if single_signal and not is_news_fetcher and self._has_token(text, ANONYMOUS_TOKENS):
            return "single_anonymous_source"

        # Single tweet from one politician with no underlying event
        # (skipped for news_fetcher: each top-story is curated, not a raw tweet)
        if single_signal and not is_news_fetcher and not self._has_token(text, EVENT_TOKENS):
            # Escape hatches: accountability OR impact saves the candidate.
            # Impact added 2026-04-19 — stories about sanctions / oil /
            # immigration / tariffs are newsworthy regardless of headline
            # verb. Without this, run 24630670415 hard-rejected the US
            # Russian-oil-waiver extension and other real news.
            if (
                not self._has_token(text, ACCOUNTABILITY_TOKENS)
                and not self._has_token(text, IMPACT_TOKENS)
            ):
                return "single_signal_no_event_no_accountability_no_impact"

        # Recycled outrage with no new facts
        outrage_hits = sum(1 for t in OUTRAGE_TOKENS if t in text)
        if outrage_hits >= 2 and not self._has_token(text, EVENT_TOKENS):
            return "recycled_outrage"

        return None

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _has_token(text: str, tokens: set[str]) -> bool:
        for token in tokens:
            if " " in token:
                if token in text:
                    return True
            else:
                # Word boundary so "vote" doesn't match "voter" mid-word in a way
                # that would distort the signal too much (we still want it to match
                # "voter" because that's a noun form — but block "promote")
                if re.search(r"\b" + re.escape(token) + r"\b", text):
                    return True
        return False

    @staticmethod
    def _has_proper_noun(headline: str) -> bool:
        """A weak signal that the headline contains a named entity."""
        for word in headline.split():
            clean = re.sub(r"[^\w]", "", word)
            if len(clean) >= 3 and clean[0].isupper() and not clean.isupper():
                # ignore obvious sentence starters
                if clean not in {"The", "This", "That", "These", "Those", "After", "Before"}:
                    return True
        return False

    # ---- optional LLM mode -------------------------------------------------

    def _llm_classify(self, candidate: "TrendCandidate") -> bool:
        """Cheap Claude Haiku classification. Returns True for "newsworthy".

        Skipped silently if no Anthropic SDK / API key is available so the
        smoke test never crashes.
        """
        client = self._anthropic_client
        if client is None:
            try:
                from anthropic import Anthropic  # local import — optional dep
            except ImportError:
                return False
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return False
            try:
                client = Anthropic(api_key=api_key)
            except Exception as e:
                print(f"[story_triage] could not init Anthropic client: {e}")
                return False

        prompt = (
            "You are a strict newsroom triage editor. Answer YES or NO only.\n"
            "Does this headline meet a need-to-know bar (real change in the world,\n"
            "checkable facts, multiple-outlet potential, accountability angle)?\n\n"
            f"Headline: {candidate.headline_seed}\n"
            f"Source signals: {candidate.source_signals}\n\n"
            "Answer:"
        )
        try:
            msg = client.messages.create(
                model=self._model,
                max_tokens=4,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (msg.content[0].text or "").strip().lower()
            return text.startswith("y")
        except Exception as e:
            print(f"[story_triage] LLM classification failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Pure-logic sanity check — no Anthropic, no network."""
    # Build a few synthetic candidates locally so we don't import trend_detector
    # at module top-level. We use a stub object that quacks like TrendCandidate.
    from dataclasses import dataclass

    @dataclass
    class _Stub:
        headline_seed: str
        detected_at: str
        source_signals: list[str]
        engagement: int
        story_id: str

    candidates = [
        _Stub(
            headline_seed="Senate passes Appropriations Bill 68-32, averting shutdown — Reuters",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["Reuters", "AP", "FoxNews"],
            engagement=200,
            story_id="a1",
        ),
        _Stub(
            headline_seed="Kim Kardashian seen wearing new outfit at premiere",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["nypost"],
            engagement=500,
            story_id="a2",
        ),
        _Stub(
            headline_seed="DOJ files indictment in alleged bribery scheme tied to FAA contract",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["Reuters", "AP"],
            engagement=80,
            story_id="a3",
        ),
        _Stub(
            headline_seed="Senator slammed by colleague in heated exchange",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["FoxNews"],
            engagement=10,
            story_id="a4",
        ),
        _Stub(
            headline_seed="Sources tell us anonymous official may resign next week",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["FoxNews"],
            engagement=5,
            story_id="a5",
        ),
    ]

    triage = StoryTriage(use_llm=False)

    # Sanity scoring
    score_a, _ = triage._heuristic_score(candidates[0])
    score_b, _ = triage._heuristic_score(candidates[1])
    score_c, _ = triage._heuristic_score(candidates[2])
    assert score_a >= 3, f"Senate vote should pass triage, got score={score_a}"
    assert score_c >= 3, f"DOJ indictment should pass triage, got score={score_c}"
    # Kardashian should be hard-rejected
    assert triage._is_hard_reject(candidates[1]), "celebrity outfit should hard-reject"
    # Anonymous + single source should be hard-rejected
    assert triage._is_hard_reject(candidates[4]), "anonymous single source should hard-reject"

    passing = triage.triage(candidates)
    headlines = [c.headline_seed for c in passing]
    assert any("Senate passes" in h for h in headlines), f"missing Senate vote: {headlines}"
    assert any("DOJ" in h for h in headlines), f"missing DOJ indictment: {headlines}"
    assert not any("Kardashian" in h for h in headlines), f"gossip leaked through: {headlines}"

    print(f"story_triage smoke test OK ({len(passing)}/{len(candidates)} passed)")


if __name__ == "__main__":
    _smoke_test()
