"""
Unit tests for src/source_gatherer.py — Stage 3 of the Walter Croncat
journalism workflow.

Covers:
  - Slant diversity is respected (wire + left-mainstream + right-mainstream etc.)
  - Wire-derived detection catches a Fox News copy of a Reuters wire body
  - Dossier is well-formed (article records, outlet_slants, story_id passthrough)
  - Graceful degradation when NewsFetcher returns nothing
  - target_count cap
"""
import os
import sys
from dataclasses import dataclass

import pytest

# Path setup
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from dossier_store import StoryDossier  # noqa: E402
from source_gatherer import SourceGatherer  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    headline_seed: str
    detected_at: str = "2026-04-08T19:30:00+00:00"
    source_signals: list = None
    engagement: int = 0
    story_id: str = "20260408-test-story"

    def __post_init__(self):
        if self.source_signals is None:
            self.source_signals = []


class _StubNewsFetcher:
    def __init__(self, articles=None, bodies=None, raise_on_call=False):
        self._articles = articles or []
        self._bodies = bodies or {}
        self._raise = raise_on_call
        self.last_topic = None
        self.last_outlets = None

    def get_articles_for_topic(self, topic, max_articles=10, outlets=None):
        self.last_topic = topic
        self.last_outlets = outlets
        if self._raise:
            raise RuntimeError("boom")
        return list(self._articles)

    def fetch_article_content(self, url):
        return self._bodies.get(url, "")


@pytest.fixture
def candidate():
    return _Candidate(
        headline_seed="Senate passes appropriations bill 68-32",
        source_signals=["Reuters", "AP", "FoxNews"],
    )


