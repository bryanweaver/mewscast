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
from urllib.parse import urlparse

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
    # Legal / criminal
    "passes", "passed", "vote", "voted", "wins", "won", "kills", "killed",
    "struck", "strikes", "attacks", "attacked", "announces", "announced",
    "fires", "fired", "signs", "signed", "arrests", "arrested",
    "declares", "declared", "rules", "ruled", "pleads", "guilty", "files",
    "filed", "denies", "denied", "dismisses", "dismissed", "testifies",
    "testified", "indicts", "indicted", "confirms", "confirmed", "admits",
    "admitted", "sentenced", "convicted", "acquitted", "charged", "jailed",
    "imprisoned", "paroled", "extradited", "sued", "settled", "appealed",
    # Disaster / incident
    "crashed", "died", "collapsed", "exploded", "erupted", "flooded",
    "burned", "drowned", "shot", "stabbed", "kidnapped", "rescued",
    # Political / institutional
    "vetoed", "impeached", "resigned", "appointed", "nominated", "elected",
    "recalled", "sanctioned", "banned", "lifted", "repealed", "ratified",
    "overturned", "upheld", "blocked", "approved", "rejected",
    # General news
    "discovered", "revealed", "leaked", "leaking", "launched", "deployed",
    "invaded", "seized", "raided", "evacuated", "ceasefire", "surrendered",
    "hacking", "stealing", "smuggling", "spying", "trafficking",
}

_STRONG_NOUNS = {
    # Government / legal institutions (not generic person-role titles like
    # president/governor/minister — those displace story-specific proper nouns)
    "court", "senate", "congress", "judge", "jury",
    "prosecutor", "attorney", "sheriff", "officer",
    "sergeant", "detective", "police", "military", "army", "navy",
    # Events / outcomes
    "election", "verdict", "ruling", "deal", "law", "bill", "treaty",
    "ceasefire", "strike", "protest", "riot", "massacre", "bombing",
    # Institutions / places
    "prison", "jail", "hospital", "school", "university", "church",
    "mosque", "embassy", "pentagon", "capitol", "clinic", "courthouse",
    # People roles (common news subjects)
    "doctor", "nurse", "teacher", "professor", "scientist", "journalist",
    "employee", "worker", "soldier", "pilot", "driver", "suspect",
    "victim", "witness", "defendant", "plaintiff",
    # News-significant descriptors
    "classified", "confidential", "secret", "whistleblower",
    # Disasters
    "fire", "flood", "earthquake", "hurricane", "tornado", "tsunami",
    "explosion", "crash", "shooting", "stabbing",
    # Economic
    "recession", "inflation", "bankruptcy", "layoffs", "merger",
    "acquisition", "tariff", "sanctions",
}

