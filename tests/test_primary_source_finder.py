"""
Unit tests for src/primary_source_finder.py — Stage 3 helper for the
Walter Croncat journalism workflow.

Covers every URL pattern in primary_source_finder.URL_PATTERNS:
  congress.gov, supremecourt.gov, pacer.uscourts.gov,
  federalregister.gov, bls.gov, bea.gov, census.gov, sec.gov,
  whitehouse.gov/briefing-room, generic .gov PDFs.

Also verifies:
  - Dossier mutation (new sources appended)
  - Idempotency (no duplicates on a second pass)
  - Trailing punctuation stripping
  - Excerpt generation around the URL
"""
import os
import sys

import pytest

# Path setup
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from dossier_store import ArticleRecord, StoryDossier  # noqa: E402
from primary_source_finder import PrimarySourceFinder  # noqa: E402


def _dossier_from_bodies(*bodies) -> StoryDossier:
    articles = [
        ArticleRecord(
            outlet=f"Outlet{i}",
            url=f"https://example.com/{i}",
            title=f"title {i}",
            body=body,
            fetched_at="2026-04-08T19:35:00+00:00",
        )
        for i, body in enumerate(bodies)
    ]
    return StoryDossier(
        story_id="20260408-test",
        headline_seed="Test story",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=articles,
    )


@pytest.fixture
def finder():
    return PrimarySourceFinder()


# ---------------------------------------------------------------------------
# Pattern-by-pattern tests
# ---------------------------------------------------------------------------

class TestUrlPatterns:
    def test_congress_gov_detected(self, finder):
        body = "See https://www.congress.gov/118/votes/2026/04/08/roll312.htm for details."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        assert len(added) == 1
        assert added[0].kind == "congress_record"
        assert "congress.gov" in added[0].url

    def test_supremecourt_gov_detected(self, finder):
        body = "Filing at https://www.supremecourt.gov/DocketPDF/22/22-123/12345/file.pdf."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "scotus_filing" in kinds

    def test_pacer_court_filing_detected(self, finder):
        body = "The complaint is on PACER at https://pacer.uscourts.gov/case/12345."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "court_filing" in kinds

    def test_federal_register_detected(self, finder):
        body = (
            "Rule text: https://www.federalregister.gov/documents/2026/04/08/2026-12345/example-rule."
        )
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "federal_register" in kinds

    def test_bls_detected_as_stats(self, finder):
        body = "BLS data: https://www.bls.gov/news.release/empsit.pdf."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "stats_release" in kinds

    def test_bea_detected_as_stats(self, finder):
        body = "BEA data: https://www.bea.gov/news/2026/example."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "stats_release" in kinds

    def test_census_detected_as_stats(self, finder):
        body = "Census data: https://www.census.gov/library/publications/2026/example.html."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "stats_release" in kinds

    def test_sec_detected(self, finder):
        body = "SEC complaint: https://www.sec.gov/litigation/complaints/2026/comp-2026-100.pdf."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "sec_filing" in kinds

    def test_whitehouse_briefing_room_detected(self, finder):
        body = "White House: https://www.whitehouse.gov/briefing-room/statements/2026/04/08/example/."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "white_house_release" in kinds

    def test_generic_gov_pdf_detected(self, finder):
        body = "See https://www.example.gov/reports/2026.pdf for the full report."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "gov_document" in kinds


# ---------------------------------------------------------------------------
# Dossier mutation + idempotency
# ---------------------------------------------------------------------------

class TestDossierMutation:
    def test_dossier_primary_sources_mutated(self, finder):
        body = "https://www.congress.gov/bill/118/HR4821/text"
        d = _dossier_from_bodies(body)
        assert d.primary_sources == []
        finder.find(d)
        assert len(d.primary_sources) == 1
        assert d.primary_sources[0].kind == "congress_record"

    def test_second_pass_is_idempotent(self, finder):
        body = "https://www.congress.gov/bill/118/HR4821/text"
        d = _dossier_from_bodies(body)
        first = finder.find(d)
        second = finder.find(d)
        assert len(first) == 1
        assert second == []
        assert len(d.primary_sources) == 1

    def test_multiple_articles_combine(self, finder):
        body_a = "https://www.congress.gov/bill/118/HR4821"
        body_b = "https://www.sec.gov/litigation/complaints/2026/example.pdf"
        d = _dossier_from_bodies(body_a, body_b)
        added = finder.find(d)
        kinds = {p.kind for p in added}
        assert "congress_record" in kinds
        assert "sec_filing" in kinds
        assert len(d.primary_sources) == 2

    def test_duplicate_url_across_articles_dedup(self, finder):
        url = "https://www.congress.gov/bill/118/HR4821"
        d = _dossier_from_bodies(f"See {url}", f"Also see {url}")
        added = finder.find(d)
        assert len(added) == 1

    def test_no_primary_sources_in_body_returns_empty(self, finder):
        d = _dossier_from_bodies("Nothing but prose here. Reuters says so.")
        added = finder.find(d)
        assert added == []


# ---------------------------------------------------------------------------
# URL punctuation / excerpt
# ---------------------------------------------------------------------------

class TestUrlCleanup:
    def test_trailing_period_stripped(self, finder):
        body = "See https://www.congress.gov/bill/118/HR4821."
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        assert added
        assert not added[0].url.endswith(".")

    def test_trailing_parenthesis_stripped(self, finder):
        body = "(see https://www.congress.gov/bill/118/HR4821)"
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        assert added
        assert not added[0].url.endswith(")")

    def test_excerpt_populated(self, finder):
        body = (
            "The bill text is here: https://www.congress.gov/bill/118/HR4821 "
            "and it runs to 2,400 pages."
        )
        d = _dossier_from_bodies(body)
        added = finder.find(d)
        assert added
        assert added[0].excerpt is not None
        assert "bill" in added[0].excerpt.lower()