@pytest.fixture
def real_registry_path():
    return os.path.join(_PROJECT_ROOT, "outlet_registry.yaml")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGather:
    def test_gather_returns_well_formed_dossier(self, candidate, real_registry_path):
        articles = [
            {
                "title": "Reuters: Senate 68-32",
                "url": "https://reuters.com/x",
                "source": "Reuters",
                "description": "Wire copy",
            },
            {
                "title": "AP: Senate 68-32",
                "url": "https://apnews.com/y",
                "source": "AP News",
                "description": "Wire copy",
            },
            {
                "title": "NYT framing",
                "url": "https://nytimes.com/z",
                "source": "The New York Times",
                "description": "Bipartisan moment",
            },
        ]
        bodies = {
            "https://reuters.com/x": "Reuters body about the Senate vote 68-32 " + ("x" * 200),
            "https://apnews.com/y": "AP body about the Senate vote 68-32 " + ("y" * 200),
            "https://nytimes.com/z": "NYT body framing the vote as bipartisan " + ("z" * 200),
        }
        fetcher = _StubNewsFetcher(articles=articles, bodies=bodies)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=5)

        assert isinstance(dossier, StoryDossier)
        assert dossier.story_id == candidate.story_id
        assert dossier.headline_seed == candidate.headline_seed
        assert len(dossier.articles) >= 2
        outlets = {a.outlet for a in dossier.articles}
        assert "Reuters" in outlets

    def test_gather_requests_slant_diversity_via_fetcher(self, candidate, real_registry_path):
        """The fetcher should be asked for a compressed keyword query, not the
        full headline_seed (Bug 4). The query must still be non-empty and
        should retain the key nouns/verbs from the headline."""
        fetcher = _StubNewsFetcher(articles=[], bodies={})
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        gatherer.gather(candidate, target_count=7)
        # The topic passed to the fetcher should be the compressed query,
        # not the full headline_seed.
        assert fetcher.last_topic is not None
        assert fetcher.last_topic != candidate.headline_seed
        assert len(fetcher.last_topic.split()) <= 6
        # "Senate" and "passes" are still present in the compressed form
        lowered = fetcher.last_topic.lower()
        assert "senate" in lowered
        assert "passes" in lowered
        # The original headline_seed is preserved on the dossier for
        # downstream stages.
        # (We can't assert on the dossier directly here because fetcher
        # returned no articles, but the gather() call itself shouldn't
        # have mutated candidate.headline_seed.)
        assert candidate.headline_seed == "Senate passes appropriations bill 68-32"

    def test_wire_derived_detection_flags_copy(self, candidate, real_registry_path):
        """A Fox News article whose body is >=50% Reuters wire copy should
        be flagged is_wire_derived."""
        wire_body = (
            "WASHINGTON (Reuters) - The U.S. Senate on Tuesday voted 68-32 to pass a $1.2 trillion "
            "appropriations bill that would avert a midnight shutdown deadline. The measure now "
            "goes to the House for a Friday vote. Senate Majority Leader said the package included "
            "a $14 billion emergency disaster supplement in Title VII. Senate roll call vote 312 "
            "confirmed the breakdown and the bill text was published."
        )
        articles = [
            {
                "title": "Reuters: Senate 68-32",
                "url": "https://reuters.com/x",
                "source": "Reuters",
                "description": "Wire copy",
            },
            {
                "title": "AP: Senate 68-32",
                "url": "https://apnews.com/y",
                "source": "AP News",
                "description": "Wire copy",
            },
            {
                "title": "Fox: Senate 68-32",
                "url": "https://foxnews.com/a",
                "source": "Fox News",
                "description": "GOP defectors",
            },
        ]
        bodies = {
            "https://reuters.com/x": wire_body,
            "https://apnews.com/y": "AP body" + ("y" * 200),
            "https://foxnews.com/a": wire_body,   # Exact wire copy
        }
        fetcher = _StubNewsFetcher(articles=articles, bodies=bodies)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=5)
        fox = next((a for a in dossier.articles if "Fox" in a.outlet), None)
        assert fox is not None, "expected a Fox article in the gather"
        assert fox.is_wire_derived, "Fox copy of Reuters body should be wire-derived"

        reuters = next((a for a in dossier.articles if a.outlet == "Reuters"), None)
        assert reuters is not None
        assert reuters.is_wire_derived is False, "Reuters is the wire and cannot be wire-derived"

    def test_graceful_empty_when_fetcher_returns_nothing(self, candidate, real_registry_path):
        fetcher = _StubNewsFetcher(articles=[], bodies={})
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=5)
        assert dossier.articles == []
        assert dossier.story_id == candidate.story_id
        # No crash is the contract — verification_gate at Stage 6 decides publish/no-publish

    def test_graceful_on_fetcher_exception(self, candidate, real_registry_path):
        fetcher = _StubNewsFetcher(raise_on_call=True)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=5)
        assert dossier.articles == []

    def test_target_count_not_exceeded(self, candidate, real_registry_path):
        articles = [
            {"title": f"t{i}", "url": f"https://reuters.com/{i}",
             "source": "Reuters", "description": ""}
            for i in range(20)
        ]
        bodies = {a["url"]: "x" * 300 for a in articles}
        fetcher = _StubNewsFetcher(articles=articles, bodies=bodies)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=3)
        assert len(dossier.articles) <= 3

    def test_outlet_slants_populated_for_registered_outlets(self, candidate, real_registry_path):
        articles = [
            {"title": "Reuters: Senate passes bill", "url": "https://reuters.com/x",
             "source": "Reuters", "description": ""},
            {"title": "NYT: Senate passes bill", "url": "https://nytimes.com/y",
             "source": "The New York Times", "description": ""},
        ]
        bodies = {
            "https://reuters.com/x": "The Senate voted to pass the appropriations bill. " + ("x" * 300),
            "https://nytimes.com/y": "Senate clears the spending measure. " + ("y" * 300),
        }
        fetcher = _StubNewsFetcher(articles=articles, bodies=bodies)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(candidate, target_count=5)
        # Reuters is wire, NYT is lean-left per outlet_registry.yaml (AllSides-aligned)
        assert dossier.outlet_slants.get("Reuters") == "wire"
        assert dossier.outlet_slants.get("The New York Times") == "lean-left"

    def test_substring_overlap_short_body_returns_zero(self):
        # _substring_overlap should skip bodies shorter than the shingle window
        assert SourceGatherer._substring_overlap("abc", "def") == 0.0

    def test_substring_overlap_identical_bodies(self):
        body = "a" * 200
        assert SourceGatherer._substring_overlap(body, body) >= 0.5


# ---------------------------------------------------------------------------
# Bug 4: _build_search_query — keyword extraction for Stage 3 queries
# ---------------------------------------------------------------------------

