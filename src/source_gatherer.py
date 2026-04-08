"""
Stage 3 — Source Gather (Walter Croncat journalism workflow).

Given a TrendCandidate, fan out to NewsFetcher to collect 5–10 articles from a
deliberately diverse set of outlets, fetch their full bodies, and assemble a
StoryDossier ready for Stage 4 (meta-analysis).

Slant matrix (workflow doc Stage 3):
  - >=1 wire (Reuters, AP, AFP, Bloomberg)
  - >=1 left-mainstream
  - >=1 right-mainstream
  - >=1 international
  - >=1 specialized / beat

If the matrix can't be filled within `target_count`, the missing slots are
LOGGED and the gather continues — Stage 4 needs *something* to chew on, even
an incomplete dossier. Stage 6 (verification_gate) is what enforces the
two-source minimum at publish time, not this stage.

Wire-derived dedup: any article whose body shows substantial substring overlap
with a wire-source article (Reuters/AP/AFP/Bloomberg) in the same dossier is
flagged with `is_wire_derived=True` so the meta-analyzer can collapse them
into one logical source per Cronkite's two-independent-sources rule.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from dossier_store import ArticleRecord, StoryDossier

if TYPE_CHECKING:
    from trend_detector import TrendCandidate


WIRE_OUTLETS = {"reuters", "associated press", "ap news", "afp", "agence france-presse", "bloomberg"}


# ---------------------------------------------------------------------------
# Keyword extraction for Stage 3 search queries
# ---------------------------------------------------------------------------
# Rationale (Bug 4): passing a full 286-char headline_seed to Google News RSS
# returns zero hits on anything non-trivial. We compress the headline down to
# a handful of proper nouns + event verbs before querying, while keeping the
# original headline intact for the dossier and downstream Opus/Sonnet calls.

_SUFFIX_STRIP_RE = re.compile(r"\s*[-—|]\s*[A-Z][\w\s&.']+$")

_FLUFF_PREFIXES = (
    "BREAKING:",
    "BREAKING NEWS:",
    "LIVE UPDATES:",
    "LIVE:",
    "WATCH LIVE:",
    "WATCH:",
    "EXCLUSIVE:",
    "UPDATE:",
    "UPDATED:",
    "DEVELOPING:",
    "JUST IN:",
)

_SENTENCE_STARTERS = {
    "The", "A", "An", "After", "Before", "This", "That", "These",
    "Those", "Hours", "Days", "Weeks", "Now", "Here", "There", "When",
    "While", "As", "If", "But", "And", "Or", "So", "Then", "Today",
    "Yesterday", "Tomorrow",
}

_EVENT_VERBS = {
    "passes", "passed", "vote", "voted", "wins", "won", "kills", "killed",
    "struck", "strikes", "attacks", "attacked", "ceasefire", "announces",
    "announced", "fires", "fired", "signs", "signed", "arrests", "arrested",
    "declares", "declared", "rules", "ruled", "pleads", "guilty", "files",
    "filed", "denies", "denied", "dismisses", "dismissed", "testifies",
    "testified", "indicts", "indicted", "confirms", "confirmed", "admits",
    "admitted",
}

_STRONG_NOUNS = {
    "court", "senate", "congress", "president", "minister", "fire", "flood",
    "earthquake", "election", "strike", "ceasefire", "verdict", "ruling",
    "deal", "law", "bill",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "from",
    "with", "by", "as", "of", "for", "that", "this", "these", "those", "is",
    "was", "are", "were", "be", "been", "being", "not", "however",
}

_TOKEN_SPLIT_RE = re.compile(r"[\s,;:!?()\[\]{}\"<>/\\]+")


def _default_registry_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "outlet_registry.yaml")


def _load_outlet_registry(path: str) -> list[dict]:
    """Load outlets list from outlet_registry.yaml. Returns [] on failure."""
    try:
        import yaml
    except ImportError:
        return []
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # pragma: no cover
        print(f"[source_gatherer] failed to read registry: {e}")
        return []
    outlets = data.get("outlets", []) if isinstance(data, dict) else []
    cleaned = []
    for o in outlets:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        cleaned.append({
            "name": o["name"],
            "domain": (o.get("domain") or "").lower(),
            "slant": o.get("slant", ""),
            "beat": o.get("beat", ""),
            "priority": o.get("priority", 99),
        })
    return cleaned


_OUTLET_NAME_SUFFIXES = (
    " english",
    " news service",
    " news network",
    " news",
    " service",
    " media",
    " network",
    " post",
    " journal",
)


def _normalize_outlet_name(name: str) -> str:
    """Normalize an outlet name for loose comparison between NewsFetcher's
    `source` field (e.g. `"BBC"`) and `outlet_registry.yaml`'s `name` field
    (e.g. `"BBC News"`).

    Strips "The " prefix, lowercases, then strips one trailing suffix like
    " News" / " English" / " Service" if present. Does NOT strip more than
    one suffix — "Christian Science Monitor" should not become "Christian"
    if " Monitor" happens to be matched.
    """
    if not name:
        return ""
    norm = name.strip().lower()
    if norm.startswith("the "):
        norm = norm[4:]
    for suffix in _OUTLET_NAME_SUFFIXES:
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)]
            break
    return norm.strip()


def _outlet_match(article_source: str, outlet_name: str, outlet_domain: str) -> bool:
    """Match a NewsFetcher article source string against a registry outlet.

    Matching is bidirectional and name-normalized. We strip "The " prefixes
    and common trailing suffixes ("News", "English", "Service") from both
    sides before comparing, so registry "BBC News" matches NewsFetcher
    "BBC", and registry "Al Jazeera English" matches "Al Jazeera", and
    registry "The New York Times" matches "New York Times".

    Domain match is checked first when available — most reliable signal.
    Falls back to normalized-name comparison. Historical special-cases
    (Associated Press / AP / AP News) are still handled.
    """
    if not article_source:
        return False
    src_lower = article_source.lower()

    # Domain match — most reliable when present
    if outlet_domain and outlet_domain in src_lower:
        return True

    src_norm = _normalize_outlet_name(article_source)
    outlet_norm = _normalize_outlet_name(outlet_name)
    if not src_norm or not outlet_norm:
        return False

    # Exact normalized match
    if src_norm == outlet_norm:
        return True

    # Bidirectional substring — either name contained in the other,
    # provided the shorter one is at least 3 chars (avoid tiny matches
    # like "ap" landing inside "apple news"). We word-boundary the check
    # to avoid matching "cbs" inside "ncbs" or similar.
    shorter, longer = sorted([src_norm, outlet_norm], key=len)
    if len(shorter) >= 3:
        # Word-boundary substring check
        if re.search(r"\b" + re.escape(shorter) + r"\b", longer):
            return True

    # Historical special cases
    if outlet_norm == "associated press" and src_norm in ("ap", "ap news", "associated"):
        return True

    return False


def _slant_for(article_source: str, registry: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """Resolve (canonical_outlet_name, slant) for an article source string."""
    for entry in registry:
        if _outlet_match(article_source, entry["name"], entry["domain"]):
            return entry["name"], entry["slant"]
    return None, None


# ---------------------------------------------------------------------------
# SourceGatherer
# ---------------------------------------------------------------------------

class SourceGatherer:
    """Stage 3 of the Croncat journalism pipeline."""

    REQUIRED_SLANTS = ["wire", "left-mainstream", "right-mainstream", "international", "specialized"]

    def __init__(self, news_fetcher=None, registry_path: Optional[str] = None):
        self.news_fetcher = news_fetcher
        self.registry_path = registry_path or _default_registry_path()
        self.registry = _load_outlet_registry(self.registry_path)

    # ---- public ------------------------------------------------------------

    def gather(self, candidate: "TrendCandidate", target_count: int = 7) -> StoryDossier:
        """Collect articles for a candidate and return a StoryDossier.

        target_count is a soft target — we keep gathering until we hit it OR
        we exhaust the slant matrix, whichever comes first. The dossier is
        returned even if incomplete; the verification gate at Stage 6 makes
        the final publish/no-publish call.
        """
        topic = candidate.headline_seed
        topic_query = self._build_search_query(topic)
        if not topic_query:
            # Nothing extractable — fall back to the first 10 words of the original
            topic_query = " ".join(topic.split()[:10])
        print(
            f"[source_gatherer] search query: {topic_query!r}  "
            f"(from headline: {topic[:80]}...)"
        )
        articles_raw = self._fetch_articles(topic_query, max_articles=max(target_count * 2, 10))

        # Map sources to canonical outlet + slant
        slant_to_articles: dict[str, list[dict]] = {s: [] for s in self.REQUIRED_SLANTS}
        unmatched: list[dict] = []
        outlet_slants: dict[str, str] = {}

        for art in articles_raw:
            source = art.get("source", "") or ""
            canonical, slant = _slant_for(source, self.registry)
            if not canonical:
                # Fall back to using the raw source string with no slant
                canonical = source or "Unknown"
                slant = ""
            outlet_slants[canonical] = slant or outlet_slants.get(canonical, "")
            entry = {**art, "canonical_outlet": canonical, "slant": slant or ""}
            if slant in slant_to_articles:
                slant_to_articles[slant].append(entry)
            else:
                unmatched.append(entry)

        # Build the gather list, taking one from each slant first
        chosen: list[dict] = []
        seen_urls: set[str] = set()

        def _take(entry: dict) -> bool:
            url = entry.get("url")
            if not url or url in seen_urls:
                return False
            seen_urls.add(url)
            chosen.append(entry)
            return True

        for slant in self.REQUIRED_SLANTS:
            bucket = slant_to_articles.get(slant) or []
            if bucket:
                _take(bucket[0])
            else:
                print(f"[source_gatherer] slant matrix gap: no '{slant}' outlet for "
                      f"'{topic[:60]}...' — continuing with what we have")

        # Backfill from remaining buckets and unmatched
        round_robin: list[dict] = []
        for slant in self.REQUIRED_SLANTS:
            round_robin.extend(slant_to_articles.get(slant, [])[1:])
        round_robin.extend(unmatched)
        for entry in round_robin:
            if len(chosen) >= target_count:
                break
            _take(entry)

        # Fetch the article bodies for the chosen articles
        article_records: list[ArticleRecord] = []
        for entry in chosen:
            body = self._fetch_body(entry.get("url", ""))
            if not body:
                # Fall back to whatever the description was — better than nothing
                body = entry.get("description", "") or ""
            record = ArticleRecord(
                outlet=entry.get("canonical_outlet") or entry.get("source") or "Unknown",
                url=entry.get("url", ""),
                title=entry.get("title", ""),
                body=body,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                is_wire_derived=False,  # set after we see the full set below
            )
            article_records.append(record)

        # Mark wire-derived duplicates
        self._mark_wire_derived(article_records)

        dossier = StoryDossier(
            story_id=candidate.story_id,
            headline_seed=candidate.headline_seed,
            detected_at=candidate.detected_at,
            articles=article_records,
            primary_sources=[],  # filled in by primary_source_finder
            outlet_slants={r.outlet: outlet_slants.get(r.outlet, "") for r in article_records},
        )
        return dossier

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _build_search_query(headline_seed: str) -> str:
        """Compress a headline_seed down to a short Google News search query.

        Heuristic-only (no LLM). Returns a space-separated string of at most
        6 keyword tokens drawn from proper nouns, event verbs, and strong
        nouns in the original headline, with outlet suffixes and fluff
        prefixes stripped. Returns "" if nothing extractable is left; the
        caller is expected to fall back on a truncated headline in that case.

        Example:
          in:  "Vote passes 68-32 - Reuters"
          out: "Vote passes Reuters"  (or similar — exact ordering depends on
                                       tokenization; the point is ≤6 tokens)
        """
        if not headline_seed:
            return ""

        # 1. Strip an outlet suffix like " - CNBC", " — Al Jazeera", " | Reuters"
        stripped = _SUFFIX_STRIP_RE.sub("", headline_seed.strip(), count=1).strip()

        # 2. Strip common fluff prefixes
        upper_prefix = stripped.upper()
        for pref in _FLUFF_PREFIXES:
            if upper_prefix.startswith(pref):
                stripped = stripped[len(pref):].lstrip()
                break

        # 3. Split on whitespace and punctuation
        raw_tokens = [t for t in _TOKEN_SPLIT_RE.split(stripped) if t]

        # 4-6. Keep proper nouns + event verbs + strong nouns, drop stopwords,
        # dedupe while preserving order.
        kept: list[str] = []
        seen_lower: set[str] = set()
        for raw in raw_tokens:
            # Strip leading/trailing punctuation that survived the split
            tok = raw.strip(".'\"`’‘")
            if not tok:
                continue
            lower = tok.lower()
            if lower in _STOPWORDS:
                continue
            if lower in seen_lower:
                continue

            is_proper = (
                len(tok) >= 3
                and tok[0].isupper()
                and tok not in _SENTENCE_STARTERS
            )
            is_event_verb = lower in _EVENT_VERBS
            is_strong_noun = lower in _STRONG_NOUNS

            if is_proper or is_event_verb or is_strong_noun:
                kept.append(tok)
                seen_lower.add(lower)

            if len(kept) >= 6:
                break

        return " ".join(kept)

    def _fetch_articles(self, topic: str, max_articles: int) -> list[dict]:
        if not self.news_fetcher:
            return []
        try:
            return self.news_fetcher.get_articles_for_topic(topic, max_articles=max_articles) or []
        except Exception as e:
            print(f"[source_gatherer] news fetch failed for '{topic[:60]}...': {e}")
            return []

    def _fetch_body(self, url: str) -> str:
        if not url or not self.news_fetcher:
            return ""
        try:
            body = self.news_fetcher.fetch_article_content(url)
            return body or ""
        except Exception as e:
            print(f"[source_gatherer] body fetch failed for {url[:60]}: {e}")
            return ""

    def _mark_wire_derived(self, records: list[ArticleRecord]) -> None:
        """Heuristic dedup: any article whose body has substantial substring
        overlap with a wire article in the same dossier is marked wire-derived."""
        wires = [r for r in records if r.outlet.lower() in WIRE_OUTLETS]
        if not wires:
            return
        for record in records:
            if record in wires:
                continue
            for wire in wires:
                if self._substring_overlap(wire.body, record.body) >= 0.5:
                    record.is_wire_derived = True
                    break

    @staticmethod
    def _substring_overlap(a: str, b: str) -> float:
        """Cheap shingle overlap: how many 30-char chunks of `b` appear in `a`."""
        if not a or not b:
            return 0.0
        a_norm = re.sub(r"\s+", " ", a)
        b_norm = re.sub(r"\s+", " ", b)
        if len(b_norm) < 60:
            return 0.0
        chunk_size = 30
        chunks = [b_norm[i:i + chunk_size] for i in range(0, len(b_norm) - chunk_size, chunk_size)]
        if not chunks:
            return 0.0
        hits = sum(1 for c in chunks if c in a_norm)
        return hits / len(chunks)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

class _StubNewsFetcher:
    """In-process stub that mimics NewsFetcher's surface area."""

    def __init__(self, articles: list[dict], bodies: dict[str, str]):
        self._articles = articles
        self._bodies = bodies

    def get_articles_for_topic(self, topic: str, max_articles: int = 10):
        return list(self._articles)

    def fetch_article_content(self, url: str):
        return self._bodies.get(url, "")