# Proper nouns that are valid but too generic to be the ONLY search tokens.
# These get demoted to the end of the query so content-specific words fill
# the 6-token limit first. "New York City police sergeant sentenced" should
# query "sergeant sentenced police" before "New York City".
_GENERIC_PROPER_NOUNS = {
    "new", "york", "city", "united", "states", "north", "south", "east",
    "west", "los", "angeles", "san", "francisco", "washington", "london",
    "district", "county", "state", "national", "federal", "american",
    "british", "european", "former", "current",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "from",
    "with", "by", "as", "of", "for", "that", "this", "these", "those", "is",
    "was", "are", "were", "be", "been", "being", "not", "however",
    "who", "then", "than", "also", "its", "his", "her", "their", "our",
    "your", "had", "has", "have", "did", "does", "do", "will", "would",
    "could", "should", "may", "might", "can", "shall", "into", "about",
    "after", "before", "during", "between", "through", "until", "since",
    "over", "under", "more", "most", "very", "just", "only", "even",
    "still", "yet", "already", "ago", "says", "said", "told", "according",
    "report", "reports", "year", "years", "day", "days", "time", "week",
    "month", "first", "last", "next", "other", "some", "many", "much",
    "every", "each", "both", "all", "any", "few", "full", "three", "nine",
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

    # Slant-diversity targets for the dossier. Updated to match AllSides-
    # aligned categories. The pipeline tries to include at least one outlet
    # from each of these functional slant groups in every dossier.
    REQUIRED_SLANTS = ["wire", "lean-left", "lean-right", "international", "specialized"]

    def __init__(self, news_fetcher=None, registry_path: Optional[str] = None):
        self.news_fetcher = news_fetcher
        self.registry_path = registry_path or _default_registry_path()
        self.registry = _load_outlet_registry(self.registry_path)

    # ---- public ------------------------------------------------------------

    def _infer_outlet_from_url(self, url: str) -> str:
        """Infer the outlet name for a URL by matching its domain against
        the loaded outlet registry. Falls back to the bare domain string
        if no registry entry matches."""
        try:
            parsed = urlparse(url)
            domain = (parsed.netloc or "").lower().lstrip("www.")
        except Exception:
            return "Unknown"
        if not domain:
            return "Unknown"
        for entry in self.registry:
            entry_domain = (entry.get("domain") or "").lower()
            if entry_domain and entry_domain in domain:
                return entry["name"]
        return domain

    def gather(
        self,
        candidate: "TrendCandidate",
        target_count: int = 7,
        seed_urls: list[str] | None = None,
    ) -> StoryDossier:
        """Collect articles for a candidate and return a StoryDossier.

        target_count is a soft target — we keep gathering until we hit it OR
        we exhaust the slant matrix, whichever comes first. The dossier is
        returned even if incomplete; the verification gate at Stage 6 makes
        the final publish/no-publish call.

        seed_urls: optional list of URLs discovered during trend detection
        (Phase 1). These are fetched directly BEFORE the keyword search so
        the dossier always has the original source article even when the
        keyword re-search returns 0 results.
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

        # ---- Seed-article injection (Phase 2) --------------------------------
        # Fetch the original article(s) from trend detection before the keyword
        # search so the dossier has them even when keyword search returns 0.
        seed_articles: list[dict] = []
        if seed_urls:
            for url in seed_urls:
                body = self._fetch_body(url)
                if not body:
                    print(f"[source_gatherer] seed URL fetch failed: {url[:80]}")
                    continue
                outlet_name = self._infer_outlet_from_url(url)
                seed_articles.append({
                    "title": "",
                    "url": url,
                    "source": outlet_name,
                    "description": "",
                    "_prefetched_body": body,
                })
            if seed_articles:
                print(f"[source_gatherer] fetched {len(seed_articles)}/{len(seed_urls)} seed articles")

        articles_raw = seed_articles + self._fetch_articles(topic_query, max_articles=max(target_count * 2, 10))

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
            body = entry.get("_prefetched_body") or self._fetch_body(entry.get("url", ""))
            if not body:
                # Fall back to whatever the description was — better than nothing
                body = entry.get("description", "") or ""
            # Determine headline_only: body is empty or too short after
            # whitespace normalization (e.g. RSS description only, <500 chars).
            body_normalized = re.sub(r"\s+", " ", body).strip() if body else ""
            is_headline_only = not body_normalized or len(body_normalized) < 500
            record = ArticleRecord(
                outlet=entry.get("canonical_outlet") or entry.get("source") or "Unknown",
                url=entry.get("url", ""),
                title=entry.get("title", ""),
                body=body,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                is_wire_derived=False,  # set after we see the full set below
                headline_only=is_headline_only,
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
        6 keyword tokens that are most likely to retrieve articles about the
        SAME specific news event.

        The key insight (learned the hard way — see the NYPD cooler incident
        where "New York City" was the only query produced): event verbs and
        distinctive content nouns are far more searchable than generic
        location proper nouns. "sentenced sergeant cooler" finds the specific
        story; "New York City" finds everything in NYC.

        Three tiers of token priority:
          Tier 1: event verbs + strong nouns (highest search precision)
          Tier 2: distinctive content words ≥5 chars (story-specific nouns)
          Tier 3: proper nouns NOT in the generic set (names, orgs)
          Tier 4: generic proper nouns (locations, demoted to backfill)

        Returns "" if nothing extractable is left.
        """
        if not headline_seed:
            return ""

        # 1. Strip outlet suffix and fluff prefix
        stripped = _SUFFIX_STRIP_RE.sub("", headline_seed.strip(), count=1).strip()
        upper_prefix = stripped.upper()
        for pref in _FLUFF_PREFIXES:
            if upper_prefix.startswith(pref):
                stripped = stripped[len(pref):].lstrip()
                break

        # 2. Split into tokens
        raw_tokens = [t for t in _TOKEN_SPLIT_RE.split(stripped) if t]

        # 3. Classify each token into priority tiers.
        #
        # Tier 1: event verbs + strong nouns from curated lists (case-insensitive).
        #         These are the MOST searchable tokens — they narrow the story.
        #         "sentenced sergeant prison" finds the NYPD cooler case;
        #         "ceasefire strikes" finds the Iran/Israel event.
        #
        # Tier 2: specific proper nouns (names, organizations, non-generic places).
        #         "Trump", "Hezbollah", "Heuermann" — specific to the story.
        #
        # Tier 3: generic proper nouns (common location/institutional words).
        #         "New", "York", "City", "Washington" — useful as backfill but
        #         not distinctive enough to be the only search terms.
        #
        # NOTE: we deliberately do NOT have a "distinctive lowercase word ≥5 chars"
        # tier. Initial implementation had one but it caught common English words
        # like "affairs", "analyst", "support" that displaced the actually-important
        # proper nouns (Trump, Iran, Hezbollah). The expanded _STRONG_NOUNS set
        # already covers the specific content nouns (police, sergeant, prison,
        # hospital, school, etc.) that the generic tier was trying to catch.
        tier1: list[str] = []  # event verbs + strong nouns (highest search precision)
        tier2: list[str] = []  # specific proper nouns (names, orgs)
        tier3: list[str] = []  # generic proper nouns (locations — backfill only)

        seen_lower: set[str] = set()
        for raw in raw_tokens:
            tok = raw.strip(".’\"`’’\u201c\u201d")
            if not tok or len(tok) < 3:
                continue
            lower = tok.lower()
            if lower in _STOPWORDS or lower in seen_lower:
                continue
            seen_lower.add(lower)

            # Curated lists first (case-insensitive) — highest search precision
            if lower in _EVENT_VERBS or lower in _STRONG_NOUNS:
                tier1.append(tok)
                continue

            # Proper noun classification (capitalized, not a sentence starter)
            is_proper = tok[0].isupper() and tok not in _SENTENCE_STARTERS
            if is_proper:
                if lower in _GENERIC_PROPER_NOUNS:
                    tier3.append(tok)
                else:
                    tier2.append(tok)

        # 4. Dynamic allocation across tiers, capped at 5 tokens total.
        # Google News RSS treats multi-word queries as AND — 5 tokens is the
        # sweet spot. Dynamic allocation ensures both event verbs AND proper
        # nouns make it into the query regardless of headline structure.
        if len(tier2) >= 3:
            # Rich in proper nouns — balance verbs and names
            result = tier1[:2] + tier2[:3] + tier3
        else:
            # Few proper nouns — lean on event verbs, backfill with whatever
            result = tier1 + tier2 + tier3
        return " ".join(result[:5])

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