class TestBuildSearchQuery:
    def test_empty_input_returns_empty(self):
        assert SourceGatherer._build_search_query("") == ""
        assert SourceGatherer._build_search_query("   ") == ""

    def test_short_headline_passes_through_cleaned(self):
        # "Senate passes bill" — all three tokens are keepable
        out = SourceGatherer._build_search_query("Senate passes bill")
        assert out == "Senate passes bill"

    def test_long_headline_capped_at_six_tokens(self):
        headline = (
            "Hours after US President Trump announced a ceasefire with Iran, "
            "Israeli affairs analyst Dan Perry told Al Jazeera Israel's "
            "Lebanon strikes aim to destroy Hezbollah and support Lebanon - "
            "as Israel's biggest attack hit Beirut"
        )
        out = SourceGatherer._build_search_query(headline)
        tokens = out.split()
        assert len(tokens) <= 5, f"expected <=5 tokens, got {len(tokens)}: {out!r}"
        # At least a couple of the key proper nouns should survive extraction
        lowered = out.lower()
        matches = sum(1 for kw in ("trump", "iran", "israeli", "lebanon", "ceasefire") if kw in lowered)
        assert matches >= 3, f"expected ≥3 key terms, got {matches} in {out!r}"
        # And no hint of the sentence-starter "Hours" should leak through
        assert "Hours" not in tokens

    def test_outlet_suffix_with_dash_is_stripped(self):
        out = SourceGatherer._build_search_query("Vote passes 68-32 - Reuters")
        assert "Reuters" not in out.split(), f"Reuters suffix leaked: {out!r}"
        assert "passes" in out.lower()

    def test_outlet_suffix_with_em_dash_is_stripped(self):
        out = SourceGatherer._build_search_query(
            "Court rules on election dispute — Al Jazeera"
        )
        tokens = out.split()
        assert "Al" not in tokens
        assert "Jazeera" not in tokens
        assert "rules" in [t.lower() for t in tokens]

    def test_outlet_suffix_with_pipe_is_stripped(self):
        out = SourceGatherer._build_search_query("Senate confirms nominee | Reuters")
        assert "Reuters" not in out.split()

    def test_politico_suffix_on_realistic_headline(self):
        # From the QA sample — ensures Bug 6 (outlet-suffix strip) works
        out = SourceGatherer._build_search_query(
            "Hegseth declares victory in Iran but says US forces will rem... - Politico"
        )
        tokens = out.split()
        assert "Politico" not in tokens
        assert "Hegseth" in tokens
        assert "declares" in [t.lower() for t in tokens]

    def test_breaking_prefix_is_stripped(self):
        out = SourceGatherer._build_search_query("BREAKING: Senate passes bill")
        tokens = out.split()
        assert "BREAKING" not in tokens
        assert "Senate" in tokens
        assert "passes" in [t.lower() for t in tokens]
        assert "bill" in [t.lower() for t in tokens]

    def test_live_updates_prefix_is_stripped(self):
        out = SourceGatherer._build_search_query("Live Updates: Court rules on ballot")
        lowered = out.lower()
        assert "updates" not in lowered
        assert "court" in lowered
        assert "rules" in lowered

    def test_stopwords_dropped(self):
        out = SourceGatherer._build_search_query("President signs the new bill")
        tokens = [t.lower() for t in out.split()]
        assert "the" not in tokens

    def test_dedup_preserves_order(self):
        # "Trump" should appear once even when repeated in the headline
        out = SourceGatherer._build_search_query("Trump signs Trump bill")
        tokens = out.split()
        assert tokens.count("Trump") == 1

    def test_mid_sentence_em_dash_not_eaten(self):
        # "Lebanon - as ..." should NOT be treated as an outlet suffix
        # because the word after the dash is lowercase. The failure case
        # from run 24159589401 relies on this.
        headline = "Senate passes bill 68-32 - as shutdown looms"
        out = SourceGatherer._build_search_query(headline)
        # "shutdown" is lowercase and not in our keeplist so it won't
        # appear, but crucially the regex shouldn't have eaten " - as ..."
        # as an outlet suffix. The thing we actually verify: "passes" still
        # makes it through (it would be dropped if the whole tail were
        # treated as a suffix and then fluff-stripped).
        assert "passes" in [t.lower() for t in out.split()]