def _smoke_test() -> None:
    from dataclasses import dataclass

    @dataclass
    class _Cand:
        headline_seed: str
        detected_at: str
        source_signals: list[str]
        engagement: int
        story_id: str

    candidate = _Cand(
        headline_seed="Senate passes appropriations bill 68-32",
        detected_at="2026-04-08T19:30:00+00:00",
        source_signals=["Reuters", "AP", "FoxNews"],
        engagement=180,
        story_id="20260408-senate-approps-test",
    )

    fake_articles = [
        {
            "title": "Senate passes $1.2T appropriations bill 68-32",
            "url": "https://reuters.com/x",
            "source": "Reuters",
            "description": "The Senate voted 68-32 ...",
        },
        {
            "title": "Senate approves spending bill, averting shutdown",
            "url": "https://apnews.com/y",
            "source": "AP News",
            "description": "By a vote of 68-32 ...",
        },
        {
            "title": "Senate clears bipartisan spending package",
            "url": "https://nytimes.com/z",
            "source": "The New York Times",
            "description": "In a rare bipartisan moment ...",
        },
        {
            "title": "Senate vote breaks down GOP defectors",
            "url": "https://foxnews.com/a",
            "source": "Fox News",
            "description": "Eight Republicans crossed over ...",
        },
        {
            "title": "Senate bill clears chamber, House next",
            "url": "https://bbc.com/b",
            "source": "BBC News",
            "description": "Lawmakers on Capitol Hill ...",
        },
        {
            "title": "Politico inside scoop: how the whip count held",
            "url": "https://politico.com/c",
            "source": "Politico",
            "description": "Behind the scenes, leadership ...",
        },
    ]
    bodies = {
        "https://reuters.com/x": (
            "WASHINGTON (Reuters) - The U.S. Senate on Tuesday voted 68-32 to pass a $1.2 trillion "
            "appropriations bill that would avert a midnight shutdown deadline. The measure now goes "
            "to the House for a Friday vote. Senate Majority Leader said the package included a $14 billion "
            "emergency disaster supplement in Title VII. Senate roll call vote 312 confirmed the breakdown."
        ),
        "https://apnews.com/y": "AP News story body about the Senate vote 68-32 ...",
        "https://nytimes.com/z": "NYT body framing the bipartisan vote as historic ...",
        "https://foxnews.com/a": (
            "WASHINGTON (Reuters) - The U.S. Senate on Tuesday voted 68-32 to pass a $1.2 trillion "
            "appropriations bill that would avert a midnight shutdown deadline. The measure now goes "
            "to the House for a Friday vote."
            # Fox is reposting Reuters wire copy nearly verbatim — should mark as wire-derived
        ),
        "https://bbc.com/b": "BBC body about the US Senate vote ...",
        "https://politico.com/c": "Politico body on whip count ...",
    }
    fetcher = _StubNewsFetcher(fake_articles, bodies)

    gatherer = SourceGatherer(news_fetcher=fetcher)
    dossier = gatherer.gather(candidate, target_count=6)

    assert isinstance(dossier, StoryDossier)
    assert dossier.story_id == candidate.story_id
    outlets = {a.outlet for a in dossier.articles}
    # We should have at least Reuters/AP/NYT/Fox in the gather
    assert "Reuters" in outlets, f"missing Reuters in {outlets}"
    assert any("New York Times" in o for o in outlets), f"missing NYT in {outlets}"
    # The Fox article reposting Reuters wire copy should be flagged
    fox = next((a for a in dossier.articles if "Fox" in a.outlet), None)
    assert fox is not None, "expected a Fox article"
    assert fox.is_wire_derived, "Fox article copying Reuters wire should be wire-derived"
    # Reuters itself is the wire — should NOT be flagged
    reuters = next(a for a in dossier.articles if a.outlet == "Reuters")
    assert not reuters.is_wire_derived

    # Slant map populated for outlets that match the registry
    if gatherer.registry:  # if registry actually loaded
        assert dossier.outlet_slants.get("Reuters") == "wire"
        assert dossier.outlet_slants.get("The New York Times") == "left-mainstream"

    print(f"source_gatherer smoke test OK ({len(dossier.articles)} articles)")


if __name__ == "__main__":
    _smoke_test()