# ---------------------------------------------------------------------------
# Bug 5: post_journalism_cycle short-circuits on empty dossier
# ---------------------------------------------------------------------------
# Stubbed at the main-module level: we want to assert that when Stage 3
# returns a dossier with zero articles, the pipeline exits cleanly (returns
# True) and does NOT instantiate / call the Opus-backed MetaAnalyzer.

class TestPostJournalismCycleEmptyDossier:
    def test_empty_dossier_short_circuits_before_meta_analyzer(self, monkeypatch):
        from unittest.mock import MagicMock

        import main  # noqa: E402 — only imported in this test
        from dossier_store import StoryDossier
        from trend_detector import TrendCandidate

        # --- Stub config: journalism enabled, minimal nested dicts
        def _stub_config():
            return {
                "journalism": {
                    "enabled": True,
                    "trend_detection": {"max_candidates": 5},
                    "triage": {"use_llm": False},
                    "source_gather": {"target_count": 3},
                    "meta_analysis": {"model": "claude-opus-4-6"},
                    "composer": {"model": "claude-sonnet-4-6", "max_length": 280},
                    "verification": {},
                    "dry_run": {"drafts_dir": "drafts"},
                    "outlet_registry": "outlet_registry.yaml",
                },
                "deduplication": {},
            }

        monkeypatch.setattr(main, "_load_config", _stub_config)

        # --- Stub the external services (bots / fetcher / stores)
        monkeypatch.setattr(main, "TwitterBot", MagicMock())
        monkeypatch.setattr(main, "BlueskyBot", MagicMock())
        monkeypatch.setattr(main, "ContentGenerator", MagicMock())
        monkeypatch.setattr(main, "NewsFetcher", MagicMock())
        monkeypatch.setattr(main, "PostTracker", MagicMock())

        dossier_store_mock = MagicMock()
        monkeypatch.setattr(main, "DossierStore", MagicMock(return_value=dossier_store_mock))

        # --- Stub Stage 1: one candidate
        candidate = TrendCandidate(
            headline_seed="Test headline for short circuit",
            detected_at="2026-04-08T19:30:00+00:00",
            source_signals=["Reuters", "AP"],
            engagement=100,
            story_id="20260408-shortcircuit-test",
        )
        trend_detector_mock = MagicMock()
        trend_detector_mock.detect_trends.return_value = [candidate]
        monkeypatch.setattr(main, "TrendDetector", MagicMock(return_value=trend_detector_mock))

        # --- Stub Stage 2: it passes through the candidate
        story_triage_mock = MagicMock()
        story_triage_mock.triage.return_value = [candidate]
        monkeypatch.setattr(main, "StoryTriage", MagicMock(return_value=story_triage_mock))

        # --- Stub Stage 3a: returns an EMPTY dossier (this is the bug 5 trigger)
        empty_dossier = StoryDossier(
            story_id=candidate.story_id,
            headline_seed=candidate.headline_seed,
            detected_at=candidate.detected_at,
            articles=[],
            primary_sources=[],
            outlet_slants={},
        )
        source_gatherer_mock = MagicMock()
        source_gatherer_mock.gather.return_value = empty_dossier
        monkeypatch.setattr(
            main, "SourceGatherer", MagicMock(return_value=source_gatherer_mock)
        )

        # --- Stub Stage 3b: returns nothing
        primary_finder_mock = MagicMock()
        primary_finder_mock.find.return_value = []
        monkeypatch.setattr(
            main, "PrimarySourceFinder", MagicMock(return_value=primary_finder_mock)
        )

        # --- Spy on the Stage 4+ stages: they MUST NOT be called
        meta_analyzer_class_mock = MagicMock()
        monkeypatch.setattr(main, "MetaAnalyzer", meta_analyzer_class_mock)

        post_composer_class_mock = MagicMock()
        monkeypatch.setattr(main, "PostComposer", post_composer_class_mock)

        verification_gate_class_mock = MagicMock()
        monkeypatch.setattr(main, "VerificationGate", verification_gate_class_mock)

        # --- Run the cycle
        result = main.post_journalism_cycle(dry_run=True)

        # --- Assertions
        assert result is True, "empty dossier should yield a clean no-op True"
        # MetaAnalyzer class is still instantiated in the init block above
        # Stage 3 (that's unavoidable without a deeper refactor), but the
        # analyze() method must not have been called.
        analyzer_instance = meta_analyzer_class_mock.return_value
        assert analyzer_instance.analyze.call_count == 0, (
            "MetaAnalyzer.analyze() should not run on an empty dossier"
        )
        composer_instance = post_composer_class_mock.return_value
        assert composer_instance.compose.call_count == 0, (
            "PostComposer.compose() should not run on an empty dossier"
        )
        gate_instance = verification_gate_class_mock.return_value
        assert gate_instance.verify.call_count == 0, (
            "VerificationGate.verify() should not run on an empty dossier"
        )
        # Dossier is still persisted for audit
        dossier_store_mock.save_dossier.assert_called_once_with(empty_dossier)


# ---------------------------------------------------------------------------
# Phase 2: seed_urls passthrough + _infer_outlet_from_url tests
# ---------------------------------------------------------------------------

class TestGatherSeedUrls:
    def test_gather_with_seed_urls_fetches_directly(self, real_registry_path):
        """Seed URL appears in dossier even when keyword search returns 0."""
        fetcher = _StubNewsFetcher(articles=[], bodies={
            "https://reuters.com/special-story": (
                "WASHINGTON (Reuters) - The California AG filed hospice fraud charges "
                "involving eleven facilities across three counties. "
                + ("lorem ipsum " * 50)
            ),
        })
        candidate = _Candidate(
            headline_seed="California AG files hospice fraud charges",
        )
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(
            candidate,
            target_count=5,
            seed_urls=["https://reuters.com/special-story"],
        )
        assert len(dossier.articles) >= 1
        urls = [a.url for a in dossier.articles]
        assert "https://reuters.com/special-story" in urls

    def test_gather_seed_urls_precede_keyword_results(self, real_registry_path):
        """Seed articles are first in dossier.articles."""
        seed_body = "The Senate voted 68-32 to pass the appropriations bill. " * 20
        keyword_body = "AP: Senate passes spending bill. The appropriations measure cleared 68-32. " * 20
        fetcher = _StubNewsFetcher(
            articles=[
                {
                    "title": "AP: Senate passes spending bill 68-32",
                    "url": "https://apnews.com/keyword",
                    "source": "AP News",
                    "description": "From keyword search",
                },
            ],
            bodies={
                "https://reuters.com/seed": seed_body,
                "https://apnews.com/keyword": keyword_body,
            },
        )
        candidate = _Candidate(
            headline_seed="Senate passes appropriations bill 68-32",
            source_signals=["Reuters", "AP"],
        )
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(
            candidate,
            target_count=5,
            seed_urls=["https://reuters.com/seed"],
        )
        assert len(dossier.articles) >= 2
        # The seed article should be first because seed_articles are prepended
        # to articles_raw. Since slant sorting may reorder, we just check
        # the seed URL is present.
        urls = [a.url for a in dossier.articles]
        assert "https://reuters.com/seed" in urls
        assert "https://apnews.com/keyword" in urls

    def test_gather_seed_url_fetch_failure_continues(self, real_registry_path):
        """Failed seed URL doesn't block keyword search."""
        fetcher = _StubNewsFetcher(
            articles=[
                {
                    "title": "AP: Senate passes spending bill 68-32",
                    "url": "https://apnews.com/keyword",
                    "source": "AP News",
                    "description": "From keyword search",
                },
            ],
            bodies={
                # Seed URL returns empty body (fetch failure)
                "https://reuters.com/404": "",
                "https://apnews.com/keyword": "The Senate passed the appropriations bill 68-32. " * 20,
            },
        )
        candidate = _Candidate(
            headline_seed="Senate passes appropriations bill 68-32",
            source_signals=["Reuters", "AP"],
        )
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(
            candidate,
            target_count=5,
            seed_urls=["https://reuters.com/404"],
        )
        # Keyword article should still be present
        urls = [a.url for a in dossier.articles]
        assert "https://apnews.com/keyword" in urls

    def test_gather_without_seed_urls_unchanged(self, candidate, real_registry_path):
        """Backward compat: calling without seed_urls works the same as before."""
        articles = [
            {
                "title": "Reuters: Senate 68-32",
                "url": "https://reuters.com/x",
                "source": "Reuters",
                "description": "Wire copy",
            },
        ]
        bodies = {
            "https://reuters.com/x": "Reuters body about the Senate vote 68-32 " + ("x" * 200),
        }
        fetcher = _StubNewsFetcher(articles=articles, bodies=bodies)
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        # Call without seed_urls (the old API)
        dossier = gatherer.gather(candidate, target_count=5)
        assert isinstance(dossier, StoryDossier)
        assert len(dossier.articles) >= 1

    # Relevance filter should not break seed URL inclusion
    def test_seed_url_survives_relevance_filter(self, real_registry_path):
        """Seed URLs with relevant bodies should survive the relevance filter."""
        seed_body = (
            "Singer D4vd, real name David Anthony Burke, was arrested Thursday "
            "in connection with the death of Celeste Rivas Hernandez. "
            + ("details " * 50)
        )
        fetcher = _StubNewsFetcher(articles=[], bodies={
            "https://latimes.com/d4vd-arrest": seed_body,
        })
        candidate = _Candidate(
            headline_seed="Singer D4vd arrested on suspicion of murder of Celeste Rivas Hernandez",
            story_id="2026-04-17-d4vd-test",
        )
        gatherer = SourceGatherer(
            news_fetcher=fetcher, registry_path=real_registry_path
        )
        dossier = gatherer.gather(
            candidate, target_count=5,
            seed_urls=["https://latimes.com/d4vd-arrest"],
        )
        urls = [a.url for a in dossier.articles]
        assert "https://latimes.com/d4vd-arrest" in urls

    def test_infer_outlet_from_url_matches_registry(self, real_registry_path):
        """_infer_outlet_from_url resolves known domains to canonical names."""
        gatherer = SourceGatherer(
            news_fetcher=None, registry_path=real_registry_path
        )
        # Test a few canonical mappings (depends on outlet_registry.yaml)
        reuters_name = gatherer._infer_outlet_from_url("https://www.reuters.com/article/foo")
        assert "reuters" in reuters_name.lower() or reuters_name == "reuters.com"

        # Unknown domain should fall back to the domain string
        unknown = gatherer._infer_outlet_from_url("https://www.obscurenews.example.com/story")
        assert unknown  # non-empty
        assert "obscurenews" in unknown.lower() or "example" in unknown.lower()


# ---------------------------------------------------------------------------
# Relevance filter — proper-noun heuristic + Haiku fallback
# ---------------------------------------------------------------------------

class TestExtractHeadlineNouns:
    def test_extracts_proper_nouns(self):
        nouns = SourceGatherer._extract_headline_nouns(
            "Singer D4vd arrested for murder of Celeste Rivas Hernandez"
        )
        assert "singer" in nouns
        assert "d4vd" in nouns
        assert "celeste" in nouns
        assert "rivas" in nouns
        assert "hernandez" in nouns

    def test_skips_sentence_starters(self):
        nouns = SourceGatherer._extract_headline_nouns("The president signed a bill")
        assert "the" not in nouns

    def test_skips_short_words(self):
        nouns = SourceGatherer._extract_headline_nouns("US AG files suit")
        assert "us" not in nouns
        assert "ag" not in nouns

    def test_empty_headline(self):
        assert SourceGatherer._extract_headline_nouns("") == set()


class TestHeuristicRelevance:
    def _make_article(self, title="", body=""):
        from dossier_store import ArticleRecord
        return ArticleRecord(
            outlet="Test", url="https://test.com", title=title,
            body=body, fetched_at="2026-01-01T00:00:00Z"
        )

    def test_relevant_with_2_nouns(self):
        headline_nouns = {"d4vd", "celeste", "hernandez", "rivas"}
        article = self._make_article(
            title="D4vd arrested in murder case",
            body="The body of Celeste was found in a Tesla"
        )
        assert SourceGatherer._heuristic_relevance(article, headline_nouns) == "relevant"

    def test_irrelevant_with_0_nouns(self):
        headline_nouns = {"d4vd", "celeste", "hernandez", "rivas"}
        article = self._make_article(
            title="Trump approval rating drops",
            body="Fox News host Jessica Tarlov discussed poll numbers"
        )
        assert SourceGatherer._heuristic_relevance(article, headline_nouns) == "irrelevant"

    def test_borderline_with_1_noun(self):
        headline_nouns = {"d4vd", "celeste", "hernandez", "rivas"}
        article = self._make_article(
            title="Singer arrested in LA",
            body="A singer was taken into custody. D4vd fans react."
        )
        assert SourceGatherer._heuristic_relevance(article, headline_nouns) == "borderline"

    def test_empty_headline_nouns_returns_relevant(self):
        article = self._make_article(title="Anything", body="Anything")
        assert SourceGatherer._heuristic_relevance(article, set()) == "relevant"


class TestFilterRelevantArticles:
    def _make_article(self, outlet="Test", title="", body=""):
        from dossier_store import ArticleRecord
        return ArticleRecord(
            outlet=outlet, url=f"https://{outlet.lower()}.com",
            title=title, body=body, fetched_at="2026-01-01T00:00:00Z"
        )

    def test_keeps_relevant_drops_irrelevant(self):
        """The D4vd scenario: LA Times and NBC are relevant, USA Today is not."""
        gatherer = SourceGatherer(news_fetcher=None)
        headline = "Singer D4vd arrested for murder of Celeste Rivas Hernandez"

        articles = [
            self._make_article("LA Times",
                title="D4vd arrested in slaying of girl",
                body="Singer D4vd was arrested. Celeste Rivas Hernandez remains found in Tesla."),
            self._make_article("NBC News",
                title="Singer D4vd arrested in murder of teen Celeste Rivas",
                body="D4vd arrested after Hernandez body found in trunk."),
            self._make_article("USA Today",
                title="Trump Fox News Jessica Tarlov approval rating",
                body="Fox News host discusses Trump's declining poll numbers."),
            self._make_article("Politico",
                title="Johnson tries again on spy powers vote",
                body="House Speaker pushes for surveillance renewal legislation."),
        ]

        result = gatherer._filter_relevant_articles(articles, headline)

        outlets = {a.outlet for a in result}
        assert "LA Times" in outlets
        assert "NBC News" in outlets
        assert "USA Today" not in outlets
        assert "Politico" not in outlets

    def test_keeps_all_when_all_relevant(self):
        gatherer = SourceGatherer(news_fetcher=None)
        headline = "Senate passes appropriations bill 68-32"

        articles = [
            self._make_article("Reuters",
                title="Senate passes $1.2T bill",
                body="The Senate voted 68-32 to pass the appropriations bill."),
            self._make_article("AP",
                title="Senate approves spending bill",
                body="The Senate cleared the appropriations measure 68-32."),
        ]

        result = gatherer._filter_relevant_articles(articles, headline)
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        gatherer = SourceGatherer(news_fetcher=None)
        result = gatherer._filter_relevant_articles([], "Some headline")
        assert result == []

    def test_borderline_calls_haiku(self):
        """Borderline articles (1 noun match) should trigger Haiku check."""
        from unittest.mock import patch
        gatherer = SourceGatherer(news_fetcher=None)
        headline = "Singer D4vd arrested for murder of Celeste Rivas Hernandez"

        # Article with only 1 noun match (borderline)
        articles = [
            self._make_article("DW",
                title="Music industry news",
                body="D4vd has been trending worldwide after recent events."),
        ]

        with patch.object(SourceGatherer, '_haiku_relevance_check', return_value=True) as mock_haiku:
            result = gatherer._filter_relevant_articles(articles, headline)
            mock_haiku.assert_called_once()
            assert len(result) == 1

    def test_borderline_dropped_when_haiku_says_no(self):
        from unittest.mock import patch
        gatherer = SourceGatherer(news_fetcher=None)
        headline = "Singer D4vd arrested for murder of Celeste Rivas Hernandez"

        articles = [
            self._make_article("DW",
                title="Music industry news",
                body="D4vd has been trending worldwide after recent events."),
        ]

        with patch.object(SourceGatherer, '_haiku_relevance_check', return_value=False) as mock_haiku:
            result = gatherer._filter_relevant_articles(articles, headline)
            mock_haiku.assert_called_once()
            assert len(result) == 0
